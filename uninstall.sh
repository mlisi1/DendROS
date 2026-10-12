#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/usr/local/dendROS"
BASHRC="${HOME}/.bashrc"
SOURCE_LINE="source /usr/local/dendROS/dendROS.sh"
CONFIG_DIR="${HOME}/.config/dendROS"

GREEN='\033[32;1m'
YELLOW='\033[33;1m'
RESET='\033[0m'
# Official DendROS brand colors — "[dend" in brand blue, "ROS]" in brand orange.
# Must stay in sync with lib.colors.DENDROS_TAG.
DENDROS_TAG='\033[38;2;0;75;107;1m[dend\033[38;2;224;127;0;1mROS]\033[0m'

# Use sudo only when not already root (same rule as install.sh, e.g. Docker)
if [[ $EUID -ne 0 ]]; then
    SUDO=sudo
else
    SUDO=''
fi

echo -e "${DENDROS_TAG} ${YELLOW}Uninstalling...${RESET}"

if [[ -d "$INSTALL_DIR" ]]; then
    $SUDO rm -rf "$INSTALL_DIR"
    echo -e "${DENDROS_TAG} ${GREEN}Removed ${INSTALL_DIR}${RESET}"
else
    echo -e "${DENDROS_TAG} ${YELLOW}${INSTALL_DIR} not found — nothing to remove${RESET}"
fi

# Remove exactly the two lines install.sh added to .bashrc (the comment and the source
# line) — never any other line that merely mentions dendROS.
if grep -qF "$SOURCE_LINE" "$BASHRC" 2>/dev/null; then
    sed -i '\|^# DendROS — colorized ROS 2 terminal output$|d; \|^source /usr/local/dendROS/dendROS\.sh$|d' "$BASHRC"
    echo -e "${DENDROS_TAG} ${GREEN}Removed from ~/.bashrc${RESET}"
fi

# Remove runtime state (saved TUI runs, color cache, flag files). Your settings
# (defaults.yaml) are kept, so a reinstall picks them up again.
if [[ -d "$CONFIG_DIR" ]]; then
    rm -rf "${CONFIG_DIR}/last_run"
    rm -f "${CONFIG_DIR}/node_colors.yaml" "${CONFIG_DIR}/disable.flag" "${CONFIG_DIR}/tui_command.flag"
    if [[ -f "${CONFIG_DIR}/defaults.yaml" ]]; then
        echo -e "${DENDROS_TAG} ${YELLOW}Kept your settings in ${CONFIG_DIR}/defaults.yaml (delete the folder to remove them)${RESET}"
    else
        rmdir "$CONFIG_DIR" 2>/dev/null || true
    fi
fi

echo -e "${DENDROS_TAG} ${GREEN}Done!${RESET}"
echo -e "${DENDROS_TAG} ${YELLOW}Open a new terminal: shells that are already open still have the ros2 wrapper loaded.${RESET}"
