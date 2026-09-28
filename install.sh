#!/usr/bin/env bash
# install.sh — One-liner installer for graph MCP server
# Usage: curl -fsSL https://raw.githubusercontent.com/nahuelhollmann109/filegraph/main/install.sh | bash
set -euo pipefail

# Never let git open a credential prompt: under `curl | bash` stdin IS this
# script, so a prompt would consume the remaining commands.
export GIT_TERMINAL_PROMPT=0

# ─── Config ──────────────────────────────────────────────────────────────────
REPO_URL="https://github.com/nahuelhollmann109/filegraph.git"
INSTALL_DIR="${HOME}/.local/share/filegraph"
VENV_DIR="${INSTALL_DIR}/.venv"
SERVER_NAME="filegraph"
# Pre-set by the caller; also the value check_opencode() resolves and exports.
OPENCODE_CONFIG="${OPENCODE_CONFIG:-}"
# Absolute path of the interpreter that will run the MCP server. Set by
# install_python_deps() and handed to setup-mcp.sh.
CHOSEN_PYTHON=""

# ─── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
error() { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

# ─── Checks ──────────────────────────────────────────────────────────────────
# First package manager on PATH, or an empty string when none was detected.
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

# Packages that provide a usable pip on this distro. Debian/Ubuntu split venv
# into python3-venv; on rpm/suse/alpine it is already part of the interpreter.
python_tooling_hint() {
  local pm
  pm="$(detect_package_manager)"

  case "${pm}" in
    apt-get|pacman|apk) package_install_cmd python3-pip python3-venv ;;
    dnf|yum|zypper)     package_install_cmd python3-pip ;;
    *)                 echo "Install a Python 3.12+ interpreter with pip (e.g. from python.org or pyenv)." ;;
  esac
}

check_deps() {
  local missing=()

  command -v git &>/dev/null || missing+=("git")
  command -v python3 &>/dev/null || missing+=("python3")
  command -v jq &>/dev/null || missing+=("jq")

  if [[ ${#missing[@]} -gt 0 ]]; then
    local hint
    hint="$(package_install_cmd "${missing[@]}")"
    if [[ -n "${hint}" ]]; then
      error "Missing dependencies: ${missing[*]}\n  Install them with:\n    ${hint}\n  then re-run this script."
    fi
    error "Missing dependencies: ${missing[*]}\n  No supported package manager found (apt-get, dnf, yum, pacman, zypper, apk).\n  Install them manually and re-run this script."
  fi
}

# Resolve the OpenCode config file that actually exists on this machine, and
# export it so setup-mcp.sh registers the server in that very same file.
# Fresh OpenCode installs create opencode.jsonc; older ones created opencode.json.
# An explicit override counts only when the file exists — setup-mcp.sh resolves
# identically, so both scripts can never target different files.
check_opencode() {
  local candidate
  for candidate in \
    "${OPENCODE_CONFIG}" \
    "${HOME}/.config/opencode/opencode.json" \
    "${HOME}/.config/opencode/opencode.jsonc"
  do
    if [[ -n "${candidate}" ]] && [[ -f "${candidate}" ]]; then
      OPENCODE_CONFIG="${candidate}"
      return 0
    fi
  done

  # Nothing exists: keep whatever the caller asked for, else the historical
  # default, so the message names the path the user is expected to create.
  [[ -n "${OPENCODE_CONFIG}" ]] || OPENCODE_CONFIG="${HOME}/.config/opencode/opencode.json"

  warn "OpenCode config not found at ${OPENCODE_CONFIG}"
  warn "Create it by running \`opencode\` once, then re-run this script to register the MCP server."
  warn "The MCP server will be installed, but OpenCode will not know about it yet."
  return 1
}

# ─── Python environment ───────────────────────────────────────────────────────
# Fresh distros ship without pip and forbid installs into the system interpreter
# (PEP 668), so `pip install` is the usual reason the server dies on import.
# Try uv, then the stdlib venv, then system pip — and stop at the first tier that
# really installs. The winner's absolute path becomes CHOSEN_PYTHON because MCP
# entries are launched with cwd set to the project, where a bare `python3` would
# not be on PATH.

# Absolute path of a command, or nothing when it is not on PATH.
abs_path() {
  command -v "$1" 2>/dev/null || true
}

# Interpreter version as "3.12", for comparing against what pip reports.
python_version() {
  "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null
}

# Version of the interpreter that owns a given pip command, as reported by pip
# itself: `pip 24.0 from /path/to/pip (python 3.12)`.
pip_python_version() {
  "$1" --version 2>/dev/null |
    sed -n 's/.*(python \([0-9][0-9.]*\)).*/\1/p' | head -1
}

# Absolute path of the interpreter that actually owns a bare `pip`, verified
# against the version pip reports. Only versioned candidates (python3.12) and
# python3 are ever considered: on Debian/Ubuntu a bare `python` can be a legacy
# python2, and pointing the MCP at it would launch the server with the wrong
# interpreter. Returns 1 rather than guessing when the owner can't be proven.
resolve_pip_owner() {
  local want have candidate resolved=""
  want="$(pip_python_version "$1")"

  if [[ -z "${want}" ]]; then
    return 1
  fi
  # pip normally reports major.minor, but tolerate a patch component so the
  # comparison against python_version() below still lines up.
  want="$(printf '%s' "${want}" | cut -d. -f1,2)"

  for candidate in "python${want}" python3; do
    resolved="$(abs_path "${candidate}")"
    [[ -n "${resolved}" ]] || continue
    have="$(python_version "${resolved}")"
    if [[ -n "${have}" ]] && [[ "${have}" == "${want}" ]]; then
      echo "${resolved}"
      return 0
    fi
    resolved=""
  done

  return 1
}

# Absolute path of the venv interpreter. Both uv and the stdlib venv ship one.
venv_python() {
  local candidate
  for candidate in "${VENV_DIR}/bin/python" "${VENV_DIR}/bin/python3"; do
    if [[ -x "${candidate}" ]]; then
      echo "${candidate}"
      return 0
    fi
  done
  return 1
}

install_python_deps() {
  local vpy

  # 1 — uv bootstraps its own venv, so the host needs no pip at all.
  if command -v uv &>/dev/null; then
    info "Installing Python dependencies with uv..."
    if uv venv --clear "${VENV_DIR}" &>/dev/null; then
      vpy="$(venv_python || true)"
      if [[ -n "${vpy}" ]] && uv pip install --python "${vpy}" -e "${INSTALL_DIR}/.[dev]" &>/dev/null; then
        CHOSEN_PYTHON="${vpy}"
        return 0
      fi
    fi
    warn "uv could not install the dependencies — falling back to python3 -m venv."
  fi

  # 2 — stdlib venv, which comes with its own pip. Note that venv prints its
  # failure reasons on stdout, so capture both streams instead of leaking them.
  info "Creating virtual environment at ${VENV_DIR}..."
  local venv_out=""
  if venv_out="$(python3 -m venv "${VENV_DIR}" 2>&1)"; then
    vpy="$(venv_python || true)"
    if [[ -n "${vpy}" ]] && "${vpy}" -m pip install -e "${INSTALL_DIR}/.[dev]" &>/dev/null; then
      CHOSEN_PYTHON="${vpy}"
      return 0
    fi
  else
    warn "python3 -m venv failed: ${venv_out%%$'\n'*}"
    rm -rf "${VENV_DIR}"
  fi

  # 3 — system-wide pip as a last resort. `--break-system-packages` is what
  # PEP 668 distros require, and a harmless no-op elsewhere.
  # Order matters. `python3 -m pip` and `pip3` name their own interpreter, so
  # they are tried first. A bare `pip` is only accepted when we can prove which
  # interpreter owns it — never by blindly resolving a bare `python`.
  local pip_cmd resolved
  for pip_cmd in python3 pip3 pip; do
    command -v "${pip_cmd}" &>/dev/null || continue

    # `python3` needs the module form; `pip`/`pip3` are standalone binaries.
    local -a args=(install --break-system-packages -e "${INSTALL_DIR}/.[dev]")
    if [[ "${pip_cmd}" == "python3" ]]; then
      args=(-m pip install --break-system-packages -e "${INSTALL_DIR}/.[dev]")
    fi

    "${pip_cmd}" "${args[@]}" &>/dev/null || continue

    # The install worked — now resolve the interpreter that owns THIS pip.
    if [[ "${pip_cmd}" == "pip" ]]; then
      resolved="$(resolve_pip_owner pip || true)"
    else
      resolved="$(abs_path python3)"
    fi

    if [[ -n "${resolved}" ]]; then
      CHOSEN_PYTHON="${resolved}"
      return 0
    fi

    warn "Installed with ${pip_cmd}, but could not determine which Python owns it."
    warn "  pip --version reports: $(pip --version 2>/dev/null || echo 'unavailable')"
    warn "  Install the dependencies by hand, then register the MCP server with an"
    warn "  explicit interpreter:  FILEGRAPH_PYTHON=<path> setup-mcp.sh install"
    return 1
  done

  return 1
}

# ─── Install ─────────────────────────────────────────────────────────────────
do_install() {
  echo ""
  echo "  FileGraph — MCP Directory Scanner"
  echo "  =================================="
  echo ""

  # Check dependencies
  check_deps
  info "Dependencies OK (git, python3, jq)"

  # Clone or update repo
  if [[ -d "${INSTALL_DIR}" ]]; then
    info "Repository already exists at ${INSTALL_DIR}"
    info "Pulling latest changes..."
    git -C "${INSTALL_DIR}" pull --ff-only || warn "Could not pull, using existing version"
  else
    info "Cloning repository to ${INSTALL_DIR}..."
    git clone "${REPO_URL}" "${INSTALL_DIR}"
  fi

  # Install Python dependencies
  install_python_deps || error "Could not install the Python dependencies from ${INSTALL_DIR}\n  Tried: uv -> python3 -m venv -> pip --break-system-packages.\n  None of those strategies worked. On most distros one package fixes it:\n    $(python_tooling_hint)\n  Or install the project by hand once pip is available:\n    python3 -m pip install -e '${INSTALL_DIR}/.[dev]'"
  info "Python dependencies installed (interpreter: ${CHOSEN_PYTHON})"

  # Install MCP server in OpenCode.
  # A registration failure (e.g. a commented .jsonc that jq cannot parse) must
  # not hide the fact that the server and its dependencies ARE installed, and it
  # must not abort us before the summary. Capture it, print everything, and exit
  # non-zero at the very end so the two outcomes stay visibly distinct.
  local registration_failed=0
  if check_opencode; then
    info "Installing MCP server in OpenCode..."
    if ! OPENCODE_CONFIG="${OPENCODE_CONFIG}" FILEGRAPH_PYTHON="${CHOSEN_PYTHON}" \
         bash "${INSTALL_DIR}/scripts/setup-mcp.sh" install; then
      registration_failed=1
    fi
  else
    registration_failed=1
  fi

  echo ""
  info "Installation complete!"
  echo ""
  echo "  Next steps:"
  echo "    1. Restart OpenCode to load the MCP server"
  echo "    2. Use the tools: scan_directory, search_by_type, get_file_metadata"
  echo ""
  echo "  Installed at:  ${INSTALL_DIR}"
  echo "  Interpreter:   ${CHOSEN_PYTHON}"

  if [[ "${registration_failed}" -ne 0 ]]; then
    echo ""
    warn "OpenCode registration did NOT complete — the server is installed but"
    warn "OpenCode does not know about it yet. Finish it with:"
    echo "    OPENCODE_CONFIG='${OPENCODE_CONFIG}' FILEGRAPH_PYTHON='${CHOSEN_PYTHON}' \\"
    echo "      bash '${INSTALL_DIR}/scripts/setup-mcp.sh' install"
  else
    echo "  OpenCode config: ${OPENCODE_CONFIG}"
  fi

  echo ""
  echo "  To uninstall: bash ${INSTALL_DIR}/scripts/setup-mcp.sh uninstall"
  echo ""

  # Signal the partial outcome only after the summary is on screen.
  if [[ "${registration_failed}" -ne 0 ]]; then
    exit 1
  fi
}

# ─── Uninstall ───────────────────────────────────────────────────────────────
do_uninstall() {
  echo ""
  info "Uninstalling filegraph MCP server..."

  # Remove from OpenCode
  if [[ -f "${INSTALL_DIR}/scripts/setup-mcp.sh" ]]; then
    bash "${INSTALL_DIR}/scripts/setup-mcp.sh" uninstall 2>/dev/null || true
  fi

  # Remove installed directory
  if [[ -d "${INSTALL_DIR}" ]]; then
    rm -rf "${INSTALL_DIR}"
    info "Removed ${INSTALL_DIR}"
  fi

  info "Uninstall complete. Restart OpenCode to fully unload."
}

# ─── Main ────────────────────────────────────────────────────────────────────
usage() {
  cat <<EOF
Usage: $(basename "$0") [install|uninstall]

Commands:
  install     Install filegraph MCP server (default)
  uninstall   Remove filegraph MCP server

EOF
}

case "${1:-install}" in
  install)   do_install ;;
  uninstall) do_uninstall ;;
  *)         usage; exit 1 ;;
esac
