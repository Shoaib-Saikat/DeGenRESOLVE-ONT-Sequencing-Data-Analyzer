#!/bin/bash

# Exit on any error. `pipefail` is essential here: without it the exit status of the LEFT
# side of `samtools view | samtools sort` is discarded, so a truncated SAM produces a
# silently truncated BAM that every downstream stage then treats as valid.
set -eo pipefail

if [ $# -lt 1 ]; then
    echo "Error: Please provide a barcode identifier (e.g., barcode01) as an argument"
    echo "Usage: $0 barcodeXX"
    exit 1
fi

BARCODE=$(basename "$1")

mapfile -t _REFS < <(find ./reference -maxdepth 1 \( -name "*.fasta" -o -name "*.fa" \) -type f 2>/dev/null | sort)
if   [ ${#_REFS[@]} -eq 0 ]; then
    echo "Error: No .fasta or .fa file found in reference/"; exit 1
elif [ ${#_REFS[@]} -gt 1 ]; then
    echo "Error: Found ${#_REFS[@]} FASTA files in reference/, expected exactly 1 - remove the extra file"; exit 1
fi
REF="${_REFS[0]}"

echo "=== Starting pipeline for ${BARCODE} ==="

if [ ! -d "fastq_pass/${BARCODE}" ]; then
    echo "Error: fastq_pass/${BARCODE} directory is missing"
    exit 1
fi

if ! ls fastq_pass/${BARCODE}/*.fastq.gz >/dev/null 2>&1; then
    echo "Error: fastq_pass/${BARCODE} directory contains no .fastq.gz files"
    exit 1
fi

TEMP_DIR="./temp_${BARCODE}"
mkdir -p "$TEMP_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASECALL_PY="$SCRIPT_DIR/../utils/basecall.py"

# Record pipeline start timestamp for this barcode
BARCODE_START_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
BARCODE_START_EPOCH=$(date +%s)

RESULTS_DIR="./results"
STEP1_DIR="$RESULTS_DIR/step_1_raw_read_qc_nanoplot/${BARCODE}"
STEP2_DIR="$RESULTS_DIR/step_2_unzipped_merged"
STEP3_DIR="$RESULTS_DIR/step_3_adapter_trimmed"
STEP4_DIR="$RESULTS_DIR/step_4_mapped/${BARCODE}"
STEP5_DIR="$RESULTS_DIR/step_5_alignment_qc_qualimap/${BARCODE}"
STEP6_DIR="$RESULTS_DIR/step_6_called_variants"
STEP7_DIR="$RESULTS_DIR/step_7_draft_consensus"
STEP8_DIR="$RESULTS_DIR/step_8_refined_consensus"
REPORTS_DIR="$RESULTS_DIR/reports"
mkdir -p "$STEP1_DIR" "$STEP2_DIR" "$STEP3_DIR" "$STEP4_DIR" \
         "$STEP5_DIR" "$STEP6_DIR" "$STEP7_DIR" "$STEP8_DIR" \
         "$REPORTS_DIR"

CPU_CORES=$(nproc --all 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || \
            sysctl -n hw.ncpu 2>/dev/null || echo 1)
THREADS="${THREADS:-$CPU_CORES}"
export THREADS

# Checkpoint detection
detect_checkpoint() {
    local barcode="$1"
    local checkpoint=0
    echo "Checking for existing results for ${barcode}..."
    if [ -f "$STEP8_DIR/${barcode}_consensus_edited.fasta" ]; then
        echo "Step 8 completed"; checkpoint=6
    elif [ -f "$STEP7_DIR/${barcode}_consensus.fasta" ]; then
        echo "Step 7 completed"; checkpoint=5
    elif [ -f "$STEP4_DIR/${barcode}.bam" ] && \
         [ -f "$STEP4_DIR/${barcode}.bam.bai" ]; then
        echo "Step 4 completed"; checkpoint=4
    elif [ -f "$STEP4_DIR/${barcode}.sam" ]; then
        echo "Step 3 completed"; checkpoint=3
    elif [ -f "$STEP3_DIR/${barcode}_trimmed.fastq" ]; then
        echo "Step 2 completed"; checkpoint=2
    elif [ -f "$STEP2_DIR/${barcode}_merged.fastq" ]; then
        echo "Step 1 completed"; checkpoint=1
    else
        echo "No completed steps found"; checkpoint=0
    fi
    echo "Checkpoint: Step $checkpoint"
    return $checkpoint
}

resume_from_step() {
    local step="$1" barcode="$2"
    local next_step="$step"
    case $step in
        0) echo "Starting from Step 1" ;;
        1) [ -f "$STEP2_DIR/${barcode}_merged.fastq" ] && \
               cp "$STEP2_DIR/${barcode}_merged.fastq" "${TEMP_DIR}/${barcode}_merged.fastq" || true
           echo "Resuming from Step 2" ;;
        2) [ -f "$STEP3_DIR/${barcode}_trimmed.fastq" ] && \
               cp "$STEP3_DIR/${barcode}_trimmed.fastq" "${TEMP_DIR}/${barcode}_trimmed.fastq" || true
           echo "Resuming from Step 3" ;;
        3) [ -f "$STEP4_DIR/${barcode}.sam" ] && \
               cp "$STEP4_DIR/${barcode}.sam" "${TEMP_DIR}/${barcode}.sam" || true
           echo "Resuming from Step 4" ;;
        4) [ -f "$STEP4_DIR/${barcode}.bam" ] && \
               cp "$STEP4_DIR/${barcode}.bam"     "${TEMP_DIR}/${barcode}.bam"     || true
           [ -f "$STEP4_DIR/${barcode}.bam.bai" ] && \
               cp "$STEP4_DIR/${barcode}.bam.bai" "${TEMP_DIR}/${barcode}.bam.bai" || true
           [ -f "$STEP4_DIR/${barcode}.coverage" ] && \
               cp "$STEP4_DIR/${barcode}.coverage" "${TEMP_DIR}/${barcode}.coverage" || true
           echo "Resuming from Step 5" ;;
        5) if [ -f "$STEP7_DIR/${barcode}_consensus.fasta" ]; then
               cp "$STEP7_DIR/${barcode}_consensus.fasta" "./${barcode}_consensus.fasta"
           else
               # See note below: the Step 4 guard is `-lt 4`, so 4 would skip the rebuild.
               echo "WARNING: Consensus FASTA missing; rebuilding from Step 4"
               next_step=3
           fi
           if [ -f "$STEP4_DIR/${barcode}.bam" ] && [ -f "$STEP4_DIR/${barcode}.bam.bai" ]; then
               cp "$STEP4_DIR/${barcode}.bam"     "${TEMP_DIR}/${barcode}.bam"     || true
               cp "$STEP4_DIR/${barcode}.bam.bai" "${TEMP_DIR}/${barcode}.bam.bai" || true
               [ -f "$STEP4_DIR/${barcode}.coverage" ] && \
                   cp "$STEP4_DIR/${barcode}.coverage" "${TEMP_DIR}/${barcode}.coverage" || true
           else
               # next_step=3, not 4. The Step 4 guard is `[ $STARTING_STEP -lt 4 ]`, so
               # STARTING_STEP=4 SKIPS the very rebuild this branch is asking for and the
               # job then dies at Step 5 on a missing BAM. 3 re-enters at SAM->BAM.
               echo "WARNING: BAM prerequisites missing; rebuilding from Step 4"
               next_step=3
           fi
           echo "Resuming from Step 6" ;;
        6) echo "All steps completed for ${barcode}, skipping"
           return 6 ;;
    esac
    return $next_step
}

set +e
detect_checkpoint "$BARCODE"; STARTING_STEP=$?
set -e

# Checkpoint detection keys purely on file existence, so re-basecalling or
# replacing a barcode's FASTQs leaves stale artifacts looking complete. The run
# fingerprint cannot catch this: it covers settings, not input data.
SIG_DIR="$RESULTS_DIR/.barcode_sigs"
SIG_FILE="$SIG_DIR/${BARCODE}"
CURRENT_SIG=$(python3 "$BASECALL_PY" --signature "fastq_pass/${BARCODE}")
if [ "$STARTING_STEP" -gt 0 ] && [ -f "$SIG_FILE" ] && \
   [ "$(cat "$SIG_FILE")" != "$CURRENT_SIG" ]; then
    echo "Input files for ${BARCODE} changed since its last run"
    echo "  stored : $(cat "$SIG_FILE")"
    echo "  current: $CURRENT_SIG   (files:bytes:newest-mtime)"
    echo "  Rebuilding ${BARCODE} from step 0; other barcodes resume normally."
    STARTING_STEP=0
fi

set +e
resume_from_step $STARTING_STEP "$BARCODE"; RESUME_CODE=$?
set -e

if [ "$RESUME_CODE" -ne "$STARTING_STEP" ]; then
    echo "Adjusted starting step from $STARTING_STEP to $RESUME_CODE"
    STARTING_STEP=$RESUME_CODE
fi

if [ $RESUME_CODE -eq 6 ]; then
    echo "${BARCODE} already complete - generating HTML report and exiting"
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    python3 "$SCRIPT_DIR/../pipeline/html_reporter.py" \
        --barcode "$BARCODE" \
        --results-dir "./results" \
        --config "pipeline_config.json" \
        --reference "$REF" || \
        echo "Warning: HTML report generation failed for ${BARCODE} - report not refreshed"
    exit 0
fi

# Step 0.5: NanoPlot Raw Read QC
# Runs on the original compressed fastq.gz files before any processing.
# Controlled by NANOPLOT_ENABLED (set from pipeline_config.json).
# Runs regardless of checkpoint - it's fast and its output dir is separate.
echo "=== Step 0.5: NanoPlot Raw Read QC for ${BARCODE} ==="
if [ "${NANOPLOT_ENABLED:-true}" = "true" ]; then
    if command -v NanoPlot >/dev/null 2>&1; then
        # Check if NanoPlot already ran for this barcode
        if [ -f "${STEP1_DIR}/NanoStats.txt" ] && \
           [ -f "${STEP1_DIR}/NanoPlot-report.html" ]; then
            echo " NanoPlot already complete for ${BARCODE} - skipping"
        else
            echo "  Running NanoPlot on raw fastq.gz files..."
            # Build file list (NanoPlot accepts multiple --fastq args)
            FASTQ_FILES=( fastq_pass/${BARCODE}/*.fastq.gz )
            if NanoPlot \
                --fastq "${FASTQ_FILES[@]}" \
                --outdir "$STEP1_DIR" \
                --threads "${THREADS}" \
                --N50 \
                --title "${BARCODE} Raw Reads" \
                --store \
                2>&1; then
                echo "NanoPlot QC complete for ${BARCODE}"
                echo "  Report: ${STEP1_DIR}/NanoPlot-report.html"
            else
                echo "Warning: NanoPlot failed for ${BARCODE} - continuing pipeline"
            fi
        fi
    else
        echo "Warning: NanoPlot not found in PATH - skipping raw read QC"
        echo "  (Install with: conda install -c bioconda nanoplot)"
    fi
else
    echo " NanoPlot disabled in configuration - skipping"
fi

# Step 1: Merge fastq files
if [ $STARTING_STEP -lt 1 ]; then
    echo "=== Step 1: Merging ${BARCODE} fastq files ==="
    find "fastq_pass/${BARCODE}" -name "*.fastq.gz" -print0 \
        | LC_ALL=C sort -z | xargs -0 zcat > "${TEMP_DIR}/${BARCODE}_merged.fastq" || {
        echo "Error: Failed to merge fastq files for ${BARCODE}"; exit 1; }
    mkdir -p "$SIG_DIR" && printf '%s\n' "$CURRENT_SIG" > "$SIG_FILE"
else
    if [ ! -f "${TEMP_DIR}/${BARCODE}_merged.fastq" ] && \
       [ -f "$STEP2_DIR/${BARCODE}_merged.fastq" ]; then
        echo "Restoring Step 1 artifact"
        cp "$STEP2_DIR/${BARCODE}_merged.fastq" "${TEMP_DIR}/${BARCODE}_merged.fastq"
    fi
    echo "Skipping Step 1: Already completed"
fi


# Basecall model provenance. ONT read headers carry basecall_model_version_id.
# The mpileup flags pinned in combined_consensus_script.sh are bcftools' "ont"
# profile, which is tuned for hac and includes -I (skip indels); sup reads would
# warrant the ont-sup profile instead. Detect what actually produced these reads
# rather than assuming, and record it in the receipt.
read -r _BCM_MODEL _BCM_N _BCM_TOTAL _BCM_DISTINCT < <(
    python3 "$BASECALL_PY" --awk-compat "${TEMP_DIR}/${BARCODE}_merged.fastq")

if [ "${_BCM_DISTINCT:-0}" -gt 1 ]; then
    echo "Error: ${BARCODE} mixes ${_BCM_DISTINCT} basecall models. The mpileup flag set"
    echo "depends on the model, so there is no correct choice for a mixed set - re-basecall"
    echo "uniformly or split the barcode. Models found:"
    awk 'NR % 4 == 1 && match($0, /basecall_model_version_id=[^ \t]+/) {
            print "  " substr($0, RSTART + 26, RLENGTH - 26) }' \
        "${TEMP_DIR}/${BARCODE}_merged.fastq" | sort | uniq -c
    exit 1
fi

if [ "${_BCM_DISTINCT:-0}" -eq 0 ]; then
    BASECALL_MODEL="unknown (no basecall_model_version_id in read headers)"
    BASECALL_TIER="unknown"
    echo "Warning: ${BARCODE} read headers carry no basecall model; assuming hac."
    echo "  The hac flag set is the conservative choice either way (-I means no indel"
    echo "  calling), so this cannot corrupt results - only under-call sup data."
else
    BASECALL_MODEL="${_BCM_MODEL} (${_BCM_N}/${_BCM_TOTAL} reads)"
    case "$_BCM_MODEL" in
        *sup*)  BASECALL_TIER="sup" ;;
        *hac*)  BASECALL_TIER="hac" ;;
        *fast*) BASECALL_TIER="fast" ;;
        *)      BASECALL_TIER="unknown" ;;
    esac
    echo "Basecall model: ${BASECALL_MODEL}  [tier: ${BASECALL_TIER}]"
    if [ "$BASECALL_TIER" = "fast" ]; then
        echo "Warning: ${BARCODE} is fast-basecalled. fast is not intended for consensus"
        echo "  refinement - its per-base error rate inflates both ambiguous positions and"
        echo "  indel artifacts. Proceeding with the hac flag set; re-basecall at hac or"
        echo "  sup before trusting these results."
    fi
fi

# Override. Not an indel-only switch: it swaps in the whole ont-sup flag set, so
# under "auto" base quality it also moves -Q and --max-BQ and SNV calls shift with
# it. Recorded in the run fingerprint, so a resume across a toggle aborts.
DETECTED_TIER="$BASECALL_TIER"
if [ "${FORCE_SUP_PROFILE:-false}" = "true" ] && [ "$BASECALL_TIER" != "sup" ]; then
    echo "Override: force_sup_profile=true - treating ${BARCODE} (${BASECALL_TIER}) as sup."
    echo "  Applies bcftools' full ont-sup flag set to reads it was not tuned for."
    BASECALL_TIER="sup"
fi

# min_base_quality / max_base_quality: "auto" takes the tier default, matching the
# bcftools profile. They are a validated pair (1/35 sup, 5/30 hac) and resolve
# together. An explicit value overrides and is passed to bcftools unchanged.
_MBQ_WAS_AUTO=false
[ "${MIN_BASE_QUALITY:-auto}" = "auto" ] && _MBQ_WAS_AUTO=true
if [ "${MIN_BASE_QUALITY:-auto}" = "auto" ]; then
    case "$BASECALL_TIER" in
        sup) MIN_BASE_QUALITY=1 ;;
        *)   MIN_BASE_QUALITY=5 ;;
    esac
fi
if [ "${MAX_BASE_QUALITY:-auto}" = "auto" ]; then
    case "$BASECALL_TIER" in
        sup) MAX_BASE_QUALITY=35 ;;
        *)   MAX_BASE_QUALITY=30 ;;
    esac
fi

# Pinned base quality plus the override decouples a pair bcftools ships together.
# Legal, but no published profile covers it, so say so rather than let it pass.
if [ "${FORCE_SUP_PROFILE:-false}" = "true" ] && [ "$_MBQ_WAS_AUTO" = "false" ]; then
    echo "Warning: force_sup_profile with an explicit min_base_quality (${MIN_BASE_QUALITY})."
    echo "  bcftools ships -Q1/--max-BQ 35 for sup and -Q5/--max-BQ 30 for hac;"
    echo "  -Q${MIN_BASE_QUALITY}/--max-BQ ${MAX_BASE_QUALITY} is neither. Uncheck the pinned"
    echo "  value to use the validated pair."
fi

# The resolver floors at 5 on every tier. bcftools admits lower-quality bases but
# down-weights them via --max-BQ; the resolver counts every surviving base at equal
# weight and has no equivalent, so following sup's -Q1 would make it strictly more
# permissive than bcftools rather than equivalent. Measured on hac data, moving this
# floor between 1 and 5 changed 21 of 598 degeneracy decisions.
if [ "${MIN_BASE_QUALITY}" -gt 5 ] 2>/dev/null; then
    RESOLVER_MIN_BQ="${MIN_BASE_QUALITY}"
else
    RESOLVER_MIN_BQ=5
fi
export BASECALL_MODEL BASECALL_TIER DETECTED_TIER MIN_BASE_QUALITY MAX_BASE_QUALITY RESOLVER_MIN_BQ

# Step 2: Adapter Trimming
if [ $STARTING_STEP -lt 2 ]; then
    echo "=== Step 2: Adapter trimming for ${BARCODE} ==="
    porechop -i ${TEMP_DIR}/${BARCODE}_merged.fastq \
             -o ${TEMP_DIR}/${BARCODE}_trimmed.fastq \
             --discard_middle --threads "${THREADS}" || {
        echo "Error: Adapter trimming failed for ${BARCODE}"; exit 1; }
else
    if [ ! -f "${TEMP_DIR}/${BARCODE}_trimmed.fastq" ] && \
       [ -f "$STEP2_DIR/${BARCODE}_trimmed.fastq" ]; then
        echo "Restoring Step 2 artifact"
        cp "$STEP2_DIR/${BARCODE}_trimmed.fastq" "${TEMP_DIR}/${BARCODE}_trimmed.fastq"
    fi
    echo "Skipping Step 2: Already completed"
fi

# Step 3: Mapping
if [ $STARTING_STEP -lt 3 ]; then
    echo "=== Step 3: Mapping ${BARCODE} to reference ==="
    # --secondary=no is required with this reference. infA_references.fasta is a 37-record
    # cross-reactive subtype panel (18 HA + 11 NA + 6 internal); HA subtypes share 40-60%
    # identity, so one physical read produces a primary hit on the true subtype plus secondary
    # hits on several others. samtools idxstats counts alignment RECORDS, so those secondaries
    # inflated the per-reference counts, the "% of Total" column summed past 100%, and a pure
    # H5N1 sample could be displayed as a mixed infection - which also drives the dominant
    # HA/NA selection. Consensus calling was never affected (pysam's 'all' stepper already
    # drops secondary alignments), so this only makes the reported counts agree with the
    # reads that actually vote.
    minimap2 -t "${THREADS}" -ax map-ont --secondary=no "$REF" \
             "${TEMP_DIR}/${BARCODE}_trimmed.fastq" > "${TEMP_DIR}/${BARCODE}.sam" || {
        echo "Error: Minimap2 mapping failed for ${BARCODE}"; exit 1; }
else
    if [ ! -f "${TEMP_DIR}/${BARCODE}.sam" ] && \
       [ -f "$STEP3_DIR/${BARCODE}.sam" ]; then
        echo "Restoring Step 3 artifact"
        cp "$STEP3_DIR/${BARCODE}.sam" "${TEMP_DIR}/${BARCODE}.sam"
    fi
    echo "Skipping Step 3: Already completed"
fi

# Step 4: SAM -> BAM
if [ $STARTING_STEP -lt 4 ]; then
    echo "=== Step 4: Converting and sorting BAM for ${BARCODE} ==="
    samtools view -@ "${THREADS}" -Sb ${TEMP_DIR}/${BARCODE}.sam | \
        samtools sort -@ "${THREADS}" -o ${TEMP_DIR}/${BARCODE}.bam || {
        echo "Error: SAM to BAM conversion failed for ${BARCODE}"; exit 1; }
    samtools index -@ "${THREADS}" ${TEMP_DIR}/${BARCODE}.bam || {
        echo "Error: BAM indexing failed for ${BARCODE}"; exit 1; }
    echo "=== Generating depth coverage for ${BARCODE} ==="
    # -a is required. Without it samtools emits only positions that already have >=1 read,
    # so the .coverage file can never contain a depth-0 row; html_reporter.parse_coverage()
    # then computes zero-coverage as a structural 0 and breadth as a structural 100.0%
    # for every barcode regardless of how bad the run was.
    # -a (not -aa) is deliberate: -aa would add all ~29 influenza subtype references that
    # this sample does not map to, making breadth meaningless. -a keeps the denominator to
    # the references that actually received reads, which is the number a bench scientist wants.
    samtools depth -a "${TEMP_DIR}/${BARCODE}.bam" > "${TEMP_DIR}/${BARCODE}.coverage" || \
        echo "Warning: Coverage generation failed for ${BARCODE}"
else
    if [ ! -f "${TEMP_DIR}/${BARCODE}.bam" ] && \
       [ -f "$STEP4_DIR/${BARCODE}.bam" ]; then
        echo "Restoring Step 4 artifacts"
        cp "$STEP4_DIR/${BARCODE}.bam"     "${TEMP_DIR}/${BARCODE}.bam"
        [ -f "$STEP4_DIR/${BARCODE}.bam.bai" ] && \
            cp "$STEP4_DIR/${BARCODE}.bam.bai" "${TEMP_DIR}/${BARCODE}.bam.bai"
        [ -f "$STEP4_DIR/${BARCODE}.coverage" ] && \
            cp "$STEP4_DIR/${BARCODE}.coverage" "${TEMP_DIR}/${BARCODE}.coverage"
    fi
    echo "Skipping Step 4: Already completed"
fi

# Step 4.5: Qualimap BAM QC
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ $STARTING_STEP -lt 5 ]; then
    echo "=== Step 4.5: Qualimap BAM QC for ${BARCODE} ==="
    if [ "${QUALIMAP_ENABLED:-true}" = "true" ]; then
        QUALIMAP_OUTDIR="${TEMP_DIR}/qualimap_output_${BARCODE}"
        mkdir -p "$QUALIMAP_OUTDIR"
        if command -v qualimap >/dev/null 2>&1; then
            export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:-} -Djava.awt.headless=true"
            QLOG="$QUALIMAP_OUTDIR/qualimap_run.log"
            QARGS=("bamqc" "-bam" "${TEMP_DIR}/${BARCODE}.bam" "-c"
                   "-outdir" "$QUALIMAP_OUTDIR"
                   "-outfile" "${BARCODE}_qualimap_report.pdf"
                   "-outformat" "PDF:HTML")
            [ -n "${QUALIMAP_THREADS:-}" ] && QARGS+=("-nt" "${QUALIMAP_THREADS}")
            _qm_ok=0
            qualimap "${QARGS[@]}" >>"$QLOG" 2>&1 && _qm_ok=1 || {
                # Fallback: HTML only
                qualimap bamqc -bam "${TEMP_DIR}/${BARCODE}.bam" -c \
                    -outdir "$QUALIMAP_OUTDIR" -outformat HTML \
                    ${QUALIMAP_THREADS:+-nt "$QUALIMAP_THREADS"} \
                    >>"$QLOG" 2>&1 && _qm_ok=1 || \
                    echo "Warning: Qualimap failed for ${BARCODE} - continuing"
            }
            [ "$_qm_ok" -eq 1 ] && echo "Qualimap QC complete for ${BARCODE}"
        else
            echo "Warning: Qualimap not found - skipping BAM QC"
        fi
    else
        echo "Qualimap disabled - skipping"
        QUALIMAP_OUTDIR=""
    fi
else
    echo "Skipping Step 4.5 (Qualimap): Already completed"
    QUALIMAP_OUTDIR=""
fi

# Step 5: Consensus generation
if [ $STARTING_STEP -lt 5 ]; then
    echo "=== Step 5: Consensus generation for ${BARCODE} ==="
    if [ ! -x "$SCRIPT_DIR/combined_consensus_script.sh" ]; then
        echo "Error: combined_consensus_script.sh not found or not executable"; exit 1; fi
    "$SCRIPT_DIR/combined_consensus_script.sh" \
        "${TEMP_DIR}/${BARCODE}.bam" "$REF" "${BARCODE}" || {
        echo "Error: Consensus script failed for ${BARCODE}"; exit 1; }
else
    echo "Skipping Step 5: Already completed"
fi

# Step 6: Consensus editing
if [ $STARTING_STEP -lt 6 ]; then
    echo "=== Step 6: Consensus editor for ${BARCODE} ==="
    EDITOR_PY="$SCRIPT_DIR/../pipeline/consensus_editor.py"
    [ -f "$EDITOR_PY" ] || { echo "Error: consensus_editor.py not found"; exit 1; }
    [ -f "./${BARCODE}_consensus.fasta" ] || {
        echo "Error: Consensus file './${BARCODE}_consensus.fasta' not found"; exit 1; }

    CONSENSUS_ARGS=("python3" "$EDITOR_PY"
        "./${BARCODE}_consensus.fasta" "$REF"
        "--bam" "${TEMP_DIR}/${BARCODE}.bam"
        "--diagnostic")

    [ -n "${MIN_COVERAGE:-}"         ] && CONSENSUS_ARGS+=("--min-coverage"         "$MIN_COVERAGE")
    [ -n "${RESOLVER_MIN_BQ:-}"      ] && CONSENSUS_ARGS+=("--min-base-quality"     "$RESOLVER_MIN_BQ")
    [ -f "./${BARCODE}_variants.vcf.gz" ] && CONSENSUS_ARGS+=("--vcf" "./${BARCODE}_variants.vcf.gz")
    if [ -n "${DEGENERACY_THRESHOLD:-}" ]; then
        # Accept both the percentage form (20) and the legacy 0-1 fraction form (0.2) that
        # core/config.py:71-73 explicitly normalises. `cut -d. -f1` used to floor 0.2 to "0",
        # which sets min_percentage_diff=0 and collapses EVERY degenerate site to its majority
        # base - a 50.1/49.9 split would be published as a pure sequence with no warning.
        _DEG_PCT=$(awk -v v="$DEGENERACY_THRESHOLD" 'BEGIN{
            if (v > 0 && v < 1) v = v * 100.0;   # strict: a literal 1 means 1%, not 100%
            printf "%d", (v < 1 ? 1 : (v > 100 ? 100 : int(v + 0.5)));
        }')
        if [ "$_DEG_PCT" != "$DEGENERACY_THRESHOLD" ]; then
            echo "  Note: degeneracy threshold ${DEGENERACY_THRESHOLD} normalised to ${_DEG_PCT}%"
        fi
        CONSENSUS_ARGS+=("--min-percentage-diff" "$_DEG_PCT")
    fi
    [ -n "${FILTER_MODE:-}"          ] && CONSENSUS_ARGS+=("--filter-mode"          "$FILTER_MODE")
    [ -n "${INDEL_INSERTIONS:-}"     ] && CONSENSUS_ARGS+=("--indel-insertions"     "$INDEL_INSERTIONS")
    [ -n "${INDEL_DELETIONS:-}"      ] && CONSENSUS_ARGS+=("--indel-deletions"      "$INDEL_DELETIONS")
    [ -n "${INDEL_CUSTOM_PERCENTAGE:-}" ] && \
        CONSENSUS_ARGS+=("--indel-custom-percentage" "$INDEL_CUSTOM_PERCENTAGE")

    # Advanced criteria
    [ -n "${STRAND_BALANCE_THRESHOLD:-}" ] && \
        CONSENSUS_ARGS+=("--strand-balance-threshold" "$STRAND_BALANCE_THRESHOLD")
    [ -n "${HOMOPOLYMER_MIN_LENGTH:-}" ] && \
        CONSENSUS_ARGS+=("--homopolymer-min-length" "$HOMOPOLYMER_MIN_LENGTH")
    [ -n "${HOMOPOLYMER_WINDOW:-}" ] && \
        CONSENSUS_ARGS+=("--homopolymer-window" "$HOMOPOLYMER_WINDOW")
    [ -n "${READ_END_THRESHOLD:-}" ] && \
        CONSENSUS_ARGS+=("--read-end-threshold" "$READ_END_THRESHOLD")
    [ -n "${READ_END_EDGE_FRACTION:-}" ] && \
        CONSENSUS_ARGS+=("--read-end-edge-fraction" "$READ_END_EDGE_FRACTION")
    [ "${STRICT_STRAND_BIAS:-false}" = "true" ] && \
        CONSENSUS_ARGS+=("--strict-strand-bias")
    [ "${STRICT_HOMOPOLYMER:-false}" = "true" ] && \
        CONSENSUS_ARGS+=("--strict-homopolymer")
    [ "${STRICT_READ_END:-false}" = "true" ] && \
        CONSENSUS_ARGS+=("--strict-read-end")

    if [ "${FILTER_MODE:-}" = "influenza" ]; then
        # Save idxstats for the HTML report
        samtools idxstats "${TEMP_DIR}/${BARCODE}.bam" > "${STEP4_DIR}/${BARCODE}_idxstats.tsv"

        major_h=""; major_n=""; max_h=0; max_n=0
        while read -r seg length reads unmapped; do
            [[ $seg == H* ]] && (( reads > max_h )) && { max_h=$reads; major_h=$seg; }
            [[ $seg == N[0-9]* || $seg == NA* ]] && (( reads > max_n )) && { max_n=$reads; major_n=$seg; }
        done < <(grep -v "^\*$(printf '\t')" "${STEP4_DIR}/${BARCODE}_idxstats.tsv")
        [ -n "$major_h" ] && CONSENSUS_ARGS+=("--major-h" "$major_h")
        [ -n "$major_n" ] && CONSENSUS_ARGS+=("--major-n" "$major_n")

        # Save selection metadata for the report (use python for safe JSON encoding)
        python3 -c "import json; print(json.dumps({'major_h': '${major_h}', 'major_h_reads': ${max_h}, 'major_n': '${major_n}', 'major_n_reads': ${max_n}}))" \
            > "${STEP4_DIR}/${BARCODE}_hn_selection.json"
    fi

    "${CONSENSUS_ARGS[@]}" || {
        echo "Error: Consensus editor failed for ${BARCODE}"; exit 1; }
else
    echo "Skipping Step 6: Already completed"
fi

# Final verification
[ -f "./${BARCODE}_consensus_edited.fasta" ] || {
    echo "Error: Edited consensus file './${BARCODE}_consensus_edited.fasta' not found"
    exit 1
}

# Write timing metadata for the HTML report
BARCODE_END_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
BARCODE_END_EPOCH=$(date +%s)
BARCODE_ELAPSED_S=$((BARCODE_END_EPOCH - BARCODE_START_EPOCH))
cat > "${REPORTS_DIR}/${BARCODE}_timing.json" <<TIMEOF
{"start": "${BARCODE_START_ISO}", "end": "${BARCODE_END_ISO}", "elapsed_seconds": ${BARCODE_ELAPSED_S}}
TIMEOF

echo "=== Step 7: Organising output files for ${BARCODE} ==="
mkdir -p "./log"

# Step 2: merged
[ -f "${TEMP_DIR}/${BARCODE}_merged.fastq" ] && {
    cp "${TEMP_DIR}/${BARCODE}_merged.fastq" "$STEP2_DIR/"
    echo "  merged.fastq -> $STEP2_DIR/"; }

# Step 3: trimmed
[ -f "${TEMP_DIR}/${BARCODE}_trimmed.fastq" ] && {
    cp "${TEMP_DIR}/${BARCODE}_trimmed.fastq" "$STEP3_DIR/"
    echo "  trimmed.fastq -> $STEP3_DIR/"; }

# Step 4: SAM + BAM + coverage (per-barcode subdir)
[ -f "${TEMP_DIR}/${BARCODE}.sam"      ] && {
    cp "${TEMP_DIR}/${BARCODE}.sam"      "$STEP4_DIR/"
    echo "  .sam -> $STEP4_DIR/"; }
[ -f "${TEMP_DIR}/${BARCODE}.bam"      ] && cp "${TEMP_DIR}/${BARCODE}.bam"      "$STEP4_DIR/"
[ -f "${TEMP_DIR}/${BARCODE}.bam.bai"  ] && cp "${TEMP_DIR}/${BARCODE}.bam.bai"  "$STEP4_DIR/"
[ -f "${TEMP_DIR}/${BARCODE}.coverage" ] && cp "${TEMP_DIR}/${BARCODE}.coverage" "$STEP4_DIR/"

# Step 5: Qualimap BAM QC
if [ -n "${QUALIMAP_OUTDIR:-}" ] && [ -d "$QUALIMAP_OUTDIR" ]; then
    cp -r "$QUALIMAP_OUTDIR" "$STEP5_DIR/"
    echo "  Qualimap -> $STEP5_DIR/"
fi

# Step 6: VCF files (flat)
[ -f "./${BARCODE}_variants.vcf.gz"     ] && {
    cp "./${BARCODE}_variants.vcf.gz"     "$STEP6_DIR/"
    echo "  variants.vcf.gz -> $STEP6_DIR/"; }
[ -f "./${BARCODE}_variants.vcf.gz.csi" ] && cp "./${BARCODE}_variants.vcf.gz.csi" "$STEP6_DIR/"
# Copy, not move: the receipt below still reads it from the run root.
[ -f "./${BARCODE}_mpileup_provenance.txt" ] && {
    cp "./${BARCODE}_mpileup_provenance.txt" "$REPORTS_DIR/"
    echo "  mpileup_provenance.txt -> $REPORTS_DIR/"; }

# Step 7: draft consensus
STEP7_FASTQ="$STEP7_DIR/fastq"
mkdir -p "$STEP7_FASTQ"
[ -f "./${BARCODE}_consensus.fasta" ] && {
    cp "./${BARCODE}_consensus.fasta" "$STEP7_DIR/"
    if ! grep -q "^>${BARCODE}_" "$STEP7_DIR/${BARCODE}_consensus.fasta" 2>/dev/null; then
        sed -i "s/^>/>${BARCODE}_/" "$STEP7_DIR/${BARCODE}_consensus.fasta"
    fi
    echo "  consensus.fasta -> $STEP7_DIR/"; }
[ -f "./${BARCODE}_consensus.fastq" ] && {
    cp "./${BARCODE}_consensus.fastq" "$STEP7_FASTQ/"
    echo "  consensus.fastq -> $STEP7_FASTQ/"; }

# Step 8: refined consensus
[ -f "./${BARCODE}_consensus_edited.fasta" ] && {
    cp "./${BARCODE}_consensus_edited.fasta" "$STEP8_DIR/"
    echo "  consensus_edited.fasta -> $STEP8_DIR/"; }

# Logs
[ -f "./${BARCODE}_per_segment_consensus.log" ] && \
    mv "./${BARCODE}_per_segment_consensus.log" "./log/"
[ -f "./${BARCODE}_consensus_edited_diagnostic_log.txt" ] && \
    mv "./${BARCODE}_consensus_edited_diagnostic_log.txt" "./log/"
[ -f "./${BARCODE}_consensus_diagnostic_log.txt" ] && \
    mv "./${BARCODE}_consensus_diagnostic_log.txt" "./log/"

# QC summary files
[ -f "./${BARCODE}_consensus_edited_qc_summary.html" ] && \
    mv "./${BARCODE}_consensus_edited_qc_summary.html" "$REPORTS_DIR/"
[ -f "./${BARCODE}_consensus_edited_qc_summary.json" ] && \
    mv "./${BARCODE}_consensus_edited_qc_summary.json" "$REPORTS_DIR/"

# Step 7.5: HTML Report (after files are organized)
echo "=== Step 7.5: Generating HTML report for ${BARCODE} ==="
REPORTER="$SCRIPT_DIR/../pipeline/html_reporter.py"
if [ -f "$REPORTER" ]; then
    python3 "$REPORTER" \
        --barcode "$BARCODE" \
        --results-dir "./results" \
        --config "pipeline_config.json" \
        --reference "$REF" && \
        echo "HTML report generated: results/reports/${BARCODE}_summary_report.html" || \
        echo "Warning: HTML report generation failed - non-fatal, continuing"
else
    echo "Warning: html_reporter.py not found - skipping HTML report"
fi

# Reproducibility receipt: config, then tool versions, then artifact checksums -
# the order the failure modes actually occur in, so a mismatch is self-diagnosing.
# Records are checksummed, not container bytes: the BAM/SAM @PG header stores the
# command line including -t <threads>, the VCF header stores a wall-clock Date, and
# line 3 of the diagnostic log is a timestamp. Those differ between two runs that
# agree on every base, so hashing them would make this file permanently red.
RECEIPT="${REPORTS_DIR}/${BARCODE}_receipt.txt"
_h() { md5sum | cut -d' ' -f1; }
{
    echo "DeGenRESOLVE run receipt - ${BARCODE}"
    echo "params md5    : ${RUN_FINGERPRINT:-not recorded}"
    echo "reference md5 : ${REFERENCE_MD5:-not recorded}"
    echo "config md5    : $(_h < pipeline_config.json 2>/dev/null)"
    echo "basecall model: ${BASECALL_MODEL:-not detected}"
    if [ -f "./${BARCODE}_mpileup_provenance.txt" ]; then
        sed 's/^/mpileup       : /' "./${BARCODE}_mpileup_provenance.txt"
    else
        echo "mpileup       : not recorded"
    fi
    echo "resolver -Q   : ${RESOLVER_MIN_BQ:-not recorded} (floored at 5; counts reads, cannot down-weight)"
    echo "environment   : $(grep -m1 '^environment_md5=' results/reports/environment_manifest.txt 2>/dev/null | cut -d= -f2 || echo 'not recorded')"
    echo "                (full package inventory: results/reports/environment_manifest.txt)"
    python3 -c "import json;v=json.load(open('results/reports/runtime_versions.json'));print('version check : '+v.get('version_match',{}).get('status','not recorded'));[print('  %s: %s'%(t,v[t])) for t in ('samtools','bcftools','minimap2','porechop','python','pysam') if t in v]" 2>/dev/null \
        || echo "version check : unavailable"
    echo "--- effective parameters ---"
    sed 's/^/  /' results/reports/effective_params.txt 2>/dev/null || echo "  not recorded"
    echo "--- scope A checksums (md5, records only) ---"
    # _hf hashes a file only if it exists and is non-empty. The previous form piped the
    # output of a failed command straight into md5sum, so a MISSING artifact was recorded
    # as d41d8cd98f00b204e9800998ecf8427e (the md5 of nothing) - which reads like a real
    # checksum and makes an incomplete run look reproducible.
    _hf() {  # $1 = label, $2 = path
        if [ ! -f "$2" ]; then printf '%-17s MISSING\n' "$1"
        elif [ ! -s "$2" ]; then printf '%-17s EMPTY FILE\n' "$1"
        else printf '%-17s %s\n' "$1" "$(_h < "$2")"; fi
    }
    _hc() {  # $1 = label, $2 = path, $3.. = command producing records on stdout
        local _lbl="$1" _path="$2"; shift 2
        if [ ! -f "$_path" ]; then printf '%-17s MISSING\n' "$_lbl"; return; fi
        # || true is required: under `set -eo pipefail` an assignment from a failing command
        # substitution aborts the whole job, and this runs at the very last step, so an
        # unreadable BAM or VCF would discard a completed barcode instead of noting it here.
        local _out; _out=$("$@" 2>/dev/null | _h) || true
        if [ -z "$_out" ] || [ "$_out" = "d41d8cd98f00b204e9800998ecf8427e" ]; then
            printf '%-17s NO RECORDS\n' "$_lbl"
        else printf '%-17s %s\n' "$_lbl" "$_out"; fi
    }
    _hf 'merged.fastq'     "$STEP2_DIR/${BARCODE}_merged.fastq"
    _hf 'trimmed.fastq'    "$STEP3_DIR/${BARCODE}_trimmed.fastq"
    _hc 'sam (records)'    "$STEP4_DIR/${BARCODE}.sam"  grep -v '^@' "$STEP4_DIR/${BARCODE}.sam"
    _hc 'bam (records)'    "$STEP4_DIR/${BARCODE}.bam"  samtools view "$STEP4_DIR/${BARCODE}.bam"
    _hc 'vcf (records)'    "$STEP6_DIR/${BARCODE}_variants.vcf.gz" bcftools view -H "$STEP6_DIR/${BARCODE}_variants.vcf.gz"
    _hf 'draft consensus'  "$STEP7_DIR/${BARCODE}_consensus.fasta"
    _hf 'edited consensus' "$STEP8_DIR/${BARCODE}_consensus_edited.fasta"
    _hc 'diagnostic log'   "./log/${BARCODE}_consensus_edited_diagnostic_log.txt" grep -v '^Generated:' "./log/${BARCODE}_consensus_edited_diagnostic_log.txt"
} > "$RECEIPT"
echo "Receipt: $RECEIPT"

# Cleanup
rm -f "./${BARCODE}_consensus.fasta" "./${BARCODE}_consensus_edited.fasta" \
      "./${BARCODE}_consensus.fastq" \
      "./${BARCODE}_variants.vcf.gz" "./${BARCODE}_variants.vcf.gz.csi" 2>/dev/null
[ -n "${QUALIMAP_OUTDIR:-}" ] && [ -d "$QUALIMAP_OUTDIR" ] && \
    rm -rf "$QUALIMAP_OUTDIR"
rm -rf "$TEMP_DIR"

echo "=== Pipeline completed for ${BARCODE}! ==="
echo ""
echo "MAIN OUTPUT  : $STEP8_DIR/${BARCODE}_consensus_edited.fasta"
echo "HTML REPORT  : $REPORTS_DIR/${BARCODE}_summary_report.html"
echo "RAW QC       : $STEP1_DIR/"
echo "ALL RESULTS  : $RESULTS_DIR/"
