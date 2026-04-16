#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="${INSTALL_DIR:-$HOME/DeGenRESOLVE}"
ENV_ARCHIVE="$SCRIPT_DIR/payload/env/pyvcf_env.tar.gz"
ENV_DIR="$INSTALL_DIR/pyvcf_env"
APP_SOURCE_DIR="$SCRIPT_DIR/payload/app"
BIN_SOURCE_DIR="$SCRIPT_DIR/payload/bin"

log() {
    printf '[+] %s\n' "$1"
}

fail() {
    printf '[✘] %s\n' "$1" >&2
    exit 1
}

log "Installing DeGenRESOLVE"
log "Target directory: $INSTALL_DIR"

log "Checking dependencies"
command -v tar >/dev/null 2>&1 || fail "tar not found"
command -v bash >/dev/null 2>&1 || fail "bash not found"

[ -f "$ENV_ARCHIVE" ] || fail "Environment archive not found: $ENV_ARCHIVE"
[ -d "$APP_SOURCE_DIR" ] || fail "Application payload directory not found: $APP_SOURCE_DIR"

mkdir -p "$INSTALL_DIR"

log "Extracting packed conda environment"
tar -xzf "$ENV_ARCHIVE" -C "$INSTALL_DIR"

if [ -x "$ENV_DIR/bin/conda-unpack" ]; then
    log "Relocating conda environment"
    "$ENV_DIR/bin/conda-unpack"
else
    fail "conda-unpack is missing at $ENV_DIR/bin/conda-unpack"
fi

log "Copying application files"
cp -a "$APP_SOURCE_DIR"/. "$INSTALL_DIR"/

if [ -d "$BIN_SOURCE_DIR" ] && [ -n "$(find "$BIN_SOURCE_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    log "Copying bundled binaries"
    mkdir -p "$INSTALL_DIR/bin"
    cp -a "$BIN_SOURCE_DIR"/. "$INSTALL_DIR/bin"/
    chmod +x "$INSTALL_DIR/bin"/* || true
fi

[ -f "$INSTALL_DIR/master_cmd.sh" ] || fail "master_cmd.sh not found in installed application"
chmod +x "$INSTALL_DIR/master_cmd.sh"

log "Creating launcher"
cat > "$INSTALL_DIR/run_DeGenRESOLVE.sh" <<LAUNCHER
#!/usr/bin/env bash
set -euo pipefail
INSTALL_DIR="$INSTALL_DIR"
ENV_DIR="$ENV_DIR"

if [ -d "\$INSTALL_DIR/bin" ]; then
    export PATH="\$INSTALL_DIR/bin:\$PATH"
fi

source "\$ENV_DIR/bin/activate"
exec bash "\$INSTALL_DIR/master_cmd.sh" "\$@"
LAUNCHER
chmod +x "$INSTALL_DIR/run_DeGenRESOLVE.sh"

log "Adding ~/.local/bin shortcut"
mkdir -p "$HOME/.local/bin"
ln -sf "$INSTALL_DIR/run_DeGenRESOLVE.sh" "$HOME/.local/bin/degenresolve"

printf '\n[✔] Installation complete\n'
printf 'Run with: degenresolve\n'
printf 'Or: %s\n' "$INSTALL_DIR/run_DeGenRESOLVE.sh"
