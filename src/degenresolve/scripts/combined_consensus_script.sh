#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Error: Please provide the BAM file path as an argument"
    echo "Usage: $0 <BAM_file> [reference_file] [barcode_name]"
    exit 1
fi

BAM="$1"
REF="${2:-./reference/reference.fasta}"
BARCODE="${3:-barcode01}"
FILTER_MODE="${FILTER_MODE:-general}"
LOG_FILE="./${BARCODE}_per_segment_consensus.log"
OUTPUT_FILE="./${BARCODE}_consensus.fasta"

echo "Starting basic consensus generation at $(date)" > "$LOG_FILE"
echo "Configuration parameters:" >> "$LOG_FILE"
echo "  - VARIANT_CALL_MODE: ${VARIANT_CALL_MODE:-c}" >> "$LOG_FILE"
echo "  - PLOIDY: ${PLOIDY:-2}" >> "$LOG_FILE"
echo "  - FILTER_MODE: ${FILTER_MODE:-general} (info only; not applied here)" >> "$LOG_FILE"
echo "  - VARIANT_CALL_DEPTH: ${VARIANT_CALL_DEPTH:-10000}" >> "$LOG_FILE"
echo "  - Note: Coverage filtering and degeneracy resolution moved to improved_consensus_editor.py" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# samtools and bcftools always required; tool-specific checks inside each branch
for tool in samtools bcftools; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "Error: Required tool '$tool' not found in PATH" | tee -a "$LOG_FILE"
        exit 1
    fi
done

for file in "$BAM" "$REF"; do
    if [ ! -f "$file" ]; then
        echo "Error: File $file not found" | tee -a "$LOG_FILE"
        exit 1
    fi
done

[[ -f "${REF}.fai" ]] || {
    echo "Indexing reference FASTA..." | tee -a "$LOG_FILE"
    samtools faidx "$REF" || { echo "Error: Failed to index $REF" | tee -a "$LOG_FILE"; exit 1; }
}

[[ -f "${BAM}.bai" ]] || {
    echo "Indexing BAM file..." | tee -a "$LOG_FILE"
    samtools index "$BAM" || { echo "Error: Failed to index $BAM" | tee -a "$LOG_FILE"; exit 1; }
}

echo "Building whole-genome consensus (single pass) for ${BARCODE}..." | tee -a "$LOG_FILE"
_CALL_FLAG="${VARIANT_CALL_MODE:-c}"
[[ "$_CALL_FLAG" == [cm] ]] || { echo "Error: Invalid VARIANT_CALL_MODE '${_CALL_FLAG}' - must be 'c' or 'm'" | tee -a "$LOG_FILE"; exit 1; }
VCF_GZ="./${BARCODE}_variants.vcf.gz"
WG_FASTQ="./${BARCODE}_consensus.fastq"
WG_FASTA_MAIN="$OUTPUT_FILE"

echo "  Step 1: Calling variants (bcftools call -${_CALL_FLAG})..." | tee -a "$LOG_FILE"
# Flag sets below are bcftools 1.24's "-X ont" and "-X ont-sup" profiles written
# out explicitly: profile *definitions* move between bcftools releases, so naming
# the profile would make output depend on a version no config file records. The
# resolved string is written to the receipt so drift is visible rather than silent.
#
# Selected by BASECALL_TIER, detected from basecall_model_version_id in the read
# headers. fast and unknown take the hac set: conservative, and -I means they
# cannot introduce a bad indel.
#
# hac (-X ont):
#   -B          no BAQ; the Illumina-era realignment model misreads indel-dense ONT
#   -Q5/--max-BQ 30  low floor made safe by capping ONT's overconfident high-Q values
#   -I          skip indels. bcftools' own recommendation for non-sup ONT data.
#               Deletion counts still reach the diagnostic log via the evidence
#               sweep, but nothing edits the consensus.
# sup (-X ont-sup):
#   --indels-cns  edlib consensus indel model, the only engine here that can tell a
#               real indel from an alignment artifact. On the reference dataset it
#               correctly rejected a 45% and an 80% deletion that a raw pileup count
#               accepted, because it realigns rather than counting columns.
#   -h110 --poly-mqual -F0.2 --indel-bias 0.7 --del-bias 0.4
#               tandem-repeat and homopolymer suppression; without these the same
#               model emits 36 calls on this data instead of 6, mostly homopolymers.
#
# Either way the draft stays reference-length: vcf2fq ignores indel records, and the
# -m path strips them before bcftools consensus. consensus_editor.py maps
# consensus->genome 1:1 (genomic_pos = consensus_pos) during degeneracy resolution
# and applies indels only afterwards, from this VCF.
case "${BASECALL_TIER:-unknown}" in
  sup) MPILEUP_FLAGS="--indels-cns -B -Q ${MIN_BASE_QUALITY:-1} --max-BQ ${MAX_BASE_QUALITY:-35} -F0.2 -o15 -e1 -h110 --delta-BQ 99 --del-bias 0.4 --indel-bias 0.7 --poly-mqual --seqq-offset 130 --indel-size 80" ;;
  *)   MPILEUP_FLAGS="-B -Q ${MIN_BASE_QUALITY:-5} --max-BQ ${MAX_BASE_QUALITY:-30} -I" ;;
esac
echo "  - Basecall tier: ${BASECALL_TIER:-unknown}" | tee -a "$LOG_FILE"
echo "  - mpileup flags: ${MPILEUP_FLAGS}" | tee -a "$LOG_FILE"
printf 'basecall_tier=%s\ndetected_tier=%s\nforce_sup_profile=%s\nmpileup_flags=%s\nbcftools_version=%s\n' \
  "${BASECALL_TIER:-unknown}" "${DETECTED_TIER:-unknown}" "${FORCE_SUP_PROFILE:-false}" "${MPILEUP_FLAGS}" \
  "$(bcftools --version 2>/dev/null | head -1 | awk '{print $2}')" \
  > "./${BARCODE}_mpileup_provenance.txt"

if ! bcftools mpileup -f "$REF" -d "${VARIANT_CALL_DEPTH:-10000}" \
    ${MPILEUP_FLAGS} "$BAM" \
    | bcftools call "-${_CALL_FLAG}" --ploidy "${PLOIDY:-2}" \
    | bcftools view -Oz -o "$VCF_GZ"; then
  echo "Error: Variant calling failed for ${BARCODE}" | tee -a "$LOG_FILE"
  exit 1
fi
bcftools index "$VCF_GZ" 2>/dev/null || true
echo "  - VCF: $VCF_GZ" | tee -a "$LOG_FILE"
if [[ "$_CALL_FLAG" == "c" ]]; then
  # -c path: vcfutils.pl vcf2fq -> seqtk
  # vcfutils.pl encodes zero-coverage positions as quality 0 (-> lowercase n -> N via seqtk)
  if ! command -v vcfutils.pl >/dev/null 2>&1; then
    [ -x "/usr/lib/bcftools/vcfutils.pl" ] && export PATH="/usr/lib/bcftools:$PATH"
  fi
  if ! command -v vcfutils.pl >/dev/null 2>&1; then
    echo "Error: vcfutils.pl not found (-c mode requires it; switch to -m or install bcftools-utils)" | tee -a "$LOG_FILE"
    exit 1
  fi
  if ! command -v seqtk >/dev/null 2>&1; then
    echo "Error: seqtk not found (-c mode requires it; switch to -m or install seqtk)" | tee -a "$LOG_FILE"
    exit 1
  fi

  echo "  Step 2: Building draft consensus (vcfutils.pl vcf2fq)..." | tee -a "$LOG_FILE"
  if ! bcftools view "$VCF_GZ" | vcfutils.pl vcf2fq 2>>"$LOG_FILE" > "$WG_FASTQ"; then
    echo "Error: Whole-genome FASTQ consensus generation failed for ${BARCODE}" | tee -a "$LOG_FILE"
    exit 1
  fi

  echo "=== Step 5.5: Draft Consensus (seqtk) for ${BARCODE} ==="
  echo "  Converting whole-genome FASTQ -> FASTA..." | tee -a "$LOG_FILE"
  if ! seqtk seq -a "$WG_FASTQ" > "$WG_FASTA_MAIN"; then
    echo "Error: Whole-genome FASTA conversion failed for ${BARCODE}" | tee -a "$LOG_FILE"
    exit 1
  fi
  echo "  - FASTQ: $WG_FASTQ" | tee -a "$LOG_FILE"

else
  # -m path: bcftools consensus --iupac-codes + samtools depth zero-coverage mask
  # vcfutils.pl does not parse multiallelic PL fields; bcftools consensus handles -m VCF correctly.
  # Zero-coverage N-masking. -aa, NOT -a: `-a` emits every position of references that have at
  # least one read, but omits unused reference sequences entirely. With the shipped 37-record
  # infA_references.fasta a sample maps to ~8 records, so ~29 references produced no BED rows,
  # nothing was masked, and `bcftools consensus` emitted them as VERBATIM REFERENCE SEQUENCE into
  # the draft FASTA - published as if it were sequencing data. -aa masks them fully to N.
  _ZERO_COV_BED="./${BARCODE}_zero_cov.bed"
  echo "  Step 2: Generating zero-coverage mask (samtools depth)..." | tee -a "$LOG_FILE"
  if ! samtools depth -aa "$BAM" \
      | awk '$3 == 0 {print $1"\t"($2-1)"\t"$2}' > "$_ZERO_COV_BED"; then
    echo "Error: Zero-coverage mask generation failed for ${BARCODE}" | tee -a "$LOG_FILE"
    exit 1
  fi
  echo "  - Zero-coverage mask: $_ZERO_COV_BED" | tee -a "$LOG_FILE"

  echo "=== Step 5.5: Draft Consensus (bcftools consensus) for ${BARCODE} ==="
  echo "  Building draft FASTA with IUPAC codes and N-masking at zero coverage..." | tee -a "$LOG_FILE"
  # Strip indels first. bcftools consensus APPLIES them, which shifts every base
  # after one and breaks the 1:1 consensus->reference mapping the resolver needs.
  # Measured on the sup profile: N1 +1, PB2 -2, and the coordinate guard below
  # then aborts the run. The indels are not lost - they stay in $VCF_GZ and are
  # adjudicated by consensus_editor.py after degeneracy resolution.
  _SNV_ONLY="./${BARCODE}_snv_only.vcf.gz"
  bcftools view -V indels -Oz -o "$_SNV_ONLY" "$VCF_GZ" 2>/dev/null
  bcftools index -f "$_SNV_ONLY" 2>/dev/null || true
  if ! bcftools consensus --iupac-codes \
      --mask "$_ZERO_COV_BED" --mask-with N \
      -f "$REF" "$_SNV_ONLY" > "$WG_FASTA_MAIN"; then
    echo "Error: bcftools consensus failed for ${BARCODE}" | tee -a "$LOG_FILE"
    exit 1
  fi
  rm -f "$_ZERO_COV_BED" "$_SNV_ONLY" "${_SNV_ONLY}.csi"

  # Coordinate guard, -m path only. consensus_editor.py maps consensus position i
  # onto reference position i. vcf2fq (-c path) pads uncovered positions with N from
  # position 1, so that mapping survives any gap. bcftools consensus does not pad -
  # it APPLIES indels, which shifts every base after one. -I upstream means no indels
  # are called at all, so this should never fire; it fires if someone removes -I.
  _LENDIFF=$(python3 -c "
import sys
fai, fa = sys.argv[1], sys.argv[2]
ref = {}
for line in open(fai):
    f = line.split('\t'); ref[f[0]] = int(f[1])
name, n = None, 0
out = []
def flush():
    if name is not None and ref.get(name) is not None and n != ref[name]:
        out.append('  %s consensus=%d reference=%d' % (name, n, ref[name]))
for line in open(fa):
    if line.startswith('>'):
        flush(); name = line[1:].split()[0]; n = 0
    else:
        n += len(line.strip())
flush()
print('\n'.join(out))
" "${REF}.fai" "$WG_FASTA_MAIN" 2>/dev/null)
  if [ -n "$_LENDIFF" ]; then
    {
      echo "Error: draft consensus length differs from reference for ${BARCODE}."
      echo "bcftools consensus applied indels, so consensus position i is no longer"
      echo "reference position i and consensus_editor.py would resolve degeneracies"
      echo "against the wrong columns. Restore -I in the mpileup flags, or fix the"
      echo "consensus->reference coordinate mapping before removing it."
      echo "$_LENDIFF"
    } | tee -a "$LOG_FILE"
    exit 1
  fi
fi

echo "Processing complete." | tee -a "$LOG_FILE"
echo "  - FASTA: $WG_FASTA_MAIN" | tee -a "$LOG_FILE"
echo "Note: Coverage filtering and degeneracy resolution will be applied by improved_consensus_editor.py" | tee -a "$LOG_FILE"
echo "Log saved to $LOG_FILE" | tee -a "$LOG_FILE"
