#!/usr/bin/env bash
# =============================================================================
#  DeGenRESOLVE - Offline Installer  v1.0.0
# =============================================================================
#  Run on the TARGET machine.  NO internet connection required.
#
#  USAGE:  bash install.sh [OPTIONS]
#  OPTIONS
#    --prefix DIR      Application install directory     (default: ~/degenresolve)
#    --conda-dir DIR   Miniconda install directory       (default: ~/miniconda3)
#    --env-name NAME   Conda environment name            (default: degenresolve)
#    --no-shortcut     Skip desktop shortcut
#    --reinstall       Force removal and re-extraction of conda environment
#    --modify-rc       Write PATH entry to ~/.bashrc     (default: print only)
#    --dry-run         Preview without doing anything
#    --help            Show this help
#
#  INCLUDED TOOLS
#    samtools - bcftools (vcfutils.pl) - minimap2 - porechop - seqtk - htslib
#    qualimap - openjdk (Java) - NanoPlot
#    PyQt5 - pysam - biopython - numpy - cyvcf2 - click - coloredlogs - humanfriendly
# =============================================================================
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="degenresolve"
APP_VERSION="1.0.0"
INSTALL_PREFIX="$HOME/${APP_NAME}"
CONDA_INSTALL_DIR="$HOME/miniconda3"
ENV_NAME="${APP_NAME}"
CREATE_SHORTCUT=true
REINSTALL=false
DRY_RUN=false
MODIFY_RC=false

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; MAGENTA='\033[0;35m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[ OK ]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()     { echo -e "${RED}[FAIL]${NC}  $*" >&2; exit 1; }
step()    { echo -e "\n${BOLD}${MAGENTA}> $*${NC}"; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix)       INSTALL_PREFIX="$2"; shift 2 ;;
        --conda-dir)    CONDA_INSTALL_DIR="$2"; shift 2 ;;
        --env-name)     ENV_NAME="$2"; shift 2 ;;
        --no-shortcut)  CREATE_SHORTCUT=false; shift ;;
        --reinstall)    REINSTALL=true; shift ;;
        --dry-run)      DRY_RUN=true; shift ;;
        --modify-rc)    MODIFY_RC=true; shift ;;
        --help|-h)      grep '^#  ' "${BASH_SOURCE[0]}" | sed 's/^#  \?//'; exit 0 ;;
        *) die "Unknown: $1  (try --help)" ;;
    esac
done

PACKED_ENV="${BUNDLE_DIR}/env/degenresolve_env.tar.gz"

# `clear` exits non-zero with TERM unset (ssh without a tty, docker build, cron), which
# under `set -e` killed the installer before pre-flight with only "TERM environment
# variable not set." to go on.
clear 2>/dev/null || true
echo -e "${BOLD}${GREEN}"
cat << 'BANNER'
     __   ___  __   ___         __    ___  ___  __              ___
    |  \ |___ | _  |___  |\ |  |__/  |___ [__  |  | |    |   | |___
    |__/ |___ |__] |___  | \|  |  \  |___ ___] |__| |___  \_/  |___
  DeGenRESOLVE  ·  ONT Sequencing Data Analyzer  ·  Offline Installer  v1.0.0
BANNER
echo -e "${NC}"
echo -e "  ${BOLD}Bundle  :${NC} ${CYAN}${BUNDLE_DIR}${NC}"
echo -e "  ${BOLD}Prefix  :${NC} ${CYAN}${INSTALL_PREFIX}${NC}"
[[ "$DRY_RUN" == true ]] && echo -e "  ${YELLOW}DRY-RUN - nothing will be installed${NC}"
echo ""

# Pre-flight
step "Pre-flight checks"
[[ "$(uname -s)" == "Linux"  ]] || die "Linux only."
[[ "$(uname -m)" == "x86_64" ]] || die "x86_64 only."
success "Platform: Linux x86_64"
[[ "${BASH_VERSINFO[0]}" -ge 4 ]] || die "bash ≥ 4 required."
success "Bash: $BASH_VERSION"
[[ -f "$PACKED_ENV" ]] || \
    die "Packed environment not found: $PACKED_ENV\nBundle may be incomplete."
success "Packed environment: $(du -sh "$PACKED_ENV" | cut -f1)"
[[ -f "${BUNDLE_DIR}/app/degenresolve.py" ]] || die "degenresolve.py missing from bundle."
success "Application source verified."
AVAIL_GB=$(df -BG "$HOME" 2>/dev/null | awk 'NR==2 {gsub("G",""); print $4}' || echo 0)
[[ "$AVAIL_GB" -lt 6 ]] && warn "Only ${AVAIL_GB} GB free - need ~6 GB." || \
    success "Disk space: ${AVAIL_GB} GB"
for t in tar gzip; do command -v "$t" &>/dev/null && success "Found: $t" || \
    die "$t not found."; done

# Step 1: Miniconda
step "Step 1/5 - Miniconda"
# Search $CONDA_EXE and miniforge/mambaforge too, not just miniconda3/anaconda3: on a
# machine that already has miniforge but no conda on PATH, this reported no conda and
# installed a second, redundant Miniconda alongside it. Kept in sync with
# create_offline_bundle.sh and uninstall.sh, which share this list.
locate_conda() {
    for _c in "${CONDA_EXE:-}" "$(command -v conda 2>/dev/null || true)" \
              "$HOME/miniforge3/bin/conda" "$HOME/mambaforge/bin/conda" \
              "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" \
              "$CONDA_INSTALL_DIR/bin/conda" "/opt/conda/bin/conda"; do
        [[ -n "$_c" && -x "$_c" ]] && { echo "$_c"; return; }
    done; echo ""
}
CONDA_BIN="$(locate_conda)"

if [[ -n "$CONDA_BIN" ]]; then
    CONDA_INSTALL_DIR="$($CONDA_BIN info --base)"
    success "conda: $($CONDA_BIN --version)  ($CONDA_BIN)"
else
    MINICONDA_SH="${BUNDLE_DIR}/miniconda/Miniconda3-latest-Linux-x86_64.sh"
    [[ -f "$MINICONDA_SH" ]] || die "Miniconda installer missing from bundle."
    info "Installing Miniconda to $CONDA_INSTALL_DIR ..."
    [[ "$DRY_RUN" == false ]] && \
        bash "$MINICONDA_SH" -b -p "$CONDA_INSTALL_DIR" -u 2>&1 | tail -5 || \
        echo "[DRY-RUN] would install Miniconda"
    CONDA_BIN="${CONDA_INSTALL_DIR}/bin/conda"
    success "Miniconda installed at $CONDA_INSTALL_DIR"
fi

ENV_DIR="${CONDA_INSTALL_DIR}/envs/${ENV_NAME}"
ENV_BIN="${ENV_DIR}/bin"
export PATH="${CONDA_INSTALL_DIR}/bin:${PATH}"
# shellcheck disable=SC1091
[[ -f "${CONDA_INSTALL_DIR}/etc/profile.d/conda.sh" ]] && \
    source "${CONDA_INSTALL_DIR}/etc/profile.d/conda.sh" || true

# Step 2: Extract packed environment
step "Step 2/5 - Extract packed conda environment"

# Sanity-check any existing env before deciding to skip
if [[ -d "$ENV_DIR" && "$REINSTALL" == false ]]; then
    info "Found existing environment at: $ENV_DIR - checking if complete..."
    BROKEN=false
    for _tool in samtools bcftools minimap2 python NanoPlot; do
        [[ -x "${ENV_DIR}/bin/${_tool}" ]] || { BROKEN=true; break; }
    done
    # -x is not enough, and bcftools was not even checked. The v1.0.0 gsl soname mismatch
    # left bcftools present and executable but unable to start (libgsl.so.25 missing), so
    # an env installed from that bundle passed this check, extraction was skipped, and the
    # upgrade silently preserved the exact bug the new bundle exists to fix. Actually run
    # the dynamically linked tools rather than testing for their existence.
    if [[ "$BROKEN" == false ]]; then
        for _tool in samtools bcftools minimap2; do
            "${ENV_DIR}/bin/${_tool}" --version &>/dev/null || { BROKEN=true; break; }
        done
    fi
    if [[ "$BROKEN" == false ]]; then
        "${ENV_DIR}/bin/python" -c "import pysam" &>/dev/null 2>&1 || BROKEN=true
    fi
    if [[ "$BROKEN" == true ]]; then
        warn "Existing environment is incomplete - replacing with bundled environment."
        [[ "$DRY_RUN" == false ]] && rm -rf "$ENV_DIR"
    else
        success "Existing environment looks complete - skipping extraction."
        info "  (Use --reinstall to force a full re-extraction)"
    fi
fi

if [[ "$REINSTALL" == true && -d "$ENV_DIR" ]]; then
    info "Removing existing environment (--reinstall): $ENV_DIR"
    [[ "$DRY_RUN" == false ]] && rm -rf "$ENV_DIR"
fi

if [[ ! -d "$ENV_DIR" ]]; then
    info "Extracting packed environment to: $ENV_DIR"
    info "This may take 3-8 minutes..."
    if [[ "$DRY_RUN" == false ]]; then
        mkdir -p "$ENV_DIR"
        tar -xzf "$PACKED_ENV" -C "$ENV_DIR" || \
            die "Extraction failed. The packed env may be corrupted.\nRe-run create_offline_bundle.sh."
        success "Extraction complete."
        if [[ -f "${ENV_DIR}/bin/conda-unpack" ]]; then
            info "Running conda-unpack to fix installation paths..."
            "${ENV_DIR}/bin/conda-unpack" && \
                success "Path rewriting complete." || \
                die "conda-unpack failed. Try: rm -rf $ENV_DIR && bash install.sh --reinstall"
        else
            warn "conda-unpack not found - OK for conda-pack ≥ 1.7."
        fi
    else
        echo "[DRY-RUN] mkdir -p $ENV_DIR && tar -xzf $PACKED_ENV -C $ENV_DIR"
    fi
fi

if [[ "$DRY_RUN" == false ]]; then
    if ! $CONDA_BIN env list 2>/dev/null | awk '{print $1}' | grep -qx "$ENV_NAME"; then
        $CONDA_BIN config --append envs_dirs "${CONDA_INSTALL_DIR}/envs" 2>/dev/null || true
    fi
    success "Environment '${ENV_NAME}' ready at: $ENV_DIR"
fi

# Step 3: Install application
step "Step 3/5 - Install application files"
if [[ "$DRY_RUN" == false ]]; then
    mkdir -p "$INSTALL_PREFIX"
    cp -r "${BUNDLE_DIR}/app"/. "$INSTALL_PREFIX/"
    find "$INSTALL_PREFIX" -name "*.sh" -exec chmod +x {} \;
    if [[ -f "$INSTALL_PREFIX/setup.py" ]]; then
        "${ENV_BIN}/python" -m pip install -e "$INSTALL_PREFIX" \
            --no-deps --quiet 2>&1 || \
            warn "setup.py install had warnings (non-fatal)."
    fi
fi
success "Application: $INSTALL_PREFIX"

LAUNCHER="${INSTALL_PREFIX}/run_degenresolve.sh"
if [[ "$DRY_RUN" == false ]]; then
    cat > "$LAUNCHER" << LAUNCHER_EOF
#!/usr/bin/env bash
# DeGenRESOLVE launcher - generated by offline installer v${APP_VERSION}
ENV_BIN="${ENV_BIN}"
CONDA_INSTALL_DIR="${CONDA_INSTALL_DIR}"
ENV_NAME="${ENV_NAME}"
if [[ -f "\${CONDA_INSTALL_DIR}/etc/profile.d/conda.sh" ]]; then
    source "\${CONDA_INSTALL_DIR}/etc/profile.d/conda.sh" 2>/dev/null || true
    conda activate "\${ENV_NAME}" 2>/dev/null || export PATH="\${ENV_BIN}:\${PATH}"
else
    export PATH="\${ENV_BIN}:\${PATH}"
fi
export JAVA_TOOL_OPTIONS="\${JAVA_TOOL_OPTIONS:-} -Djava.awt.headless=true"
cd "${INSTALL_PREFIX}"
exec "\${ENV_BIN}/python" degenresolve.py "\$@"
LAUNCHER_EOF
    chmod +x "$LAUNCHER"
fi
success "Launcher: $LAUNCHER"
[[ -d "$HOME/bin" ]] && ln -sf "$LAUNCHER" "$HOME/bin/degenresolve" 2>/dev/null && \
    success "Symlink: ~/bin/degenresolve" || true

# Step 4: Desktop integration
step "Step 4/5 - Desktop integration"
if [[ "$CREATE_SHORTCUT" == true && "$DRY_RUN" == false ]]; then
    ICON=""
    for _c in "${INSTALL_PREFIX}/app_data/img/banner.jpg" \
               "${INSTALL_PREFIX}/app_data/img/icon.png"; do
        [[ -f "$_c" ]] && { ICON="$_c"; break; }
    done
    DESK="[Desktop Entry]
Version=1.0
Type=Application
Name=DeGenRESOLVE
Comment=ONT Sequencing Data Analyzer
Exec=bash ${LAUNCHER}
Icon=${ICON}
Terminal=false
Categories=Science;Biology;"
    APPS="$HOME/.local/share/applications"
    mkdir -p "$APPS"
    echo "$DESK" > "${APPS}/degenresolve.desktop"
    chmod +x "${APPS}/degenresolve.desktop"
    success "App menu: ${APPS}/degenresolve.desktop"
    [[ -d "$HOME/Desktop" ]] && \
        echo "$DESK" > "$HOME/Desktop/DeGenRESOLVE.desktop" && \
        chmod +x "$HOME/Desktop/DeGenRESOLVE.desktop" && \
        success "Desktop shortcut created." || true
    command -v update-desktop-database &>/dev/null && \
        update-desktop-database "$APPS" 2>/dev/null || true
fi

# Shell RC (opt-in only)
SHELL_RC=""
[[ -f "$HOME/.bashrc" ]] && SHELL_RC="$HOME/.bashrc"
[[ -f "$HOME/.zshrc"  ]] && SHELL_RC="$HOME/.zshrc"
RC_S="# >>> DeGenRESOLVE installer >>>"
RC_E="# <<< DeGenRESOLVE installer <<<"
RC_LINES="$(printf '%s\n' \
    "" "$RC_S" \
    "export PATH=\"${INSTALL_PREFIX}:\${PATH}\"" \
    "[[ -f \"${CONDA_INSTALL_DIR}/etc/profile.d/conda.sh\" ]] && \\" \
    "    source \"${CONDA_INSTALL_DIR}/etc/profile.d/conda.sh\"" \
    "$RC_E")"

if [[ "$DRY_RUN" == false ]]; then
    if [[ "$MODIFY_RC" == true && -n "$SHELL_RC" ]]; then
        if ! grep -q "$RC_S" "$SHELL_RC" 2>/dev/null; then
            echo "$RC_LINES" >> "$SHELL_RC"
            success "Added PATH entry to $SHELL_RC  (--modify-rc)"
        else
            info "PATH entry already present in $SHELL_RC."
        fi
    else
        echo ""
        echo -e "  ${BOLD}${YELLOW}Optional: add DeGenRESOLVE to your PATH${NC}"
        echo -e "  Add these lines to ${CYAN}${SHELL_RC:-~/.bashrc}${NC} manually:"
        echo -e "  ${CYAN} ${NC}"
        echo "$RC_LINES" | sed 's/^/  /'
        echo -e "  ${CYAN} ${NC}"
        echo -e "  Or re-run with  ${CYAN}--modify-rc${NC}  to do it automatically."
        echo ""
    fi
fi

# Step 5: Verification
step "Step 5/5 - Verification"
PASS=0; FAIL=0

# Gate every binary check: exists, and every shared lib resolves. ldd is the real test.
# The version probes run under `set -o pipefail`, so a binary that dies on a missing
# library reports "installed" - indistinguishable from seqtk, which legitimately has no
# --version. ldd must run on the symlink-resolved path: $ORIGIN-relative RPATHs resolve
# against the real binary (conda's bin/java -> lib/jvm/bin/java), so ldd'ing a symlink
# reports false "not found" for libs that load fine at runtime.
chk_bin() {
    local t="$1" bin="$2"
    if [[ ! -x "$bin" ]]; then
        warn "$t  ->  NOT FOUND at $bin"; ((FAIL++)) || true; return 1
    fi
    local real; real="$(readlink -f "$bin")"
    if ldd "$real" 2>/dev/null | grep -q "not found"; then
        warn "$t  ->  BROKEN LINKAGE: $(ldd "$real" 2>/dev/null | grep 'not found' | head -1 | xargs)"
        ((FAIL++)) || true; return 1
    fi
    return 0
}

chk_cmd() {
    local t="$1" bin="${ENV_BIN}/$1"
    [[ "$DRY_RUN" == true ]] && { info "(dry-run) $t"; return 0; }
    # return 0, not 1: chk_bin already counted the failure, and callers invoke chk_cmd as
    # a bare statement under `set -e` - a non-zero return would abort the whole script at
    # the first bad tool instead of reporting every one and printing the summary.
    chk_bin "$t" "$bin" || return 0
    local ver; ver=$("$bin" --version 2>&1 | head -1) || ver="installed"
    success "$t  ->  $ver"; ((PASS++)) || true
}
chk_py() {
    local m="$1"
    [[ "$DRY_RUN" == true ]] && { info "(dry-run) import $m"; return; }
    if "${ENV_BIN}/python" -c "import $m" &>/dev/null 2>&1; then
        success "python: import $m"; ((PASS++)) || true
    else
        warn "python: import $m  ->  FAILED"; ((FAIL++)) || true
    fi
}

chk_cmd samtools
chk_cmd bcftools
chk_cmd minimap2
chk_cmd seqtk
chk_cmd python

if [[ "$DRY_RUN" == false ]]; then
    # qualimap
    if chk_bin qualimap "${ENV_BIN}/qualimap"; then
        QVER=$("${ENV_BIN}/qualimap" 2>&1 | grep -E -i 'QualiMap|version [0-9]' \
               | grep -Eiv 'java|memory|warning|error' | head -1 | xargs || true)
        [[ -z "$QVER" ]] && QVER="installed"
        success "qualimap  ->  $QVER"; ((PASS++)) || true
    fi
    # java
    if chk_bin "java (openjdk)" "${ENV_BIN}/java"; then
        JV=$("${ENV_BIN}/java" -version 2>&1 | head -1) || JV="installed"
        success "java (openjdk)  ->  $JV"; ((PASS++)) || true
    fi
    # nanoplot
    if chk_bin NanoPlot "${ENV_BIN}/NanoPlot"; then
        NV=$("${ENV_BIN}/NanoPlot" --version 2>&1 | head -1) || NV="installed"
        success "NanoPlot  ->  $NV"; ((PASS++)) || true
    fi
    # vcfutils.pl
    if [[ -x "${ENV_BIN}/vcfutils.pl" ]]; then
        success "vcfutils.pl  ->  found"; ((PASS++)) || true
    else
        warn "vcfutils.pl  ->  not in ${ENV_BIN}"; ((FAIL++)) || true
    fi
fi

# --- Minimum tool versions -------------------------------------------------------------
# The bundled environment satisfies these by construction (bcftools 1.24 etc.), but
# --env-name can point this installer at a pre-existing environment, and a partially
# extracted archive can leave an older binary in place. An audit found that the sup
# basecall profile passes --indels-cns and --max-BQ to bcftools mpileup: both are 1.21+
# flags, and an older bcftools fails mid-run with a bare usage error that names nothing.
# Catch that here, at install time, rather than three steps into someone's analysis.
chk_ver() {
    local t="$1" want="$2" bin="${ENV_BIN}/$1" have
    [[ "$DRY_RUN" == true ]] && { info "(dry-run) $t >= $want"; return; }
    [[ -x "$bin" ]] || return 0                      # absence already counted by chk_cmd
    have=$("$bin" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1) || have=""
    if [[ -z "$have" ]]; then
        warn "$t  ->  version could not be determined (wanted >= $want)"; return
    fi
    if [[ "$(printf '%s\n%s\n' "$want" "$have" | sort -V | head -1)" != "$want" ]]; then
        warn "$t $have is older than the required $want"
        [[ "$t" == "bcftools" ]] && \
            warn "  the sup profile needs --indels-cns and --max-BQ, absent before 1.21"
        ((FAIL++)) || true
    else
        success "$t $have  >=  $want"; ((PASS++)) || true
    fi
}
chk_ver samtools 1.10
chk_ver bcftools 1.21
chk_ver minimap2 2.17

# The bundled interpreter is 3.10.21. consensus_editor.py uses PEP 604 `str | None`
# annotations, which are evaluated at class-definition time and raise TypeError on 3.8/3.9,
# so a mis-pointed --env-name would fail at import with an error that points nowhere useful.
if [[ "$DRY_RUN" == false && -x "${ENV_BIN}/python" ]]; then
    if "${ENV_BIN}/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
        success "python >= 3.10  ->  $("${ENV_BIN}/python" -V 2>&1)"; ((PASS++)) || true
    else
        warn "python $("${ENV_BIN}/python" -V 2>&1) is too old; DeGenRESOLVE needs 3.10+"
        ((FAIL++)) || true
    fi
fi

chk_py PyQt5
chk_py PyQt5.QtWebEngineWidgets
chk_py markdown_it
chk_py pysam
chk_py Bio
chk_py numpy
chk_py cyvcf2
chk_py coloredlogs
chk_py humanfriendly
chk_py porechop

# --- Optional: run the test suite ------------------------------------------------------
# pytest is deliberately NOT part of the packed environment (see app/requirements.txt), so
# this is skipped rather than failed when it is absent. When it is available the suite is a
# genuine post-install check: 121 project tests plus 13 regression tests that pin defects
# fixed in this release.
if [[ "$DRY_RUN" == false ]]; then
    if "${ENV_BIN}/python" -c 'import pytest' &>/dev/null; then
        info "Running the test suite (pytest found)..."
        if ( cd "${INSTALL_PREFIX}/app" 2>/dev/null && \
             QT_QPA_PLATFORM=offscreen "${ENV_BIN}/python" -m pytest tests/ -q \
                 -p no:cacheprovider --no-header ) ; then
            success "test suite passed"; ((PASS++)) || true
        else
            warn "test suite reported failures - inspect before relying on results"
            ((FAIL++)) || true
        fi
    else
        info "pytest not installed - skipping the test suite (pip install pytest to enable)"
    fi
fi

echo ""
echo -e "${BOLD}${GREEN}+=======================================================+${NC}"
if   [[ "$DRY_RUN" == true ]]; then
    echo -e "${BOLD}${YELLOW}|   DRY-RUN complete - nothing was installed             |${NC}"
elif [[ "$FAIL" -eq 0 ]]; then
    echo -e "${BOLD}${GREEN}|    Installation successful! All tools verified.      |${NC}"
else
    echo -e "${BOLD}${YELLOW}|    Installed with ${FAIL} warning(s) - see above.       |${NC}"
fi
echo -e "${BOLD}${GREEN}+=======================================================+${NC}"

if [[ "$DRY_RUN" == false ]]; then
    echo ""
    echo -e "  ${BOLD}Application :${NC} ${CYAN}${INSTALL_PREFIX}${NC}"
    echo -e "  ${BOLD}Launcher    :${NC} ${CYAN}${LAUNCHER}${NC}"
    echo -e "  ${BOLD}Conda env   :${NC} ${CYAN}${ENV_DIR}${NC}"
    echo -e "  ${BOLD}Verified    :${NC} ${GREEN}${PASS} passed${NC}, ${YELLOW}${FAIL} warnings${NC}"
    echo ""
    echo -e "  ${BOLD}To start:${NC}  ${CYAN}bash ${LAUNCHER}${NC}"
    echo ""
    echo -e "  Uninstall:  ${CYAN}bash ${BUNDLE_DIR}/uninstall.sh${NC}"
fi
echo ""
