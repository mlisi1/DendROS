#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/usr/local/dendROS"
BASHRC="${HOME}/.bashrc"

GREEN='\033[32;1m'
YELLOW='\033[33;1m'
RESET='\033[0m'
# Official DendROS brand colors — "[dend" in brand blue, "ROS]" in brand orange.
# Must stay in sync with lib.colors.DENDROS_TAG.
DENDROS_TAG='\033[38;2;0;75;107;1m[dend\033[38;2;224;127;0;1mROS]\033[0m'

echo -e "${DENDROS_TAG} ${YELLOW}Uninstalling...${RESET}"

if [[ -d "$INSTALL_DIR" ]]; then
    sudo rm -rf "$INSTALL_DIR"
    echo -e "${DENDROS_TAG} ${GREEN}Removed ${INSTALL_DIR}${RESET}"
else
    echo -e "${DENDROS_TAG} ${YELLOW}${INSTALL_DIR} not found — nothing to remove${RESET}"
fi

# Remove the source line and comment from .bashrc
if grep -qF "dendROS" "$BASHRC" 2>/dev/null; then
    sed -i '/# DendROS/d; /dendROS/d' "$BASHRC"
    echo -e "${DENDROS_TAG} ${GREEN}Removed from ~/.bashrc${RESET}"
fi

echo -e "${DENDROS_TAG} ${GREEN}Done!${RESET}"
