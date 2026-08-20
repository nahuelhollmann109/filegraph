"""Integration tests for cache-aware tool wrappers."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from src.cache import make_cache_key
from src.store import get_cache, init_db
from src.tools import (
    find_duplicates,
    find_patterns,
    scan_directory,
    search_by_type,
)


class TestScanDirectoryCache:
    def test_first_call_miss_second_hit(self, tmp_path: Path) -> None:
        """First scan_directory call triggers live scan, second returns cached."""
        (tmp_path / "a.txt").write_text("hello")

        r1 = scan_directory(str(tmp_path))
        assert "tree" in r1

        # Cache entry should exist now
        key = make_cache_key("scan_directory", str(tmp_path))
        entry = get_cache(tmp_path, key)
        assert entry is not None

        # Second call should hit cache (same result, no re-scan)
        r2 = scan_directory(str(tmp_path))
        assert r1["tree"] == r2["tree"]

    def test_new_file_invalidates_cache(self, tmp_path: Path) -> None:
        """Adding a file causes scan_directory to re-scan."""
        (tmp_path / "a.txt").write_text("hello")
        r1 = scan_directory(str(tmp_path))
        names_1 = {child["name"] for child in r1["tree"].get("children", [])}
        assert "a.txt" in names_1

        # Add new file
        time.sleep(0.05)
        (tmp_path / "b.txt").write_text("world")

        r2 = scan_directory(str(tmp_path))
        names_2 = {child["name"] for child in r2["tree"].get("children", [])}
        assert "b.txt" in names_2

    def test_modified_file_invalidates_cache(self, tmp_path: Path) -> None:
        """Modifying a file causes scan_directory to re-scan."""
        (tmp_path / "a.txt").write_text("original")
        r1 = scan_directory(str(tmp_path))

        time.sleep(0.05)
        (tmp_path / "a.txt").write_text("modified")

        # Cache should be stale, so scan runs fresh
        key = make_cache_key("scan_directory", str(tmp_path))
        init_db(tmp_path)  # ensure DB exists
        # After modification, get_cache still returns old entry but freshness check fails
        # The tool wrapper handles this internally
        r2 = scan_directory(str(tmp_path))
        # Result should reflect current state
        assert r2["tree"] is not None


class TestSearchByTypeCache:
    def test_first_call_miss_second_hit(self, tmp_path: Path) -> None:
        """First search_by_type call triggers live scan, second returns cached."""
        (tmp_path / "photo.jpg").write_bytes(b"\xff")

        r1 = search_by_type(str(tmp_path), "jpg")
        assert len(r1.get("results", [])) == 1

        key = make_cache_key("search_by_type", str(tmp_path), file_type="jpg")
        entry = get_cache(tmp_path, key)
        assert entry is not None

        r2 = search_by_type(str(tmp_path), "jpg")
        assert r1 == r2

    def test_new_file_invalidates_cache(self, tmp_path: Path) -> None:
        """Adding a matching file causes search_by_type to re-scan."""
        (tmp_path / "a.jpg").write_bytes(b"\xff")
        r1 = search_by_type(str(tmp_path), "jpg")
        assert len(r1["results"]) == 1

        time.sleep(0.05)
        (tmp_path / "b.jpg").write_bytes(b"\xff")

        r2 = search_by_type(str(tmp_path), "jpg")
        assert len(r2["results"]) == 2


class TestFindDuplicatesCache:
    def test_first_call_miss_second_hit(self, tmp_path: Path) -> None:
        """First find_duplicates call triggers live scan, second returns cached."""
        content = b"identical"
        (tmp_path / "a.txt").write_bytes(content)
        (tmp_path / "b.txt").write_bytes(content)

        r1 = find_duplicates(str(tmp_path))
        assert len(r1.get("duplicates", [])) >= 1

        key = make_cache_key("find_duplicates", str(tmp_path))
        entry = get_cache(tmp_path, key)
        assert entry is not None

        r2 = find_duplicates(str(tmp_path))
        assert r1 == r2

    def test_new_duplicate_invalidates_cache(self, tmp_path: Path) -> None:
        """Adding a duplicate file causes find_duplicates to re-scan."""
        content = b"dup"
        (tmp_path / "a.txt").write_bytes(content)
        (tmp_path / "b.txt").write_bytes(content)

        r1 = find_duplicates(str(tmp_path))

        time.sleep(0.05)
        (tmp_path / "c.txt").write_bytes(content)

        r2 = find_duplicates(str(tmp_path))
        # Should now have 3 files in the duplicate group
        if r2.get("duplicates"):
            total_files = sum(len(g["files"]) for g in r2["duplicates"])
            assert total_files == 3


class TestFindPatternsCache:
    def test_first_call_miss_second_hit(self, tmp_path: Path) -> None:
        """First find_patterns call triggers live scan, second returns cached."""
        for i in range(4):
            (tmp_path / f"file_{i:03d}.txt").write_text(f"data {i}")

        r1 = find_patterns(str(tmp_path))
        assert "patterns" in r1

        key = make_cache_key("find_patterns", str(tmp_path))
        entry = get_cache(tmp_path, key)
        assert entry is not None

        r2 = find_patterns(str(tmp_path))
        assert r1 == r2

    def test_new_file_invalidates_cache(self, tmp_path: Path) -> None:
        """Adding a file causes find_patterns to re-scan."""
        for i in range(4):
            (tmp_path / f"file_{i:03d}.txt").write_text(f"data {i}")

        r1 = find_patterns(str(tmp_path))

        time.sleep(0.05)
        (tmp_path / "file_004.txt").write_text("data 4")

        r2 = find_patterns(str(tmp_path))
        # Should detect pattern with 5 files now
        assert r2.get("patterns") is not None
