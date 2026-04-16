#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALLER_NAME="DeGenRESOLVE_installer.run"
PAYLOAD_DIR="$SCRIPT_DIR/payload"
INSTALL_SCRIPT="$SCRIPT_DIR/install.sh"

[ -d "$PAYLOAD_DIR" ] || {
    echo "[✘] Missing payload directory: $PAYLOAD_DIR" >&2
    exit 1
}

[ -x "$INSTALL_SCRIPT" ] || {
    echo "[✘] install.sh is not executable. Run: chmod +x $INSTALL_SCRIPT" >&2
    exit 1
}

command -v makeself >/dev/null 2>&1 || {
    echo "[✘] makeself is not installed. Install it with: sudo apt install makeself" >&2
    exit 1
}

echo "[+] Building installer archive"

makeself \
    --nox11 \
    "$PAYLOAD_DIR" \
    "$SCRIPT_DIR/$INSTALLER_NAME" \
    "DeGenRESOLVE Offline Installer" \
    ./install.sh

echo "[✔] Installer created: $SCRIPT_DIR/$INSTALLER_NAME"
