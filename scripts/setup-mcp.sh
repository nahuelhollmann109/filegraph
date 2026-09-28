#!/usr/bin/env bash
# setup-mcp.sh — Install/uninstall graph MCP server in OpenCode
# Works from any location — auto-detects project root
set -euo pipefail

OPENCODE_CONFIG="${OPENCODE_CONFIG:-}"
SERVER_NAME="filegraph"
PROJECT_DIR=""

# ─── Package manager hints ────────────────────────────────────────────────────
# Intentionally duplicated from install.sh: this script must work standalone,
# without the installer having been run.
detect_package_manager() {
  local pm
  for pm in apt-get dnf yum pacman zypper apk; do
    if command -v "${pm}" &>/dev/null; then
      echo "${pm}"
      return 0
    fi
  done
  echo ""
}

# Copy-pasteable install command for the given packages, in the detected
# package manager's dialect. Echoes nothing when no package manager was found.
package_install_cmd() {
  local pm
  pm="$(detect_package_manager)"

  case "${pm}" in
    apt-get) echo "sudo apt-get install -y $*" ;;
    dnf)     echo "sudo dnf install -y $*" ;;
    yum)     echo "sudo yum install -y $*" ;;
    pacman)  echo "sudo pacman -S --needed --noconfirm $*" ;;
    zypper)  echo "sudo zypper install -y $*" ;;
    apk)     echo "sudo apk add $*" ;;
  esac
}

require_jq() {
  if command -v jq &>/dev/null; then
    return 0
  fi

  local hint
  hint="$(package_install_cmd jq)"
  if [[ -n "${hint}" ]]; then
    echo "Error: jq is required to read and update the OpenCode config." >&2
    echo "       Install it with: ${hint}" >&2
  else
    echo "Error: jq is required to read and update the OpenCode config." >&2
    echo "       No supported package manager found (apt-get, dnf, yum, pacman," >&2
    echo "       zypper, apk) — install jq manually and re-run." >&2
  fi
  exit 1
}

# ─── Resolution ──────────────────────────────────────────────────────────────
# Resolve the OpenCode config file once, so install/uninstall/status can never
# disagree about which file they operate on. An explicit OPENCODE_CONFIG counts
# only when that file actually exists; otherwise fall through and probe both
# locations OpenCode uses — fresh installs create opencode.jsonc, older ones
# created opencode.json. install.sh resolves identically.
resolve_opencode_config() {
  if [[ -n "${OPENCODE_CONFIG}" ]] && [[ -f "${OPENCODE_CONFIG}" ]]; then
    return 0
  fi

  local candidate
  for candidate in \
    "${HOME}/.config/opencode/opencode.json" \
    "${HOME}/.config/opencode/opencode.jsonc"
  do
    if [[ -f "${candidate}" ]]; then
      OPENCODE_CONFIG="${candidate}"
      return 0
    fi
  done

  # Nothing exists: keep whatever the caller asked for, else the historical
  # default, so the error message names the path the user is expected to create.
  [[ -n "${OPENCODE_CONFIG}" ]] || OPENCODE_CONFIG="${HOME}/.config/opencode/opencode.json"
}

# This script rewrites the config with jq, and jq reads only plain JSON. A
# .jsonc file carrying comments is therefore unusable here. Stripping comments
# ourselves is not an option: "//" also occurs inside strings (e.g. "https://"),
# and a naive strip would corrupt the config. So: report it, and let the caller
# decide whether an unparseable config is fatal.
unparseable_config_warning() {
  echo "Warning: ${OPENCODE_CONFIG} is not valid JSON — it cannot be read." >&2
  if [[ "${OPENCODE_CONFIG}" == *.jsonc ]]; then
    echo "         jq (used here) does not support JSONC comments, which is the" >&2
    echo "         usual cause. Run 'opencode' once to regenerate it, or remove" >&2
    echo "         the comments / repair the file by hand." >&2
  else
    echo "         Validate or repair the file by hand, then re-run." >&2
  fi
}

# Mutating commands must never write to a file they cannot read back: a failed
# parse would risk destroying it. Hard failure.
assert_config_is_parseable() {
  if jq empty "$OPENCODE_CONFIG" 2>/dev/null; then
    return 0
  fi
  unparseable_config_warning
  exit 1
}

# Copy the mode of the config onto the temp file: mktemp creates 0600, and
# renaming it into place would silently tighten the user's config permissions.
copy_file_mode() {
  local src="$1" dst="$2" mode
  mode="$(stat -c '%a' "$src" 2>/dev/null)" || \
    mode="$(stat -f '%Lp' "$src" 2>/dev/null)" || return 0
  chmod "$mode" "$dst"
}

# ─── Project root ────────────────────────────────────────────────────────────
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

  return 1
}

# Resolved lazily and only when needed, so `status` and `help` keep working
# from outside a checkout.
require_project_dir() {
  if [[ -z "${PROJECT_DIR}" ]]; then
    PROJECT_DIR="$(find_project_root)" || {
      echo "Error: Could not find the project root (no pyproject.toml above $0)." >&2
      exit 1
    }
  fi
}

# Absolute path of the interpreter that will run the MCP server.
# Precedence: --python flag > $FILEGRAPH_PYTHON > python3.
# MCP entries are launched with cwd set to the project, so a bare name would be
# resolved against whatever PATH OpenCode happens to have — always go absolute.
resolve_python() {
  local candidate="${PYTHON_OVERRIDE:-${FILEGRAPH_PYTHON:-}}"

  if [[ -n "${candidate}" ]]; then
    if [[ -x "${candidate}" ]]; then
      echo "${candidate}"
      return 0
    fi
    echo "Error: interpreter is not executable: ${candidate}" >&2
    return 1
  fi

  if candidate="$(command -v python3 2>/dev/null)" && [[ -n "${candidate}" ]]; then
    echo "${candidate}"
    return 0
  fi

  echo "Error: no python3 found. Set FILEGRAPH_PYTHON or pass --python <path>." >&2
  return 1
}

usage() {
  cat <<EOF
Usage: $(basename "$0") [--python <path>] [install|uninstall|status]

Commands:
  install     Add filegraph MCP server to OpenCode config
  uninstall   Remove filegraph MCP server from OpenCode config
  status      Check if filegraph MCP server is installed
  help        Show this message

Options:
  --python <path>  Interpreter to run the MCP server with (absolute path)

Environment:
  OPENCODE_CONFIG  Path to the OpenCode config (default: auto-detected)
  FILEGRAPH_PYTHON  Interpreter to run the MCP server with

EOF
}

cmd_install() {
  require_jq

  if [[ ! -f "$OPENCODE_CONFIG" ]]; then
    echo "Error: OpenCode config not found at $OPENCODE_CONFIG" >&2
    exit 1
  fi

  assert_config_is_parseable

  # Check if already installed
  if jq -e ".mcp.${SERVER_NAME}" "$OPENCODE_CONFIG" &>/dev/null; then
    echo "FileGraph MCP server is already installed."
    echo "Run '$(basename "$0") uninstall' first to reinstall."
    exit 0
  fi

  require_project_dir

  # Verify project has the entry point
  if [[ ! -f "${PROJECT_DIR}/src/main.py" ]]; then
    echo "Error: src/main.py not found in ${PROJECT_DIR}" >&2
    exit 1
  fi

  # Resolve the interpreter before touching the config, so a bad --python fails
  # without leaving a half-written entry behind.
  local interpreter
  interpreter="$(resolve_python)" || exit 1

  # Build the new config in a temp file created NEXT TO the target, so the final
  # rename stays on one filesystem and is therefore atomic. A plain `cp` can
  # truncate the user's config if it is interrupted mid-write.
  local tmp
  tmp=$(mktemp "${OPENCODE_CONFIG}.filegraph.XXXXXX")
  trap 'rm -f "'"$tmp"'"' EXIT

  jq --arg name "$SERVER_NAME" \
     --arg cmd "$interpreter" \
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

  copy_file_mode "$OPENCODE_CONFIG" "$tmp"
  mv -f "$tmp" "$OPENCODE_CONFIG"
  trap - EXIT

  echo "✅ FileGraph MCP server installed in OpenCode."
  echo "   Server: ${SERVER_NAME}"
  echo "   Command: ${interpreter} -m src.main"
  echo "   CWD: ${PROJECT_DIR}"
  echo "   Config: ${OPENCODE_CONFIG}"
  echo ""
  echo "Restart OpenCode to load the new MCP server."
}

cmd_uninstall() {
  require_jq

  if [[ ! -f "$OPENCODE_CONFIG" ]]; then
    echo "Error: OpenCode config not found at $OPENCODE_CONFIG" >&2
    exit 1
  fi

  assert_config_is_parseable

  # Check if installed
  if ! jq -e ".mcp.${SERVER_NAME}" "$OPENCODE_CONFIG" &>/dev/null; then
    echo "FileGraph MCP server is not installed."
    exit 0
  fi

  local tmp
  tmp=$(mktemp "${OPENCODE_CONFIG}.filegraph.XXXXXX")
  trap 'rm -f "'"$tmp"'"' EXIT

  jq --arg name "$SERVER_NAME" 'del(.mcp[$name])' "$OPENCODE_CONFIG" > "$tmp"

  if ! jq empty "$tmp" 2>/dev/null; then
    echo "Error: Generated invalid JSON. Aborting." >&2
    exit 1
  fi

  copy_file_mode "$OPENCODE_CONFIG" "$tmp"
  mv -f "$tmp" "$OPENCODE_CONFIG"
  trap - EXIT

  echo "✅ FileGraph MCP server removed from OpenCode."
  echo ""
  echo "Restart OpenCode to unload the MCP server."
}

cmd_status() {
  require_jq

  if [[ ! -f "$OPENCODE_CONFIG" ]]; then
    echo "Error: OpenCode config not found at $OPENCODE_CONFIG" >&2
    exit 1
  fi

  # `status` only reads, so an unparseable config is reported, not fatal: the
  # previous behaviour of a hard error here was noise for a read-only command.
  if ! jq empty "$OPENCODE_CONFIG" 2>/dev/null; then
    unparseable_config_warning
    echo "❌ FileGraph MCP server state could not be determined." >&2
    echo "   Treat it as NOT registered and repair the config above." >&2
    exit 0
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

# ─── Arguments ───────────────────────────────────────────────────────────────
# Accepts the command and --python in any order so callers can write
# `setup-mcp.sh install --python /abs/path` as well as `--python ... install`.
parse_args() {
  COMMAND=""
  PYTHON_OVERRIDE=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --python)
        if [[ $# -lt 2 ]]; then
          echo "Error: --python requires a path" >&2
          exit 1
        fi
        PYTHON_OVERRIDE="$2"
        shift 2
        ;;
      --python=*)
        PYTHON_OVERRIDE="${1#*=}"
        shift
        ;;
      -h|--help)
        COMMAND="help"
        shift
        ;;
      -*)
        echo "Error: Unknown option '$1'" >&2
        usage
        exit 1
        ;;
      *)
        if [[ -z "$COMMAND" ]]; then
          COMMAND="$1"
        fi
        shift
        ;;
    esac
  done
}

# Main
parse_args "$@"

if [[ -z "$COMMAND" ]]; then
  usage
  exit 1
fi

# `help` must work from anywhere: it needs neither the config nor a checkout, so
# it runs before either is resolved.
case "$COMMAND" in
  help) usage; exit 0 ;;
esac

resolve_opencode_config

case "$COMMAND" in
  install)   cmd_install ;;
  uninstall) cmd_uninstall ;;
  status)    cmd_status ;;
  *)
    echo "Error: Unknown command '$COMMAND'" >&2
    usage
    exit 1
    ;;
esac
