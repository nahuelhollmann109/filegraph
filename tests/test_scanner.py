"""Unit tests for directory scanning logic."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from src.scanner import (
    DEFAULT_EXCLUDED_DIRS,
    _resolve_exclusions,
    file_info,
    find_duplicates,
    find_patterns,
    scan_tree,
    search_files,
    walk_directory,
)


# ---------------------------------------------------------------------------
# scan_tree tests
# ---------------------------------------------------------------------------


class TestScanTree:
    def test_happy_path(self, tmp_path: Path) -> None:
        """scan_tree returns correct tree structure for nested dirs."""
        (tmp_path / "subdir1").mkdir()
        (tmp_path / "subdir2").mkdir()
        (tmp_path / "file1.txt").write_text("hello")
        (tmp_path / "subdir1" / "nested.txt").write_text("nested")

        result = scan_tree(tmp_path)
        tree = result["tree"]

        assert tree["type"] == "directory"
        assert tree["name"] == tmp_path.name
        assert len(tree["children"]) == 3  # file1.txt, subdir1, subdir2

        names = {c["name"] for c in tree["children"]}
        assert "file1.txt" in names
        assert "subdir1" in names

        subdir1 = next(c for c in tree["children"] if c["name"] == "subdir1")
        assert subdir1["type"] == "directory"
        assert len(subdir1["children"]) == 1
        assert subdir1["children"][0]["name"] == "nested.txt"

    def test_max_depth_honored(self, tmp_path: Path) -> None:
        """scan_tree with max_depth=1 returns only top-level entries."""
        (tmp_path / "level1").mkdir()
        (tmp_path / "level1" / "level2").mkdir()
        (tmp_path / "level1" / "level2" / "level3.txt").write_text("deep")
        (tmp_path / "top.txt").write_text("top")

        result = scan_tree(tmp_path, max_depth=1)
        tree = result["tree"]

        names = {c["name"] for c in tree["children"]}
        assert "top.txt" in names
        assert "level1" in names

        level1 = next(c for c in tree["children"] if c["name"] == "level1")
        # max_depth=1 means directory children are empty
        assert level1["children"] == []

    def test_permission_error_returns_partial(self, tmp_path: Path) -> None:
        """scan_tree returns partial results when a subfolder is unreadable."""
        (tmp_path / "good").mkdir()
        (tmp_path / "good" / "file.txt").write_text("ok")
        (tmp_path / "noaccess").mkdir()

        # Remove read permission
        os.chmod(tmp_path / "noaccess", 0o000)

        try:
            result = scan_tree(tmp_path)
            tree = result["tree"]
            warnings = result["warnings"]

            # The readable portion should be present
            names = {c["name"] for c in tree["children"]}
            assert "good" in names

            # There should be a warning about the unreadable folder
            assert any("noaccess" in w for w in warnings)
        finally:
            # Restore permissions for cleanup
            os.chmod(tmp_path / "noaccess", 0o755)

    def test_symlink_not_followed(self, tmp_path: Path) -> None:
        """scan_tree records symlinks but does not recurse into them."""
        target = tmp_path / "real_dir"
        target.mkdir()
        (target / "secret.txt").write_text("secret")

        link = tmp_path / "link_dir"
        link.symlink_to(target)

        result = scan_tree(tmp_path)
        tree = result["tree"]

        link_node = next(
            (c for c in tree["children"] if c["name"] == "link_dir"), None
        )
        assert link_node is not None
        assert link_node["type"] == "symlink"
        assert "target" in link_node
        # Should NOT have children
        assert "children" not in link_node

    def test_unicode_filenames(self, tmp_path: Path) -> None:
        """scan_tree preserves Unicode filenames exactly."""
        unicode_name = "archivo_日本語.txt"
        (tmp_path / unicode_name).write_text("unicode test")

        result = scan_tree(tmp_path)
        tree = result["tree"]

        names = [c["name"] for c in tree["children"]]
        assert unicode_name in names

    def test_missing_path_rejected(self) -> None:
        """scan_tree rejects invocation without a path parameter."""
        with pytest.raises(TypeError):
            scan_tree()  # type: ignore[call-arg]

    def test_empty_directory(self, tmp_path: Path) -> None:
        """scan_tree handles empty directories."""
        result = scan_tree(tmp_path)
        tree = result["tree"]

        assert tree["type"] == "directory"
        assert tree["children"] == []
        assert result["warnings"] == []


# ---------------------------------------------------------------------------
# search_files tests
# ---------------------------------------------------------------------------


class TestSearchFiles:
    def test_happy_path(self, tmp_path: Path) -> None:
        """search_files filters by extension correctly."""
        (tmp_path / "photo.jpg").write_bytes(b"\xff")
        (tmp_path / "image.png").write_bytes(b"\x89")
        (tmp_path / "photo2.jpg").write_bytes(b"\xff")
        (tmp_path / "doc.txt").write_text("text")

        results = search_files(tmp_path, "jpg")

        assert len(results) == 2
        names = {r["name"] for r in results}
        assert names == {"photo.jpg", "photo2.jpg"}
        # Each result should have name, path, size
        for r in results:
            assert "name" in r
            assert "path" in r
            assert "size" in r

    def test_no_matches(self, tmp_path: Path) -> None:
        """search_files returns empty list when no files match."""
        (tmp_path / "doc.txt").write_text("text")

        results = search_files(tmp_path, "jpg")

        assert results == []

    def test_recursive_search(self, tmp_path: Path) -> None:
        """search_files searches recursively into subdirectories."""
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "nested.jpg").write_bytes(b"\xff")
        (tmp_path / "top.jpg").write_bytes(b"\xff")

        results = search_files(tmp_path, "jpg")

        assert len(results) == 2

    def test_excludes_symlinks(self, tmp_path: Path) -> None:
        """search_files does not include symlinks in results."""
        real = tmp_path / "real.jpg"
        real.write_bytes(b"\xff")
        link = tmp_path / "link.jpg"
        link.symlink_to(real)

        results = search_files(tmp_path, "jpg")

        assert len(results) == 1
        assert results[0]["name"] == "real.jpg"

    def test_nonexistent_path(self, tmp_path: Path) -> None:
        """search_files raises FileNotFoundError for missing path."""
        with pytest.raises(FileNotFoundError):
            search_files(tmp_path / "nope", "txt")


# ---------------------------------------------------------------------------
# file_info tests
# ---------------------------------------------------------------------------


class TestFileInfo:
    def test_happy_path(self, tmp_path: Path) -> None:
        """file_info returns size, dates, and permissions."""
        target = tmp_path / "test.txt"
        target.write_text("hello world")

        info = file_info(target)

        assert info["name"] == "test.txt"
        assert info["size"] == 11  # len("hello world")
        assert "modified" in info
        assert "created" in info
        assert "permissions" in info
        assert info["is_symlink"] is False

    def test_directory_raises(self, tmp_path: Path) -> None:
        """file_info raises IsADirectoryError for directories."""
        with pytest.raises(IsADirectoryError):
            file_info(tmp_path)

    def test_nonexistent_path(self, tmp_path: Path) -> None:
        """file_info raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            file_info(tmp_path / "nope.txt")

    def test_symlink_reported(self, tmp_path: Path) -> None:
        """file_info reports is_symlink=True for symlinks."""
        real = tmp_path / "real.txt"
        real.write_text("data")
        link = tmp_path / "link.txt"
        link.symlink_to(real)

        info = file_info(link)

        assert info["is_symlink"] is True
        assert info["name"] == "link.txt"

    def test_unicode_filename(self, tmp_path: Path) -> None:
        """file_info handles Unicode filenames."""
        name = "archivo_テスト.txt"
        target = tmp_path / name
        target.write_text("unicode")

        info = file_info(target)

        assert info["name"] == name


# ---------------------------------------------------------------------------
# DEFAULT_EXCLUDED_DIRS tests
# ---------------------------------------------------------------------------


class TestDefaultExcludedDirs:
    def test_contains_expected_dirs(self) -> None:
        """DEFAULT_EXCLUDED_DIRS contains the four standard exclusions."""
        assert ".git" in DEFAULT_EXCLUDED_DIRS
        assert "node_modules" in DEFAULT_EXCLUDED_DIRS
        assert "__pycache__" in DEFAULT_EXCLUDED_DIRS
        assert ".venv" in DEFAULT_EXCLUDED_DIRS

    def test_is_frozenset(self) -> None:
        """DEFAULT_EXCLUDED_DIRS is a frozenset (immutable)."""
        assert isinstance(DEFAULT_EXCLUDED_DIRS, frozenset)


# ---------------------------------------------------------------------------
# _resolve_exclusions tests
# ---------------------------------------------------------------------------


class TestResolveExclusions:
    def test_no_exclude_no_include(self) -> None:
        """None exclude_dirs + include_excluded=False → DEFAULT_EXCLUDED_DIRS."""
        result = _resolve_exclusions(None, False)
        assert result == DEFAULT_EXCLUDED_DIRS

    def test_custom_exclude_no_include(self) -> None:
        """Custom list + include_excluded=False → custom set."""
        result = _resolve_exclusions(["build", "dist"], False)
        assert result == {"build", "dist"}

    def test_no_exclude_with_include(self) -> None:
        """None exclude_dirs + include_excluded=True → empty set (no exclusions)."""
        result = _resolve_exclusions(None, True)
        assert result == set()

    def test_custom_exclude_with_include(self) -> None:
        """Custom list + include_excluded=True → custom set (override still applies)."""
        result = _resolve_exclusions(["build"], True)
        assert result == {"build"}


# ---------------------------------------------------------------------------
# walk_directory tests
# ---------------------------------------------------------------------------


class TestWalkDirectory:
    def test_yields_all_files(self, tmp_path: Path) -> None:
        """walk_directory yields all files in a simple directory."""
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "c.txt").write_text("c")

        files = sorted(walk_directory(tmp_path))
        assert len(files) == 3
        names = {f.name for f in files}
        assert names == {"a.txt", "b.txt", "c.txt"}

    def test_excludes_default_dirs(self, tmp_path: Path) -> None:
        """walk_directory skips .git, node_modules, __pycache__, .venv by default."""
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("git")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "pkg.js").write_text("js")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "mod.pyc").write_bytes(b"\x00")
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "lib").mkdir()
        (tmp_path / ".venv" / "lib" / "pkg").write_text("pkg")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("code")

        files = list(walk_directory(tmp_path))
        assert len(files) == 1
        assert files[0].name == "main.py"

    def test_custom_exclude_dirs(self, tmp_path: Path) -> None:
        """walk_directory respects custom exclude_dirs."""
        (tmp_path / "build").mkdir()
        (tmp_path / "build" / "out.js").write_text("js")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("py")

        files = list(walk_directory(tmp_path, exclude_dirs={"build"}))
        assert len(files) == 1
        assert files[0].name == "app.py"

    def test_empty_exclude_set_skips_nothing(self, tmp_path: Path) -> None:
        """walk_directory with empty set skips nothing."""
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("git")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("py")

        files = list(walk_directory(tmp_path, exclude_dirs=set()))
        assert len(files) == 2

    def test_max_depth_respected(self, tmp_path: Path) -> None:
        """walk_directory stops at max_depth."""
        (tmp_path / "level1").mkdir()
        (tmp_path / "level1" / "level2").mkdir()
        (tmp_path / "level1" / "level2" / "deep.txt").write_text("deep")
        (tmp_path / "level1" / "shallow.txt").write_text("shallow")
        (tmp_path / "top.txt").write_text("top")

        # max_depth=1: yields files at depth 0 (root) but not inside depth-1 dirs
        files = list(walk_directory(tmp_path, max_depth=1))
        names = {f.name for f in files}
        assert "top.txt" in names
        assert "shallow.txt" not in names
        assert "deep.txt" not in names

        # max_depth=2: yields files inside level1 but not inside level2
        files = list(walk_directory(tmp_path, max_depth=2))
        names = {f.name for f in files}
        assert "top.txt" in names
        assert "shallow.txt" in names
        assert "deep.txt" not in names

    def test_symlinks_skipped(self, tmp_path: Path) -> None:
        """walk_directory skips symlink files."""
        real = tmp_path / "real.txt"
        real.write_text("real")
        link = tmp_path / "link.txt"
        link.symlink_to(real)

        files = list(walk_directory(tmp_path))
        assert len(files) == 1
        assert files[0].name == "real.txt"

    def test_symlink_dirs_not_traversed(self, tmp_path: Path) -> None:
        """walk_directory skips symlink directories."""
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        (real_dir / "file.txt").write_text("file")
        link_dir = tmp_path / "link_dir"
        link_dir.symlink_to(real_dir)

        files = list(walk_directory(tmp_path))
        assert len(files) == 1
        assert files[0].name == "file.txt"

    def test_nonexistent_root(self, tmp_path: Path) -> None:
        """walk_directory yields nothing for nonexistent root."""
        files = list(walk_directory(tmp_path / "nope"))
        assert files == []

    def test_file_root(self, tmp_path: Path) -> None:
        """walk_directory yields nothing when root is a file."""
        f = tmp_path / "file.txt"
        f.write_text("data")
        files = list(walk_directory(f))
        assert files == []


# ---------------------------------------------------------------------------
# Exclusion integration: scan_tree
# ---------------------------------------------------------------------------


class TestScanTreeExclusion:
    def test_scan_tree_excludes_default_dirs(self, tmp_path: Path) -> None:
        """scan_tree omits .git, node_modules, __pycache__, .venv by default."""
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("git")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "pkg.js").write_text("js")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("code")

        result = scan_tree(tmp_path)
        tree = result["tree"]
        names = {c["name"] for c in tree["children"]}
        assert ".git" not in names
        assert "node_modules" not in names
        assert "src" in names

    def test_scan_tree_custom_exclude(self, tmp_path: Path) -> None:
        """scan_tree with custom exclude_dirs omits specified dirs."""
        (tmp_path / "build").mkdir()
        (tmp_path / "build" / "out.js").write_text("js")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("py")

        result = scan_tree(tmp_path, exclude_dirs={"build"})
        tree = result["tree"]
        names = {c["name"] for c in tree["children"]}
        assert "build" not in names
        assert "src" in names

    def test_scan_tree_empty_exclude_includes_all(self, tmp_path: Path) -> None:
        """scan_tree with empty exclude_dirs includes everything."""
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("git")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("py")

        result = scan_tree(tmp_path, exclude_dirs=set())
        tree = result["tree"]
        names = {c["name"] for c in tree["children"]}
        assert ".git" in names
        assert "src" in names


# ---------------------------------------------------------------------------
# Exclusion integration: search_files
# ---------------------------------------------------------------------------


class TestSearchFilesExclusion:
    def test_search_files_excludes_default_dirs(self, tmp_path: Path) -> None:
        """search_files skips .git by default."""
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "hooks").mkdir()
        (tmp_path / ".git" / "hooks" / "pre-commit.py").write_text("hook")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("app")

        results = search_files(tmp_path, "py")
        assert len(results) == 1
        assert results[0]["name"] == "app.py"

    def test_search_files_custom_exclude(self, tmp_path: Path) -> None:
        """search_files respects custom exclude_dirs."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_app.py").write_text("test")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("app")

        results = search_files(tmp_path, "py", exclude_dirs={"tests"})
        assert len(results) == 1
        assert results[0]["name"] == "app.py"


# ---------------------------------------------------------------------------
# find_duplicates tests
# ---------------------------------------------------------------------------


class TestFindDuplicates:
    def test_happy_path(self, tmp_path: Path) -> None:
        """find_duplicates groups identical files by hash."""
        content = b"identical content here"
        (tmp_path / "copy_a.txt").write_bytes(content)
        (tmp_path / "copy_b.txt").write_bytes(content)
        (tmp_path / "unique.txt").write_bytes(b"different content")

        results = find_duplicates(tmp_path)

        assert len(results) == 1
        group = results[0]
        assert group["size"] == len(content)
        assert len(group["files"]) == 2
        names = {Path(f).name for f in group["files"]}
        assert names == {"copy_a.txt", "copy_b.txt"}

    def test_no_duplicates(self, tmp_path: Path) -> None:
        """find_duplicates returns empty list when all files are unique."""
        (tmp_path / "a.txt").write_bytes(b"alpha")
        (tmp_path / "b.txt").write_bytes(b"beta")
        (tmp_path / "c.txt").write_bytes(b"gamma")

        results = find_duplicates(tmp_path)
        assert results == []

    def test_min_size_filter(self, tmp_path: Path) -> None:
        """find_duplicates ignores files smaller than min_size."""
        (tmp_path / "small_a.txt").write_bytes(b"hi")
        (tmp_path / "small_b.txt").write_bytes(b"hi")
        (tmp_path / "big_a.bin").write_bytes(b"x" * 100)
        (tmp_path / "big_b.bin").write_bytes(b"x" * 100)

        # min_size=50 should only return the big files
        results = find_duplicates(tmp_path, min_size=50)
        assert len(results) == 1
        assert results[0]["size"] == 100
        names = {Path(f).name for f in results[0]["files"]}
        assert names == {"big_a.bin", "big_b.bin"}

    def test_hash_algo_selection(self, tmp_path: Path) -> None:
        """find_duplicates uses the specified hash algorithm."""
        content = b"hash me please"
        (tmp_path / "a.bin").write_bytes(content)
        (tmp_path / "b.bin").write_bytes(content)

        results_md5 = find_duplicates(tmp_path, hash_algo="md5")
        assert len(results_md5) == 1
        # MD5 hex digest is 32 chars
        assert len(results_md5[0]["hash"]) == 32

        results_sha1 = find_duplicates(tmp_path, hash_algo="sha1")
        assert len(results_sha1) == 1
        # SHA1 hex digest is 40 chars
        assert len(results_sha1[0]["hash"]) == 40

    def test_invalid_hash_algo(self, tmp_path: Path) -> None:
        """find_duplicates returns empty list for invalid hash algorithm."""
        (tmp_path / "a.txt").write_bytes(b"data")
        (tmp_path / "b.txt").write_bytes(b"data")

        results = find_duplicates(tmp_path, hash_algo="not_a_real_algo")
        assert results == []

    def test_unreadable_files_skipped(self, tmp_path: Path) -> None:
        """find_duplicates skips files it cannot read."""
        (tmp_path / "good_a.txt").write_bytes(b"readable")
        (tmp_path / "good_b.txt").write_bytes(b"readable")
        (tmp_path / "bad.txt").write_bytes(b"secret")

        # Make bad.txt unreadable
        os.chmod(tmp_path / "bad.txt", 0o000)

        try:
            results = find_duplicates(tmp_path)
            assert len(results) == 1
            names = {Path(f).name for f in results[0]["files"]}
            assert names == {"good_a.txt", "good_b.txt"}
        finally:
            os.chmod(tmp_path / "bad.txt", 0o644)

    def test_symlinks_skipped(self, tmp_path: Path) -> None:
        """find_duplicates does not include symlinks."""
        real = tmp_path / "real.txt"
        real.write_bytes(b"content")
        link = tmp_path / "link.txt"
        link.symlink_to(real)

        results = find_duplicates(tmp_path)
        # Only the real file exists; no duplicates
        assert results == []

    def test_empty_directory(self, tmp_path: Path) -> None:
        """find_duplicates returns empty list for empty directory."""
        results = find_duplicates(tmp_path)
        assert results == []

    def test_nonexistent_path(self, tmp_path: Path) -> None:
        """find_duplicates returns empty list for nonexistent path."""
        results = find_duplicates(tmp_path / "nope")
        assert results == []

    def test_excludes_default_dirs(self, tmp_path: Path) -> None:
        """find_duplicates skips default excluded directories."""
        content = b"excluded duplicate"
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "obj_a").write_bytes(content)
        (tmp_path / ".git" / "obj_b").write_bytes(content)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.txt").write_bytes(b"unique")

        results = find_duplicates(tmp_path)
        assert results == []

    def test_three_way_duplicate(self, tmp_path: Path) -> None:
        """find_duplicates handles three or more identical files."""
        content = b"triple"
        (tmp_path / "a.txt").write_bytes(content)
        (tmp_path / "b.txt").write_bytes(content)
        (tmp_path / "c.txt").write_bytes(content)

        results = find_duplicates(tmp_path)
        assert len(results) == 1
        assert len(results[0]["files"]) == 3


# ---------------------------------------------------------------------------
# find_patterns tests
# ---------------------------------------------------------------------------


class TestFindPatterns:
    def test_sequence_strategy(self, tmp_path: Path) -> None:
        """find_patterns detects numeric sequences."""
        for i in range(1, 6):
            (tmp_path / f"photo_{i:03d}.jpg").write_bytes(b"\xff")

        results = find_patterns(tmp_path, strategy="sequence")
        assert len(results) >= 1
        seq = next(r for r in results if r["type"] == "sequence")
        assert len(seq["files"]) == 5

    def test_prefix_strategy(self, tmp_path: Path) -> None:
        """find_patterns detects common prefixes."""
        for i in range(4):
            (tmp_path / f"report_2024_{i}.txt").write_text(f"doc {i}")

        results = find_patterns(tmp_path, strategy="prefix")
        assert len(results) >= 1
        prefix_group = next(r for r in results if r["type"] == "prefix")
        assert len(prefix_group["files"]) >= 3
        assert len(prefix_group["pattern"]) >= 3

    def test_suffix_strategy(self, tmp_path: Path) -> None:
        """find_patterns detects common suffixes."""
        for i in range(4):
            (tmp_path / f"draft_v{i}_report.txt").write_text(f"v{i}")

        results = find_patterns(tmp_path, strategy="suffix")
        assert len(results) >= 1
        suffix_group = next(r for r in results if r["type"] == "suffix")
        assert len(suffix_group["files"]) >= 3
        assert len(suffix_group["pattern"]) >= 2

    def test_date_strategy(self, tmp_path: Path) -> None:
        """find_patterns detects date tokens in filenames."""
        for i in range(4):
            (tmp_path / f"photo_2024-01-{10+i:02d}.jpg").write_bytes(b"\xff")

        results = find_patterns(tmp_path, strategy="date")
        assert len(results) >= 1
        date_group = next(r for r in results if r["type"] == "date")
        assert len(date_group["files"]) == 4
        assert "YYYY" in date_group["pattern"]

    def test_min_group_size(self, tmp_path: Path) -> None:
        """find_patterns respects min_group_size."""
        # Create only 2 files with same prefix (below default min_group_size=3)
        for i in range(2):
            (tmp_path / f"item_{i}.txt").write_text(f"v{i}")

        results = find_patterns(tmp_path, strategy="prefix", min_group_size=5)
        # No group should have >= 5 members
        for r in results:
            assert len(r["files"]) >= 5

    def test_auto_mode(self, tmp_path: Path) -> None:
        """find_patterns with auto runs all strategies."""
        for i in range(5):
            (tmp_path / f"data_{i:03d}.txt").write_text(f"row {i}")

        results = find_patterns(tmp_path, strategy="auto")
        # Should detect at least the sequence pattern
        types = {r["type"] for r in results}
        assert "sequence" in types

    def test_nonexistent_path(self, tmp_path: Path) -> None:
        """find_patterns returns empty list for nonexistent path."""
        results = find_patterns(tmp_path / "nope")
        assert results == []

    def test_empty_directory(self, tmp_path: Path) -> None:
        """find_patterns returns empty list for empty directory."""
        results = find_patterns(tmp_path)
        assert results == []

    def test_invalid_strategy(self, tmp_path: Path) -> None:
        """find_patterns returns empty list for invalid strategy."""
        results = find_patterns(tmp_path, strategy="not_valid")
        assert results == []

    def test_date_with_underscores(self, tmp_path: Path) -> None:
        """find_patterns detects dates with underscore separators."""
        for i in range(4):
            (tmp_path / f"log_2024_{1+i:02d}_15.txt").write_text(f"entry {i}")

        results = find_patterns(tmp_path, strategy="date")
        assert len(results) >= 1

    def test_excludes_default_dirs(self, tmp_path: Path) -> None:
        """find_patterns skips default excluded directories."""
        (tmp_path / ".git").mkdir()
        for i in range(4):
            (tmp_path / ".git" / f"obj_{i:03d}.bin").write_bytes(b"\x00")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("code")

        results = find_patterns(tmp_path, strategy="sequence")
        # .git files should not be included
        for r in results:
            for f in r["files"]:
                assert ".git" not in f
