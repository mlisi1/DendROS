#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/usr/local/dendROS"
BASHRC="${HOME}/.bashrc"

GREEN='\033[32;1m'
YELLOW='\033[33;1m'
RESET='\033[0m'

echo -e "${YELLOW}[DendROS] Uninstalling...${RESET}"

if [[ -d "$INSTALL_DIR" ]]; then
    sudo rm -rf "$INSTALL_DIR"
    echo -e "${GREEN}[DendROS] Removed ${INSTALL_DIR}${RESET}"
else
    echo -e "${YELLOW}[DendROS] ${INSTALL_DIR} not found — nothing to remove${RESET}"
fi

# Remove the source line and comment from .bashrc
if grep -qF "dendROS" "$BASHRC" 2>/dev/null; then
    sed -i '/# DendROS/d; /dendROS/d' "$BASHRC"
    echo -e "${GREEN}[DendROS] Removed from ~/.bashrc${RESET}"
fi

echo -e "${GREEN}[DendROS] Done!${RESET}"
