#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/usr/local/dendROS"
BASHRC="${HOME}/.bashrc"
SOURCE_LINE="source /usr/local/dendROS/dendROS.sh"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GREEN='\033[32;1m'
YELLOW='\033[33;1m'
RED='\033[31;1m'
RESET='\033[0m'

# -y / --yes flag or CI env skips all interactive prompts
YES=false
for arg in "$@"; do
    [[ "$arg" == "-y" || "$arg" == "--yes" ]] && YES=true
done
[[ "${CI:-}" == "true" ]] && YES=true

# Use sudo only when not already root
if [[ $EUID -ne 0 ]]; then
    SUDO=sudo
else
    SUDO=''
fi

echo -e "${GREEN}[DendROS] Installing to ${INSTALL_DIR}${RESET}"

# Check for PyYAML
if ! python3 -c "import yaml" 2>/dev/null; then
    echo -e "${YELLOW}[DendROS] PyYAML not found.${RESET}"
    if [[ "$YES" == true ]]; then
        pip3 install pyyaml
    else
        read -r -p "Install PyYAML now? (pip3 install pyyaml) [y/N] " yn
        if [[ "${yn:-}" =~ ^[Yy]$ ]]; then
            pip3 install pyyaml
        else
            echo -e "${RED}[DendROS] PyYAML is required. Install it manually: pip3 install pyyaml${RESET}"
            exit 1
        fi
    fi
fi

# Copy files
$SUDO mkdir -p "$INSTALL_DIR"
$SUDO cp "${SCRIPT_DIR}/dendROS/dendROS_pipe.py" "$INSTALL_DIR/"
$SUDO cp "${SCRIPT_DIR}/dendROS/dendros_config.py" "$INSTALL_DIR/"
$SUDO cp "${SCRIPT_DIR}/dendROS/dendROS.sh" "$INSTALL_DIR/"
[[ -f "${SCRIPT_DIR}/res/dendros.png" ]] && $SUDO cp "${SCRIPT_DIR}/res/dendros.png" "$INSTALL_DIR/"
$SUDO chmod +x "$INSTALL_DIR/dendROS_pipe.py"
$SUDO chmod +x "$INSTALL_DIR/dendros_config.py"
$SUDO chmod 644 "$INSTALL_DIR/dendROS.sh"

echo -e "${GREEN}[DendROS] Files installed to ${INSTALL_DIR}${RESET}"

# Patch .bashrc
if grep -qF "$SOURCE_LINE" "$BASHRC" 2>/dev/null; then
    echo -e "${YELLOW}[DendROS] .bashrc already patched — skipping${RESET}"
else
    if [[ "$YES" == true ]]; then
        printf '\n# DendROS — colorized ROS 2 terminal output\n%s\n' "$SOURCE_LINE" >> "$BASHRC"
        echo -e "${GREEN}[DendROS] Added to ~/.bashrc${RESET}"
    else
        read -r -p "Add source line to ~/.bashrc? [Y/n] " yn
        if [[ ! "${yn:-}" =~ ^[Nn]$ ]]; then
            printf '\n# DendROS — colorized ROS 2 terminal output\n%s\n' "$SOURCE_LINE" >> "$BASHRC"
            echo -e "${GREEN}[DendROS] Added to ~/.bashrc${RESET}"
            echo -e "${YELLOW}[DendROS] Run: source ~/.bashrc${RESET}"
        else
            echo -e "${YELLOW}[DendROS] Skipped. Add manually to ~/.bashrc:${RESET}"
            echo "  $SOURCE_LINE"
        fi
    fi
fi

echo -e "${GREEN}[DendROS] Done!${RESET}"
