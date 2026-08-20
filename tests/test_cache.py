"""Unit tests for cache logic (key generation, freshness, get_or_scan)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.cache import check_freshness, extract_file_set, get_or_scan, make_cache_key
from src.store import init_db, set_cache


# ---------------------------------------------------------------------------
# make_cache_key tests
# ---------------------------------------------------------------------------


class TestMakeCacheKey:
    def test_deterministic(self) -> None:
        """Same inputs produce the same key."""
        k1 = make_cache_key("scan_directory", "/a", max_depth=None)
        k2 = make_cache_key("scan_directory", "/a", max_depth=None)
        assert k1 == k2

    def test_different_options_different_key(self) -> None:
        """Different kwargs produce different keys."""
        k1 = make_cache_key("scan_directory", "/a", max_depth=None)
        k2 = make_cache_key("scan_directory", "/a", max_depth=2)
        assert k1 != k2

    def test_different_paths_different_key(self) -> None:
        """Different paths produce different keys."""
        k1 = make_cache_key("scan_directory", "/a")
        k2 = make_cache_key("scan_directory", "/b")
        assert k1 != k2

    def test_different_tools_different_key(self) -> None:
        """Different tool names produce different keys."""
        k1 = make_cache_key("scan_directory", "/a")
        k2 = make_cache_key("search_by_type", "/a")
        assert k1 != k2

    def test_returns_64_char_hex(self) -> None:
        """Key is a 64-character hex string (SHA256)."""
        key = make_cache_key("t", "/p")
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)


# ---------------------------------------------------------------------------
# extract_file_set tests
# ---------------------------------------------------------------------------


class TestExtractFileSet:
    def test_search_by_type_result(self, tmp_path: Path) -> None:
        """extract_file_set handles search_by_type flat result format."""
        (tmp_path / "a.jpg").write_bytes(b"\xff")
        (tmp_path / "b.jpg").write_bytes(b"\xff")

        result = {
            "results": [
                {"name": "a.jpg", "path": str(tmp_path / "a.jpg"), "size": 1},
                {"name": "b.jpg", "path": str(tmp_path / "b.jpg"), "size": 1},
            ]
        }
        file_set = extract_file_set(result, "search_by_type")
        assert len(file_set) == 2
        paths = {fp for fp, _ in file_set}
        assert str(tmp_path / "a.jpg") in paths
        assert str(tmp_path / "b.jpg") in paths

    def test_find_duplicates_result(self, tmp_path: Path) -> None:
        """extract_file_set handles find_duplicates result format."""
        (tmp_path / "a.txt").write_text("dup")
        (tmp_path / "b.txt").write_text("dup")

        result = {
            "duplicates": [
                {"hash": "abc", "size": 3, "files": [
                    str(tmp_path / "a.txt"),
                    str(tmp_path / "b.txt"),
                ]}
            ]
        }
        file_set = extract_file_set(result, "find_duplicates")
        assert len(file_set) == 2

    def test_find_patterns_result(self, tmp_path: Path) -> None:
        """extract_file_set handles find_patterns result format."""
        (tmp_path / "file_001.txt").write_text("x")
        (tmp_path / "file_002.txt").write_text("x")

        result = {
            "patterns": [
                {"type": "sequence", "pattern": "file_{001}", "files": [
                    str(tmp_path / "file_001.txt"),
                    str(tmp_path / "file_002.txt"),
                ]}
            ]
        }
        file_set = extract_file_set(result, "find_patterns")
        assert len(file_set) == 2

    def test_empty_result(self) -> None:
        """extract_file_set handles empty results."""
        file_set = extract_file_set({}, "search_by_type")
        assert file_set == []

    def test_skips_unstatable_files(self, tmp_path: Path) -> None:
        """extract_file_set skips files that cannot be statted."""
        result = {
            "results": [
                {"name": "real.txt", "path": str(tmp_path / "real.txt"), "size": 1},
                {"name": "gone.txt", "path": "/nonexistent/file.txt", "size": 0},
            ]
        }
        (tmp_path / "real.txt").write_text("ok")
        file_set = extract_file_set(result, "search_by_type")
        assert len(file_set) == 1
        assert file_set[0][0] == str(tmp_path / "real.txt")


# ---------------------------------------------------------------------------
# check_freshness tests
# ---------------------------------------------------------------------------


class TestFreshness:
    def test_fresh_when_no_changes(self, tmp_path: Path) -> None:
        """Cache is fresh when no files have changed."""
        init_db(tmp_path)
        (tmp_path / "a.txt").write_text("hello")
        file_set = [(str(tmp_path / "a.txt"), os.stat(tmp_path / "a.txt").st_mtime)]

        key = "k1"
        set_cache(tmp_path, key, "t", str(tmp_path), json.dumps({}), file_set)

        assert check_freshness(tmp_path, key) is True

    def test_stale_when_file_modified(self, tmp_path: Path) -> None:
        """Cache is stale when a cached file has been modified."""
        init_db(tmp_path)
        (tmp_path / "a.txt").write_text("hello")
        file_set = [(str(tmp_path / "a.txt"), os.stat(tmp_path / "a.txt").st_mtime)]

        key = "k1"
        set_cache(tmp_path, key, "t", str(tmp_path), json.dumps({}), file_set)

        # Modify the file
        time.sleep(0.05)
        (tmp_path / "a.txt").write_text("modified")

        assert check_freshness(tmp_path, key) is False

    def test_stale_when_new_file_added(self, tmp_path: Path) -> None:
        """Cache is stale when a new file appears in the directory."""
        init_db(tmp_path)
        (tmp_path / "a.txt").write_text("hello")
        file_set = [(str(tmp_path / "a.txt"), os.stat(tmp_path / "a.txt").st_mtime)]

        key = "k1"
        set_cache(tmp_path, key, "t", str(tmp_path), json.dumps({}), file_set)

        # Add a new file
        time.sleep(0.05)
        (tmp_path / "b.txt").write_text("new")

        assert check_freshness(tmp_path, key) is False

    def test_stale_when_file_deleted(self, tmp_path: Path) -> None:
        """Cache is stale when a cached file is deleted."""
        init_db(tmp_path)
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world")
        file_set = [
            (str(tmp_path / "a.txt"), os.stat(tmp_path / "a.txt").st_mtime),
            (str(tmp_path / "b.txt"), os.stat(tmp_path / "b.txt").st_mtime),
        ]

        key = "k1"
        set_cache(tmp_path, key, "t", str(tmp_path), json.dumps({}), file_set)

        # Delete a file
        (tmp_path / "b.txt").unlink()

        assert check_freshness(tmp_path, key) is False

    def test_fresh_when_no_files_recorded(self, tmp_path: Path) -> None:
        """Cache with no file set is always fresh (empty result)."""
        init_db(tmp_path)
        key = "k1"
        set_cache(tmp_path, key, "t", str(tmp_path), json.dumps({}), [])

        assert check_freshness(tmp_path, key) is True

    def test_nonexistent_key_returns_false(self, tmp_path: Path) -> None:
        """check_freshness returns False for nonexistent key."""
        init_db(tmp_path)
        assert check_freshness(tmp_path, "nope") is False

    def test_skips_dotfilegraph_in_walk(self, tmp_path: Path) -> None:
        """Freshness check excludes .filegraph directory from file set comparison."""
        init_db(tmp_path)
        (tmp_path / "a.txt").write_text("hello")
        file_set = [(str(tmp_path / "a.txt"), os.stat(tmp_path / "a.txt").st_mtime)]

        key = "k1"
        set_cache(tmp_path, key, "t", str(tmp_path), json.dumps({}), file_set)

        # .filegraph/cache.db exists but should not cause staleness
        assert check_freshness(tmp_path, key) is True


# ---------------------------------------------------------------------------
# get_or_scan tests
# ---------------------------------------------------------------------------


class TestGetOrScan:
    def test_cache_hit_returns_cached(self, tmp_path: Path) -> None:
        """get_or_scan returns cached result on cache hit."""
        init_db(tmp_path)
        (tmp_path / "a.txt").write_text("hello")

        scan_count = [0]
        def mock_scan():
            scan_count[0] += 1
            return {"results": [{"name": "a.txt", "path": str(tmp_path / "a.txt"), "size": 5}]}

        r1 = get_or_scan(tmp_path, "search_by_type", str(tmp_path), mock_scan)
        assert scan_count[0] == 1

        r2 = get_or_scan(tmp_path, "search_by_type", str(tmp_path), mock_scan)
        assert scan_count[0] == 1  # No re-scan
        assert r1 == r2

    def test_cache_miss_triggers_scan(self, tmp_path: Path) -> None:
        """get_or_scan scans when no cache entry exists."""
        init_db(tmp_path)
        scan_called = [False]

        def mock_scan():
            scan_called[0] = True
            return {"results": []}

        get_or_scan(tmp_path, "search_by_type", str(tmp_path), mock_scan)
        assert scan_called[0]

    def test_stale_cache_triggers_rescan(self, tmp_path: Path) -> None:
        """get_or_scan re-scans when cache is stale."""
        init_db(tmp_path)
        (tmp_path / "a.txt").write_text("hello")

        scan_count = [0]
        def mock_scan():
            scan_count[0] += 1
            return {"results": [{"name": "a.txt", "path": str(tmp_path / "a.txt"), "size": 5}]}

        get_or_scan(tmp_path, "search_by_type", str(tmp_path), mock_scan)
        assert scan_count[0] == 1

        # Modify file to invalidate cache
        time.sleep(0.05)
        (tmp_path / "a.txt").write_text("modified")

        get_or_scan(tmp_path, "search_by_type", str(tmp_path), mock_scan)
        assert scan_count[0] == 2  # Re-scanned

    def test_result_is_json_roundtrip(self, tmp_path: Path) -> None:
        """Cached result survives JSON serialization round-trip."""
        init_db(tmp_path)
        (tmp_path / "a.txt").write_text("hello")

        original = {"tree": {"name": "root", "type": "directory", "children": []}}

        def mock_scan():
            return original

        r1 = get_or_scan(tmp_path, "scan_directory", str(tmp_path), mock_scan)
        r2 = get_or_scan(tmp_path, "scan_directory", str(tmp_path), mock_scan)
        assert r1 == r2
        assert r1 == original
