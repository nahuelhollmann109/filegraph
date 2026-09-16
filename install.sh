#!/usr/bin/env bash
# install.sh — One-liner installer for graph MCP server
# Usage: curl -fsSL https://raw.githubusercontent.com/nahuelhollmann109/filegraph/main/install.sh | bash
set -euo pipefail

# ─── Config ──────────────────────────────────────────────────────────────────
REPO_URL="https://github.com/nahuelhollmann109/filegraph.git"
INSTALL_DIR="${HOME}/.local/share/filegraph"
SERVER_NAME="filegraph"

# ─── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
error() { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

# ─── Checks ──────────────────────────────────────────────────────────────────
check_deps() {
  local missing=()

  command -v git &>/dev/null || missing+=("git")
  command -v python3 &>/dev/null || missing+=("python3")
  command -v jq &>/dev/null || missing+=("jq")

  if [[ ${#missing[@]} -gt 0 ]]; then
    error "Missing dependencies: ${missing[*]}\n  Install them and re-run this script."
  fi
}

check_opencode() {
  if [[ ! -f "${HOME}/.config/opencode/opencode.json" ]]; then
    warn "OpenCode config not found at ~/.config/opencode/opencode.json"
    warn "The MCP server will be installed, but you'll need to configure OpenCode manually."
    return 1
  fi
  return 0
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
  info "Installing Python dependencies..."
  pip install --break-system-packages -e "${INSTALL_DIR}/.[dev]" 2>/dev/null || \
    pip3 install --break-system-packages -e "${INSTALL_DIR}/.[dev]" 2>/dev/null || \
    warn "Could not install Python deps automatically. Run: pip install -e '${INSTALL_DIR}/.[dev]'"

  # Install MCP server in OpenCode
  if check_opencode; then
    info "Installing MCP server in OpenCode..."
    bash "${INSTALL_DIR}/scripts/setup-mcp.sh" install
  fi

  echo ""
  info "Installation complete!"
  echo ""
  echo "  Next steps:"
  echo "    1. Restart OpenCode to load the MCP server"
  echo "    2. Use the tools: scan_directory, search_by_type, get_file_metadata"
  echo ""
  echo "  To uninstall: bash ${INSTALL_DIR}/scripts/setup-mcp.sh uninstall"
  echo ""
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
