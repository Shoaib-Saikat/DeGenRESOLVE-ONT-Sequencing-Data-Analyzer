#!/usr/bin/env bash
#
# DeGenRESOLVE - SOURCE installer (Option A).
#
# For a machine that already has the bioinformatics tools on PATH and does not want the
# bundled conda environment. Most users should run install.sh instead: it is fully offline,
# ships every external tool, and needs nothing but tar and gzip.
#
# This script installs into a Python virtual environment and installs no external tools; it
# verifies that the ones it needs are present and new enough, then refuses to continue if
# they are not.
#
# Usage:
#   ./install.sh              # install into a new venv at ./degenresolve-venv
#   ./install.sh --prefix DIR # install into DIR instead
#   ./install.sh --check-only # verify prerequisites and exit without installing

set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${BUNDLE_DIR}/app"
VENV_DIR="${BUNDLE_DIR}/degenresolve-venv"
CHECK_ONLY=0

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix)     VENV_DIR="$2"; shift 2 ;;
        --check-only) CHECK_ONLY=1; shift ;;
        -h|--help)    sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

say()  { printf '  %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

echo "DeGenRESOLVE installer"
echo "======================"

# ---------------------------------------------------------------- Python version
echo
echo "Checking Python..."
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || fail "$PY not found. Install Python 3.10 or newer."
PYV=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
"$PY" - <<'PYEOF' || fail "Python ${PYV} is too old. DeGenRESOLVE requires 3.10+ because consensus_editor.py uses PEP 604 (str | None) annotations, which are evaluated at import time."
import sys
sys.exit(0 if sys.version_info >= (3, 10) else 1)
PYEOF
say "Python ${PYV} OK (3.10+ required)"

# ---------------------------------------------------------------- external tools
echo
echo "Checking external tools (these are NOT installed by pip)..."
MISSING=()
check_tool() {          # $1 = binary, $2 = min "major.minor" or "" for presence only
    local tool="$1" want="${2:-}"
    if ! command -v "$tool" >/dev/null 2>&1; then
        MISSING+=("$tool"); say "MISSING  $tool"; return
    fi
    if [ -z "$want" ]; then say "found    $tool"; return; fi
    local have
    have=$("$tool" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
    if [ -z "$have" ]; then say "found    $tool (version not determined)"; return; fi
    if [ "$(printf '%s\n%s\n' "$want" "$have" | sort -V | head -1)" != "$want" ]; then
        say "TOO OLD  $tool $have (need >= $want)"
        MISSING+=("$tool>=$want")
    else
        say "found    $tool $have"
    fi
}
check_tool samtools 1.10
# bcftools >= 1.21: the sup basecall profile passes --indels-cns and --max-BQ, which older
# versions reject with a bare usage error that points nowhere useful.
check_tool bcftools 1.21
check_tool minimap2 2.17
check_tool seqtk
check_tool porechop
command -v vcfutils.pl >/dev/null 2>&1 || { MISSING+=("vcfutils.pl"); say "MISSING  vcfutils.pl (ships with bcftools)"; }
for opt in NanoPlot qualimap java; do
    command -v "$opt" >/dev/null 2>&1 && say "found    $opt (optional)" || say "absent   $opt (optional - the matching QC step will be skipped)"
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo
    echo "Required tools missing or too old: ${MISSING[*]}"
    echo "Install them with your package manager or conda, e.g.:"
    echo "  conda install -c bioconda 'samtools>=1.10' 'bcftools>=1.21' 'minimap2>=2.17' seqtk porechop nanoplot qualimap"
    [ "$CHECK_ONLY" -eq 1 ] && exit 1
    fail "Cannot continue until the tools above are available on PATH."
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
    echo; echo "All prerequisites satisfied."; exit 0
fi

# ---------------------------------------------------------------- python packages
echo
echo "Creating virtual environment at ${VENV_DIR}..."
[ -e "$VENV_DIR" ] && fail "${VENV_DIR} already exists. Remove it or pass --prefix DIR."
"$PY" -m venv "$VENV_DIR" || fail "venv creation failed (on Debian/Ubuntu: apt install python3-venv)"
# shellcheck disable=SC1091
. "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip >/dev/null
say "virtual environment created"

echo
echo "Installing Python dependencies (pinned in app/requirements.txt)..."
python -m pip install -r "${APP_DIR}/requirements.txt" || fail "dependency installation failed"
say "dependencies installed"

echo
echo "Installing DeGenRESOLVE..."
python -m pip install -e "${APP_DIR}" || fail "package installation failed"
say "package installed"

# ---------------------------------------------------------------- verify
echo
echo "Verifying installation..."
python - <<'PYEOF' || fail "the installed package could not be imported"
import degenresolve
from degenresolve.pipeline import ConsensusDegeneracyProcessor
from degenresolve.core import ConfigManager, InputValidator
print(f"  degenresolve {degenresolve.__version__} imports OK")
ok, problems = InputValidator().validate_tool_versions()
print("  tool versions OK" if ok else "  tool version problems: " + "; ".join(problems))
PYEOF

for s in main_with_config.sh _clean_master_cmd_with_config.sh combined_consensus_script.sh; do
    p="${APP_DIR}/src/degenresolve/scripts/${s}"
    [ -f "$p" ] || fail "pipeline script missing: $p"
    bash -n "$p" || fail "pipeline script has a syntax error: $p"
done
say "all three pipeline scripts present and parse cleanly"

if [ -f "${APP_DIR}/tests/test_core_functions.py" ]; then
    echo
    echo "Running the regression suite..."
    ( cd "$APP_DIR" && python3 tests/test_core_functions.py ) || fail "regression tests failed"
fi

cat <<EOF

Installation complete.

  Activate:   source ${VENV_DIR}/bin/activate
  GUI:        degenresolve
  Headless:   degenresolve-consensus <consensus.fasta> <reference.fasta> --bam <in.bam> --vcf <in.vcf.gz> --diagnostic

Your data directory must contain:
  fastq_pass/barcodeXX/*.fastq.gz     one directory per barcode
  reference/<anything>.fasta          exactly one FASTA

See app/README.md for the full guide.
EOF
