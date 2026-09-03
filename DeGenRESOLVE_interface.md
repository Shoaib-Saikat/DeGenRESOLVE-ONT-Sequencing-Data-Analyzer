# DeGenRESOLVE - Interface Guide

A complete reference for every element of the graphical interface. For the scientific reasoning behind each parameter, see the **[Bench Scientist Guide](readme_bench_scientist.md)**. For installation and CLI usage, see the **[README](README.md)**.

---

## Table of Contents

1. [Getting around](#1-getting-around)
2. [Menu bar](#2-menu-bar)
3. [Analysis tab](#3-analysis-tab)
4. [Configuration tab](#4-configuration-tab)
5. [Results tab](#5-results-tab)
6. [Logs tab](#6-logs-tab)
7. [Diagnostic log columns](#7-diagnostic-log-columns)

---

## 1. Getting Around

The window is divided into four tabs along the top edge. Click a tab label to switch to it at any time - switching tabs never interrupts a running analysis.

| Tab | When to use it |
|-----|---------------|
| **Analysis** | Start a run, watch live progress |
| **Configuration** | Adjust parameters before running |
| **Results** | Browse finished output, open reports |
| **Logs** | Read the raw pipeline output; save or clear it |

**Typical workflow:** Configure -> Analysis -> (run) -> Results -> (open report or diagnostic log).

---

## 2. Menu Bar

### File

| Item | Keyboard | What it does |
|------|----------|-------------|
| **Open Directory** | - | Same as clicking **Browse** in the Analysis tab - opens a folder picker to select your data directory |
| **Exit** | - | Closes the application |

### Help

| Item | What it opens |
|------|--------------|
| **Bench Scientist Guide** | A scrollable in-app window showing `readme_bench_scientist.md` - explains what each parameter measures, how to interpret QC metrics, and platform-specific recommendations. If markdown-it-py is installed the guide is rendered as HTML; otherwise it displays as plain text. |
| **Understanding DeGenRESOLVE Interface** | This guide rendered in-app - a complete reference for every tab, button, icon, and the 27 diagnostic log columns. Source: `DeGenRESOLVE_interface.md`. |
| **About** | Version string, author, and institution |

---

## 3. Analysis Tab

This tab is your control centre. You select where your data lives, start or stop the pipeline, and watch it execute in real time.

### 3.1 Input Directory

```
[ No directory selected                      ] [ Browse ]
```

**Browse** - opens a system folder picker. Select the directory that contains your `fastq_pass/` and `reference/` folders. You can also use **File -> Open Directory** from the menu.

The selected path is shown in the grey box. It is selectable by mouse (click and drag) so you can copy it.

**Folder structure preview** - a tree below the path box shows the expected layout:

```
your_data_directory/
| fastq_pass/
|   | barcode01/  ->  reads.fastq.gz
|   + barcode02/  ->  reads.fastq.gz
+ reference/
    + reference.fasta
```

This is static - it illustrates the required layout, not the actual contents of your directory. See the [README - Input](README.md#input) section for naming rules.

### 3.2 Analysis Controls

Three buttons control the pipeline:

| Button | Colour | State |
|--------|--------|-------|
| **Start Analysis** | Green | Enabled when a directory is selected and no run is active |
| **Stop Analysis** | Red | Enabled only while a run is in progress; requests a clean stop |
| **Validate Setup** | Blue | Available at any time; checks that all required tools and files exist without starting a run |

**Validate Setup** is useful before your first run. It verifies that `fastq_pass/` exists and contains barcode directories, that `reference/` contains **exactly one** `*.fasta`/`*.fa` file (the name does not matter), and that all required bioinformatics tools (`samtools`, `bcftools`, `minimap2`, etc.) are on PATH **and new enough** - bcftools must be 1.21 or later for the sup profile. A summary dialog lists any problems found.

### 3.3 Analysis Progress

This section shows everything happening during a run.

#### Status ticker

The bar at the top of the progress section (`Ready to start analysis` at rest) slides a new message in from below each time the pipeline advances. During a run you will see entries like:

```
barcode01: Adapter Trimming (Porechop)
barcode02: Mapping to reference (minimap2)
```

Each event is pushed to the **Logs tab** as well, so if a message scrolls past before you read it, check there.

#### Time Elapsed / Completed Barcode

Two pill-shaped counters sit below the status ticker:

| Counter | Meaning |
|---------|---------|
| **Time Elapsed** | Wall-clock time since the current run started (HH:MM:SS). Resets on the next run. |
| **Completed Barcode** | `done/total` - increments as each barcode finishes. With parallel processing enabled you will see this jump. |

#### Pipeline step tracker

Eight coloured circles connected by lines represent the eight processing steps. Above each circle is a small **count badge** that shows how many barcodes are currently at that step. The badge is green when count > 0 and invisible when 0.

| Circle colour | Meaning |
|--------------|---------|
| **Green** (bright) | Step currently executing |
| **Blue** (accent) | Step already completed |
| **Red** | Step was skipped (e.g. NanoPlot disabled) |
| **Dark / border** | Step not yet reached |

The eight steps in order, left to right:

| # | Label | Tool | What happens |
|---|-------|------|-------------|
| 1 | Raw Read QC | NanoPlot | Generates a read-quality HTML report before any trimming. Optional - disable in Configuration if speed is a priority. |
| 2 | Unzipping & Concatenation | cat + gunzip | All `.fastq.gz` files for the barcode are decompressed and merged into one FASTQ. |
| 3 | Adapter Trimming | Porechop | Oxford Nanopore adapter sequences are detected and removed from both ends of each read. |
| 4 | Mapping | minimap2 + samtools | Trimmed reads are aligned to the reference. The SAM output is converted to BAM, sorted, and indexed. |
| 5 | Alignment QC | samtools + Qualimap | Per-site coverage depth is computed. Qualimap (if enabled) produces a full alignment QC report. |
| 6 | Variant Calling | bcftools + vcfutils.pl | A pileup is computed and variants are called using the configured call mode (`-c` consensus caller by default). The VCF is saved to `results/step_6_called_variants/` for downstream inspection in IGV or a spreadsheet. `vcfutils.pl vcf2fq` converts it to a consensus FASTQ with IUPAC ambiguity codes at heterozygous sites; zero-coverage positions are encoded as `N`. |
| 7 | Draft Consensus | seqtk | The consensus FASTQ is converted to a FASTA file used as input for the refinement step. |
| 8 | Refining Consensus | DeGenRESOLVE consensus editor | Ambiguous IUPAC positions are resolved using the decision engine. See the [Bench Scientist Guide](readme_bench_scientist.md#the-decision-rules) for how each position is adjudicated. |

Below the circles, step labels (`Raw Read QC`, `Adapter Trimming`, ...) are separated by `❯` arrows to reinforce left-to-right sequence.

#### Progress bar

A percentage bar fills from left to right across all barcodes. The label inside reads `X%` during the run and `Complete - 100%` or `Failed` at the end.

---

## 4. Configuration Tab

All parameters are pre-set to validated defaults. Change them only when you have a reason to. The [Bench Scientist Guide](readme_bench_scientist.md#understanding-the-parameters) explains the biology behind each setting.

Configuration is saved automatically between sessions. You can also export/import a JSON file for reproducibility.

### 4.1 Basecall Model

Detection runs automatically when you select an input directory, and the result is cached, so
reopening the app on an unchanged directory is instant. **Re-detect** forces a fresh scan.

#### Summary line
Reads every FASTQ header in `fastq_pass` and reports each barcode's `basecall_model_version_id`,
e.g. `100 barcodes: 97 hac, 3 sup`. A full scan rather than a sample, because sampling cannot see
a barcode that mixes basecall models - and that case aborts the run. Warnings appear here for
mixed tiers across barcodes, mixed models within a barcode, and `fast` or unidentifiable reads.

**Details...** opens a per-barcode table: barcode, model, tier, and whether indel calling is on.

#### Force sup variant-calling profile
**Control:** toggle, default off.

Applies bcftools' full `ont-sup` flag set regardless of what the reads say.

**This is not an indel-only switch.** Enabling indel calling on non-sup reads means dropping `-I`,
which only happens by swapping in the whole sup profile - and that profile also changes `-Q` and
`--max-BQ`. SNV calls and degeneracy codes shift with it.

`hac` carries `-I` on bcftools' own recommendation, so on hac data indels are reported as evidence
rather than resolved (see [the two indel sections](#the-two-indel-sections)). Turn this on only
when you intend to apply the sup indel model to reads it was not tuned for. The setting is part of
the run fingerprint, so toggling it makes a resume abort rather than mix artifacts.

---

### 4.2 Coverage and Degeneracy Settings

#### Minimum Coverage Threshold
**Control:** spinner, default 100, range 1-1 000.

The minimum number of reads that must cover a position before the consensus editor will attempt to resolve an ambiguity. Positions with coverage below this value are left as-is (the original ambiguity code is kept).

-> See [Bench Scientist Guide - Understanding the parameters](readme_bench_scientist.md#understanding-the-parameters)

#### Degeneracy Threshold / δ (%)
**Control:** spinner, default 20, range 1-100.

The minimum difference (in percentage points) between the most common and second-most common base at an ambiguous site for the editor to call the dominant base. If the top base is at 55 % and the second is at 45 %, δ = 10 - below a threshold of 20 this position stays ambiguous.

-> See [Bench Scientist Guide - The decision rules](readme_bench_scientist.md#the-decision-rules)

### 4.3 Ploidy Settings

**Control:** spinner, default 2, range 1-10.

Sets the `--ploidy` argument passed to `bcftools call`. Although RNA viruses are biologically haploid, **ploidy 2 is required** for the DeGenRESOLVE workflow. With ploidy 2, `bcftools call` emits heterozygous genotype calls (GT = 0/1) at sites where two alleles coexist in the sequenced population. These heterozygous calls are encoded as IUPAC ambiguity codes by `vcfutils.pl vcf2fq` - and those IUPAC codes are exactly what the resolution engine examines and resolves. With ploidy 1, `bcftools call` forces homozygous-only calls, suppressing nearly all mixed-allele sites and leaving the resolution engine with almost nothing to process (empirically: ploidy 1 -> 4 IUPAC sites vs ploidy 2 -> 336 IUPAC sites on the same data). Do not lower ploidy to 1 unless you specifically want a majority-rules consensus with no ambiguity codes.

-> See [Bench Scientist Guide - Ploidy](readme_bench_scientist.md#ploidy)

### 4.4 Indel Rules

**Control:** dropdown with optional custom percentage spinner.

Determines how much read support an indel needs before it may edit the consensus.

The rule is evaluated against **IMF** - the fraction of reads supporting the indel, computed by
`bcftools mpileup`.

| Option | Meaning |
|--------|---------|
| **Equal to or more than top base** | Accept when IMF >= 0.50 (half the reads or more support the indel) |
| **More than top base** | Accept only when IMF > 0.50 |
| **Custom percentage of top base** | Accept when IMF >= N/100 (enter N in the spinner that appears) |

IMF is used rather than the caller's `QUAL` score because mpileup computes it before the caller
runs, so it is identical whether Call Mode is `c` or `m`. The same evidence scores about 4.7
QUAL points higher under `-m`, which would otherwise make indel strictness depend on a setting
that is about allele multiplicity.

**This rule is one of three conditions.** An indel is applied only when all three hold:

1. read depth >= Min Coverage
2. IMF satisfies this rule
3. the indel does not break a reading frame

Condition 3 has no control here - it is always on. Indels within 12 nt of one another are judged
as a group, so a -1 nt and a +1 nt four bases apart are recognised as cancelling rather than
rejected individually.

**On `hac` basecalls no indel ever reaches this rule.** The mpileup profile for `hac` carries
`-I`, so bcftools produces no indel calls at all; the rule takes effect on `sup` data only.
Deletion evidence is still reported in the diagnostic log under INDEL EVIDENCE (not acted upon).

-> See [Bench Scientist Guide - Insertions and deletions](readme_bench_scientist.md#insertions-and-deletions-indels)

### 4.5 Variant Call Settings

#### Depth per site
**Control:** spinner, default 10 000, range 1-10 000 000.

Maps to the `-d` flag of `bcftools mpileup`. Sets the maximum read depth per position considered during variant calling. Very deep datasets can safely use a higher value; the default is suitable for most amplicon runs.

#### Min base quality / Max base quality / Auto
**Controls:** two spinners plus an **Auto (tier default)** toggle, default on.

`-Q` and `--max-BQ` of `bcftools mpileup`. `-Q` ignores bases below that quality when counting
evidence at a position; `--max-BQ` caps ONT's overconfident high-Q values, which is what makes a
low `-Q` floor safe. They are not removed from your FASTQ or BAM.

**They are a validated pair and move together.** bcftools ships `-Q1 --max-BQ 35` for sup and
`-Q5 --max-BQ 30` for hac. With **Auto** on, both keys are omitted from the config file and
resolved from the detected tier; the spinners display the resolved values. Unchecking Auto pins
both, and any pinned combination is passed to bcftools unchanged.

Pinning while **Force sup variant-calling profile** is on produces a pair no published profile
covers; that is allowed, and warned about in the Basecall Model group.

**The refinement pileup floors at 5 whatever this is set to.** bcftools admits low-quality
bases but down-weights them through `--max-BQ`; the refinement pileup counts every surviving
base at equal weight and has no equivalent, so following `sup`'s `-Q1` would make it more
permissive than bcftools rather than equivalent. The counts are deliberately not weighted, so
that the A/C/G/T columns in the diagnostic log stay countable reads you can check against IGV.

Nanopore quality values at the high end are optimistic, which is what the `--max-BQ` cap is
for - the floor and the cap are tuned together. Raising this setting makes the tool count
fewer, better reads; lowering it admits bases the basecaller itself considered unreliable.

-> See [Bench Scientist Guide - Base quality](readme_bench_scientist.md#base-quality-which-reads-get-a-vote)

#### Call mode
**Control:** dropdown, two options.

| Option | Flag | Description |
|--------|------|-------------|
| **Consensus Caller (`-c`: default)** | `-c` | Standard biallelic caller. Outputs are processed by `vcfutils.pl vcf2fq`, which encodes zero-coverage positions as `N` and pads uncovered positions from position 1, keeping the draft at reference length. This is the default and the path the pipeline's validation covers. Reliable for single-strain amplicon samples and all influenza workflows. |
| **Multiallelic Caller (`-m`: alternative)** | `-m` | Considers all alternate alleles simultaneously - correctly captures genuine tri-allelic sites (Danecek et al. 2021, PMID 33590861). Uses `bcftools consensus --iupac-codes` with a `samtools depth` coverage mask for `N`-masking. Use when you have evidence of co-infection or mixed-strain populations requiring tri-allelic site handling. |

Maps to the `-c` / `-m` flag of `bcftools call`.

The two are not interchangeable variants of one call set: `-c` derives ambiguity codes from
`vcfutils.pl vcf2fq`, `-m` derives them from genotypes. Measured on the reference test data,
`-m` differs from `-c` at 0.29% and 1.06% of positions on two barcodes, predominantly by
marking positions ambiguous that `-c` resolved - it is the more conservative of the two. See
`REFERENCES.md` for the measurement.

### 4.6 Filter Mode

Two mutually exclusive checkboxes:

| Mode | When to use |
|------|------------|
| **General Consensus** (default) | Any organism - no segment filtering applied |
| **Influenza Filter** | Influenza A/B - activates segment-aware processing. Segment names are matched by prefix and both spellings are accepted: the subtyped form (`H5_...`, `N1_...`) and the untyped form (`HA_...`, `NA_...`), plus `PB2`, `PB1`, `PA`, `NP`, `MP`/`M`/`M1`/`M2`, `NS`/`NS1`/`NS2`. The major HA and NA subtypes are auto-detected by mapped read count, and can be overridden with `--major-h` / `--major-n`. |

-> See [Bench Scientist Guide - Influenza mode](readme_bench_scientist.md#influenza-mode) and [README - Segmented virus support](README.md#segmented-virus-support-influenza-mode)

### 4.7 Qualimap BAM QC Settings

#### Enable Qualimap BAM QC
**Control:** toggle switch (on by default).

When enabled, Qualimap generates a per-barcode alignment quality report. Qualimap requires Java and can be slow on large BAM files. Disable it to speed up runs when alignment QC is not needed.

Threading is automatic - Qualimap uses all CPU cores available to it.

Output location: `results/step_5_alignment_qc_qualimap/barcodeXX/qualimap_output_barcodeXX/qualimapReport.html`

### 4.8 NanoPlot Raw Read QC Settings

#### Enable NanoPlot Raw Reads QC
**Control:** toggle switch (on by default).

When enabled, NanoPlot analyses the raw FASTQ reads before trimming and writes an HTML report. This gives you a pre-trim view of read-length distribution, quality scores, and yield.

Output location: `results/step_1_raw_read_qc_nanoplot/barcodeXX/NanoPlot-report.html`

Disable if you do not need raw-read QC or want to reduce runtime.

### 4.9 Parallel Processing

#### Enable parallel barcode processing
**Control:** toggle switch (on by default).

When enabled, multiple barcodes are processed simultaneously. The shell pipeline prefixes each barcode's log output with `[barcodeXX]` so the GUI can track each barcode's progress independently in real time.

#### Threads
**Control:** spinner, default = all detected CPU cores, range 1-CPU count.

Sets how many barcodes run at the same time. The detected core count is shown below the spinner. Setting this to 1 processes barcodes sequentially (equivalent to disabling parallelism).

### 4.10 Advanced Criteria Settings

These parameters control QC warning flags. A warning does not automatically change a call unless the corresponding **Strict** toggle is on.

-> For a full explanation of why these flags exist, see [Bench Scientist Guide - Quality control metrics](readme_bench_scientist.md#quality-control-metrics)

#### Minimum Strand Balance Threshold
**Control:** decimal spinner, default 0.1, range 0-1.

A strand balance of 1.0 means equal forward and reverse coverage. Values below this threshold trigger a `strand_bias(...)` warning. The balance is computed as `min(fwd, rev) / max(fwd, rev)`.

#### Strict: strand bias warnings override base calls
**Control:** toggle, default off.

When on, any position with a `strand_bias(...)` warning is kept as-is rather than resolved, even if the allele frequency delta exceeds the threshold. Use with caution - this can leave many positions unresolved on low-diversity amplicons.

#### Homopolymer Min Length
**Control:** spinner, default 5, range 2-20.

Minimum number of consecutive identical bases to count as a homopolymer run (e.g. `AAAAAAA` = 7). Positions near a run of this length or longer receive an `homopolymer(...)` warning.

#### Homopolymer Window
**Control:** spinner, default 5, range 1-50.

Number of reference bases on each side of a position to search for homopolymer runs.

#### Strict: homopolymer warnings override base calls
**Control:** toggle, default off.

When on, positions with `homopolymer(...)` warnings are not resolved.

#### Maximum Read-End Enrichment Threshold
**Control:** decimal spinner, default 0.8, range 0-1.

A score near 1.0 means reads piled up at a position mostly have their ends near that position - a common nanopore artefact. Positions above this threshold receive a `read_end_enrichment(...)` warning.

#### Read-End Edge Fraction (%)
**Control:** spinner, default 10, range 1-50.

The fraction of each read (from either end) considered the "edge zone". A base at position 5 of a 100-base read with edge fraction 10 % (= 10 bases) counts as a read-end hit.

#### Strict: read-end enrichment warnings override base calls
**Control:** toggle, default off.

When on, positions with `read_end_enrichment(...)` warnings are not resolved.

### 4.11 Configuration Management

Three utility buttons at the bottom of the tab:

| Button | What it does |
|--------|-------------|
| **Save Configuration** | Exports current settings to a JSON file (you choose the path). Use this to record the exact configuration used for a run. |
| **Load Configuration** | Imports a previously saved JSON file and applies all settings. |
| **Reset to Defaults** | Restores all values to the original defaults. |

---

## 5. Results Tab

After a run completes, the Results tab is populated automatically. You can also click the **refresh** button to re-scan the results folder without running the pipeline again (useful after a CLI run).

### 5.1 Sidebar - Sample List

The left panel lists all barcodes for which results were found, numbered in discovery order (e.g. `1) barcode01`). Click a barcode to load its report in the main viewer on the right.

**Refresh button ()** - re-scans the working directory for new or updated results.

### 5.2 Top bar - Quick-access buttons

| Button | Icon / Label | What it opens |
|--------|-------------|--------------|
| **≡** | Three lines | NanoPlot raw-read QC report for the selected barcode (`results/step_1_raw_read_qc_nanoplot/barcodeXX/NanoPlot-report.html`) |
| **≈** | Wave lines | Qualimap alignment QC report for the selected barcode (`qualimapReport.html`) |
| **▓** | Block | Opens the folder containing the BAM file in your system file manager |
| **⚗** | Flask | Opens the refined consensus FASTA directly (`results/step_8_refined_consensus/barcodeXX_consensus_edited.fasta`) |
| **Open Folder** | Text button | Opens the top-level `results/` folder in your file manager |
| **Log** | Text button | Opens the diagnostic TSV log for the selected barcode (see [Section 7](#7-diagnostic-log-columns) for column reference) |
| **Back ›** | Text button | Navigates back one page in the embedded browser (useful after following links inside an HTML report) |

> **Tip:** Hovering over any icon button shows a tooltip with its name.

### 5.3 Main Viewer

The large panel on the right is an embedded web browser (Chromium via QtWebEngine). It displays:

- The **per-barcode HTML report** when a barcode is selected from the sidebar. The report contains eleven cards:

  | Card | Contents |
  |------|---------|
  | Parameters | The configuration used for this barcode's run |
  | Input Files | Detected FASTQ files and their total size |
  | NanoPlot QC | Inline link to the NanoPlot report (or "not found" if disabled) |
  | Qualimap | Inline link to the Qualimap report (or "not found" if disabled) |
  | Segment Selection | (Influenza mode only) Which HA/NA subtypes were selected |
  | Coverage | Per-segment mean depth, min, max |
  | Degeneracy | Count of ambiguous sites processed, resolved, and kept |
  | Indels | Insertion and deletion resolution summary |
  | Consensus | Final consensus sequence length and ambiguity count |
  | Output Files | Clickable links to every output file with file size |
  | Environment & Versions | DeGenRESOLVE v1.0.0 and all tool versions in pipeline-execution order |

- A **run summary HTML** if no barcode is selected (overview of all barcodes).

- A **"not found"** message if results for the selected barcode do not exist on disk.

Links inside reports (e.g. NanoPlot -> qualimapReport -> output files) are followed within the same viewer. Use **Back ›** to return.

---

## 6. Logs Tab

The Logs tab shows the raw stdout of the pipeline - every line printed by `main_with_config.sh` and the sub-scripts appears here in real time.

### Reading log lines

Each line is prefixed by the source:

| Prefix | Source |
|--------|--------|
| `[MAIN]` | Main shell script startup / validation |
| `[PIPELINE]` | Per-line output from the pipeline (includes `[barcodeXX]` prefix for parallel runs) |
| `[CONFIG]` | Configuration file written event |
| `[VALIDATION]` | Input structure check |
| `[ERROR]` | Python-level exception |

During a parallel run you will see interleaved lines from multiple barcodes:

```
[PIPELINE] [barcode01] === Step 3: Mapping to reference
[PIPELINE] [barcode02] === Step 2: Porechop trimming
[PIPELINE] [barcode01] === Step 4.5: Qualimap alignment QC
```

### Controls

| Button | What it does |
|--------|-------------|
| **Clear Logs** | Removes all text from the display. A `Logs cleared` entry is added immediately after so the display is never completely blank. The underlying run is unaffected. |
| **Save Logs** | Opens a file dialog. Saves the full log content as a `.txt` file. The default filename is `ont_analysis_log_YYYYMMDD_HHMMSS.txt`. |

> **Tip:** If the pipeline appears to hang, switch to the Logs tab to see the last line printed. A stalled NanoPlot or Qualimap job will be visible here.

---

## 7. Diagnostic Log Columns

The diagnostic log (`log/barcodeXX_consensus_edited_diagnostic_log.txt`) is a tab-separated file with one row per ambiguous site processed. Open it with **Log** in the Results tab top bar, or directly in a spreadsheet.

The file has a header line, a separator line of dashes, the data rows, and a summary statistics block at the end.

| Column | Type | Description |
|--------|------|-------------|
| **Segment** | string | Sequence name from the consensus FASTA (e.g. `HA`, `barcode01_consensus`). In influenza mode this is the segment ID. |
| **Cons_Pos** | integer | 1-based position in the consensus sequence file |
| **Genomic_Pos** | integer | 1-based position in the aligned reference. `N/A` if the site did not align. |
| **Original** | char | The IUPAC ambiguity code as it appeared in the input consensus. All 11 standard codes are processed: 2-base (R, Y, W, S, M, K), 3-base (B, D, H, V), and N (4-base). |
| **New** | char | The base written to the output FASTA. Same as Original if KEEP; the resolved base if RESOLVE. |
| **Status** | string | `CHANGED` if Original ≠ New; `UNCHANGED` otherwise |
| **Coverage** | integer | pysam's raw column depth (`pileup_column.n`). **Not** base-quality filtered and not equal to `A+C+G+T+INS+DEL` (a read carrying an insertion is counted in both its base column and INS). Use **Usable_Coverage** for the number the min_coverage gate actually judges. |
| **Usable_Coverage** | integer | Base-quality-filtered depth: the A+C+G+T that survived the `-Q` floor. **This is the number compared against `--min-coverage`**, and the one to quote as the depth behind a call. It can be several-fold lower than Coverage. |
| **A** | integer | Read count supporting adenine |
| **C** | integer | Read count supporting cytosine |
| **G** | integer | Read count supporting guanine |
| **T** | integer | Read count supporting thymine |
| **INS** | integer | Read count supporting an insertion at this position |
| **DEL** | integer | Read count supporting a deletion at this position |
| **Major_Base** | char | The single base with the highest read count at this position |
| **Second_Base** | char | The base with the second-highest read count |
| **Major_AF%** | decimal | Allele frequency of Major_Base as a percentage of **quality-filtered A+C+G+T only** (`standard_bases_total`). Deletions, insertions and quality-failed reads are excluded from the denominator, so this is not a percentage of the Coverage column. |
| **Second_AF%** | decimal | Allele frequency of Second_Base, over the same quality-filtered A+C+G+T denominator as Major_AF%. |
| **Delta%** | decimal | `Major_AF% - Second_AF%`. Must be **greater than or equal to** the Degeneracy Threshold for a RESOLVE call (the code tests `>=`, so a delta exactly equal to the threshold resolves). -> [Bench Scientist Guide - The decision rules](readme_bench_scientist.md#the-decision-rules) |
| **Fwd** | integer | Count of reads aligned in the forward direction at this position |
| **Rev** | integer | Count of reads aligned in the reverse direction |
| **Strand_Balance** | decimal | `min(fwd, rev) / max(fwd, rev)` **for the major base only**, not for the Fwd/Rev columns (which are totals over all four bases and will not reproduce this number). Range 0-1; 1.0 = perfect balance. Below Strand Balance Threshold -> `strand_bias(...)` warning. -> [Bench Scientist Guide - Strand balance](readme_bench_scientist.md#strand-balance) |
| **HP_Len** | integer | Length of the longest homopolymer run found near this position (within Homopolymer Window). 0 = none found. |
| **HP_Dist** | integer | Distance in bases from this position to the nearest homopolymer run. 0 = position is inside the run. |
| **ReadEnd_Score** | decimal | Fraction of reads at this position where the base falls in the read-end edge zone. Range 0-1. Above Read-End Threshold -> `read_end_enrichment(...)` warning. -> [Bench Scientist Guide - Read-end enrichment](readme_bench_scientist.md#read-end-enrichment) |
| **Warnings** | string | Semicolon-separated list of active warning flags, each carrying its measured value: `strand_bias(<balance>)`, `homopolymer(len=<n>,dist=<d>)`, `read_end_enrichment(<score>)`. `-` if none. |
| **Decision** | string | `RESOLVE` (ambiguity was resolved to a single base) or `KEEP` (ambiguity retained). Indels are not decided in this table - see the INDEL DECISIONS section below. |
| **Reason** | string | Human-readable explanation of why this decision was made (e.g. `"Delta% 45.2 >= threshold 20.0"`, `"Coverage 12 below minimum 40"`, `"Strict strand bias: reverting RESOLVE to KEEP"`). |

### The two indel sections

After the per-site table the log carries two sections that concern indels. Neither has a row in
the table above, because indels are not degeneracies and are not decided per ambiguous site.

**INDEL DECISIONS (bcftools calls, adjudicated here)**

One row per indel that `bcftools` called, with the verdict and the reason.

| Column | Meaning |
|--------|---------|
| **Genomic_Pos** | Left-aligned position of the indel, as bcftools reports it |
| **Change** | `REF->ALT`, e.g. `GAA->GA` for a 1 nt deletion |
| **Net_nt** | Length change: negative for a deletion, positive for an insertion |
| **IMF** | Fraction of reads supporting the indel, from mpileup |
| **IDV** | Number of reads supporting the indel |
| **DP** | Read depth at the position |
| **Verdict** | `ACCEPT` (applied to the consensus) or `REJECT` |
| **Reason** | Which condition decided it - coverage, the IMF rule, or the reading frame |

A `Reason` of the form `group of 2 at 674-678 nets +0 nt, frame preserved` means two indels
were judged together: individually each would break the frame, together they cancel.

On a `hac` basecall this section reads *"bcftools called no indels"*, which is expected - the
`hac` mpileup profile carries `-I`.

**INDEL EVIDENCE (not acted upon)**

Columns where at least 30% of reads show a deletion and coverage meets Min Coverage, but no
indel was applied. On `hac` data that is every such column, because no indel calling ran at all.

This section exists so that a real deletion is never silently invisible. It is a report, not a
resolution: a deletion count on its own cannot distinguish a genuine indel from an alignment
artifact, so the sites listed here are the ones worth opening in IGV, or re-basecalling at
`sup` so that bcftools can model them properly.

### Reading the summary block

At the end of the file, after a `=` separator line, a plain-text summary lists:

- Total degeneracies processed
- Number resolved to a single base
- Number kept ambiguous
- Counts of each warning type triggered

This summary is useful for a quick sanity check: if hundreds of sites triggered `strand_bias(...)`, your library may have a strand asymmetry issue worth investigating before submission.

---

*For parameter guidance, see the [Bench Scientist Guide](readme_bench_scientist.md). For installation, CLI usage, and output structure, see the [README](README.md).*
