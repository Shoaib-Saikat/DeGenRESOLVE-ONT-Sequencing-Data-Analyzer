#!/usr/bin/env bash
# =============================================================================
# DeGenRESOLVE - Offline Installer Builder  v1.0.0
# =============================================================================
# PURPOSE
#   Run ONCE on an internet-connected machine.
#   Produces a fully self-contained archive that installs on any Linux x86-64
#   machine with ZERO internet access.
#
# HOW IT AVOIDS gcc_impl ERRORS
#   Two-phase install:
#   Phase A - conda: system tools only  (no C-extension Python packages)
#   Phase B - pip:   binary wheels only (no gcc, no compilation)
#   The finished environment is compressed with conda-pack.
#   Target machine only needs tar + gzip to install - no conda, no pip.
#
# USAGE
#   bash create_offline_bundle.sh [--output-dir DIR]
#
# OUTPUT
#   degenresolve_offline_bundle_1.0.0.tar.gz
#     install.sh - uninstall.sh - miniconda/ - env/ - app/
# =============================================================================
set -euo pipefail

APP_NAME="degenresolve"
APP_VERSION="1.0.0"
BUILD_ENV_NAME="${APP_NAME}_build_$$"
BUNDLE_DIR="$(pwd)/${APP_NAME}_bundle"
SCRIPT_DIR_SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
PYTHON_VERSION="3.10"

# Phase A: conda - system tools only (zero gcc_impl risk)
CONDA_PACKAGES=(
    "python=${PYTHON_VERSION}"
    "pyqt"
    "pyqtwebengine"
    "samtools"
    "bcftools"
    "htslib"
    "minimap2"
    "seqtk"
    "porechop"
    "qualimap"
    "openjdk"
    "nanoplot"       # <- ONT raw read QC
)

# Phase B: pip binary wheels (no C compilation, no gcc_impl)
PIP_PACKAGES=(
    "pysam"
    "biopython"
    "numpy"
    "cyvcf2"
    "click"
    "coloredlogs"
    "humanfriendly"
    "markdown-it-py"
)

# Helpers
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[ OK ]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()     { echo -e "${RED}[FAIL]${NC}  $*" >&2; exit 1; }
step()    { echo -e "\n${BOLD}${CYAN}== $* ==${NC}"; }

retry() {
    local attempts="$1" delay="$2"; shift 2
    local i=0
    until "$@"; do
        ((i++)) || true
        [[ $i -ge $attempts ]] && die "Failed after $attempts attempts: $*"
        warn "Attempt $i/$attempts failed - retrying in ${delay}s..."
        sleep "$delay"
    done
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) BUNDLE_DIR="$2"; shift 2 ;;
        --help|-h)    grep '^# ' "${BASH_SOURCE[0]}" | head -20 | sed 's/^# //'; exit 0 ;;
        *) die "Unknown: $1" ;;
    esac
done

if command -v curl &>/dev/null; then
    DL() { curl -fsSL --retry 10 --retry-delay 5 --retry-max-time 300 -o "$1" "$2"; }
elif command -v wget &>/dev/null; then
    DL() { wget -q --tries=10 --waitretry=5 --timeout=60 -O "$1" "$2"; }
else
    die "curl or wget required."
fi

CONDA_BIN=""
# $CONDA_EXE is exported by conda's own shell integration and is the most reliable hit.
# miniforge/mambaforge must be searched explicitly: the list previously knew only
# miniconda3, anaconda3 and /opt/conda, so on a miniforge box with conda not on PATH
# (any non-login shell, or one where `conda init` was never run) this aborted with
# "conda not found" while conda sat in ~/miniforge3/bin.
for _c in "${CONDA_EXE:-}" "$(command -v conda 2>/dev/null || true)" \
          "$HOME/miniforge3/bin/conda" "$HOME/mambaforge/bin/conda" \
          "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" \
          "/opt/conda/bin/conda" "/opt/miniforge3/bin/conda"; do
    [[ -n "$_c" && -x "$_c" ]] && { CONDA_BIN="$_c"; break; }
done
[[ -n "$CONDA_BIN" ]] || die \
"conda not found in \$CONDA_EXE, PATH, or the usual prefixes (miniforge3, mambaforge,
        miniconda3, anaconda3, /opt/conda).
        If conda IS installed, activate it first, then re-run:
          source <conda-base>/etc/profile.d/conda.sh
        Otherwise install Miniconda:
          bash <(curl -fsSL $MINICONDA_URL)"

CONDA_BASE="$($CONDA_BIN info --base)"
info "conda  : $($CONDA_BIN --version)"
info "base   : $CONDA_BASE"
# shellcheck disable=SC1091
source "${CONDA_BASE}/etc/profile.d/conda.sh"

$CONDA_BIN config --set remote_max_retries          10
$CONDA_BIN config --set remote_backoff_factor        2
$CONDA_BIN config --set remote_connect_timeout_secs 60
$CONDA_BIN config --set remote_read_timeout_secs   120

SOLVER_BIN="$CONDA_BIN"
if command -v mamba &>/dev/null; then
    SOLVER_BIN="$(command -v mamba)"; info "mamba detected."
elif [[ -x "${CONDA_BASE}/bin/mamba" ]]; then
    SOLVER_BIN="${CONDA_BASE}/bin/mamba"; info "mamba found in base."
else
    info "Installing mamba..."
    retry 5 10 $CONDA_BIN install -n base --yes -c conda-forge mamba 2>&1 | tail -5
    SOLVER_BIN="${CONDA_BASE}/bin/mamba"
    success "mamba installed."
fi

cleanup() {
    local code=$?
    [[ $code -ne 0 ]] && warn "Build failed (exit $code) - cleaning up..."
    $CONDA_BIN remove -n "$BUILD_ENV_NAME" --all --yes --quiet 2>/dev/null || true
}
trap cleanup EXIT

rm -rf "$BUNDLE_DIR"
mkdir -p "$BUNDLE_DIR"/{miniconda,env,app}

# =============================================================================
step "Step 1/7 - Miniconda installer"
# =============================================================================
retry 5 10 DL \
    "$BUNDLE_DIR/miniconda/Miniconda3-latest-Linux-x86_64.sh" \
    "$MINICONDA_URL"
chmod +x "$BUNDLE_DIR/miniconda/Miniconda3-latest-Linux-x86_64.sh"
success "Miniconda installer downloaded."

# =============================================================================
step "Step 2/7 - conda-pack in base"
# =============================================================================
if ! $CONDA_BIN run -n base python -c "import conda_pack" &>/dev/null 2>&1; then
    retry 5 15 $SOLVER_BIN install -n base --yes -c conda-forge conda-pack 2>&1 | tail -5
fi
success "conda-pack ready."

# =============================================================================
step "Step 3/7 - Phase A: conda system tools (no gcc_impl)"
# =============================================================================
info "Packages: ${CONDA_PACKAGES[*]}"
# Do NOT add -c defaults. bioconda builds against conda-forge, and defaults ships
# incompatible rebuilds of the same libs: its gsl 2.7.1 is soname libgsl.so.27, while
# bioconda's bcftools links libgsl.so.25 (conda-forge gsl 2.7). Mixing them yields a
# bcftools that cannot start. --override-channels is required because ~/.condarc lists
# defaults, which is otherwise appended back. Channel priority alone does NOT save you
# here - mamba 2.x ignores --strict-channel-priority for this solve (verified); the flag
# is kept only for the conda fallback path, where it is honoured.
# Reproducibility: an unpinned solve resolves to whatever the channels serve that
# day, which is how two bundles built from this same script ended up shipping
# different minimap2 versions. When env.lock exists the environment is rebuilt from
# exact package URLs; otherwise we resolve fresh and WRITE the lock, so the next
# build is reproducible even though this one could not be.
CONDA_LOCK="$SCRIPT_DIR_SELF/env.lock"
PIP_LOCK="$SCRIPT_DIR_SELF/requirements.lock"
if [[ -f "$CONDA_LOCK" ]]; then
    info "Using pinned environment: $CONDA_LOCK"
    retry 5 30 $CONDA_BIN create -n "$BUILD_ENV_NAME" --yes --file "$CONDA_LOCK" \
        2>&1 | tee "$BUNDLE_DIR/build_phase_a.log"
else
    warn "No env.lock found - resolving latest. This build defines the pin."
    retry 5 30 $SOLVER_BIN create -n "$BUILD_ENV_NAME" --yes \
        --override-channels --strict-channel-priority \
        -c conda-forge -c bioconda \
        "${CONDA_PACKAGES[@]}" \
        2>&1 | tee "$BUNDLE_DIR/build_phase_a.log"
fi
success "Phase A complete."

# =============================================================================
step "Step 4/7 - Phase B: pip binary wheels (no gcc)"
# =============================================================================
info "Packages: ${PIP_PACKAGES[*]}"
if [[ -f "$PIP_LOCK" ]]; then
    info "Using pinned wheels: $PIP_LOCK"
    PIP_SPEC=(-r "$PIP_LOCK")
else
    PIP_SPEC=("${PIP_PACKAGES[@]}")
fi
retry 5 15 $CONDA_BIN run -n "$BUILD_ENV_NAME" \
    python -m pip install --only-binary ":all:" --prefer-binary \
    "${PIP_SPEC[@]}" \
    2>&1 | tee "$BUNDLE_DIR/build_phase_b.log" || {
    warn "--only-binary failed for some; retrying without restriction..."
    retry 5 15 $CONDA_BIN run -n "$BUILD_ENV_NAME" \
        python -m pip install --prefer-binary \
        "${PIP_SPEC[@]}" \
        2>&1 | tee -a "$BUNDLE_DIR/build_phase_b.log"
}
success "Phase B complete."

# =============================================================================
step "Step 5/7 - Verify environment (fail fast)"
# =============================================================================
ENV_BIN="${CONDA_BASE}/envs/${BUILD_ENV_NAME}/bin"
VERIFY_FAILED=false

# Gate every binary check: exists, and every shared lib resolves.
# ldd is the real test - the version probes below all pipe to head, which masks the
# binary's exit status, so a linker error would otherwise be reported as a version
# string under a green [ OK ]. Shell wrappers ("not a dynamic executable") pass through.
check_bin() {
    local t="$1" bin="$2"
    if [[ ! -x "$bin" ]]; then
        warn "$t  ->  NOT FOUND at $bin"; VERIFY_FAILED=true; return 1
    fi
    # ldd must run on the symlink-resolved path: $ORIGIN-relative RPATHs resolve against
    # the real binary location, so ldd'ing a symlink (conda's bin/java -> lib/jvm/bin/java)
    # reports false "not found" for libs that load fine at runtime.
    local real; real="$(readlink -f "$bin")"
    if ldd "$real" 2>/dev/null | grep -q "not found"; then
        warn "$t  ->  BROKEN LINKAGE: $(ldd "$real" 2>/dev/null | grep 'not found' | head -1 | xargs)"
        VERIFY_FAILED=true; return 1
    fi
    return 0
}

verify_cmd() {
    local t="$1" bin="${ENV_BIN}/$1"
    # return 0, not 1: check_bin already set VERIFY_FAILED, and callers invoke verify_cmd
    # as a bare statement under `set -e` - a non-zero return would abort the script at the
    # first bad tool, skipping the remaining checks and the "Verification failed" message.
    check_bin "$t" "$bin" || return 0
    local ver; ver=$("$bin" --version 2>&1 | head -1) || ver="installed"
    success "$t  ->  $ver"
}
verify_py() {
    local m="$1"
    if "${ENV_BIN}/python" -c "import $m" &>/dev/null 2>&1; then
        success "python: import $m"
    else
        warn "python: import $m  ->  FAILED"; VERIFY_FAILED=true
    fi
}

verify_cmd samtools
verify_cmd bcftools
verify_cmd minimap2
verify_cmd seqtk
verify_cmd python

# qualimap - Java wrapper; version extracted from help output
if check_bin qualimap "${ENV_BIN}/qualimap"; then
    QVER=$("${ENV_BIN}/qualimap" 2>&1 \
        | grep -E -i 'QualiMap|version [0-9]' \
        | grep -Eiv 'java|memory|warning|error' \
        | head -1 | xargs || true)
    [[ -z "$QVER" ]] && QVER="installed"
    success "qualimap  ->  $QVER"
fi

if check_bin "java (openjdk)" "${ENV_BIN}/java"; then
    JVER=$("${ENV_BIN}/java" -version 2>&1 | head -1) || JVER="installed"
    success "java (openjdk)  ->  $JVER"
fi

# nanoplot
if check_bin NanoPlot "${ENV_BIN}/NanoPlot"; then
    NVER=$("${ENV_BIN}/NanoPlot" --version 2>&1 | head -1) || NVER="installed"
    success "NanoPlot  ->  $NVER"
fi

verify_py PyQt5
verify_py PyQt5.QtWebEngineWidgets
verify_py markdown_it
verify_py pysam
verify_py Bio
verify_py numpy
verify_py cyvcf2
verify_py click
verify_py coloredlogs
verify_py humanfriendly
verify_py porechop

[[ "$VERIFY_FAILED" == true ]] && \
    die "Verification failed. Check build logs in $BUNDLE_DIR/"
success "All packages verified."

# Write bundled tool version manifest
info "Writing tool version manifest..."
# Every value must be one JSON-safe line. Capture first, then emit: under `set -o pipefail`
# a probe that prints output *and* exits non-zero made `... || echo unknown` append a second
# line, embedding a raw newline in the string. seqtk is exactly that case - it has no
# --version, so it printed its usage error and "unknown". java quotes its own version
# string, which closes the JSON value early. Both defects produced a manifest that no
# JSON parser could read. main_with_config.sh solves the same two cases for the runtime
# manifest (_jver strips quotes; seqtk is probed bare) - keep the two in sync.
# Probe via $ENV_BIN, never `command -v`: the build env is not activated here, so
# `command -v vcfutils.pl` resolved against the *build host's* PATH and reported "not
# found" for a file the bundle does ship. That idiom is correct only in
# main_with_config.sh, which runs at runtime with the env on PATH.
_san()   { tr -d '"' | tr -d '\n'; }
_ver()   { local o; o=$("${ENV_BIN}/$1" --version 2>&1 | head -1 | _san) || true; printf '%s' "${o:-unknown}"; }
_pyver() { local o; o=$("${ENV_BIN}/python" -c "import $1; print(getattr($1,'__version__','unknown'))" 2>/dev/null | _san) || true; printf '%s' "${o:-unknown}"; }
_seqtkver() { local o; o=$("${ENV_BIN}/seqtk" 2>&1 | grep -i 'version' | head -1 | _san) || true; printf '%s' "${o:-unknown}"; }
# PATH must include ENV_BIN: qualimap is a shell wrapper that calls java, and the
# build env is not activated here. Without it the wrapper prints its preamble and no
# version, which is why this probe previously recorded "unknown" and made every
# runtime check report qualimap as differing from the bundle.
QVER_M=$(PATH="${ENV_BIN}:$PATH" \
    JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:-} -Djava.awt.headless=true" \
    "${ENV_BIN}/qualimap" --help 2>&1 | grep -Eio 'v\.?[0-9][^ ]*' | head -1 | _san) || true
JVER_M=$("${ENV_BIN}/java" -version 2>&1 | head -1 | _san) || true
QVER_M="${QVER_M:-unknown}"; JVER_M="${JVER_M:-unknown}"
cat > "$BUNDLE_DIR/app/bundled_tool_versions.json" << MANEOF
{
  "bundle_date": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "app_version": "${APP_VERSION}",
  "python": "$(_ver python)",
  "samtools": "$(_ver samtools)",
  "bcftools": "$(_ver bcftools)",
  "vcfutils.pl": "$([[ -x "${ENV_BIN}/vcfutils.pl" ]] && echo "bundled with $(_ver bcftools)" || echo "not found")",
  "minimap2": "$(_ver minimap2)",
  "seqtk": "$(_seqtkver)",
  "porechop": "$(_ver porechop)",
  "qualimap": "${QVER_M}",
  "java": "${JVER_M}",
  "NanoPlot": "$(_ver NanoPlot)",
  "pysam": "$(_pyver pysam)",
  "biopython": "$(_pyver Bio)",
  "numpy": "$(_pyver numpy)",
  "cyvcf2": "$(_pyver cyvcf2)",
  "PyQt5": "$("${ENV_BIN}/python" -c "from PyQt5.QtCore import PYQT_VERSION_STR; print(PYQT_VERSION_STR)" 2>/dev/null || echo "unknown")",
  "PyQtWebEngine": "$("${ENV_BIN}/python" -c "from PyQt5.QtWebEngineWidgets import QWebEngineView; print('available')" 2>/dev/null || echo "missing")",
  "markdown-it-py": "$(_pyver markdown_it)"
}
MANEOF
success "Version manifest: $BUNDLE_DIR/app/bundled_tool_versions.json"

# =============================================================================
step "Step 5.5/7 - Write dependency locks"
# =============================================================================
# Written only after verification passes: a lock produced by a failed build would
# pin an environment that never worked. These are the artifacts that make the next
# build reproducible - keep them in version control alongside this script.
if $CONDA_BIN list -n "$BUILD_ENV_NAME" --explicit > "${BUNDLE_DIR}/env.lock" 2>/dev/null \
   && [[ -s "${BUNDLE_DIR}/env.lock" ]]; then
    cp "${BUNDLE_DIR}/env.lock" "$CONDA_LOCK"
    success "conda lock: $CONDA_LOCK ($(grep -c '^https\?://' "$CONDA_LOCK") packages)"
else
    warn "Could not write conda lock"
fi
# Pin exactly the Phase B package set, resolved to installed versions - not the whole
# environment. Two reasons a full `pip freeze` is wrong here: conda-built packages are
# reported as `name @ file:///home/conda/feedstock_root/...`, a path that exists only on
# the conda-forge build machine, and packages conda provides under a different name
# (pyqt -> PyQt5) would be re-fetched from PyPI by Phase B, replacing conda's Qt with a
# pip one. The conda side is already pinned completely by env.lock.
if "${CONDA_BASE}/envs/${BUILD_ENV_NAME}/bin/python" - "${PIP_PACKAGES[@]}" \
     > "${BUNDLE_DIR}/requirements.lock" 2>/dev/null <<'PYPIN' \
   && [[ -s "${BUNDLE_DIR}/requirements.lock" ]]; then
import sys
from importlib.metadata import version, PackageNotFoundError
for name in sys.argv[1:]:
    try:
        print("%s==%s" % (name, version(name)))
    except PackageNotFoundError:
        print("# %s: not installed" % name, file=sys.stderr)
PYPIN
    cp "${BUNDLE_DIR}/requirements.lock" "$PIP_LOCK"
    success "pip lock: $PIP_LOCK ($(wc -l < "$PIP_LOCK") packages)"
else
    warn "Could not write pip lock"
fi

# =============================================================================
step "Step 6/7 - conda-pack"
# =============================================================================
PACKED_ENV="$BUNDLE_DIR/env/degenresolve_env.tar.gz"
info "Packing to: $PACKED_ENV  (may take 5-15 min)..."
$CONDA_BIN run -n base conda-pack \
    -n "$BUILD_ENV_NAME" -o "$PACKED_ENV" --compress-level 6 \
    2>&1 | tee "$BUNDLE_DIR/build_pack.log"
success "Packed: $(du -sh "$PACKED_ENV" | cut -f1)  ->  $PACKED_ENV"

$CONDA_BIN remove -n "$BUILD_ENV_NAME" --all --yes --quiet 2>/dev/null || true
trap - EXIT

# =============================================================================
step "Step 7/7 - Assemble bundle"
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# LICENSE and REFERENCES.md were previously omitted: recipients received the software
# with no licence terms and without the document justifying every parameter default,
# which is the first thing a reviewer or a cautious lab asks for.
for f in degenresolve.py consensus_editor.py requirements.txt \
          setup.py README.md LICENSE REFERENCES.md \
          example_pipeline_config.json \
          readme_bench_scientist.md DeGenRESOLVE_interface.md; do
    [[ -f "$SCRIPT_DIR/$f" ]] && \
        cp "$SCRIPT_DIR/$f" "$BUNDLE_DIR/app/" && success "Copied: $f" || \
        warn "Not found (skipped): $f"
done
[[ -d "$SCRIPT_DIR/src"      ]] && \
    cp -r "$SCRIPT_DIR/src"      "$BUNDLE_DIR/app/src"      && success "Copied: src/"
[[ -d "$SCRIPT_DIR/app_data" ]] && \
    cp -r "$SCRIPT_DIR/app_data" "$BUNDLE_DIR/app/app_data" && success "Copied: app_data/"

# Copy install.sh
cp "$SCRIPT_DIR/install.sh" "$BUNDLE_DIR/install.sh"
chmod +x "$BUNDLE_DIR/install.sh"
success "install.sh copied."

# Copy uninstall.sh
cp "$SCRIPT_DIR/uninstall.sh" "$BUNDLE_DIR/uninstall.sh"
chmod +x "$BUNDLE_DIR/uninstall.sh"
success "uninstall.sh copied."

cat > "$BUNDLE_DIR/INSTALL_README.txt" << 'README_EOF'
DeGenRESOLVE Offline Bundle v1.0.0
====================================
INSTALL:   bash install.sh
LAUNCH:    bash ~/degenresolve/run_degenresolve.sh
UNINSTALL: bash uninstall.sh

Options:
  --prefix DIR    Custom app location   (default: ~/degenresolve)
  --reinstall     Force full re-extraction of conda environment
  --modify-rc     Write PATH to ~/.bashrc  (default: print instructions only)
  --dry-run       Preview without installing

Included tools (all pre-built, zero downloads on install):
  samtools  -  bcftools (+ vcfutils.pl)  -  minimap2  -  porechop
  seqtk  -  htslib  -  qualimap  -  openjdk (Java)  -  NanoPlot
  Python 3.10: PyQt5  pysam  biopython  numpy  cyvcf2
               click  coloredlogs  humanfriendly

In-app help:
  Help > Bench Scientist Guide         - parameter reference
  Help > Understanding DeGenRESOLVE Interface - full UI reference (all tabs,
         icons, pipeline steps, diagnostic log columns)
README_EOF

step "Bundle integrity check"
[[ -f "$BUNDLE_DIR/miniconda/Miniconda3-latest-Linux-x86_64.sh" ]] && \
    success "miniconda installer: present" || warn "miniconda installer: MISSING"
[[ -f "$BUNDLE_DIR/env/degenresolve_env.tar.gz" ]] && \
    success "packed env: $(du -sh "$BUNDLE_DIR/env/degenresolve_env.tar.gz" | cut -f1)" || \
    die "PACKED ENV MISSING"
# die, not warn: the Step 7 copy loop only warns on a missing source file, so a bundle
# with no app in it would otherwise still be archived and shipped, and the failure would
# not surface until install.sh aborted on the target machine.
[[ -f "$BUNDLE_DIR/app/degenresolve.py" ]] && \
    success "app source: present" || die "degenresolve.py MISSING from bundle - refusing to archive."
[[ -d "$BUNDLE_DIR/app/src/degenresolve" ]] && \
    success "app package: present" || die "src/degenresolve MISSING from bundle - refusing to archive."

ARCHIVE="${APP_NAME}_offline_bundle_${APP_VERSION}.tar.gz"
ARCHIVE_PATH="$(dirname "$BUNDLE_DIR")/${ARCHIVE}"
info "Creating archive: $ARCHIVE_PATH ..."
tar -czf "$ARCHIVE_PATH" -C "$(dirname "$BUNDLE_DIR")" "$(basename "$BUNDLE_DIR")"
ARCHIVE_SIZE=$(du -sh "$ARCHIVE_PATH" | cut -f1)
rm -rf "$BUNDLE_DIR"

echo ""
echo -e "${BOLD}${GREEN}==========================================================${NC}"
echo -e "${BOLD}${GREEN}  Bundle ready - guaranteed offline install!${NC}"
echo -e "${BOLD}${GREEN}==========================================================${NC}"
echo ""
echo -e "  Archive : ${CYAN}${ARCHIVE_PATH}${NC}  (${ARCHIVE_SIZE})"
echo ""
echo -e "  Transfer to target, then:"
echo -e "    ${CYAN}tar -xzf ${ARCHIVE}${NC}"
echo -e "    ${CYAN}bash ${APP_NAME}_bundle/install.sh${NC}"
echo ""
