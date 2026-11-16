"""Contract of the MCP entry that the installer writes.

These drive ``scripts/setup-mcp.sh install`` as a black box against a scratch
config, because what users depend on is the entry that ends up on disk, not the
jq expression that produces it. The entry is a consumed contract: a stale module
name leaves the server unable to start while everything still looks installed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "scripts" / "setup-mcp.sh"
PROJECT_ROOT = str(REPO_ROOT)
MODULE = "filegraph.main"

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None, reason="scripts/setup-mcp.sh requires jq"
)


def run(config: Path, command: str) -> subprocess.CompletedProcess[str]:
    """Run the installer as a user would, pointed at one scratch config."""
    env = dict(
        os.environ,
        OPENCODE_CONFIG=str(config),
        FILEGRAPH_PYTHON=sys.executable,
    )
    return subprocess.run(
        ["bash", str(INSTALLER), command],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def install(config: Path) -> subprocess.CompletedProcess[str]:
    return run(config, "install")


def entry_of(config: Path) -> dict:
    return json.loads(config.read_text(encoding="utf-8"))["mcp"]["filegraph"]


def test_install_registers_the_filegraph_module_and_keeps_other_keys(tmp_path):
    config = tmp_path / "opencode.json"
    config.write_text(
        json.dumps({"mcp": {"other": {"command": ["x"]}}, "theme": "dark"}),
        encoding="utf-8",
    )

    result = install(config)

    assert result.returncode == 0, result.stderr
    entry = entry_of(config)
    assert entry["command"] == [sys.executable, "-m", MODULE]
    assert entry["cwd"] == PROJECT_ROOT
    assert entry["type"] == "local"
    written = json.loads(config.read_text(encoding="utf-8"))
    assert written["theme"] == "dark"
    assert written["mcp"]["other"] == {"command": ["x"]}


def test_repair_updates_a_stale_src_module_and_cwd(tmp_path):
    config = tmp_path / "opencode.json"
    config.write_text(
        json.dumps(
            {
                "mcp": {
                    "filegraph": {
                        "command": ["/old/python", "-m", "src.main"],
                        "type": "local",
                        "cwd": "/old/checkout",
                    }
                },
                "theme": "dark",
            }
        ),
        encoding="utf-8",
    )

    result = install(config)

    assert result.returncode == 0, result.stderr
    entry = entry_of(config)
    assert entry["command"] == [sys.executable, "-m", MODULE]
    assert entry["cwd"] == PROJECT_ROOT
    assert json.loads(config.read_text(encoding="utf-8"))["theme"] == "dark"


def test_repair_keeps_keys_the_user_added_inside_the_entry(tmp_path):
    """The installer owns command, type and cwd. Everything else is the user's."""
    config = tmp_path / "opencode.json"
    config.write_text(
        json.dumps(
            {
                "mcp": {
                    "filegraph": {
                        "command": ["/old/python", "-m", "src.main"],
                        "type": "local",
                        "cwd": "/old/checkout",
                        "enabled": False,
                        "env": {"API_KEY": "secret"},
                        "description": "user note",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = install(config)

    assert result.returncode == 0, result.stderr
    entry = entry_of(config)
    assert entry["command"] == [sys.executable, "-m", MODULE]
    assert entry["enabled"] is False
    assert entry["env"] == {"API_KEY": "secret"}
    assert entry["description"] == "user note"


def test_second_install_is_a_no_op_and_the_backup_stays_pristine(tmp_path):
    config = tmp_path / "opencode.json"
    original = json.dumps({"mcp": {}})
    config.write_text(original, encoding="utf-8")

    assert install(config).returncode == 0
    backup = config.with_name(config.name + ".filegraph.bak")
    assert backup.read_text(encoding="utf-8") == original
    after_first = config.read_bytes()

    result = install(config)

    assert result.returncode == 0, result.stderr
    assert "already installed" in result.stdout
    assert config.read_bytes() == after_first
    assert backup.read_text(encoding="utf-8") == original


def test_repair_rewrites_a_command_whose_shape_is_not_an_array(tmp_path):
    """A hand-edited string command has no index 2; it must still be repaired.

    jq fails with "Cannot index string with number" when asked for
    ``.command[2]`` of a string, and the installer used to abort there with that
    raw error instead of rewriting the entry.
    """
    config = tmp_path / "opencode.json"
    config.write_text(
        json.dumps(
            {
                "mcp": {
                    "filegraph": {
                        "command": "python3 -m src.main",
                        "type": "local",
                        "enabled": False,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = install(config)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    entry = entry_of(config)
    assert entry["command"] == [sys.executable, "-m", MODULE]
    assert entry["cwd"] == PROJECT_ROOT
    assert entry["enabled"] is False
    # Both halves of the repair notice: what the entry had, and what it becomes.
    assert "'command' is not an array: \"python3 -m src.main\"" in result.stdout
    assert "Rewriting it as [interpreter, -m, module]." in result.stdout


def test_status_reports_a_non_array_command_instead_of_failing(tmp_path):
    config = tmp_path / "opencode.json"
    config.write_text(
        json.dumps({"mcp": {"filegraph": {"command": "python3 -m src.main"}}}),
        encoding="utf-8",
    )

    result = run(config, "status")

    assert result.returncode == 0
    assert result.stderr == ""
    assert "INSTALLED" in result.stdout
    assert "not an array" in result.stdout
    assert "python3 -m src.main" in result.stdout
    assert "install" in result.stdout


def test_status_still_flags_an_array_entry_that_runs_another_module(tmp_path):
    """The warning for a well-formed but stale entry must survive the shape check."""
    config = tmp_path / "opencode.json"
    config.write_text(
        json.dumps(
            {
                "mcp": {
                    "filegraph": {
                        "command": ["/old/python", "-m", "src.main"],
                        "cwd": "/old/checkout",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = run(config, "status")

    assert result.returncode == 0
    assert result.stderr == ""
    assert "INSTALLED" in result.stdout
    assert "The entry runs '-m src.main'" in result.stdout
    assert f"expects '-m {MODULE}'" in result.stdout


def test_status_says_nothing_extra_when_the_entry_already_matches(tmp_path):
    config = tmp_path / "opencode.json"
    config.write_text(json.dumps({"mcp": {}}), encoding="utf-8")
    assert install(config).returncode == 0

    result = run(config, "status")

    assert result.returncode == 0
    assert "INSTALLED" in result.stdout
    assert "⚠️" not in result.stdout


def test_malformed_config_is_reported_and_left_untouched(tmp_path):
    config = tmp_path / "opencode.json"
    config.write_text('{"mcp": {,}', encoding="utf-8")
    original = config.read_bytes()

    result = install(config)

    assert result.returncode != 0
    assert config.read_bytes() == original
