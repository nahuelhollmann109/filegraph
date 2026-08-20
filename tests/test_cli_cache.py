"""Integration tests for CLI cache commands."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from src.cli import main
from src.store import cache_stats, init_db


class TestCliIndex:
    def test_index_creates_cache(self, tmp_path: Path) -> None:
        """filegraph index creates .filegraph/cache.db."""
        (tmp_path / "file.txt").write_text("data")
        rc = main(["index", str(tmp_path)])
        assert rc == 0

        db_path = tmp_path / ".filegraph" / "cache.db"
        assert db_path.exists()

    def test_index_nonexistent_path(self) -> None:
        """filegraph index with invalid path returns error."""
        rc = main(["index", "/nonexistent/path"])
        assert rc == 1

    def test_index_not_a_directory(self, tmp_path: Path) -> None:
        """filegraph index on a file returns error."""
        f = tmp_path / "file.txt"
        f.write_text("data")
        rc = main(["index", str(f)])
        assert rc == 1


class TestCliSync:
    def test_sync_refreshes_stale(self, tmp_path: Path) -> None:
        """filegraph sync re-scans when files changed."""
        (tmp_path / "a.txt").write_text("hello")
        main(["index", str(tmp_path)])

        time.sleep(0.05)
        (tmp_path / "b.txt").write_text("world")

        rc = main(["sync", str(tmp_path)])
        assert rc == 0

    def test_sync_no_cache(self, tmp_path: Path) -> None:
        """filegraph sync without prior index returns error."""
        (tmp_path / "a.txt").write_text("hello")
        rc = main(["sync", str(tmp_path)])
        assert rc == 1

    def test_sync_nonexistent_path(self) -> None:
        """filegraph sync with invalid path returns error."""
        rc = main(["sync", "/nonexistent/path"])
        assert rc == 1


class TestCliStatus:
    def test_status_shows_stats(self, tmp_path: Path) -> None:
        """filegraph status displays cache statistics."""
        (tmp_path / "file.txt").write_text("data")
        main(["index", str(tmp_path)])

        # Change cwd so status can find the cache
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            rc = main(["status"])
            assert rc == 0
        finally:
            os.chdir(orig_cwd)

    def test_status_no_cache(self, tmp_path: Path) -> None:
        """filegraph status with no cache shows zeros."""
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            rc = main(["status"])
            assert rc == 0
        finally:
            os.chdir(orig_cwd)


class TestCliUnindex:
    def test_unindex_removes_entries(self, tmp_path: Path) -> None:
        """filegraph unindex removes cached entries for the path."""
        (tmp_path / "file.txt").write_text("data")
        main(["index", str(tmp_path)])

        rc = main(["unindex", str(tmp_path)])
        assert rc == 0

        stats = cache_stats(tmp_path)
        assert stats["entries"] == 0

    def test_unindex_idempotent(self, tmp_path: Path) -> None:
        """filegraph unindex succeeds even with no cache."""
        rc = main(["unindex", str(tmp_path)])
        assert rc == 0


class TestCliEndToEnd:
    def test_full_flow(self, tmp_path: Path) -> None:
        """Complete flow: index → scan (cache hit) → sync → status → unindex."""
        # 1. Create temp dir with files
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world")

        # 2. Index
        rc = main(["index", str(tmp_path)])
        assert rc == 0

        # 3. Scan — should use cache (same result as live scan)
        rc = main(["scan", str(tmp_path), "--format", "json"])
        assert rc == 0

        # 4. Add new file
        time.sleep(0.05)
        (tmp_path / "c.txt").write_text("new")

        # 5. Sync — should detect change
        rc = main(["sync", str(tmp_path)])
        assert rc == 0

        # 6. Scan again — should include new file
        rc = main(["scan", str(tmp_path), "--format", "json"])
        assert rc == 0

        # 7. Status — should show stats
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            rc = main(["status"])
            assert rc == 0
        finally:
            os.chdir(orig_cwd)

        # 8. Unindex — should remove cache
        rc = main(["unindex", str(tmp_path)])
        assert rc == 0

        stats = cache_stats(tmp_path)
        assert stats["entries"] == 0
