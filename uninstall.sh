#!/usr/bin/env bash
# DeGenRESOLVE - Uninstaller
set -euo pipefail
APP_NAME="degenresolve"
INSTALL_PREFIX="$HOME/${APP_NAME}"
CONDA_INSTALL_DIR="$HOME/miniconda3"
ENV_NAME="${APP_NAME}"
KEEP_ENV=false

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
success() { echo -e "${GREEN}[ OK ]${NC}  $*"; }
info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix)     INSTALL_PREFIX="$2"; shift 2 ;;
        --conda-dir)  CONDA_INSTALL_DIR="$2"; shift 2 ;;
        --env-name)   ENV_NAME="$2"; shift 2 ;;
        --keep-env)   KEEP_ENV=true; shift ;;
        --help|-h)
            echo "Usage: bash uninstall.sh [--prefix DIR] [--conda-dir DIR] [--env-name NAME] [--keep-env]"
            exit 0 ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

# Same search list as install.sh / create_offline_bundle.sh - keep the three in sync.
# Without the miniforge entries this fell back to the ~/miniconda3 default on a miniforge
# box, so ENV_DIR pointed at a path that does not exist and the -d guard below silently
# skipped removing the real environment.
for _c in "${CONDA_EXE:-}" "$(command -v conda 2>/dev/null || true)" \
          "$HOME/miniforge3/bin/conda" "$HOME/mambaforge/bin/conda" \
          "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" \
          "${CONDA_INSTALL_DIR}/bin/conda" "/opt/conda/bin/conda"; do
    [[ -n "$_c" && -x "$_c" ]] && {
        CONDA_INSTALL_DIR="$($_c info --base 2>/dev/null || echo "$CONDA_INSTALL_DIR")"
        break; }
done
ENV_DIR="${CONDA_INSTALL_DIR}/envs/${ENV_NAME}"

echo ""
echo -e "${BOLD}${RED}DeGenRESOLVE Uninstaller${NC}"
echo -e "Will remove:  ${CYAN}${INSTALL_PREFIX}${NC}  -  ${CYAN}${ENV_DIR}${NC}"
read -rp "Continue? [y/N] " C; [[ "${C,,}" == "y" ]] || { echo "Aborted."; exit 0; }
echo ""

[[ "$KEEP_ENV" == false && -d "$ENV_DIR" ]] && \
    rm -rf "$ENV_DIR" && success "Removed env: $ENV_DIR" || true
[[ -d "$INSTALL_PREFIX" ]] && rm -rf "$INSTALL_PREFIX" && \
    success "Removed: $INSTALL_PREFIX" || true
for f in "$HOME/Desktop/DeGenRESOLVE.desktop" \
         "$HOME/.local/share/applications/degenresolve.desktop"; do
    [[ -f "$f" ]] && rm -f "$f" && success "Removed: $f" || true
done
command -v update-desktop-database &>/dev/null && \
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
[[ -L "$HOME/bin/degenresolve" ]] && rm -f "$HOME/bin/degenresolve" && \
    success "Removed symlink" || true
for RC in "$HOME/.bashrc" "$HOME/.zshrc"; do
    [[ -f "$RC" ]] && grep -q "# >>> DeGenRESOLVE installer >>>" "$RC" && \
        sed -i '/# >>> DeGenRESOLVE installer >>>/,/# <<< DeGenRESOLVE installer <<</d' "$RC" && \
        success "Cleaned: $RC" || true
done
echo ""; success "Uninstalled."; echo ""
