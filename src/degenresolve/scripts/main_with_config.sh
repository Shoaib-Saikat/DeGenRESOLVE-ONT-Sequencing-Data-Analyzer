#!/bin/bash

set -e

CONFIG_FILE="${1:-pipeline_config.json}"

echo "=================================================="
echo "Starting Analysis Pipeline..."
echo ""
echo "        Authored By: Shoaib Saikat"
echo "        Research Fellow, OHL, IDD, icddr,b, Bangladesh"
echo "        MS in Biochemistry and Biotechnology"
echo "        University of Barishal, Bangladesh"
echo "        Email: saikatshoaib@gmail.com"
echo "        LinkedIn: linkedin.com/in/shoaib-saikat"
echo "=================================================="

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file $CONFIG_FILE not found"
    exit 1
fi

read_config() {
    local key="$1" default="$2"
    # Values are passed via argv, not interpolated into the program text: a config path or
    # default containing a quote used to corrupt the Python source.
    #
    # Two config schemas exist in this project and both are in active use:
    #   nested (pipeline_config.json, written by the GUI worker and documented as the template)
    #   flat   (ont_analyzer_config.json, the GUI's own persisted settings)
    # The CLI only ever did the nested lookup, so handing it a flat config silently substituted
    # a hard-coded default for EVERY nested parameter - the run then used indel rules, variant
    # caller settings and advanced filters the user never chose, with nothing printed. ALIASES
    # maps each nested key to its flat equivalent, and any fallback is announced on stderr.
    python3 -c "
import json, sys
key, default, path = sys.argv[1], sys.argv[2], sys.argv[3]
ALIASES = {
    'indel_rules.insertions':                    ['indel_rules'],
    'indel_rules.deletions':                     ['indel_rules'],
    'indel_rules.custom_percentage':             ['indel_custom_percentage'],
    'variant_call_settings.call_mode':           ['variant_call_mode'],
    'variant_call_settings.depth_per_site':      ['variant_call_depth'],
    'variant_call_settings.min_base_quality':    ['min_base_quality'],
    'variant_call_settings.max_base_quality':    ['max_base_quality'],
    'qualimap.enabled':                          ['qualimap_enabled'],
    'nanoplot.enabled':                          ['nanoplot_enabled'],
    'parallel.enabled':                          ['parallel_enabled'],
    'parallel.threads':                          ['parallel_threads'],
  }
for _k in ('strand_balance_threshold', 'homopolymer_min_length', 'homopolymer_window',
           'read_end_threshold', 'read_end_edge_fraction', 'strict_strand_bias',
           'strict_homopolymer', 'strict_read_end'):
    ALIASES['advanced_criteria.' + _k] = [_k]

def emit(v):
    print(str(v).lower() if isinstance(v, bool) else str(v)); sys.exit(0)

try:
    with open(path) as f:
        config = json.load(f)
except Exception:
    sys.stderr.write('  Warning: could not read %s; using default %s=%s\\n' % (path, key, default))
    print(default); sys.exit(0)

value, ok = config, True
for part in key.split('.'):
    if isinstance(value, dict) and part in value:
        value = value[part]
    else:
        ok = False; break
if ok and not isinstance(value, (dict, list)):
    emit(value)

for cand in ALIASES.get(key, []):
    if isinstance(config, dict) and cand in config:
        v = config[cand]
        if not isinstance(v, (dict, list)):
            sys.stderr.write('  Note: %s not present; using flat key %s=%s\\n' % (key, cand, v))
            emit(v)

sys.stderr.write('  Note: %s not set in config; using default %s\\n' % (key, default))
print(default)
" "$key" "$default" "$CONFIG_FILE"
}


echo "Reading configuration from $CONFIG_FILE..."

MIN_COVERAGE=$(read_config "min_coverage" "100")
DEGENERACY_THRESHOLD=$(read_config "degeneracy_threshold" "20")
PLOIDY=$(read_config "ploidy" "2")
FILTER_MODE=$(read_config "filter_mode" "general")
INDEL_INSERTIONS=$(read_config "indel_rules.insertions" "equal_or_more")
INDEL_DELETIONS=$(read_config "indel_rules.deletions" "equal_or_more")
INDEL_CUSTOM_PERCENTAGE=$(read_config "indel_rules.custom_percentage" "50")
VARIANT_CALL_MODE=$(read_config "variant_call_settings.call_mode" "c")
VARIANT_CALL_DEPTH=$(read_config "variant_call_settings.depth_per_site" "10000")
# "auto" resolves per basecall tier in _clean_master_cmd_with_config.sh:
# 5 for hac/fast/unknown, 1 for sup, matching the bcftools ont / ont-sup profiles.
MIN_BASE_QUALITY=$(read_config "variant_call_settings.min_base_quality" "auto")
# -Q and --max-BQ are a validated pair (1/35 sup, 5/30 hac); they resolve together.
MAX_BASE_QUALITY=$(read_config "variant_call_settings.max_base_quality" "auto")
# Applies the sup flag set to reads of any tier. This is not an indel-only switch:
# under "auto" it also moves -Q and --max-BQ, so SNV calls shift with it.
FORCE_SUP_PROFILE=$(read_config "force_sup_profile" "false")
QUALIMAP_ENABLED=$(read_config "qualimap.enabled" "true")
NANOPLOT_ENABLED=$(read_config "nanoplot.enabled" "true")
QUALIMAP_THREADS=$(nproc --all 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)

# Advanced criteria
STRAND_BALANCE_THRESHOLD=$(read_config "advanced_criteria.strand_balance_threshold" "0.1")
HOMOPOLYMER_MIN_LENGTH=$(read_config "advanced_criteria.homopolymer_min_length" "5")
HOMOPOLYMER_WINDOW=$(read_config "advanced_criteria.homopolymer_window" "5")
READ_END_THRESHOLD=$(read_config "advanced_criteria.read_end_threshold" "0.8")
READ_END_EDGE_FRACTION=$(read_config "advanced_criteria.read_end_edge_fraction" "0.1")
STRICT_STRAND_BIAS=$(read_config "advanced_criteria.strict_strand_bias" "false")
STRICT_HOMOPOLYMER=$(read_config "advanced_criteria.strict_homopolymer" "false")
STRICT_READ_END=$(read_config "advanced_criteria.strict_read_end" "false")
PARALLEL_ENABLED=$(read_config "parallel.enabled" "true")
PARALLEL_THREADS=$(read_config "parallel.threads" "1")

export MIN_COVERAGE DEGENERACY_THRESHOLD PLOIDY FILTER_MODE
export INDEL_INSERTIONS INDEL_DELETIONS INDEL_CUSTOM_PERCENTAGE
export VARIANT_CALL_MODE VARIANT_CALL_DEPTH MIN_BASE_QUALITY MAX_BASE_QUALITY
export FORCE_SUP_PROFILE
export QUALIMAP_ENABLED QUALIMAP_THREADS
export NANOPLOT_ENABLED
export STRAND_BALANCE_THRESHOLD HOMOPOLYMER_MIN_LENGTH HOMOPOLYMER_WINDOW
export READ_END_THRESHOLD READ_END_EDGE_FRACTION
export STRICT_STRAND_BIAS STRICT_HOMOPOLYMER STRICT_READ_END

echo "Configuration loaded:"
echo "  - Min Coverage          : $MIN_COVERAGE"
echo "  - Degeneracy Threshold  : $DEGENERACY_THRESHOLD%"
echo "  - Ploidy                : $PLOIDY"
echo "  - Filter Mode           : $FILTER_MODE"
echo "  - Indel Rules           : insertions=$INDEL_INSERTIONS, deletions=$INDEL_DELETIONS"
echo "  - Variant Call Mode     : $VARIANT_CALL_MODE"
echo "  - Depth per Site        : $VARIANT_CALL_DEPTH"
echo "  - Min Base Quality      : $MIN_BASE_QUALITY"
echo "  - Max Base Quality      : $MAX_BASE_QUALITY"
echo "  - Force sup profile     : $FORCE_SUP_PROFILE"
echo "  - Qualimap Enabled      : $QUALIMAP_ENABLED"
echo "  - NanoPlot Enabled      : $NANOPLOT_ENABLED"
echo "  - Qualimap Threads      : $QUALIMAP_THREADS (auto-detected)"

echo "Validating input directory structure..."
if [ ! -d "fastq_pass" ]; then
    echo "Error: fastq_pass directory not found"; exit 1
fi
if [ ! -d "reference" ]; then
    echo "Error: reference/ directory not found"; exit 1
fi
mapfile -t _REFS < <(find reference -maxdepth 1 \( -name "*.fasta" -o -name "*.fa" \) -type f 2>/dev/null | sort)
if   [ ${#_REFS[@]} -eq 0 ]; then
    echo "Error: No .fasta or .fa file found in reference/"; exit 1
elif [ ${#_REFS[@]} -gt 1 ]; then
    echo "Error: Found ${#_REFS[@]} FASTA files in reference/, expected exactly 1 - remove the extra file"; exit 1
fi
echo "Using reference: ${_REFS[0]}"

# Pre-index reference FASTA once before any parallel jobs start.
# Always re-index (don't skip if .fai exists): if the user replaced or
# updated the FASTA between runs, a stale .fai causes bcftools mpileup
# to emit [E::faidx_adjust_position] "sequence not found" for any
# sequence that is new in the FASTA but absent from the old .fai.
# samtools faidx is fast even on large references so the cost is trivial.
echo "Indexing reference FASTA (one-time, before parallel processing)..."
samtools faidx "${_REFS[0]}" || { echo "Error: Failed to index reference FASTA"; exit 1; }
echo "Reference indexed: ${_REFS[0]}.fai"

BARCODE_COUNT=$(find fastq_pass -maxdepth 1 -type d -name "barcode*" | wc -l)
echo "Found $BARCODE_COUNT barcode directories"
if [ "$BARCODE_COUNT" -eq 0 ]; then
    echo "Error: No barcode directories found in fastq_pass/"; exit 1
fi

mkdir -p log results/reports

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Collect runtime tool versions once per run
_rtver() { "$1" --version 2>&1 | head -1 || echo "not found"; }
_qmver() { JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:-} -Djava.awt.headless=true" qualimap --help 2>&1 | grep -Eio 'v\.?[0-9][^ ]*' | head -1 || echo "unknown"; }
_jver()  { java -version 2>&1 | head -1 | tr -d '"' || echo "not found"; }
_pymod() { python3 -c "import $1; print(getattr($1,'__version__','unknown'))" 2>/dev/null || echo "not found"; }

APP_VERSION="1.0.0"
# scripts/ -> degenresolve/ -> src/ -> app root. The previous form resolved to
# src/, one level short, so BUNDLED_VER_FILE never found the manifest the
# installer places at the app root and the version check always reported
# "no bundle manifest" even on a genuine bundle install.
APP_DIR="$(cd "$SCRIPT_DIR/../../.."; pwd)"

# ---------------------------------------------------------------------------
# Run fingerprint. Checkpoint resume keys purely on file existence, so without
# this a stale results/ silently reuses artifacts built under different settings
# and two machines with identical configs disagree.
#
# The fingerprint covers the EFFECTIVE parameters (post-default resolution), not
# the config file bytes: that survives reformatting, and it catches a changed
# default even when the config is byte-identical.
#
# Thread and QC settings are deliberately EXCLUDED. Thread count is proven not to
# affect any scope-A artifact, and including it would make a 4-core and a 64-core
# machine mismatch by construction - defeating the guarantee this exists to hold.
# ---------------------------------------------------------------------------
REFERENCE_MD5=$(md5sum < "${_REFS[0]}" | cut -d' ' -f1)
EFFECTIVE_PARAMS="results/reports/effective_params.txt"
{
    echo "app_version=${APP_VERSION}"
    echo "reference_file=$(basename "${_REFS[0]}")"
    echo "reference_md5=${REFERENCE_MD5}"
    echo "min_coverage=${MIN_COVERAGE}"
    echo "degeneracy_threshold=${DEGENERACY_THRESHOLD}"
    echo "ploidy=${PLOIDY}"
    echo "filter_mode=${FILTER_MODE}"
    echo "indel_insertions=${INDEL_INSERTIONS}"
    echo "indel_deletions=${INDEL_DELETIONS}"
    echo "indel_custom_percentage=${INDEL_CUSTOM_PERCENTAGE}"
    echo "variant_call_mode=${VARIANT_CALL_MODE}"
    echo "variant_call_depth=${VARIANT_CALL_DEPTH}"
    echo "min_base_quality=${MIN_BASE_QUALITY}"
    echo "max_base_quality=${MAX_BASE_QUALITY}"
    echo "force_sup_profile=${FORCE_SUP_PROFILE}"
    echo "strand_balance_threshold=${STRAND_BALANCE_THRESHOLD}"
    echo "homopolymer_min_length=${HOMOPOLYMER_MIN_LENGTH}"
    echo "homopolymer_window=${HOMOPOLYMER_WINDOW}"
    echo "read_end_threshold=${READ_END_THRESHOLD}"
    echo "read_end_edge_fraction=${READ_END_EDGE_FRACTION}"
    echo "strict_strand_bias=${STRICT_STRAND_BIAS}"
    echo "strict_homopolymer=${STRICT_HOMOPOLYMER}"
    echo "strict_read_end=${STRICT_READ_END}"
} | LC_ALL=C sort > "$EFFECTIVE_PARAMS"
RUN_FINGERPRINT=$(md5sum < "$EFFECTIVE_PARAMS" | cut -d' ' -f1)
export RUN_FINGERPRINT REFERENCE_MD5

# Per-run provenance archive, at the run root beside fastq_pass and reference.
# Accumulating and never overwritten: the point is to be able to look back at
# what settings and tool versions produced any past output. Canonical copies stay
# where they are, so html_reporter.py and the receipt printer are unaffected.
TOOL_DATA_DIR="tool_data/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$TOOL_DATA_DIR"
# pipeline_config.json is treated as a temporary file elsewhere in the codebase;
# this is the only durable record of what a given run was actually configured with.
cp "$CONFIG_FILE" "$TOOL_DATA_DIR/" 2>/dev/null || \
    echo "Warning: could not archive $CONFIG_FILE to $TOOL_DATA_DIR"
export TOOL_DATA_DIR

STORED_PARAMS="results/.run_params"
if [ -f "$STORED_PARAMS" ] && ! cmp -s "$STORED_PARAMS" "$EFFECTIVE_PARAMS"; then
    echo "Error: results/ was produced with different settings than this run."
    echo "Resuming would mix artifacts built under two configurations. Differences"
    echo "(< stored in results/, > this run):"
    diff "$STORED_PARAMS" "$EFFECTIVE_PARAMS" | grep '^[<>]' | sed 's/^/  /'
    echo
    echo "Either restore the previous settings, or move/remove results/ to start clean."
    exit 1
fi
cp "$EFFECTIVE_PARAMS" "$STORED_PARAMS"
echo "Run fingerprint: ${RUN_FINGERPRINT} (effective params: $EFFECTIVE_PARAMS)"

# Read bundled version if available
BUNDLED_VER_FILE="${APP_DIR}/bundled_tool_versions.json"

cat > "results/reports/runtime_versions.json" << RVEOF
{
  "run_date": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "app_version": "${APP_VERSION}",
  "os": "$(uname -srm)",
  "python": "$(_rtver python3)",
  "samtools": "$(_rtver samtools)",
  "bcftools": "$(_rtver bcftools)",
  "vcfutils.pl": "$(command -v vcfutils.pl >/dev/null 2>&1 && echo "bundled with $(_rtver bcftools)" || echo "not found")",
  "minimap2": "$(_rtver minimap2)",
  "seqtk": "$(seqtk 2>&1 | grep -i 'version' | head -1 || echo "not found")",
  "porechop": "$(_rtver porechop)",
  "qualimap": "$(_qmver)",
  "java": "$(_jver)",
  "NanoPlot": "$(_rtver NanoPlot)",
  "pysam": "$(_pymod pysam)",
  "biopython": "$(_pymod Bio)",
  "numpy": "$(_pymod numpy)",
  "PyQt5": "$(python3 -c "from PyQt5.QtCore import PYQT_VERSION_STR; print(PYQT_VERSION_STR)" 2>/dev/null || echo "not found")"
}
RVEOF
echo "Runtime tool versions saved to results/reports/runtime_versions.json"

# ---------------------------------------------------------------------------
# Full environment manifest. runtime_versions.json carries a curated set for the
# HTML report; this records EVERYTHING, so a result can be traced to the exact
# software that produced it rather than to eight tool names.
#
# Read from conda-meta and site-packages directly rather than calling `conda list`
# or `pip freeze`: a conda-packed bundle ships neither conda nor, necessarily, pip,
# but it does ship both metadata directories.
#
# [packages.*] and [tools.host] are hashed into environment_md5 and the receipt.
# [host] is logged but NOT hashed - kernel and CPU differ legitimately between two
# machines that must still agree on every base.
# ---------------------------------------------------------------------------
python3 - "results/reports/environment_manifest.txt" "$SCRIPT_DIR" <<'PYENV' || echo "Warning: environment manifest failed"
import glob, hashlib, os, platform, subprocess, sys

out_path = sys.argv[1]
script_dir = sys.argv[2] if len(sys.argv) > 2 else ""
prefix = os.path.dirname(os.path.dirname(sys.executable))

# Identity of the code that produces scope-A artifacts. Logged for transparency;
# it is deliberately NOT part of the run fingerprint, so editing these files does
# not invalidate an existing results/ directory.
code_files = [
    os.path.join(script_dir, "main_with_config.sh"),
    os.path.join(script_dir, "_clean_master_cmd_with_config.sh"),
    os.path.join(script_dir, "combined_consensus_script.sh"),
    os.path.join(script_dir, "..", "pipeline", "consensus_editor.py"),
]
code_h = hashlib.md5()
code_detail = []
for f in code_files:
    try:
        b = open(f, "rb").read()
        code_h.update(b)
        code_detail.append("%s: %s" % (os.path.basename(f), hashlib.md5(b).hexdigest()))
    except OSError:
        code_detail.append("%s: MISSING" % os.path.basename(f))
pipeline_code_md5 = code_h.hexdigest()

def run(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
        return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr).strip() else "not found"
    except Exception:
        return "not found"

# Every conda package: conda-meta/<name>-<version>-<build>.json
conda_pkgs = sorted(
    os.path.basename(p)[:-5] for p in glob.glob(os.path.join(prefix, "conda-meta", "*.json"))
)

# Every python distribution (covers pip installs, which leave no conda-meta entry)
py_pkgs = set()
for pat in ("*.dist-info", "*.egg-info"):
    for d in glob.glob(os.path.join(prefix, "lib", "python*", "site-packages", pat)):
        base = os.path.basename(d).rsplit(".", 1)[0]
        if "-" in base:
            name, _, ver = base.rpartition("-")
            py_pkgs.add(f"{name}=={ver}")
        else:
            py_pkgs.add(base)
py_pkgs = sorted(py_pkgs)

# Host-provided tools the pipeline shells out to. These come from the operating
# system, not the bundle, so they are the part of the toolchain the bundle does
# NOT pin - which makes them exactly what needs logging.
host_tools = {
    "bash":     run("bash --version"),
    "awk":      run("awk --version || awk -W version"),
    "sort":     run("sort --version"),
    "md5sum":   run("md5sum --version"),
    "gzip":     run("gzip --version"),
    "find":     run("find --version"),
    "xargs":    run("xargs --version"),
    "perl":     run("perl --version | sed -n 2p"),
    "sed":      run("sed --version"),
    "grep":     run("grep --version"),
}

pkg_lines = []
pkg_lines.append("[packages.conda]")
pkg_lines += conda_pkgs or ["(no conda-meta found at %s)" % prefix]
pkg_lines.append("")
pkg_lines.append("[packages.python]")
pkg_lines += py_pkgs or ["(no site-packages found)"]
pkg_lines.append("")
pkg_lines.append("[tools.host]")
pkg_lines += [f"{k}: {v}" for k, v in sorted(host_tools.items())]

env_md5 = hashlib.md5("\n".join(pkg_lines).encode()).hexdigest()

host_lines = [
    "[host]",
    f"env_prefix: {prefix}",
    f"os: {platform.platform()}",
    f"kernel: {platform.release()}",
    f"machine: {platform.machine()}",
    f"libc: {' '.join(platform.libc_ver())}",
    f"python: {sys.version.split()[0]} ({sys.executable})",
    f"cores: {os.cpu_count()}",
    f"locale_LC_ALL: {os.environ.get('LC_ALL', '(unset)')}",
    f"locale_LANG: {os.environ.get('LANG', '(unset)')}",
]

with open(out_path, "w") as fh:
    fh.write("# DeGenRESOLVE environment manifest\n")
    fh.write("# environment_md5 covers [packages.*] and [tools.host] only.\n")
    fh.write("# [host] is recorded for transparency but excluded from the hash:\n")
    fh.write("# kernel and CPU differ legitimately between machines that must still agree.\n")
    fh.write(f"environment_md5={env_md5}\n")
    fh.write(f"pipeline_code_md5={pipeline_code_md5}\n\n")
    fh.write("[pipeline.code]\n" + "\n".join(code_detail) + "\n\n")
    fh.write("\n".join(host_lines) + "\n\n")
    fh.write("\n".join(pkg_lines) + "\n")

print(f"Environment manifest: {out_path} ({len(conda_pkgs)} conda, {len(py_pkgs)} python packages)")
print(f"environment_md5={env_md5}")
PYENV


# Compare runtime tools against the bundle manifest. A file without a bundle_date
# key is not a manifest (older installs left a copy of the GUI config under this
# name) - treat that as "no manifest" rather than comparing ploidy against samtools.
python3 - "$BUNDLED_VER_FILE" results/reports/runtime_versions.json <<'PYVER' || true
import json, sys
bundled_path, runtime_path = sys.argv[1], sys.argv[2]
norm = lambda s: str(s).replace('"', '').strip()
rt = json.load(open(runtime_path))
try:
    bd = json.load(open(bundled_path))
    if "bundle_date" not in bd:
        raise ValueError("not a version manifest")
except Exception as e:
    rt["version_match"] = {"status": "no bundle manifest", "detail": str(e)}
else:
    skip = {"run_date", "bundle_date", "app_version", "os"}
    shared = (rt.keys() & bd.keys()) - skip
    UNKNOWN = {"unknown", "not found", ""}
    comparable = [k for k in sorted(shared)
                  if norm(rt[k]).lower() not in UNKNOWN and norm(bd[k]).lower() not in UNKNOWN]
    skipped = sorted(set(shared) - set(comparable))
    diffs = {k: {"runtime": norm(rt[k]), "bundled": norm(bd[k])}
             for k in comparable if norm(rt[k]) != norm(bd[k])}
    rt["version_match"] = {
        "status": "MATCHES BUNDLE" if not diffs else "DIFFERS",
        "bundle_date": bd["bundle_date"],
        "compared": len(comparable),
        "not_comparable": skipped,
        "differences": diffs,
    }
    for k, v in diffs.items():
        print(f"WARNING: {k} differs from bundle: runtime {v['runtime']} vs bundled {v['bundled']}")
json.dump(rt, open(runtime_path, "w"), indent=2)
print("Version check: " + rt["version_match"]["status"])
PYVER

cp results/reports/runtime_versions.json "$TOOL_DATA_DIR/" 2>/dev/null || \
    echo "Warning: could not archive runtime_versions.json to $TOOL_DATA_DIR"
echo "Run provenance archived to $TOOL_DATA_DIR"

TOTAL_START_TS=$(date +%s)
TIMINGS_FILE="log/pipeline_timings.txt"
{ echo "Pipeline run: $(date)"; echo "---------------------------------------------"; } > "$TIMINGS_FILE"

# Only real directories, and only ones that exist. The glob used to also match plain files
# and dangling symlinks, so the job loop and BARCODE_COUNT (computed with `find -type d`)
# could disagree and the completeness check below would misfire.
BARCODES=()
for _cand in fastq_pass/barcode*; do
    [ -d "$_cand" ] && BARCODES+=("$_cand")
done

CPU_CORES=$(nproc --all 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || \
            sysctl -n hw.ncpu 2>/dev/null || echo 1)
if ! [[ "$CPU_CORES" =~ ^[0-9]+$ ]] || [ "$CPU_CORES" -lt 1 ]; then CPU_CORES=1; fi

if [ "$PARALLEL_ENABLED" = "true" ] || [ "$PARALLEL_ENABLED" = "True" ]; then
    MAX_JOBS=$PARALLEL_THREADS
    [ "$MAX_JOBS" -gt "$CPU_CORES" ] && MAX_JOBS=$CPU_CORES
else
    MAX_JOBS=1
fi
[ "$MAX_JOBS" -gt "$BARCODE_COUNT" ] && MAX_JOBS=$BARCODE_COUNT
[ "$MAX_JOBS" -lt 1 ] && MAX_JOBS=1

THREADS_PER_JOB=$(( CPU_CORES / MAX_JOBS ))
[ "$THREADS_PER_JOB" -lt 1 ] && THREADS_PER_JOB=1
ROUNDS=$(( (BARCODE_COUNT + MAX_JOBS - 1) / MAX_JOBS ))

echo "Detected CPU cores   : $CPU_CORES"
echo "Total barcodes       : $BARCODE_COUNT"
echo "Parallel processing  : $PARALLEL_ENABLED (configured threads: $PARALLEL_THREADS)"
echo "Parallel slots       : $MAX_JOBS"
echo "Estimated rounds     : $ROUNDS"
echo "Threads per barcode  : $THREADS_PER_JOB"

wait_for_slot() {
    while [ "$(jobs -rp | wc -l)" -ge "$MAX_JOBS" ]; do sleep 1; done
}

STATUS_FILE="log/pipeline_status.tmp"
> "$STATUS_FILE"

for barcode in "${BARCODES[@]}"; do
    barcode_name=$(basename "$barcode")
    wait_for_slot
    echo "Processing $barcode_name... (background)"
    (
        BARCODE_START_TS=$(date +%s)
        THREADS="$THREADS_PER_JOB" QUALIMAP_THREADS="$THREADS_PER_JOB" \
            "$SCRIPT_DIR/_clean_master_cmd_with_config.sh" "$barcode_name" 2>&1 \
            | sed -u "s/^/[$barcode_name] /"
        status=${PIPESTATUS[0]}
        echo "$barcode:$status" >> "$STATUS_FILE"
        BARCODE_END_TS=$(date +%s)
        BARCODE_ELAPSED=$((BARCODE_END_TS - BARCODE_START_TS))
        BARCODE_H=$((BARCODE_ELAPSED / 3600))
        BARCODE_M=$(((BARCODE_ELAPSED % 3600) / 60))
        BARCODE_S=$((BARCODE_ELAPSED % 60))
        printf "Time for %s: %02dh:%02dm:%02ds [exit %d]\n" \
            "$barcode_name" "$BARCODE_H" "$BARCODE_M" "$BARCODE_S" "$status" \
            | tee -a "$TIMINGS_FILE"
        exit $status
    ) &
done

wait

# Account for every job. A barcode killed (OOM, SIGKILL, power loss) before it could append
# its status line leaves NO line at all, and `grep -qv ":0$"` on an empty or short file
# returns 1 - which used to be reported as a fully successful run.
_STATUS_LINES=$(grep -c . "$STATUS_FILE" 2>/dev/null || echo 0)
_FAILED=0
if [ "$_STATUS_LINES" -ne "$BARCODE_COUNT" ]; then
    echo "Error: ${_STATUS_LINES} of ${BARCODE_COUNT} barcode jobs reported a status." \
        | tee -a "$TIMINGS_FILE"
    echo "The missing jobs were killed before they could report (out of memory, or the" \
        | tee -a "$TIMINGS_FILE"
    echo "process was terminated). Their output is incomplete and must not be published." \
        | tee -a "$TIMINGS_FILE"
    for _bc in "${BARCODES[@]}"; do
        _bn=$(basename "$_bc")
        grep -q "^${_bn}:" "$STATUS_FILE" 2>/dev/null || \
            echo "  no status reported: ${_bn}" | tee -a "$TIMINGS_FILE"
    done
    _FAILED=1
fi
if grep -qv ":0$" "$STATUS_FILE" 2>/dev/null; then
    echo "One or more barcode jobs failed:" | tee -a "$TIMINGS_FILE"
    cat "$STATUS_FILE" | tee -a "$TIMINGS_FILE"
    _FAILED=1
fi
if [ "$_FAILED" -ne 0 ]; then
    exit 1
fi

TOTAL_END_TS=$(date +%s)
TOTAL_ELAPSED=$((TOTAL_END_TS - TOTAL_START_TS))
TOTAL_H=$((TOTAL_ELAPSED / 3600))
TOTAL_M=$(((TOTAL_ELAPSED % 3600) / 60))
TOTAL_S=$((TOTAL_ELAPSED % 60))
printf "Total pipeline time: %02dh:%02dm:%02ds\n" \
    "$TOTAL_H" "$TOTAL_M" "$TOTAL_S" | tee -a "$TIMINGS_FILE"

echo "Processing complete. Starting cleanup..."
mkdir -p results/step_8_refined_consensus
mv *_consensus_edited_diagnostic_log.txt log/ 2>/dev/null || true
rm -f reference/*.fai 2>/dev/null || true

echo "Cleanup complete!"
echo ""
echo "FINAL RESULTS:"
echo "  results/"
echo "    | step_1_raw_read_qc_nanoplot/  barcode*/ (NanoPlot raw read QC)"
echo "    | step_2_unzipped_merged/       barcode*_merged.fastq"
echo "    | step_3_adapter_trimmed/       barcode*_trimmed.fastq"
echo "    | step_4_mapped/                barcode*/ (SAM, BAM, coverage)"
echo "    | step_5_alignment_qc_qualimap/ barcode*/ (Qualimap BAM QC)"
echo "    | step_6_called_variants/       barcode*_variants.vcf.gz"
echo "    | step_7_draft_consensus/       barcode*_consensus.fasta"
echo "    | step_8_refined_consensus/     barcode*_consensus_edited.fasta"
echo "    + reports/                      barcode*_summary_report.html"
echo "        + summary_all.html          Combined run summary"
echo ""
echo "  log/   All processing logs and diagnostic files"
echo ""
echo "Pipeline completed successfully!"
