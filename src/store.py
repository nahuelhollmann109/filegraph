"""SQLite cache store for scan results."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

_DB_NAME = "cache.db"
_DB_DIR = ".filegraph"


def _get_db_path(project_root: Path) -> Path:
    """Return the path to the cache database."""
    return project_root / _DB_DIR / _DB_NAME


def init_db(project_root: Path) -> None:
    """Create the cache database with schema and WAL mode.

    Args:
        project_root: Root directory of the project (where .filegraph/ is created).
    """
    db_path = _get_db_path(project_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cache (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key   TEXT UNIQUE NOT NULL,
                tool_name   TEXT NOT NULL,
                path        TEXT NOT NULL,
                result_json TEXT NOT NULL,
                cached_at   REAL NOT NULL,
                max_mtime   REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_cache_path ON cache(path);
            CREATE INDEX IF NOT EXISTS idx_cache_tool ON cache(tool_name);

            CREATE TABLE IF NOT EXISTS cache_files (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key   TEXT NOT NULL,
                file_path   TEXT NOT NULL,
                mtime       REAL NOT NULL,
                FOREIGN KEY (cache_key) REFERENCES cache(cache_key) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_cache_files_key ON cache_files(cache_key);
        """)

        # Try to create FTS5 virtual table; fall back gracefully if unavailable
        try:
            conn.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS cache_fts USING fts5(
                    file_path,
                    content=cache_files,
                    content_rowid=id
                );
                CREATE TRIGGER IF NOT EXISTS cache_files_ai AFTER INSERT ON cache_files BEGIN
                    INSERT INTO cache_fts(rowid, file_path) VALUES (new.id, new.file_path);
                END;
                CREATE TRIGGER IF NOT EXISTS cache_files_ad AFTER DELETE ON cache_files BEGIN
                    INSERT INTO cache_fts(cache_fts, rowid, file_path) VALUES('delete', old.id, old.file_path);
                END;
            """)
        except sqlite3.OperationalError:
            # FTS5 not available — LIKE fallback will be used
            pass

        conn.commit()
    finally:
        conn.close()


def _connect(project_root: Path) -> sqlite3.Connection:
    """Open a connection to the cache database, initializing if needed."""
    db_path = _get_db_path(project_root)
    if not db_path.exists():
        init_db(project_root)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def get_cache(project_root: Path, cache_key: str) -> dict | None:
    """Retrieve a cached entry by key.

    Args:
        project_root: Project root path.
        cache_key: SHA256 key for the cache entry.

    Returns:
        Dict with result_json, cached_at, max_mtime, path, tool_name — or None.
    """
    conn = _connect(project_root)
    try:
        row = conn.execute(
            "SELECT result_json, cached_at, max_mtime, path, tool_name "
            "FROM cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if row is None:
            return None
        return {
            "result_json": row["result_json"],
            "cached_at": row["cached_at"],
            "max_mtime": row["max_mtime"],
            "path": row["path"],
            "tool_name": row["tool_name"],
        }
    finally:
        conn.close()


def set_cache(
    project_root: Path,
    cache_key: str,
    tool_name: str,
    path: str,
    result_json: str,
    file_set: list[tuple[str, float]],
) -> None:
    """Store a scan result and its file manifest. Upserts on cache_key.

    Args:
        project_root: Project root path.
        cache_key: SHA256 key.
        tool_name: Name of the tool that produced the result.
        path: Scanned directory path.
        result_json: JSON-serialized tool result.
        file_set: List of (file_path, mtime) tuples for every file in the result.
    """
    max_mtime = max((mtime for _, mtime in file_set), default=0.0)
    cached_at = time.time()

    conn = _connect(project_root)
    try:
        conn.execute("BEGIN")
        # Upsert cache entry
        conn.execute(
            "INSERT INTO cache (cache_key, tool_name, path, result_json, cached_at, max_mtime) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(cache_key) DO UPDATE SET "
            "tool_name=excluded.tool_name, path=excluded.path, "
            "result_json=excluded.result_json, cached_at=excluded.cached_at, "
            "max_mtime=excluded.max_mtime",
            (cache_key, tool_name, path, result_json, cached_at, max_mtime),
        )
        # Delete old file set for this key (if upsert)
        conn.execute("DELETE FROM cache_files WHERE cache_key = ?", (cache_key,))
        # Insert new file set
        conn.executemany(
            "INSERT INTO cache_files (cache_key, file_path, mtime) VALUES (?, ?, ?)",
            [(cache_key, fp, mt) for fp, mt in file_set],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def invalidate_path(project_root: Path, path: str) -> int:
    """Delete all cache entries matching a path prefix.

    Args:
        project_root: Project root path.
        path: Path prefix to invalidate.

    Returns:
        Number of cache entries deleted.
    """
    conn = _connect(project_root)
    try:
        cursor = conn.execute(
            "DELETE FROM cache WHERE path = ? OR path LIKE ?",
            (path, path + "/%"),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def get_file_set(project_root: Path, cache_key: str) -> list[dict]:
    """Retrieve the recorded file manifest for a cache entry.

    Args:
        project_root: Project root path.
        cache_key: Cache key to look up.

    Returns:
        List of dicts with file_path and mtime.
    """
    conn = _connect(project_root)
    try:
        rows = conn.execute(
            "SELECT file_path, mtime FROM cache_files WHERE cache_key = ?",
            (cache_key,),
        ).fetchall()
        return [{"file_path": r["file_path"], "mtime": r["mtime"]} for r in rows]
    finally:
        conn.close()


def list_entries_by_path(project_root: Path, path: str) -> list[dict]:
    """List all cache entries matching a path (exact or prefix).

    Args:
        project_root: Project root path.
        path: Path prefix to match.

    Returns:
        List of dicts with cache_key, tool_name, path, cached_at, max_mtime.
    """
    conn = _connect(project_root)
    try:
        rows = conn.execute(
            "SELECT cache_key, tool_name, path, cached_at, max_mtime "
            "FROM cache WHERE path = ? OR path LIKE ?",
            (path, path + "/%"),
        ).fetchall()
        return [
            {
                "cache_key": r["cache_key"],
                "tool_name": r["tool_name"],
                "path": r["path"],
                "cached_at": r["cached_at"],
                "max_mtime": r["max_mtime"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def search_fts(project_root: Path, query: str) -> list[dict]:
    """Search cached filenames using FTS5 or LIKE fallback.

    Args:
        project_root: Project root path.
        query: Substring to search for in file paths.

    Returns:
        List of dicts with file_path and cache_key.
    """
    conn = _connect(project_root)
    try:
        # Check if FTS5 table exists
        has_fts = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cache_fts'"
        ).fetchone()

        if has_fts:
            # Use quote() to safely wrap the query for FTS5 MATCH
            fts_query = f'"{query}"'
            rows = conn.execute(
                "SELECT cf.file_path, cf.cache_key "
                "FROM cache_fts fts "
                "JOIN cache_files cf ON cf.id = fts.rowid "
                "WHERE cache_fts MATCH ?",
                (fts_query,),
            ).fetchall()
        else:
            # LIKE fallback
            rows = conn.execute(
                "SELECT file_path, cache_key FROM cache_files WHERE file_path LIKE ?",
                (f"%{query}%",),
            ).fetchall()

        return [{"file_path": r["file_path"], "cache_key": r["cache_key"]} for r in rows]
    finally:
        conn.close()


def cache_stats(project_root: Path) -> dict:
    """Return cache statistics.

    Args:
        project_root: Project root path.

    Returns:
        Dict with entries, total_files, and size_bytes.
    """
    conn = _connect(project_root)
    try:
        entries = conn.execute("SELECT COUNT(*) as cnt FROM cache").fetchone()["cnt"]
        total_files = conn.execute("SELECT COUNT(*) as cnt FROM cache_files").fetchone()["cnt"]

        db_path = _get_db_path(project_root)
        size_bytes = db_path.stat().st_size if db_path.exists() else 0

        return {
            "entries": entries,
            "total_files": total_files,
            "size_bytes": size_bytes,
        }
    finally:
        conn.close()
