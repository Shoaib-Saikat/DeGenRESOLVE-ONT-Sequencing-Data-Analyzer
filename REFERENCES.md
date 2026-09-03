# DeGenRESOLVE - Parameter References

Literature supporting the default parameter values used in DeGenRESOLVE.
Retrieved from PubMed (E-utilities API), June 2026.

---

## Minimum Coverage Threshold (default: 100)

**Bull RA et al. (2020)**
Analytical validity of nanopore sequencing for rapid SARS-CoV-2 genome analysis.
*Nature Communications* 11(1):6272.
PMID: 33298935 | doi: 10.1038/s41467-020-20075-6

> "Highly accurate consensus-level sequence determination was achieved, with SNVs
> detected at >99% sensitivity and >99% precision above a minimum ~60-fold
> coverage depth."

Establishes ~60× as the empirical lower bound for accurate ONT viral consensus.
DeGenRESOLVE's default of 100 is deliberately conservative. The CLI fallback of
40 reflects lower-depth amplicon scenarios where sequencing yield is limited.

---

## Degeneracy Threshold δ (default: 20%)

**Roder AE et al. (2023)**
Optimized quantification of intra-host viral diversity in SARS-CoV-2 and
influenza virus sequence data.
*mBio* 14(4):e0104623.
PMID: 37389439 | doi: 10.1128/mbio.01046-23

> "Both allele frequency and coverage thresholds impact both false discovery and
> false-negative rates ... using more stringent cutoffs is recommended when
> replicates are not available."

Directly validates the use of allele frequency delta thresholds in viral
sequencing. A 20% minimum delta between the dominant and second allele separates
genuine quasi-species ambiguity from sequencing noise and PCR artefacts.

---

## Variant Caller: Consensus (-c, default) vs Multiallelic (-m, alternative)

**Li H (2011)**
A statistical framework for SNP calling, mutation discovery, association mapping
and population genetical parameter estimation from sequencing data.
*Bioinformatics* 27(21):2987-2993.
PMID: 21903627 | doi: 10.1093/bioinformatics/btr509

> Original statistical model underlying both `bcftools call -c` and `-m`.

**Danecek P et al. (2021)**
Twelve years of SAMtools and BCFtools.
*GigaScience* 10(2):giab008.
PMID: 33590861 | doi: 10.1093/gigascience/giab008

> Explicitly recommends `bcftools call -m` (multiallelic) over `-c` (consensus
> caller) for all new analyses. The `-c` flag is retained for backward
> compatibility only.

DeGenRESOLVE defaults to `-c` (consensus caller) because the `-c` pathway uses
`vcfutils.pl vcf2fq` for consensus generation, which correctly N-masks
zero-coverage positions rather than silently backfilling them from the reference
(the behaviour of `bcftools consensus`). See the vcfutils.pl vs bcftools consensus
section below for the empirical comparison. The `-m` (multiallelic) caller is
available as an alternative for samples where genuine tri-allelic co-circulation
is expected.

**Measured difference.** On the two test barcodes, `-m` differs from `-c` at 39 of 13,317
positions (0.29%) for `barcode01` and 120 of 11,306 (1.06%) for `barcode09`. The difference is
predominantly one-directional: 34 and 85 of those positions change from a definite base to an
ambiguity code, against 4 and 29 in the opposite direction. `-m` is therefore the more
conservative caller on this data, resolving fewer sites and leaving more marked ambiguous. The
two are not variations on one call set - `-m` draws ambiguity from genotypes via
`bcftools consensus --iupac-codes`, while `-c` draws it from `vcfutils.pl vcf2fq`.

---

## Ploidy = 2 (diploid calling for IUPAC generation)

**Li H (2011)** - PMID: 21903627 (see above)
**Danecek P et al. (2021)** - PMID: 33590861 (see above)

The `--ploidy` flag of `bcftools call` sets the assumed genome copy number for
genotype calling. Although RNA viruses are biologically haploid within a single
virion, setting ploidy to **2** is required so that sites where two alleles
coexist in the sequenced population are called as heterozygous (GT = 0/1).
These heterozygous calls are encoded as IUPAC ambiguity codes by
`vcfutils.pl vcf2fq`, and it is these IUPAC codes that DeGenRESOLVE's
resolution engine examines and resolves.

Empirical validation (same barcode, same data):

| Ploidy | Call mode | IUPAC sites in draft consensus |
|--------|-----------|-------------------------------|
| 1 | `-c` | 4 |
| 2 | `-c` | 336 |
| 2 | `-m` | 342-354 |

With ploidy 1, `bcftools call` forces homozygous-only genotypes, suppressing
nearly all heterozygous (mixed-allele) calls and leaving almost nothing for
DeGenRESOLVE to process. Ploidy 2 is the correct setting for ONT amplicon
workflows where the goal is to detect and characterise within-sample sequence
diversity.

---

## Depth per Site = 10,000 (bcftools mpileup -d)

**Danecek P et al. (2021)** - PMID: 33590861 (see above)

The `-d` flag of `bcftools mpileup` caps the read depth considered per position.
For deep amplicon sequencing (common in ONT runs targeting specific viral genes),
coverage can exceed 10,000× at peak positions. The default of 10,000 ensures
variant calling is not truncated at highly covered amplicon centres while
remaining computationally tractable.

---

## mpileup Flag Set: `-B -Q 5 --max-BQ 30 -I` (bcftools `ont` profile)

**Danecek P et al. (2021)** - PMID: 33590861 (see above)

`bcftools mpileup` ships platform profiles selectable with `-X`. Listing them with
`bcftools mpileup -X list` gives, for Oxford Nanopore:

```
ont
    -B -Q5 --max-BQ 30 -I
```

DeGenRESOLVE applies these four flags **written out explicitly** rather than passing
`-X ont`. The reason is reproducibility: profile *definitions* are part of bcftools and can
change between releases, so naming a profile makes the analysis depend on a bcftools version
that no configuration file records. Writing the flags out pins the behaviour in this
repository, where it is visible and version-controlled. (The definition above was verified
identical in bcftools 1.23.1 and 1.24.)

What each flag does, and why it matters for ONT amplicon data:

- **`-B`** disables Base Alignment Quality. BAQ is a realignment-based model developed for
  Illumina data; on indel-dense ONT alignments it depresses base qualities around exactly the
  positions of interest.
- **`-Q 5`** sets the minimum base quality. bcftools' own default is 13, which on this data
  discards roughly a quarter of all bases - including bases the basecaller itself accepted.
- **`--max-BQ 30`** caps reported base qualities. ONT quality values above Q30 are optimistic,
  and this cap is what makes the permissive `-Q 5` floor safe. The two are tuned together and
  should be changed together.
- **`-I`** skips indel calling. This is bcftools' recommendation for ONT reads that are not
  sup-basecalled; the separate `ont-sup` profile, intended for super-accuracy basecalls,
  enables indel calling through a different model (`--indels-cns`). It is also a structural
  requirement here - see the coordinate mapping note below.

### Why `-I` is required by the consensus editor, not merely recommended

`consensus_editor.py` maps consensus position *i* onto reference position *i* directly. That
mapping is valid because the draft consensus is always reference-length: on the `-c` path,
`vcfutils.pl vcf2fq` pads uncovered positions with `N` starting from position 1, so gaps in
coverage shorten the sequence only at the 3' end and never shift the positions that are
present. Applying indels would break this - a one-base insertion would displace every
subsequent position, and each degeneracy after it would be resolved against the wrong
reference column, silently.

On the `-m` path, `bcftools consensus` *does* apply indels, so the pipeline verifies each
draft segment against the reference length and aborts if they disagree. With `-I` in force
that check cannot fire; it exists to catch the flag being removed.

---

## Minimum Base Quality: tier-dependent for bcftools, floored at 5 for the resolver

**The two stages no longer use the same number**, and the difference is deliberate.

`bcftools mpileup` is given the base-quality pair that bcftools itself ships for the detected
basecall tier: `-Q 1 / --max-BQ 35` for **sup**, `-Q 5 / --max-BQ 30` for **hac**, fast and
unknown (`_clean_master_cmd_with_config.sh`, the `case "$BASECALL_TIER"` block).

The resolver's own pileup is floored at 5 on every tier (`RESOLVER_MIN_BQ`). It is raised if
the user pins a higher `min_base_quality`, but never lowered below 5. The reason is that
bcftools admits low-quality bases and then **down-weights** them through `--max-BQ`, whereas
the resolver counts every surviving base at equal weight and has no equivalent mechanism.
Following sup's `-Q 1` would therefore make the resolver strictly more permissive than the
variant caller, not equivalent to it. Measured on hac data, moving this floor between 1 and 5
changed 21 of 598 degeneracy decisions.

So on **hac** data the two stages do judge the same reads (both at Q>=5); on **sup** data
bcftools sees more reads than the resolver does, by design.

This matters because of what the resolver does. A degenerate site is resolved when the top and
second base differ by at least the degeneracy threshold (default 20%). If the resolver counted
bases that the variant caller had already rejected, a minor allele inflated by basecaller
noise could push a site across that threshold - and on ONT data those low-quality bases
cluster in homopolymers, the very positions the resolver already flags as suspect.

The pileup depth limit for the resolver is set to 1,000,000 rather than pysam's default of
8,000, so that deep amplicon positions are counted in full. Truncation would both lose evidence
and make the counts depend on read order.

---

---

## Strand Balance Threshold (default: 0.1, flag `--strand-balance-threshold`)

**Operational default, not a literature value.** No published threshold applies to this
statistic. The filter computes `min(forward, reverse) / max(forward, reverse)` for the major
base at a site - a plain ratio, not the Fisher's exact test or GATK `FS` score the variant-
calling literature uses for strand bias. A citation for those methods would not support this
number and is deliberately not given.

The artefact class is real and well described: a variant seen almost exclusively on one strand
is a classic false-positive signature, which is why BCFtools reports per-sample strand counts
and why callers filter on them (Li H, 2011; Danecek P et al., 2021, both cited above).
DeGenRESOLVE flags rather than filters: a low ratio raises a warning, and only reverts a call
when `--strict-strand-bias` is enabled.

**Measured on the 100-barcode influenza dataset.** Across the 985 sites where the statistic is
defined - usable depth >= 100 and a major base present - the distribution was:

| Statistic | Value |
|---|---|
| Median | 0.881 |
| 10th percentile | 0.681 |
| 1st percentile | 0.446 |
| Minimum | 0.335 |
| Sites below 0.30 | 0 |
| Sites below 0.10 (the default) | 0 |

The default therefore did not fire once on this dataset. It is a permissive safety net for
grossly one-sided evidence, not a routine filter, and a run reporting zero strand-bias flags is
the expected outcome for amplicon data of this quality rather than a sign the check is inactive.
Laboratories with more variable strand representation may wish to raise it toward 0.3-0.5, where
1.3% of these sites would have been flagged.

---

## Read-End Enrichment (default: 0.8, edge fraction 0.1)

**Vijaya Satya R, Zavaljevski N, Reifman J (2014)**
Edge effects in calling variants from targeted amplicon sequencing.
*BMC Genomics* 15:1073.
doi: 10.1186/1471-2164-15-1073

Directly applicable: DeGenRESOLVE processes amplicon data, and this paper characterises the
specific failure mode the filter targets. Reads from amplicons have fixed start positions at the
amplicon boundaries, so a variant near those boundaries causes correlated misalignment across
many reads and produces false-positive calls. The authors note that positional-bias filtering is
applied when an overwhelming majority of alternative-allele reads carry the allele near a read
end.

**The threshold value itself is an operational default.** The paper does not prescribe 0.8 for
this statistic. It was chosen from the observed distribution: across the same 985 well-covered
sites, the read-end score had a median of 0.033 and a 95th percentile of 0.798, so 0.8 flags
approximately the top 5% of sites - an outlier cut, not an accept/reject boundary. 4.98% of
sites exceeded it.

The edge fraction of 0.1 defines the "read end" zone as the first and last 10% of each read.
It is deliberately conservative for amplicon data, where the true ends of every read coincide
with the primer sites and a wider zone would flag most of the amplicon.

Note that the score is computed over reads carrying the minority allele only, not over all reads
spanning the position; a site with fewer than three such reads returns 0 rather than a score,
because read placement cannot be assessed from so little evidence.

---

## Indel Rules and Custom Percentage (default: `equal_or_more`, 50%)

**No citation, and none is appropriate.** These parameters are retained for backward
compatibility with configuration files written before v1.0.0. They selected indels from raw
pileup insertion/deletion frequencies, and that rule has been withdrawn - see "Refined Consensus
Generation" in the manuscript Methods for the reasoning. Indels are now taken from the BCFtools
VCF, where they are called from realigned evidence, and adjudicated on indel-supporting fraction,
depth and net reading-frame change.

The parameters are documented here rather than removed so that an older configuration file still
loads, but they no longer influence which indels are applied.

## Determinism: what has been measured

These are the measurements behind the reproducibility claims in `README.md`. All were taken on
the two test barcodes (`barcode01`, 37,245 reads; `barcode09`, 19,473 reads).

**Thread count does not change output.** `porechop --threads`, `minimap2 -t` and
`samtools sort -@` were each run at 1, 4 and 8 threads on identical input. All three produced
byte-identical output at every thread count (SAM and BAM compared as records, since the `@PG`
header records the thread count itself).

**Nor does sort partitioning.** `samtools sort` was forced to spill to disk with `-m 1M`,
producing different numbers of temporary files at each thread count (3 files/1 in-memory block
at `-@ 1`, 8/4 at `-@ 4`, 4/8 at `-@ 8`). All three matched each other and matched the
in-memory sort exactly, so the merge is stable regardless of how the data is partitioned.

**Input file order is fixed.** Merging the per-barcode `fastq.gz` chunks uses
`LC_ALL=C sort -z`. Without the explicit `C` locale the order would depend on the machine's
collation settings; without sorting at all it would depend on filesystem directory order.
Porechop decides which adapter sets are present by inspecting the first reads it sees, so
merge order affects trimming, which affects everything downstream.

**Tie-breaking is deterministic.** Where two bases occur exactly the same number of times at a
site, the resolver breaks the tie alphabetically rather than by whichever read the aligner
happened to emit first. Such a site remains ambiguous either way (a zero difference cannot
exceed the degeneracy threshold), but the reported top base and the strand-balance metric
computed from it would otherwise vary between machines.

**Two identical runs agree.** Two full runs from a clean `results/` produced identical
checksums for all eight recorded artifacts, on both barcodes.

**A toolchain update did not change results.** Rebuilding the environment from samtools/
bcftools/htslib 1.23.1 to 1.24 and minimap2 2.30 to 2.31 left all eight artifacts identical on
both barcodes.

---

## Read Mapping: minimap2

**Li H (2018)**
Minimap2: pairwise alignment for nucleotide sequences.
*Bioinformatics* 34(18):3094-3100.
PMID: 29750242 | doi: 10.1093/bioinformatics/bty191

> "Minimap2 is a general-purpose alignment program ... works with ... ≥1 kb genomic
> reads at error rate ~15%."

The standard long-read aligner for ONT data. Handles the elevated per-read error
rate (~5-15%) of nanopore sequencing without requiring re-training or
platform-specific parameters.

---

## Adapter Trimming: Porechop

**Note on which tool this bundle actually runs:** the pipeline invokes `porechop`
**0.2.4** (Wick RR, unpublished; https://github.com/rrwick/Porechop), *not* Porechop_ABI.
Porechop_ABI is a separate later tool with a different adapter-inference method, and the
indented text below is a paraphrase of its rationale rather than a quotation from it.
The citation is retained for the adapter-trimming rationale only.

**Bonenfant Q et al. (2022)**
Porechop_ABI: discovering unknown adapters in Oxford Nanopore Technology
sequencing reads for downstream trimming.
*Bioinformatics Advances* 3(1):vbac085.
PMID: 36698762 | doi: 10.1093/bioadv/vbac085

> "Adapter sequences should be removed before downstream analyses ... Porechop is
> the established standard for ONT adapter detection and trimming."

Establishes Porechop as the canonical ONT adapter trimmer and validates the
necessity of the trimming step for accurate downstream consensus generation.

---

## Homopolymer Error Flagging

**Liu-Wei W et al. (2024)**
Sequencing accuracy and systematic errors of nanopore direct RNA sequencing.
*BMC Genomics* 25(1):528.
PMID: 38807060 | doi: 10.1186/s12864-024-10440-w

Characterises systematic nanopore sequencing errors, with homopolymer runs being
a primary source of false insertion/deletion calls. DeGenRESOLVE's homopolymer
proximity flag warns when an ambiguous site falls near a run of ≥5 identical
bases (default window: 5 bases each side), reducing the risk of accepting
homopolymer-driven artefacts as real variants.

---

## Influenza Amplicon ONT Sequencing Context

**King J et al. (2020)**
Rapid multiplex MinION nanopore sequencing workflow for Influenza A viruses.
*BMC Infectious Diseases* 20(1):648.
PMID: 32883215 | doi: 10.1186/s12879-020-05367-y

> MinION multiplexed influenza A whole-genome sequencing; >99.9% identity
> between MinION and IonTorrent consensus sequences.

**Croville G et al. (2024)**
An amplicon-based nanopore sequencing workflow for rapid tracking of avian
influenza outbreaks, France, 2020-2022.
*Frontiers in Cellular and Infection Microbiology* 14:1257586.
PMID: 38318163 | doi: 10.3389/fcimb.2024.1257586

> Validates amplicon-based MinION sequencing for field H5 HPAIV surveillance
> with real-time consensus generation and phylogenetic analysis.

These two papers establish the methodological precedent for the influenza filter
mode (segment-aware processing, ordered output, subtype auto-detection) and
confirm the applicability of ONT amplicon sequencing to influenza consensus
determination.

---

## vcfutils.pl vs bcftools consensus (comparison experiment)

**Danecek P et al. (2021)** - PMID: 33590861 (see above)

An internal comparison run on PRJNA1366758 (PR8 H1N1 DVG amplicon data,
barcode01, 5,000 MinION reads) showed:

| Method | N bases | ACGT bases | Notes |
|--------|---------|------------|-------|
| vcfutils.pl vcf2fq | 1,953 | 388 | Honest N-masking at zero-coverage sites |
| bcftools consensus --iupac-codes | 0 | 2,341 | Silently fills zero-coverage sites with reference sequence |

`vcfutils.pl` is retained as the consensus generator because it masks
low-coverage positions as N rather than backfilling from the reference,
producing scientifically accurate consensus sequences. See
the comparison methodology and results described in this section. (Note: a `comparison_run/COMPARISON_REPORT.txt` file is referenced in some drafts but is not part of this bundle; the figures quoted here are the record.)

---

## Coverage and Mapping Quality Control for Organism/Strain Confirmation

**García-Alcalde F et al. (2012)**
Qualimap: evaluating next-generation sequencing alignment data.
*Bioinformatics* 28(20):2678-2679.
PMID: 22914218 | doi: 10.1093/bioinformatics/bts503

> "SAM/BAM files usually contain information from tens to hundreds of millions of reads. Often, the sequencing technology, protocol and/or the selected mapping algorithm introduce some unwanted biases in these data."

The primary tool DeGenRESOLVE uses for BAM-level quality assessment. Provides mean coverage depth, percentage of mapped reads, and genome coverage breadth - the three metrics required to confirm correct organism mapping before consensus calling.

---

**Okonechnikov K, Conesa A, García-Alcalde F (2016)**
Qualimap 2: advanced multi-sample quality control for high-throughput sequencing data.
*Bioinformatics* 32(2):292-294.
PMID: 26428292 | doi: 10.1093/bioinformatics/btv566

> "Detection of random errors and systematic biases is a crucial step of a robust pipeline for processing high-throughput sequencing (HTS) data."

Extends Qualimap to multi-sample comparisons. Cited for the BAM QC methodology and coverage statistics used to evaluate alignment quality across barcodes.

---

**Raven KE et al. (2020)**
Defining metrics for whole-genome sequence analysis of MRSA in clinical practice.
*Microbial Genomics* 6(4):e000354.
PMID: 32228804 | doi: 10.1099/mgen.0.000354

> "At least 80% of the CC22 mapping reference genome covered with at least 20× depth."

Establishes the clinical WGS standard of ≥ 80% breadth at ≥ 20× depth for organism confirmation and strain typing. This is the combined threshold DeGenRESOLVE documents as the minimum acceptable for reliable consensus.

---

**Desai A et al. (2013)**
Identification of optimum sequencing depth especially for de novo genome assembly of small genomes using next generation sequencing data.
*PLoS One* 8(4):e60204.
PMID: 23593174 | doi: 10.1371/journal.pone.0060204

> "50× or lower depth of coverage provides opportunity for sequencing multiple samples per run thereby further reducing the cost of whole genome sequencing."

Establishes 50× as the optimum depth for bacterial and small-genome assembly. Depths above 100× show no additional assembly benefit. Supports the recommendation of ≥ 50× as a practical target for ONT amplicon workflows.

---

**Wingett SW, Andrews S (2018)**
FastQ Screen: A tool for multi-genome mapping and quality control.
*F1000Research* 7:1338.
PMID: 30254741 | doi: 10.12688/f1000research.15931.2

> "Typically, the amount of reads that correctly maps to the specific reference genome ranges between 70% and 90%."

Establishes 70-90% as the expected mapping rate for a correctly matched reference genome. Mapping rates below 70% indicate reference mismatch or contamination and should trigger reference re-evaluation before proceeding with consensus generation.

---

**Petrackova A et al. (2019)**
Standardization of Sequencing Coverage Depth in NGS: Recommendation for Detection of Clonal and Subclonal Mutations in Cancer Diagnostics.
*Frontiers in Oncology* 9:851.
PMID: 31552176 | doi: 10.3389/fonc.2019.00851

> "Minimum coverage depth of 1,650 with a threshold of ≥ 30 mutated reads for detecting variants at ≥ 3% variant allele frequency."

Provides a quantitative framework linking coverage depth to variant allele frequency sensitivity. The coverage-sensitivity relationship is platform-agnostic. Informs the 20× minimum used in DeGenRESOLVE's general filter guidance for reliable SNP and variant calling.

---

*All PMIDs verified via NCBI PubMed E-utilities API.*
