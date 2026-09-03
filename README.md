# DeGenRESOLVE: ONT Sequencing Data Analyzer

A GUI-based, offline-capable pipeline for processing Oxford Nanopore amplicon sequencing data and generating refined consensus sequences with automated IUPAC ambiguity resolution.

Designed for laboratories with limited bioinformatics expertise or internet connectivity. Input your raw FASTQ reads, select a reference, and get publication-ready consensus FASTA files with detailed QC reports.

## Requirements

### Hardware

- **OS**: Linux x86_64 (tested on Ubuntu 22.04, 24.04). Windows users need WSL 2 with a Linux distribution.
- **RAM**: 8 GB minimum, 16 GB recommended for large datasets
- **Disk**: ~6 GB for the offline bundle install; analysis output size depends on dataset
- **CPU**: Multi-core recommended (Qualimap and NanoPlot benefit from parallelism)

### Software dependencies

| Tool | Purpose |
|------|---------|
| samtools | BAM sorting, indexing, pileup |
| bcftools (+ vcfutils.pl) | Variant calling |
| minimap2 | Read-to-reference mapping |
| porechop | Adapter trimming |
| seqtk | FASTQ/FASTA conversion |
| htslib | Low-level BAM/VCF support |
| qualimap | Alignment QC (optional, toggle in config) |
| NanoPlot | Raw read QC (optional, toggle in config) |
| OpenJDK | Required by Qualimap |
| Python 3.10+ | Application runtime |
| PyQt5 + PyQtWebEngine | GUI framework |
| pysam, biopython, numpy, cyvcf2 | Sequence analysis |
| markdown-it-py | Help guide rendering |
| click, coloredlogs, humanfriendly | CLI and logging |

## Installation

### Option A: Online install (conda + pip)

Requires internet. For machines with conda/mamba already installed:

```bash
# Create environment with bioinformatics tools
conda create -n degenresolve -c conda-forge -c bioconda -c defaults \
  python=3.10 pyqt pyqtwebengine \
  samtools bcftools htslib minimap2 seqtk porechop \
  qualimap openjdk nanoplot

conda activate degenresolve

# Install Python packages
pip install pysam biopython numpy cyvcf2 click coloredlogs humanfriendly markdown-it-py

# Clone and install
git clone https://github.com/Shoaib-Saikat/DeGenRESOLVE-ONT-Sequencing-Data-Analyzer.git
cd DeGenRESOLVE-ONT-Sequencing-Data-Analyzer
pip install -e . --no-deps
```

### Option B: Offline bundle (no internet on target machine)

Build the bundle on an internet-connected machine, then transfer:

Two install paths are supported. **Option B (offline) is the recommended one** - it needs
no internet and no pre-installed bioinformatics tools.

```bash
# Option B - offline install (recommended). Bundles Miniconda and a packed conda
# environment with every external tool; the target machine needs only tar and gzip.
tar -xzf degenresolve_offline_bundle_1.0.0.tar.gz
bash degenresolve_bundle/install.sh

# Options: --prefix DIR, --conda-dir DIR, --env-name NAME, --no-shortcut,
#          --reinstall, --modify-rc, --dry-run
```

```bash
# Option A - source install, for a machine that already has the tools on PATH
# and does not want the bundled conda environment.
bash degenresolve_bundle/install_source.sh --check-only   # verify prerequisites
bash degenresolve_bundle/install_source.sh                # then install
```

Option A requires Python 3.10+ and the external tools on PATH (`samtools` >= 1.10,
`bcftools` >= 1.21, `minimap2` >= 2.17, `seqtk`, `porechop`, `vcfutils.pl`); it checks all of
them and their versions before installing anything. `NanoPlot`, `qualimap` and `java` are
optional - the matching QC steps are skipped if absent. Option B needs none of this.

### Uninstall

```bash
bash uninstall.sh
# Options: --prefix DIR, --conda-dir DIR, --keep-env
```

## Quick start

### GUI mode

```bash
bash run_degenresolve.sh

# or

conda activate degenresolve
python degenresolve.py
```

1. **Analysis tab**: Select your data directory (containing `fastq_pass/` and `reference/`), click Start. The status ticker slides through live per-barcode step updates (`barcode01: Mapping`, `barcode02: Adapter Trimming`, ...). Count badges above each pipeline step dot show how many barcodes are at that step in real time. The **Completed Barcode** counter increments as each barcode finishes.
2. **Configuration tab**: Adjust parameters before running (or use defaults). The threads spinner controls how many barcodes run in parallel; defaults to all available CPU cores.
3. **Results tab**: Browse per-barcode outputs, view QC reports, open diagnostic logs.
4. **Help > Bench Scientist Guide**: In-app parameter reference with platform-specific recommendations.
5. **Help > Understanding DeGenRESOLVE Interface**: In-app guide covering every element of the four tabs - navigation, icons, progress indicators, Results viewer buttons, and a full reference for all 27 diagnostic log columns. See `DeGenRESOLVE_interface.md` for the source.

### CLI mode - full pipeline

The same pipeline the GUI runs, driven by a JSON config file:

```bash
conda activate degenresolve
cd /path/to/your/data_directory
bash /path/to/src/degenresolve/scripts/main_with_config.sh pipeline_config.json
```

See `example_pipeline_config.json` in the repository for a complete, documented config template. The data directory must contain the expected folder structure (see [Input](#input) below).

### CLI mode - consensus editor only

Run the consensus editor standalone on existing BAM + consensus files:

```bash
# Basic usage. The reference is any single FASTA - the name does not matter.
python consensus_editor.py barcode01_consensus.fasta reference/infA_references.fasta

# Influenza mode with diagnostic output
python consensus_editor.py barcode65_consensus.fasta reference/infA_references.fasta \
  --bam barcode65.bam \
  --filter-mode influenza \
  --diagnostic

# With indel adjudication. --vcf is REQUIRED for any indel handling: without it no indel is
# applied and the --indel-* flags below have no effect at all.
python consensus_editor.py barcode65_consensus.fasta reference/infA_references.fasta \
  --bam barcode65.bam \
  --vcf barcode65_variants.vcf.gz \
  --indel-insertions custom_percentage \
  --indel-custom-percentage 30 \
  --diagnostic

# Strict homopolymer filtering
python consensus_editor.py barcode65_consensus.fasta reference/infA_references.fasta \
  --bam barcode65.bam \
  --strict-homopolymer
```

See the [Consensus editor CLI reference](#consensus-editor-cli-reference) section below for all options.

## Reading the consensus FASTA: case carries meaning

**Lowercase bases are low-confidence calls, not repeats.** DeGenRESOLVE preserves the
soft-mask that `vcfutils.pl vcf2fq` applies on the `-c` variant-calling path: a base is
lowercase where read depth was below 3 or the call quality was below 10. Uppercase means
the position had adequate support, or that the consensus editor positively resolved it from
the pileup.

Earlier pre-release builds destroyed this mask by uppercasing the whole sequence, so every
position looked equally well supported. It is preserved now because the difference is large
and material: in the shipped demo data, `barcode01` is 0.3% soft-masked while `barcode09`
is **60.2%** soft-masked. Both would previously have been published as fully confident.

Two consequences worth planning for:

- **Most downstream tools ignore case, but not all.** BLAST, minimap2, samtools and
  Biopython treat lowercase as ordinary sequence. Repeat-aware tools and some submission
  pipelines interpret lowercase as soft-masked and may hard-mask or discard it. If you are
  submitting to GenBank or a similar archive, uppercase the sequence first
  (`seqtk seq -U in.fasta > out.fasta`) and report the masked fraction separately.
- **Judge a sample by its masked fraction before using its consensus.** The figure is in the
  QC summary and the per-barcode HTML report. A segment that is largely lowercase has not
  been sequenced deeply enough to support base-level claims, whatever its length suggests.

To recover the old behaviour for a single file:

```bash
seqtk seq -U <barcode>_consensus_edited.fasta > <barcode>_consensus_uppercase.fasta
```


## Input

### Supported formats

- **Reads**: FASTQ.gz (gzip-compressed FASTQ) only. Copy the sequencer's `fastq_pass` folder directly.
- **Reference**: Multi-FASTA file with one entry per segment/genome.

Uncompressed FASTQ is not supported. The pipeline expects `.fastq.gz` files as produced by ONT sequencers.

### Required folder structure

```
your_data_directory/
| fastq_pass/
|   | barcode01/
|   |   | FAX12345_pass_barcode01_abcdef_0.fastq.gz
|   |   + ...
|   | barcode02/
|   |   + *.fastq.gz
|   + ...
+ reference/
    + reference.fasta
```

- Each barcode directory under `fastq_pass/` must start with `barcode`.
- The reference file must be a single `*.fasta` or `*.fa` inside `reference/`. The
  filename does not matter, but there must be **exactly one**: zero files or more than
  one is a hard error, because the pipeline cannot choose for you.
- For segmented viruses (e.g., influenza), the reference should contain all segments in one file.

### Naming conventions

Output files are named by barcode: `barcode01_consensus_edited.fasta`, `barcode01.bam`, etc. The barcode directory name is the sample identifier throughout the pipeline.

## Output

Results are organized in an 8-step structure that mirrors the pipeline tracker shown in the GUI:

```
results/
| step_1_raw_read_qc_nanoplot/   barcode*/  (NanoPlot raw read QC report)
| step_2_unzipped_merged/        barcode*_merged.fastq
| step_3_adapter_trimmed/        barcode*_trimmed.fastq
| step_4_mapped/                 barcode*/  (SAM, sorted BAM, BAM index)
| step_5_alignment_qc_qualimap/  barcode*/  (Qualimap alignment QC report)
| step_6_called_variants/        barcode*_variants.vcf.gz + .csi
| step_7_draft_consensus/        barcode*_consensus.fasta
| step_8_refined_consensus/      barcode*_consensus_edited.fasta
+ reports/                       barcode*_summary_report.html, runtime_versions.json
log/                               barcode*_consensus_edited_diagnostic_log.txt, pipeline_timings.txt
```

Key output files per barcode:

| File | Location | Description |
|------|----------|-------------|
| `*_consensus_edited.fasta` | `results/step_8_refined_consensus/` | Final consensus with resolved ambiguities |
| `*_consensus_edited_diagnostic_log.txt` | `log/` | 27-column TSV with per-site resolution details |
| `*_summary_report.html` | `results/reports/` | Human-readable QC report (includes Environment & Versions card listing all tools in pipeline-execution order) |
| `*_consensus_edited_qc_summary.json` | `results/step_8_refined_consensus/` | Machine-readable QC summary written by the consensus editor |
| `*.bam` + `*.bam.bai` | `results/step_4_mapped/barcodeXX/` | Sorted, indexed alignment |
| `*_variants.vcf.gz` + `.csi` | `results/step_6_called_variants/` | Compressed VCF with all variant calls + index |
| NanoPlot report | `results/step_1_raw_read_qc_nanoplot/barcodeXX/NanoPlot-report.html` | Raw read QC (if enabled) |
| Qualimap report | `results/step_5_alignment_qc_qualimap/barcodeXX/qualimap_output_barcodeXX/qualimapReport.html` | Alignment QC (if enabled) |

## Configuration

### GUI configuration

The Configuration tab provides controls for all parameters with sensible defaults. Toggle switches enable/disable Qualimap, NanoPlot, and parallel barcode processing. A threads spinner sets the parallel slot count (defaults to all CPU cores). Filter mode selects between General and Influenza modes.

### JSON configuration (CLI)

When running the pipeline from the command line, pass a JSON config file. See `example_pipeline_config.json` for the full template. Key fields:

| Field | Default | Description |
|-------|---------|-------------|
| `min_coverage` | 100 | Minimum depth to resolve an ambiguity, counted as bases that actually vote: reads passing the base-quality filter and contributing an A, C, G or T. Reads showing a deletion or a filtered base are excluded, so a 478-read column with 88 called bases is judged on 88. The log prints both numbers. |
| `degeneracy_threshold` | 20 | Minimum allele frequency delta (%) to resolve |
| `ploidy` | 2 | Ploidy passed to `bcftools call --ploidy`. Set to **2** so that sites where two alleles coexist in the sequenced population are called as heterozygous (0/1), producing IUPAC ambiguity codes for DeGenRESOLVE's resolution engine to examine. Ploidy 1 forces homozygous-only calls and suppresses nearly all IUPAC sites (empirically: ploidy 1 -> 4 IUPAC sites; ploidy 2 -> 336 IUPAC sites on the same data). (Danecek P et al. 2021, PMID 33590861) |
| `filter_mode` | `"general"` | `"general"` or `"influenza"` |
| `indel_rules.insertions` | `"equal_or_more"` | How much read support an insertion needs before it may edit the consensus. Evaluated against `IMF`, the fraction of reads supporting the indel, which `bcftools mpileup` computes: `"equal_or_more"` -> IMF >= 0.50, `"more_than"` -> IMF > 0.50, `"custom_percentage"` -> IMF >= N/100. `IMF` is used rather than `QUAL` because it is computed before the caller runs and is therefore identical under `call_mode` `c` and `m`; the same evidence scores about 4.7 QUAL points higher under `-m`, which would make indel strictness depend on a setting that is documented as being about allele multiplicity. |
| `indel_rules.deletions` | `"equal_or_more"` | Same options and the same `IMF` mapping as insertions |
| `variant_call_settings.depth_per_site` | 10000 | Max read depth for variant calling (`-d` flag of `bcftools mpileup`) |
| `variant_call_settings.min_base_quality` | `"auto"` | `-Q` for `bcftools mpileup`. `"auto"` takes the value from the detected basecall tier: **5** for `hac`, `fast` and unknown (paired with `--max-BQ 30`), **1** for `sup` (paired with `--max-BQ 35`), matching bcftools' `ont` and `ont-sup` profiles. An explicit integer overrides the tier and is passed to bcftools unchanged. **The refinement pileup floors at 5 regardless of tier.** bcftools admits low-quality bases but down-weights them through `--max-BQ`; the refinement pileup counts every surviving base at equal weight and has no equivalent, so following `sup`'s `-Q1` would make it more permissive than bcftools rather than equivalent. Weighting those counts instead was rejected: the diagnostic log's A/C/G/T columns must stay countable reads that can be checked against IGV. Measured on hac data, moving this floor between 1 and 5 changed 21 of 598 degeneracy decisions. See `REFERENCES.md`. |
| `variant_call_settings.max_base_quality` | `"auto"` | `--max-BQ` for `bcftools mpileup`, capping ONT's overconfident high-Q values - this is what makes a low `-Q` floor safe. Paired with `min_base_quality` and resolved from the same tier: **30** for `hac`, `fast` and unknown, **35** for `sup`. Omit both keys to take the validated pair; pin both to override. Pinning one and leaving the other on `"auto"` produces a combination no published profile covers, which the pipeline warns about rather than blocking. |
| `force_sup_profile` | false | Applies bcftools' full `ont-sup` flag set regardless of the detected tier. **Not an indel-only switch:** enabling indel calling on non-sup reads requires dropping `-I`, which only happens by swapping in the whole sup profile - and that also moves `-Q` and `--max-BQ`, so SNV calls and degeneracy codes shift with it. Part of the run fingerprint, so toggling it makes a resume abort rather than mix artifacts. The detected tier and the applied tier are both written to the receipt. |
| `variant_call_settings.call_mode` | `"c"` | `"c"` = Consensus Caller (default - biallelic, works correctly with `vcfutils.pl vcf2fq`); `"m"` = Multiallelic Caller (handles genuine tri-allelic sites, uses `bcftools consensus` + coverage mask instead of `vcfutils.pl`) |
| `qualimap.enabled` | true | Run Qualimap alignment QC |
| `nanoplot.enabled` | true | Run NanoPlot raw read QC |
| `advanced_criteria.strand_balance_threshold` | 0.1 | Strand balance below this triggers warning |
| `advanced_criteria.homopolymer_min_length` | 5 | Minimum homopolymer run to flag |
| `advanced_criteria.homopolymer_window` | 5 | Bases on each side to scan for homopolymers |
| `advanced_criteria.read_end_threshold` | 0.8 | Read-end enrichment above this triggers warning |
| `advanced_criteria.strict_strand_bias` | false | Revert resolution at strand-biased sites |
| `advanced_criteria.strict_homopolymer` | false | Revert resolution near homopolymers |
| `advanced_criteria.strict_read_end` | false | Revert resolution at read-end-enriched sites |
| `parallel.enabled` | true | Process barcodes in parallel |
| `parallel.threads` | 1 if the key is absent; the shipped template sets 8 | Number of barcodes to process simultaneously; each barcode's log output is prefixed `[barcodeXX]` so the GUI can track them independently |

### Parameter guidance

The in-app **Bench Scientist Guide** (Help menu) contains detailed guidance on when and how to adjust each parameter, including:

- Platform-specific recommendations (Oxford Nanopore, Illumina, amplicon workflows)
- Conservative vs. permissive preset configurations
- Explanations of what each QC metric measures and how to interpret it

See `readme_bench_scientist.md` for the full guide.

The in-app **Understanding DeGenRESOLVE Interface** (Help menu) is a complete reference for the graphical interface: every tab, every button and icon, the 8-step pipeline tracker, Results viewer cards, and all 27 diagnostic log columns with descriptions. See `DeGenRESOLVE_interface.md` for the source.

## Segmented virus support (influenza mode)

Set `filter_mode` to `"influenza"` (GUI: check "Influenza Filter") to activate segment-aware processing:

1. **Multi-reference input**: Provide all segments (HA subtypes, NA subtypes, PB2, PB1, PA, NP, MP, NS) in a single `reference.fasta`. Reads map against all sequences.
2. **Auto subtype detection**: For each of the 8 canonical segments the sequence with the most mapped reads is selected; duplicate internal segments and non-major H/N subtypes are dropped.
3. **One consensus per segment**: Each segment gets its own consensus sequence in the output FASTA.
4. **Ordered output**: Segments are written in standard order: major H, major N, PB2, PB1, PA, MP, NP, NS.
5. **Missing segment**: A warning is printed and the run continues; output contains however many segments were found.

**Reference FASTA naming convention**: Each sequence ID must begin with the segment name, optionally followed by `_` and an accession number:

| Segment | Example ID |
|---------|-----------|
| HA subtype 5 | `H5_OP023667.1` |
| NA subtype 1 | `N1_OR467201.1` |
| Polymerase basic 2 | `PB2_OP023708.1` |
| Matrix protein | `MP_OP023555.1` |

Bare names (`H5`, `PB2`) also work. Matrix protein synonyms `M`, `M1`, `M2` are accepted.

Override auto-detection with `--major-h H5 --major-n N1` (CLI) if needed.

For detailed Q&A on mixed infections, missing segments, and edge cases, see the Influenza mode section in `readme_bench_scientist.md`.

## Checkpoint system

The pipeline detects completed steps and resumes from where it left off. If interrupted, restart and completed barcode steps are skipped automatically. Use this for both GUI and CLI runs.

**Resuming is refused when the settings changed.** At the start of every run the pipeline
resolves each parameter to its effective value, writes the list to
`results/reports/effective_params.txt`, and compares it against the copy stored in
`results/.run_params` from the run that produced the existing artifacts. If they differ, the
run stops and prints the changed lines:

```
Error: results/ was produced with different settings than this run.
Resuming would mix artifacts built under two configurations. Differences
(< stored in results/, > this run):
  < min_coverage=100
  > min_coverage=150
```

Either restore the previous settings or move/remove `results/` and start clean. Without this
check a stale `results/` would silently contribute artifacts built under one configuration to
a run reporting another.

The comparison uses **effective** values rather than the config file's bytes, so reformatting
the JSON does not trigger it, and a changed default does trigger it even when the file is
untouched. The identity of the reference FASTA is included. Thread counts and the Qualimap
and NanoPlot toggles are deliberately **excluded**: thread count does not affect any pipeline
artifact (see Reproducibility below), and including it would make two machines with different
core counts disagree by construction.

## Reproducibility and provenance

The pipeline is built so that the same input, the same settings and the same tool versions
produce byte-identical results on any machine, and so that a result can be traced back to the
software that produced it. Every run writes the evidence for both claims.

### Per-barcode receipt

`results/reports/<barcode>_receipt.txt` is a single page that answers "are these two runs
comparable, and if not, why not?". It is ordered the way the failure modes occur:

```
DeGenRESOLVE run receipt - barcode01
params md5    : e3444bfcf060e2667ba0b39448ba7dfa
reference md5 : 4ae1d10e109c7ba29d7a0f9d0820229c
config md5    : a3a2ef911715c1287b2168eab311e84c
basecall model: dna_r10.4.1_e8.2_400bps_hac@v4.3.0 (37245/37245 reads)
mpileup       : basecall_tier=hac
mpileup       : mpileup_flags=-B -Q 5 --max-BQ 30 -I
mpileup       : bcftools_version=1.24
resolver -Q   : 5 (floored at 5; counts reads, cannot down-weight)
environment   : c13a6b841038b386cd3648787a572d3f
version check : MATCHES BUNDLE
--- effective parameters ---
  ...
--- scope A checksums (md5, records only) ---
merged.fastq      ...
trimmed.fastq     ...
sam (records)     ...
bam (records)     ...
vcf (records)     ...
draft consensus   ...
edited consensus  ...
diagnostic log    ...
```

Comparing two runs is `diff` on two receipts. Matching checksums mean the runs agree on every
base; a mismatch is diagnosed by the lines above it - different parameters, different
reference, different tool versions, or none of those, in which case something genuinely
unexpected happened.

**Records are checksummed, not whole files.** The BAM and SAM `@PG` headers record the command
line including the thread count, the VCF header records a wall-clock date, and the diagnostic
log's third line is a timestamp. Two runs that agree on every base still differ in those bytes,
so hashing the containers would make every receipt disagree with every other and prove nothing.

### Environment manifest

`results/reports/environment_manifest.txt` records the complete software inventory, not a
curated list of headline tools: every conda package with its version and build string, every
Python distribution, and the host-provided tools the pipeline shells out to (`bash`, `awk`,
`sort`, `md5sum`, `gzip`, `find`, `xargs`, `perl`, `sed`, `grep`). The host tools matter
because they come from the operating system rather than the bundle - they are the part of the
toolchain the offline bundle does *not* pin.

`environment_md5` covers the package sections. `[host]` - kernel, CPU, locale - is recorded but
excluded from that hash, because those differ legitimately between two machines that must
still agree on every base. `pipeline_code_md5` records the identity of the four files that
determine output.

### Tool versions against the bundle

`results/reports/runtime_versions.json` records the versions actually in use and, when the
installation came from an offline bundle, compares them against the manifest the bundle was
built with. The receipt reports the verdict:

- `MATCHES BUNDLE` - runtime tools are the ones the bundle shipped
- `DIFFERS` - listed per tool, with runtime and bundled values
- `no bundle manifest` - not a bundle install (for example a conda environment built by hand)

A tool whose version cannot be determined at both ends is reported as `not_comparable` rather
than as a mismatch: missing information is not evidence of disagreement.

### Reproducible bundle builds

`env.lock` (conda, exact package URLs) and `requirements.lock` (pip) pin the environment.
`create_offline_bundle.sh` builds from them when present and writes them when absent, so the
first build defines the pin and later builds reproduce it. Without this, two builds of the
same script on different days resolve to different tool versions - which is how two bundles
with identical filenames can produce different alignments.

### What has been measured

Thread count does not affect output. On `barcode01`, `porechop --threads`, `minimap2 -t` and
`samtools sort -@` at 1, 4 and 8 threads produce byte-identical records, including when
`samtools sort` is forced to spill to disk with different partition counts (`-m 1M`: 3, 8 and
4 temporary files). Two full runs from a clean `results/` produce identical receipts for both
test barcodes. See `REFERENCES.md` for the full evidence.

## Known limitations

**On `hac` basecalls the consensus contains no indels.** The `ont` profile runs `bcftools
mpileup` with `-I` (skip indel calling), which is bcftools' own recommendation for reads that
are not sup-basecalled. No indel records are produced, so nothing can edit the consensus
length. Deletion evidence is still reported: the resolver sweeps every column and lists those
with a deletion fraction >= 30% under **INDEL EVIDENCE (not acted upon)** in the diagnostic
log, so a real deletion is visible even though it is not applied.

This is deliberate rather than conservative. A raw pileup deletion count cannot distinguish a
real indel from an alignment artifact. On the bundled `barcode01` dataset the three columns
with the highest deletion fractions (45%, 46% and 80%) are indistinguishable on every
pileup-visible feature - deletion percentage, strand balance, gap-length purity, mapping
quality, read-end score, homopolymer length - yet `--indels-cns` accepts one and rejects the
other two. What separates them is realignment, which a pileup has already discarded.

**On `sup` basecalls indels are called and adjudicated.** The `ont-sup` profile enables
`--indels-cns`, bcftools' consensus indel model. Those calls are then judged by the resolver
against three conditions, all of which must hold:

- read depth >= `min_coverage`
- `IMF` satisfies your `indel_rules` setting
- the indel does not break a reading frame

The frame test is the part no upstream tool performs. Indels within 12 nt of each other are
judged **as a group**, not individually, because a -1 nt and a +1 nt four bases apart cancel:
alone each truncates a 560-residue protein to roughly 217, together they leave one amino acid
changed. bcftools evaluates each independently and cannot see the relationship.

Reading frames are found by taking the longest ORF per reference segment at run time - no
annotation file is needed. This recovers all eight canonical influenza proteins exactly
(PB2 759, PB1 757, PA 716, HA 560, NP 498, NA 469, M1 252, NS1 230). It finds the primary
product only: spliced products such as M2, NEP and PB1-F2 are invisible to it, and a
compensating pair spanning more than 12 nt is not detected.

Indels are applied only after every degeneracy is resolved, because resolution maps consensus
position *i* onto reference position *i* and an applied indel breaks that mapping downstream.
On the `m` call path, indels are stripped from the VCF before `bcftools consensus` builds the
draft for the same reason; they remain in the VCF for the resolver to adjudicate.

**The basecall tier is detected, not assumed.** The pipeline reads
`basecall_model_version_id` from the read headers, classifies it as `hac`, `sup`, `fast` or
unknown, and records both the tier and the resolved mpileup flag string in the receipt. Reads
that mix two basecall models abort the run, because the correct flags differ between them.
`fast` and unknown take the `hac` flag set, `fast` with a warning: it is not intended for
consensus refinement.

**The `sup` path is implemented but not validated on this dataset.** All bundled test data is
`hac`-basecalled, so the `ont-sup` flag set and the indel adjudication path have not been
exercised against reads they were designed for. `force_sup_profile` will run that path on hac
reads, but that is a diagnostic, not a validation: the indel model earns its trust by realigning
and was tuned on sup data.

**Thread invariance is measured to 8 cores**, not proven for larger machines. The three
threaded tools agree at 1, 4 and 8; the receipts make the same comparison cheap to repeat on
a bigger machine.

**The multiallelic caller (`-m`) is measured but less exercised.** Against `-c` on the two
test barcodes it changes 0.29% and 1.06% of positions, predominantly by turning definite bases
into ambiguity codes - it is the more conservative of the two. It draws ambiguity from
genotypes rather than from `vcfutils.pl vcf2fq`, so it is a genuinely different call set, not
a variation on the same one.

**Result correctness is not established by any of this.** Everything above shows results are
stable, reproducible and platform-appropriate. Whether the calls are *right* would need a mock
community or Sanger-confirmed sites, which the test data does not contain.

**A regression test suite ships at `app/tests/test_core_functions.py`.** It runs with Python
alone - no pytest, and no pysam, Biopython or PyQt5 needed, because it loads the functions
under test by path:

```bash
cd app && python3 tests/test_core_functions.py     # or: pytest tests/
```

Each test pins the behaviour of a defect that was found and fixed, and names it in the
docstring: homopolymer detection radius and length, major-base fabrication at zero usable
coverage, influenza segment naming, HTML escaping, coverage breadth, residual IUPAC counting,
missing-log handling, and config error handling.

The project's original suite is also present under `app/tests/`: `test_consensus_editor.py`,
`test_indel_adjudication.py`, `test_config.py`, `test_validator.py`, `test_basecall_detection.py`,
`test_html_reporter_versions.py`, `test_parallel_parser.py`, `test_consensus_script.py`,
`test_gui.py`, plus the two shell checks `test_coordinate_guard.sh` and
`test_run_fingerprint.sh`. Those need pytest, which the conda environment provides.

Neither suite executes the pipeline end to end - that still requires the external tools and
real data. Use the demo dataset for that.

## Consensus editor CLI reference

The consensus editor can be used independently on any BAM + consensus FASTA pair, outside the full pipeline.

### Decision engine

```
Degenerate site
  -> usable coverage < min?        -> KEEP (low coverage)
       usable coverage = A+C+G+T surviving the base-quality floor,
       NOT the raw pileup depth. Both are printed in the diagnostic log.
  -> only one base present?        -> RESOLVE to that base
  -> freq_delta >= threshold?      -> RESOLVE to major base
       ... unless the major base is not in the ambiguity code's own
           allele set (e.g. majority C at a site called R = A/G),
           which is a disagreement between the pileup and the variant
           call -> KEEP (allele-set conflict), flagged for review
  -> else                          -> KEEP (ambiguous)
  -> strict flag triggered?        -> revert RESOLVE -> KEEP
```

Indels are **not** decided here. A raw pileup count cannot distinguish a real indel from an
alignment artefact, so indels come from bcftools' `--indels-cns` calls in the VCF and are
adjudicated separately in `_adjudicate_indels()` against IMF, coverage and reading frame.
DEL/INS counts remain in the diagnostic log as evidence only. This requires `--vcf`; without
it no indel is applied and `--indel-*` flags have no effect.

### Core parameters

| Flag | Default | Description |
|------|---------|-------------|
| `--bam` | auto-detect | Path to sorted, indexed BAM |
| `--output` | auto-generate | Output FASTA path |
| `--min-coverage` | 100 | Minimum **usable** depth (quality-filtered A+C+G+T) to consider resolution |
| `--min-percentage-diff` | 20 | Minimum allele frequency delta (%) to resolve |
| `--filter-mode` | `general` | `general` or `influenza` |
| `--diagnostic` | off | Write detailed TSV log |

### Indel parameters

| Flag | Default | Description |
|------|---------|-------------|
| `--vcf` | none | **Required for any indel handling.** Path to the bcftools VCF. Without it `_read_vcf_indels()` returns immediately, no indel is adjudicated or applied, and the three flags below have no effect. |
| `--indel-insertions` | `equal_or_more` | Rule for accepting insertions |
| `--indel-deletions` | `equal_or_more` | Rule for accepting deletions |
| `--indel-custom-percentage` | `50.0` | Threshold for `custom_percentage` rule |
| `--min-base-quality` | `5` | Base-quality floor for the resolver's own pileup. Reads below it are excluded from the usable-coverage count and from the allele vote. |

### QC thresholds

| Flag | Default | Description |
|------|---------|-------------|
| `--strand-balance-threshold` | `0.1` | Strand balance below this triggers warning |
| `--homopolymer-min-length` | `5` | Minimum run length to flag |
| `--homopolymer-window` | `5` | Reference window to scan around each site |
| `--read-end-threshold` | `0.8` | Read-end enrichment above this triggers warning |
| `--read-end-edge-fraction` | `0.1` | Fraction of each read end considered "edge" |

### Strict overrides

| Flag | Default | Description |
|------|---------|-------------|
| `--strict-strand-bias` | off | Strand bias warnings override calls |
| `--strict-homopolymer` | off | Homopolymer warnings override calls |
| `--strict-read-end` | off | Read-end warnings override calls |

### Influenza-specific

| Flag | Description |
|------|-------------|
| `--major-h` | Override major H segment ID (e.g., `H3`) |
| `--major-n` | Override major N segment ID (e.g., `N2`) |

### Programmatic usage

```python
from degenresolve.pipeline.consensus_editor import ConsensusDegeneracyProcessor

processor = ConsensusDegeneracyProcessor(
    consensus_file="barcode65_consensus.fasta",
    reference_file="reference/reference.fasta",
    bam_file="barcode65.bam",
    min_coverage=40,
    min_percentage_diff=20,
    filter_mode="influenza",
    diagnostic_mode=True,
)
processor.process_consensus()
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `No barcode directories found` | Ensure `fastq_pass/` contains subdirectories named `barcode01`, `barcode02`, etc. |
| `No reference FASTA found in ./reference` | Place exactly one `*.fasta`/`*.fa` file in `reference/` inside the data directory. |
| Pipeline hangs at NanoPlot | NanoPlot can be slow on large datasets. Disable it in Configuration if not needed. |
| Qualimap out of memory | Qualimap loads BAM files into memory. For very large BAMs, increase Java heap or disable Qualimap. |
| `seqtk: command not found` | Ensure the conda environment is activated: `conda activate degenresolve`. |
| GUI does not start / blank window | PyQtWebEngine requires a display server. On WSL, install an X server (e.g., VcXsrv) or use WSLg. |
| `ImportError: PyQt5.QtWebEngineWidgets` | Install PyQtWebEngine: `conda install -c conda-forge pyqtwebengine`. |
| Low-coverage positions remain ambiguous | Expected behavior - positions below `min_coverage` are not resolved. Lower the threshold if appropriate for your data. |

## Version

v1.0.0

## Author

**Shoaib Saikat**
- Research Fellow, One Health Laboratory, Infectious Diseases Division, International Centre for Diarrhoeal Disease Research, Bangladesh (icddr,b), Dhaka 1212, Bangladesh
- MS in Biochemistry and Biotechnology, University of Barishal, Barishal-8254, Bangladesh
- Email: saikatshoaib@gmail.com
- LinkedIn: linkedin.com/in/shoaib-saikat

## License

This project is developed for research purposes at icddr,b.
