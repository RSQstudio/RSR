#!/usr/bin/env bash
# RSQ Skill Router — one-command installer
# curl -sSL https://raw.githubusercontent.com/RSHQ/skill-router/main/install.sh | bash

set -euo pipefail

REPO="https://github.com/RSHQ/skill-router.git"
INSTALL_DIR="${HOME}/.rsq-skill-router"
BIN_DIR="${HOME}/.local/bin"
SCRIPT_NAME="skill-router"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "${CYAN}╔═══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║          🧠  RSQ Skill Router — Installer         ║${NC}"
echo -e "${CYAN}║  Intelligent skill loading for AI coding agents   ║${NC}"
echo -e "${CYAN}╚═══════════════════════════════════════════════════╝${NC}"
echo ""

# ── Check prerequisites ──
echo -e "${YELLOW}[1/4] Checking prerequisites...${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 is required but not installed.${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "  ✓ python3 ${PYTHON_VERSION}"

if ! command -v git &> /dev/null; then
    echo -e "${RED}Error: git is required but not installed.${NC}"
    exit 1
fi
echo "  ✓ git"

# ── Clone repo ──
echo ""
echo -e "${YELLOW}[2/4] Downloading RSQ Skill Router...${NC}"

if [ -d "$INSTALL_DIR" ]; then
    echo "  Updating existing installation..."
    cd "$INSTALL_DIR"
    git pull --ff-only origin main 2>/dev/null || echo "  (could not update, continuing with existing copy)"
else
    git clone --depth 1 "$REPO" "$INSTALL_DIR" 2>/dev/null || {
        echo -e "${RED}Failed to clone repository.${NC}"
        echo "  Make sure the repo exists and is public: $REPO"
        exit 1
    }
fi

echo -e "  ✓ Installed to ${INSTALL_DIR}"

# ── Create CLI wrapper ──
echo ""
echo -e "${YELLOW}[3/4] Creating CLI entry point...${NC}"

mkdir -p "$BIN_DIR"

cat > "${BIN_DIR}/${SCRIPT_NAME}" << 'WRAPPER'
#!/usr/bin/env bash
# RSQ Skill Router CLI wrapper
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${HOME}/.rsq-skill-router"
exec python3 "${INSTALL_DIR}/src/skill_router_cli.py" "$@"
WRAPPER

chmod +x "${BIN_DIR}/${SCRIPT_NAME}"

# Add to PATH if needed
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "  Adding ${BIN_DIR} to PATH..."

    # Detect shell
    SHELL_NAME=$(basename "$SHELL")
    case "$SHELL_NAME" in
        zsh)  RC_FILE="${HOME}/.zshrc" ;;
        bash) RC_FILE="${HOME}/.bashrc" ;;
        fish) RC_FILE="${HOME}/.config/fish/config.fish" ;;
        *)    RC_FILE="${HOME}/.profile" ;;
    esac

    if ! grep -q "$BIN_DIR" "$RC_FILE" 2>/dev/null; then
        echo "export PATH=\"\$PATH:${BIN_DIR}\"" >> "$RC_FILE"
        echo "  ✓ Added to ${RC_FILE}"
        echo "  Run 'source ${RC_FILE}' or restart your terminal."
    fi
fi

echo -e "  ✓ CLI available at ${BIN_DIR}/${SCRIPT_NAME}"

# ── Run installer ──
echo ""
echo -e "${YELLOW}[4/4] Running setup wizard...${NC}"
echo ""
echo "  The interactive wizard will:"
echo "    • Auto-detect your AI agent (Hermes, Claude Code, Cursor, etc.)"
echo "    • Find your installed skills"
echo "    • Let you pick always-on skills"
echo "    • Move the rest into a read-only vault"
echo ""

if [[ -t 0 ]]; then
    # Interactive terminal — run wizard
    python3 "${INSTALL_DIR}/src/skill_router_cli.py" install
else
    # Non-interactive (piped) — run with --yes
    echo "  (non-interactive mode — using defaults)"
    python3 "${INSTALL_DIR}/src/skill_router_cli.py" install --yes
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ RSQ Skill Router installed!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo ""
echo "  Quick start:"
echo "    skill-router status        See current state"
echo "    skill-router route \"...\"   Match skills to a task"
echo "    skill-router reconcile \"...\" Full auto-activation cycle"
echo ""
echo "  Update later:"
echo "    cd ~/.rsq-skill-router && git pull"
echo ""
echo "  Install cron jobs (background maintenance):"
echo "    skill-router cron setup"
echo ""