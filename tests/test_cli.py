"""Integration tests for CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.cli import main


class TestCliScan:
    def test_scan_tree_format(self, tmp_path: Path) -> None:
        """scan with --format tree outputs tree characters."""
        (tmp_path / "file.txt").write_text("data")
        rc = main(["scan", str(tmp_path), "--format", "tree"])
        assert rc == 0

    def test_scan_json_format(self, tmp_path: Path) -> None:
        """scan with --format json outputs valid JSON."""
        (tmp_path / "file.txt").write_text("data")
        rc = main(["scan", str(tmp_path), "--format", "json"])
        assert rc == 0

    def test_scan_no_exclude(self, tmp_path: Path) -> None:
        """scan with --no-exclude includes default excluded dirs."""
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("git")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("code")

        rc = main(["scan", str(tmp_path), "--format", "json", "--no-exclude"])
        assert rc == 0

    def test_scan_nonexistent_path(self) -> None:
        """scan with nonexistent path returns error."""
        rc = main(["scan", "/nonexistent/path"])
        assert rc == 1


class TestCliSearch:
    def test_search_json_format(self, tmp_path: Path) -> None:
        """search with --format json outputs valid JSON."""
        (tmp_path / "photo.jpg").write_bytes(b"\xff")
        rc = main(["search", str(tmp_path), "jpg", "--format", "json"])
        assert rc == 0

    def test_search_tree_format(self, tmp_path: Path) -> None:
        """search with --format tree outputs results."""
        (tmp_path / "photo.jpg").write_bytes(b"\xff")
        rc = main(["search", str(tmp_path), "jpg", "--format", "tree"])
        assert rc == 0

    def test_search_no_exclude(self, tmp_path: Path) -> None:
        """search with --no-exclude includes excluded dirs."""
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "hook.py").write_text("hook")
        rc = main(["search", str(tmp_path), "py", "--format", "json", "--no-exclude"])
        assert rc == 0

    def test_search_nonexistent_path(self) -> None:
        """search with nonexistent path returns error."""
        rc = main(["search", "/nonexistent/path", "txt"])
        assert rc == 1


class TestCliFindDuplicates:
    def test_duplicates_json_format(self, tmp_path: Path) -> None:
        """find-duplicates with --format json outputs valid JSON."""
        content = b"identical"
        (tmp_path / "a.txt").write_bytes(content)
        (tmp_path / "b.txt").write_bytes(content)
        rc = main(["find-duplicates", str(tmp_path), "--format", "json"])
        assert rc == 0

    def test_duplicates_tree_format(self, tmp_path: Path) -> None:
        """find-duplicates with --format tree outputs groups."""
        content = b"identical"
        (tmp_path / "a.txt").write_bytes(content)
        (tmp_path / "b.txt").write_bytes(content)
        rc = main(["find-duplicates", str(tmp_path), "--format", "tree"])
        assert rc == 0

    def test_duplicates_no_matches(self, tmp_path: Path) -> None:
        """find-duplicates with no duplicates returns empty."""
        (tmp_path / "unique.txt").write_bytes(b"different")
        rc = main(["find-duplicates", str(tmp_path)])
        assert rc == 0


class TestCliFindPatterns:
    def test_patterns_json_format(self, tmp_path: Path) -> None:
        """find-patterns with --format json outputs valid JSON."""
        for i in range(4):
            (tmp_path / f"file_{i:03d}.txt").write_text(f"data {i}")
        rc = main(["find-patterns", str(tmp_path), "--format", "json"])
        assert rc == 0

    def test_patterns_tree_format(self, tmp_path: Path) -> None:
        """find-patterns with --format tree outputs groups."""
        for i in range(4):
            (tmp_path / f"file_{i:03d}.txt").write_text(f"data {i}")
        rc = main(["find-patterns", str(tmp_path), "--format", "tree"])
        assert rc == 0

    def test_patterns_no_matches(self, tmp_path: Path) -> None:
        """find-patterns with no patterns returns empty."""
        (tmp_path / "random.txt").write_text("data")
        rc = main(["find-patterns", str(tmp_path)])
        assert rc == 0


class TestCliNoCommand:
    def test_no_args_returns_1(self) -> None:
        """No command shows help and returns 1."""
        rc = main([])
        assert rc == 1
