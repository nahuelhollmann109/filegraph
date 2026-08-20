#!/usr/bin/env bash
# setup-mcp.sh — Install/uninstall graph MCP server in OpenCode
# Works from any location — auto-detects project root
set -euo pipefail

OPENCODE_CONFIG="${HOME}/.config/opencode/opencode.json"
SERVER_NAME="filegraph"

# Detect project root: look for pyproject.toml walking up from script location
find_project_root() {
  local dir
  dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

  while [[ "$dir" != "/" ]]; do
    if [[ -f "${dir}/pyproject.toml" ]]; then
      echo "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done

  echo "Error: Could not find project root (pyproject.toml not found)" >&2
  exit 1
}

PROJECT_DIR="$(find_project_root)"

usage() {
  cat <<EOF
Usage: $(basename "$0") [install|uninstall|status]

Commands:
  install     Add filegraph MCP server to OpenCode config
  uninstall   Remove filegraph MCP server from OpenCode config
  status      Check if filegraph MCP server is installed

EOF
}

cmd_install() {
  if ! command -v jq &>/dev/null; then
    echo "Error: jq is required. Install with: sudo apt install jq" >&2
    exit 1
  fi

  if [[ ! -f "$OPENCODE_CONFIG" ]]; then
    echo "Error: OpenCode config not found at $OPENCODE_CONFIG" >&2
    exit 1
  fi

  # Check if already installed
  if jq -e ".mcp.${SERVER_NAME}" "$OPENCODE_CONFIG" &>/dev/null; then
    echo "FileGraph MCP server is already installed."
    echo "Run '$(basename "$0") uninstall' first to reinstall."
    exit 0
  fi

  # Verify project has the entry point
  if [[ ! -f "${PROJECT_DIR}/src/main.py" ]]; then
    echo "Error: src/main.py not found in ${PROJECT_DIR}" >&2
    exit 1
  fi

  # Create temp file with jq update
  local tmp
  tmp=$(mktemp)
  trap 'rm -f "'"$tmp"'"' EXIT

  jq --arg name "$SERVER_NAME" \
     --arg cmd "python3" \
     --arg arg1 "-m" \
     --arg arg2 "src.main" \
     --arg cwd "$PROJECT_DIR" \
     '.mcp[$name] = {
        "command": [$cmd, $arg1, $arg2],
        "type": "local",
        "cwd": $cwd
      }' "$OPENCODE_CONFIG" > "$tmp"

  # Validate JSON before overwriting
  if ! jq empty "$tmp" 2>/dev/null; then
    echo "Error: Generated invalid JSON. Aborting." >&2
    exit 1
  fi

  cp "$tmp" "$OPENCODE_CONFIG"
  echo "✅ FileGraph MCP server installed in OpenCode."
  echo "   Server: ${SERVER_NAME}"
  echo "   Command: python3 -m src.main"
  echo "   CWD: ${PROJECT_DIR}"
  echo ""
  echo "Restart OpenCode to load the new MCP server."
}

cmd_uninstall() {
  if ! command -v jq &>/dev/null; then
    echo "Error: jq is required." >&2
    exit 1
  fi

  if [[ ! -f "$OPENCODE_CONFIG" ]]; then
    echo "Error: OpenCode config not found at $OPENCODE_CONFIG" >&2
    exit 1
  fi

  # Check if installed
  if ! jq -e ".mcp.${SERVER_NAME}" "$OPENCODE_CONFIG" &>/dev/null; then
    echo "FileGraph MCP server is not installed."
    exit 0
  fi

  local tmp
  tmp=$(mktemp)
  trap 'rm -f "'"$tmp"'"' EXIT

  jq --arg name "$SERVER_NAME" 'del(.mcp[$name])' "$OPENCODE_CONFIG" > "$tmp"

  if ! jq empty "$tmp" 2>/dev/null; then
    echo "Error: Generated invalid JSON. Aborting." >&2
    exit 1
  fi

  cp "$tmp" "$OPENCODE_CONFIG"
  echo "✅ FileGraph MCP server removed from OpenCode."
  echo ""
  echo "Restart OpenCode to unload the MCP server."
}

cmd_status() {
  if ! command -v jq &>/dev/null; then
    echo "Error: jq is required." >&2
    exit 1
  fi

  if [[ ! -f "$OPENCODE_CONFIG" ]]; then
    echo "Error: OpenCode config not found at $OPENCODE_CONFIG" >&2
    exit 1
  fi

  if jq -e ".mcp.${SERVER_NAME}" "$OPENCODE_CONFIG" &>/dev/null; then
    echo "✅ FileGraph MCP server is INSTALLED."
    echo ""
    jq ".mcp.${SERVER_NAME}" "$OPENCODE_CONFIG"
  else
    echo "❌ FileGraph MCP server is NOT installed."
    echo ""
    echo "Run '$(basename "$0") install' to add it."
  fi
}

# Main
if [[ $# -eq 0 ]]; then
  usage
  exit 1
fi

case "$1" in
  install)   cmd_install ;;
  uninstall) cmd_uninstall ;;
  status)    cmd_status ;;
  *)
    echo "Error: Unknown command '$1'" >&2
    usage
    exit 1
    ;;
esac
