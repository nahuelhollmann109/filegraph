#!/usr/bin/env bash
# install.sh — One-liner installer for graph MCP server
# Usage: curl -fsSL https://raw.githubusercontent.com/nahuelhollmann109/filegraph/main/install.sh | bash
set -euo pipefail

# Never let git open a credential prompt: under `curl | bash` stdin IS this
# script, so a prompt would consume the remaining commands.
export GIT_TERMINAL_PROMPT=0

# ─── Config ──────────────────────────────────────────────────────────────────
REPO_URL="https://github.com/nahuelhollmann109/filegraph.git"
# Overridable so a test run (or a user with a different layout) can redirect the
# whole installation. Unset keeps the historical location.
INSTALL_DIR="${FILEGRAPH_INSTALL_DIR:-${HOME}/.local/share/filegraph}"
# ONE venv location, shared by every tier: system uv, stdlib venv, bootstrapped
# uv. Tier 2 and Tier 4 must not create competing environments.
VENV_DIR="${INSTALL_DIR}/.venv"
# Tier 4 user-space bootstrap. Pinned so an install is reproducible.
UV_VERSION="0.12.20"
UV_BIN_DIR="${INSTALL_DIR}/.uv/bin"
UV_BIN="${UV_BIN_DIR}/uv"
SERVER_NAME="filegraph"
# Pre-set by the caller; also the value check_opencode() resolves and exports.
# An explicit value is authoritative: we must never silently register into a
# different file than the one the caller asked for.
OPENCODE_CONFIG="${OPENCODE_CONFIG:-}"
OPENCODE_CONFIG_EXPLICIT=0
[[ -n "${OPENCODE_CONFIG}" ]] && OPENCODE_CONFIG_EXPLICIT=1
# Absolute path of the interpreter that will run the MCP server. Set by
# install_python_deps() and handed to setup-mcp.sh.
CHOSEN_PYTHON=""
# Why the last tier failed, so the final error can name the failing step
# instead of just "it did not work".
BOOTSTRAP_REASON=""
# Why the post-install smoke test failed, for the same reason.
SMOKE_REASON=""
# `--dry-run`: print the plan and stop before any mutation.
DRY_RUN=0

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

  # An explicit OPENCODE_CONFIG is taken literally, even when the file is
  # missing: falling back to a discovered config would write somewhere the
  # caller did not ask for.
  if [[ "${OPENCODE_CONFIG_EXPLICIT}" -eq 1 ]]; then
    if [[ -f "${OPENCODE_CONFIG}" ]]; then
      return 0
    fi
    warn "OpenCode config not found at ${OPENCODE_CONFIG}"
    warn "Create it by running \`opencode\` once, then re-run this script to register the MCP server."
    warn "The MCP server will be installed, but OpenCode will not know about it yet."
    return 1
  fi

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

# ─── Tier 4: user-space uv bootstrap ──────────────────────────────────────────
# When the host has no uv, no ensurepip and no pip, download the pinned uv
# release ourselves. Design constraints, deliberately:
#   * binary download only — we never pipe a remote script into a shell
#   * the published .sha256 asset MUST match before anything is extracted
#   * everything lands under INSTALL_DIR: no sudo, no PATH edits, no profile
#     edits, and no system package installs
uv_arch() {
  case "$(uname -m)" in
    x86_64|amd64)  echo "x86_64" ;;
    aarch64|arm64) echo "aarch64" ;;
    *)             echo "" ;;
  esac
}

# sha256 of a file, or nothing when no hasher is available.
sha256_of() {
  if command -v sha256sum &>/dev/null; then
    sha256sum "$1" 2>/dev/null | cut -d' ' -f1
  elif command -v shasum &>/dev/null; then
    shasum -a 256 "$1" 2>/dev/null | cut -d' ' -f1
  else
    echo ""
  fi
}

# Expected hash from a published checksum asset. Handles the sha256sum layout
# ("<hash>  <name>") and the BSD one ("SHA256 (<name>) = <hash>").
extract_sha256() {
  local line
  line="$(head -1 "$1" 2>/dev/null)" || return 1

  if [[ "${line}" =~ ^([0-9a-fA-F]{64})([[:space:]]|$) ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
    return 0
  fi
  if [[ "${line}" =~ ([0-9a-fA-F]{64})[[:space:]]*$ ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
    return 0
  fi
  return 1
}

# Fetch, verify and install the pinned uv binary into ${UV_BIN}.
# On failure, BOOTSTRAP_REASON names the step that broke. Nothing is extracted
# unless the checksum matched, and a failed download leaves no partial binary.
bootstrap_uv() {
  BOOTSTRAP_REASON=""
  local arch tarball base_url tmp expected actual extracted

  arch="$(uv_arch)"
  if [[ -z "${arch}" ]]; then
    BOOTSTRAP_REASON="uv has no release for this architecture ($(uname -m)); only x86_64 and aarch64 are supported"
    return 1
  fi

  if ! command -v curl &>/dev/null; then
    BOOTSTRAP_REASON="curl is not installed, so the uv download cannot start"
    return 1
  fi

  tarball="uv-${arch}-unknown-linux-gnu.tar.gz"
  base_url="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}"

  # Reuse a previous bootstrap only when it is exactly the pinned version.
  # `uv --version` prints "uv 0.12.20 (x86_64-unknown-linux-gnu)", so compare
  # the first two fields rather than the whole line.
  if [[ -x "${UV_BIN}" ]]; then
    local have reported
    have="$("${UV_BIN}" --version 2>/dev/null | head -1)"
    reported="$(echo "${have}" | awk '{print $1" "$2}')"
    if [[ "${reported}" == "uv ${UV_VERSION}" ]]; then
      info "Reusing uv ${UV_VERSION} from ${UV_BIN}"
    else
      info "Replacing uv bootstrap (${have:-unusable} -> uv ${UV_VERSION})..."
      rm -f "${UV_BIN}"
    fi
  fi

  if [[ ! -x "${UV_BIN}" ]]; then
    tmp="$(mktemp -d)" || { BOOTSTRAP_REASON="could not create a temporary directory"; return 1; }
    # shellcheck disable=SC2064  # expand ${tmp} now, not at trap time
    trap "rm -rf '${tmp}'" RETURN

    info "Downloading uv ${UV_VERSION} for ${arch}..."
    if ! curl -fsSL --connect-timeout 10 --max-time 300 \
         -o "${tmp}/${tarball}" "${base_url}/${tarball}"; then
      BOOTSTRAP_REASON="could not download ${base_url}/${tarball}"
      return 1
    fi
    if ! curl -fsSL --connect-timeout 10 --max-time 60 \
         -o "${tmp}/${tarball}.sha256" "${base_url}/${tarball}.sha256"; then
      BOOTSTRAP_REASON="could not download the checksum asset ${tarball}.sha256"
      return 1
    fi

    expected="$(extract_sha256 "${tmp}/${tarball}.sha256" || true)"
    if [[ -z "${expected}" ]]; then
      BOOTSTRAP_REASON="the downloaded checksum asset is unreadable"
      return 1
    fi
    actual="$(sha256_of "${tmp}/${tarball}")"
    if [[ -z "${actual}" ]]; then
      BOOTSTRAP_REASON="no sha256 tool available to verify the download"
      return 1
    fi
    if [[ "${expected}" != "${actual}" ]]; then
      BOOTSTRAP_REASON="checksum mismatch for ${tarball}: expected ${expected}, got ${actual}"
      return 1
    fi
    info "Checksum verified: ${actual}"

    if ! tar -xzf "${tmp}/${tarball}" -C "${tmp}" 2>/dev/null; then
      BOOTSTRAP_REASON="could not extract ${tarball} (the download is corrupt)"
      return 1
    fi
    # The release archive holds uv-<arch>-unknown-linux-gnu/uv; locate it rather
    # than hardcoding the layout.
    extracted="$(find "${tmp}" -type f -name uv -perm -u+x 2>/dev/null | head -1)"
    if [[ -z "${extracted}" ]]; then
      BOOTSTRAP_REASON="the ${tarball} archive did not contain a 'uv' binary"
      return 1
    fi

    mkdir -p "${UV_BIN_DIR}"
    cp -f "${extracted}" "${UV_BIN}"
    chmod +x "${UV_BIN}"
  fi

  # Prefer a compatible system interpreter; ask uv for a managed 3.12 only if
  # the host has none. uv keeps managed interpreters in its own data dir, so
  # this stays entirely in user space.
  info "Creating virtual environment at ${VENV_DIR} with uv..."
  if "${UV_BIN}" venv --clear "${VENV_DIR}" &>/dev/null; then
    :
  elif "${UV_BIN}" venv --clear --python 3.12 "${VENV_DIR}" &>/dev/null; then
    info "No compatible system Python found — uv downloaded a managed Python 3.12."
  else
    BOOTSTRAP_REASON="uv could not create a virtual environment at ${VENV_DIR}"
    return 1
  fi

  local vpy out
  vpy="$(venv_python || true)"
  if [[ -z "${vpy}" ]]; then
    BOOTSTRAP_REASON="uv created ${VENV_DIR} but it has no usable interpreter"
    return 1
  fi

  if ! out="$("${UV_BIN}" pip install --python "${vpy}" -e "${INSTALL_DIR}/.[dev]" 2>&1)"; then
    BOOTSTRAP_REASON="uv could not install the project dependencies: ${out##*: }"
    return 1
  fi

  CHOSEN_PYTHON="${vpy}"
  return 0
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

  # 4 — no usable local tooling at all: fetch a pinned, checksum-verified uv
  # into INSTALL_DIR and let it do the work. Still no sudo and no system changes.
  info "No usable Python installer found — bootstrapping uv ${UV_VERSION} in ${INSTALL_DIR}..."
  if bootstrap_uv; then
    info "Bootstrapped uv: $( "${UV_BIN}" --version 2>/dev/null | head -1 )"
    return 0
  fi

  return 1
}

# ─── Plan and verification ────────────────────────────────────────────────────
# Printed after config detection and before any mutation, so the user can see
# exactly what will happen while it is still harmless to abort.
print_action_summary() {
  local opencode_ready="$1"

  echo ""
  echo "  This will do the following, all inside ${INSTALL_DIR}:"
  echo "    * clone or update the filegraph repository"
  echo "    * create a Python virtual environment at ${VENV_DIR}"
  if command -v uv &>/dev/null; then
    echo "    * use the uv already on your PATH (${UV_BIN_DIR} not needed)"
  else
    echo "    * download a pinned, checksum-verified uv ${UV_VERSION} to ${UV_BIN_DIR}"
    echo "      only if no local uv, venv, or pip can do the job"
  fi

  if [[ "${opencode_ready}" -eq 1 ]]; then
    echo ""
    echo "  OpenCode config to register: ${OPENCODE_CONFIG}"
  else
    echo ""
    echo "  OpenCode config: SKIPPED — ${OPENCODE_CONFIG} does not exist yet."
    echo "    Run \`opencode\` once to create it, then re-run this script."
  fi

  echo ""
  echo "  No system packages, shell profiles, or other files will be touched."
  echo "  Nothing needs sudo, and nothing will ask you a question."
  echo ""
}

# Prove the installed interpreter can actually load the server before claiming
# success. Runs in a subshell with cwd=${INSTALL_DIR} (the MCP entry uses that
# same cwd) and under `timeout`, so a module that starts a server on import can
# never hang the installer and no background process is left behind.
smoke_test() {
  SMOKE_REASON=""

  if [[ ! -f "${INSTALL_DIR}/src/main.py" ]]; then
    SMOKE_REASON="src/main.py is missing from ${INSTALL_DIR}"
    return 1
  fi

  # `timeout` is coreutils on Linux; without it, still run the check uncapped.
  local cap=""
  if command -v timeout &>/dev/null; then
    cap="timeout 15"
  fi

  # src/main.py only calls mcp.run() under `if __name__ == "__main__"`, so
  # importing it exercises the real startup path without starting a server.
  if ( cd "${INSTALL_DIR}" && ${cap} "${CHOSEN_PYTHON}" -c "import src.main" ) &>/dev/null; then
    return 0
  fi

  # If the deps import but the module does not, say so precisely.
  if ( cd "${INSTALL_DIR}" && ${cap} "${CHOSEN_PYTHON}" -c "import fastmcp" ) &>/dev/null; then
    SMOKE_REASON="the dependencies import, but \`import src.main\` failed — run it by hand to see why:\n      (cd '${INSTALL_DIR}' && '${CHOSEN_PYTHON}' -c 'import src.main')"
    return 1
  fi

  SMOKE_REASON="'${CHOSEN_PYTHON}' cannot import fastmcp — the dependencies were not installed into that interpreter"
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

  # Resolve the config file BEFORE any mutation so the plan can name it, and so
  # check_opencode's warning appears while aborting is still free.
  local opencode_ready=0
  if check_opencode; then
    opencode_ready=1
  fi

  print_action_summary "${opencode_ready}"

  if [[ "${DRY_RUN}" -ne 0 ]]; then
    info "Dry run — nothing was changed."
    return 0
  fi

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
  install_python_deps || error "Could not install the Python dependencies from ${INSTALL_DIR}\n  Tried: uv -> python3 -m venv -> pip --break-system-packages -> bootstrapped uv.\n  Last failure: ${BOOTSTRAP_REASON:-no strategy reported a reason}\n  Fix the reported step and re-run, or install by hand once pip is available:\n    $(python_tooling_hint)"
  info "Python dependencies installed (interpreter: ${CHOSEN_PYTHON})"

  # Install MCP server in OpenCode.
  # A registration failure (e.g. a commented .jsonc that jq cannot parse) must
  # not hide the fact that the server and its dependencies ARE installed, and it
  # must not abort us before the summary. Capture it, print everything, and exit
  # non-zero at the very end so the two outcomes stay visibly distinct.
  local registration_failed=0
  if [[ "${opencode_ready}" -eq 1 ]]; then
    info "Installing MCP server in OpenCode..."
    if ! OPENCODE_CONFIG="${OPENCODE_CONFIG}" FILEGRAPH_PYTHON="${CHOSEN_PYTHON}" \
         bash "${INSTALL_DIR}/scripts/setup-mcp.sh" install; then
      registration_failed=1
    fi
  else
    registration_failed=1
  fi

  # ── Verification ───────────────────────────────────────────────────────────
  local smoke_failed=0
  local config_key_missing=0

  info "Verifying the installation..."
  if ! smoke_test; then
    smoke_failed=1
    warn "Smoke test failed: ${SMOKE_REASON}"
  else
    info "Smoke test passed (the interpreter imports src.main)"
  fi

  if [[ "${registration_failed}" -eq 0 ]]; then
    if ! jq -e ".mcp.${SERVER_NAME}" "$OPENCODE_CONFIG" &>/dev/null; then
      config_key_missing=1
      warn "The MCP entry '.mcp.${SERVER_NAME}' is not present in ${OPENCODE_CONFIG}"
    else
      info "OpenCode config contains the '${SERVER_NAME}' entry"
    fi
  fi

  # One clear status block, then a non-zero exit only for a real failure.
  local failed=0
  [[ "${smoke_failed}" -ne 0 ]] && failed=1
  [[ "${registration_failed}" -ne 0 ]] && failed=1
  [[ "${config_key_missing}" -ne 0 ]] && failed=1

  echo ""
  if [[ "${failed}" -eq 0 ]]; then
    info "Installation complete!"
  else
    warn "Installation did NOT fully complete."
  fi
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

  if [[ "${config_key_missing}" -ne 0 ]]; then
    echo ""
    warn "The config file does not actually contain '.mcp.${SERVER_NAME}'."
    warn "  Check the file by hand:  jq '.mcp' '${OPENCODE_CONFIG}'"
  fi

  echo ""
  echo "  To uninstall: bash ${INSTALL_DIR}/scripts/setup-mcp.sh uninstall"
  echo ""

  # Signal the partial outcome only after the summary is on screen.
  if [[ "${failed}" -ne 0 ]]; then
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
Usage: $(basename "$0") [install|uninstall] [--dry-run]

Commands:
  install     Install filegraph MCP server (default)
  uninstall   Remove filegraph MCP server

Options:
  --dry-run   Print the plan and exit without changing anything

Environment:
  FILEGRAPH_INSTALL_DIR  Install location (default: ~/.local/share/filegraph)
  OPENCODE_CONFIG        OpenCode config to register (default: auto-detected)

EOF
}

# Accept the command in any position so `install --dry-run` and `--dry-run`
# behave the same. Unknown flags still fail loudly.
COMMAND=""
for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=1 ;;
    -*)       echo "Error: unknown option '${arg}'" >&2; usage; exit 1 ;;
    *)        [[ -n "${COMMAND}" ]] || COMMAND="${arg}" ;;
  esac
done

case "${COMMAND:-install}" in
  install)   do_install ;;
  uninstall) do_uninstall ;;
  *)         usage; exit 1 ;;
esac
