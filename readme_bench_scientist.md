# DeGenRESOLVE - A Bench Scientist's Guide

This guide explains what DeGenRESOLVE does, why it does it, and how to interpret the results. It is written for scientists who work with sequencing data but may not have a bioinformatics background. No programming knowledge is required.

---

## Table of contents

1. [The problem this tool solves](#the-problem-this-tool-solves)
2. [Sequencing fundamentals](#sequencing-fundamentals)
3. [IUPAC degeneracy codes](#iupac-degeneracy-codes)
4. [How the tool examines each position](#how-the-tool-examines-each-position)
5. [The decision rules](#the-decision-rules)
6. [Quality control metrics](#quality-control-metrics)
   - [Strand balance](#strand-balance)
   - [Homopolymer proximity](#homopolymer-proximity)
   - [Read-end enrichment](#read-end-enrichment)
7. [Strict mode: when warnings override decisions](#strict-mode-when-warnings-override-decisions)
8. [Insertions and deletions (indels)](#insertions-and-deletions-indels)
9. [Base quality: which reads get a vote](#base-quality-which-reads-get-a-vote)
10. [When the consensus can contain insertions or deletions](#when-the-consensus-can-contain-insertions-or-deletions)
11. [Every setting, in plain terms](#every-setting-in-plain-terms)
11. [Proving two runs agree](#proving-two-runs-agree)
12. [When a run refuses to start](#when-a-run-refuses-to-start)
13. [Understanding the parameters](#understanding-the-parameters)
14. [Influenza mode](#influenza-mode)
15. [How to read the QC report](#how-to-read-the-qc-report)
16. [Checking coverage and mapping in Qualimap](#checking-coverage-and-mapping-in-qualimap)
17. [Practical guidance by platform](#practical-guidance-by-platform)

---

## The problem this tool solves

When you sequence a biological sample, the bioinformatics pipeline produces a **consensus sequence** - a single FASTA file representing the most likely genome. But at some positions, the pipeline cannot confidently call a single base. Maybe 60% of the reads say "A" and 40% say "G." Instead of guessing, the pipeline writes an **ambiguity code** - in this case "R," which means "A or G."

These ambiguity codes are scientifically honest, but they cause problems downstream. Phylogenetic tools, clade assignment software, and submission databases often struggle with ambiguous bases. Someone has to review each ambiguous position and decide: is this a real mixture, or is the dominant base clear enough to call?

That review is traditionally done by hand in IGV (Integrative Genomics Viewer), one position at a time. DeGenRESOLVE automates that process. It examines every ambiguous position in your consensus, checks the actual read-level evidence, and decides whether to:

- **Resolve** the ambiguity to the dominant base (when the evidence is clear)
- **Keep** the ambiguity code (when the evidence is genuinely mixed)
- **Report indel evidence** it found but did not act on, so you can check it yourself

It also flags positions where the evidence may be unreliable due to strand bias, homopolymer artifacts, or read-end effects - the same things you would look for in IGV.

---

## Sequencing fundamentals

If you already understand reads, alignment, coverage, and pileup, skip to the next section.

### What is a read?

When you sequence a sample, the sequencer breaks the DNA/RNA into fragments and reads each fragment. Each fragment produces a **read** - a string of bases (A, C, G, T) typically a few hundred to a few thousand bases long, depending on your platform.

```
Read 1:    ATCGATCGATCG
Read 2:      CGATCGATCGAA
Read 3:        ATCGATCGAATT
Read 4:    ATCGATCGATCG
```

### What is alignment?

Your reads are short fragments from a longer genome. **Alignment** is the process of figuring out where each read came from - matching it to the correct position on a reference genome.

```
Reference: ATCGATCGATCGAATTCG
Read 1:    ATCGATCGATCG
Read 2:      CGATCGATCGAA
Read 3:          ATCGATCGAATT
Read 4:    ATCGATCGATCG
```

The aligned reads are stored in a **BAM file** - a compressed binary file that records where each read maps and what bases it contains.

### What is coverage?

**Coverage** (or depth) at a position is the number of reads that overlap that position. Higher coverage means more evidence.

```
Reference: ATCGATCGATCGAATTCG
Read 1:    ATCGATCGATCG
Read 2:      CGATCGATCGAA
Read 3:          ATCGATCGAATT
Read 4:    ATCGATCGATCG
                ^
                Position 6: 3 reads cover it -> coverage = 3
```

In a typical amplicon run, you might see coverage of 100-5000x at most positions. The tool's default minimum coverage is 40x - below that, there is not enough evidence to confidently resolve an ambiguity.

### What is a pileup?

A **pileup** is what you see when you look at one specific position and ask: "What does every read say here?"

```
Position 292 on segment H4:

  Read 1:   ...G...    (forward strand)
  Read 2:   ...G...    (forward strand)
  Read 3:   ...A...    (reverse strand)
  Read 4:   ...G...    (forward strand)
  Read 5:   ...G...    (reverse strand)
  Read 6:   ...A...    (forward strand)
  Read 7:   ...G...    (reverse strand)

  Pileup summary:
    G: 5 reads (71%)
    A: 2 reads (29%)
    Coverage: 7
```

This is exactly what the tool does at every ambiguous position - it builds a pileup and counts the bases.

### What are forward and reverse reads?

DNA is double-stranded. When you sequence, some reads come from the **forward strand** (5' -> 3') and others from the **reverse strand** (3' -> 5'). A real variant should appear on reads from both strands. If a variant appears only on forward reads, it may be a sequencing artifact.

```
Forward reads (->): G > G > G >
Reverse reads (<-):   < G < A < G

    G on forward: 3       G on reverse: 2
    A on forward: 0       A on reverse: 1

    G is supported by both strands 
    A is only on reverse reads - suspicious
```

---

## IUPAC degeneracy codes

When a consensus caller cannot pick a single base, it uses a standard set of codes defined by the International Union of Pure and Applied Chemistry (IUPAC):

| Code | Bases represented | Mnemonic |
|------|------------------|----------|
| R | A, G | pu**R**ine |
| Y | C, T | p**Y**rimidine |
| S | G, C | **S**trong (3 H-bonds) |
| W | A, T | **W**eak (2 H-bonds) |
| K | G, T | **K**eto |
| M | A, C | a**M**ino |
| B | C, G, T | not A |
| D | A, G, T | not C |
| H | A, C, T | not G |
| V | A, C, G | not T |
| N | A, C, G, T | a**N**y base |

When the tool encounters one of these codes, it checks the BAM reads to determine whether the evidence supports a clear winner or whether the ambiguity is genuine.

---

## How the tool examines each position

For each degenerate base in your consensus, the tool:

1. **Finds the matching position** in the BAM file by mapping the consensus segment to the corresponding reference sequence.

2. **Builds a pileup** - counts how many reads say A, C, G, T, insertion, or deletion at that exact position.

3. **Separates forward and reverse reads** - records how many reads supporting each base came from the forward strand versus the reverse strand.

4. **Calculates allele frequencies** - what percentage of reads support each base.

5. **Checks the surrounding reference sequence** for homopolymer runs that could cause artifacts.

6. **Checks whether supporting reads cluster at read edges** - a sign of primer artifacts in amplicon workflows.

7. **Applies the decision rules** to resolve or keep the ambiguity.

All of this information is recorded in the diagnostic log and QC report so you can audit any decision the tool made.

---

## The decision rules

The tool applies a series of rules in order. It stops at the first rule that matches:

### 1. Is there enough coverage?

If the position has fewer reads than the minimum coverage threshold (default: 100), the tool does not have enough evidence to decide. It **keeps the original ambiguity code** unchanged.

**Why this matters:** With only 10 reads, a 60/40 split could easily be 50/50 with a few more reads. Low coverage means low confidence.

**What counts as a read here.** Only reads that actually contribute an A, C, G or T at that
position - reads that pass the base-quality filter and are not showing a gap. A column can be
500 reads deep and still fail the threshold if most of those reads carry a deletion or a
low-quality base. The log names both numbers so the two never look contradictory:

```
KEEP    Coverage too low (88 usable of 478 reads < 100)
```

That column is 478 reads deep, but 361 of them show a deletion and others fall below the
quality floor, leaving 88 that vote. Judging it on 478 would be counting reads that never
had a say.

### 2. Is only one base present?

If every read agrees on the same base (e.g., all reads say G), the ambiguity code is clearly wrong and the tool resolves to that base.

### 3. Is the dominant base clearly ahead?

This is the most common scenario. The tool calculates the **percentage difference** between the top two bases:

```
Example: Position has G at 77% and A at 20%
Percentage difference = 77% - 20% = 57%
Default threshold = 20%
57% > 20% -> RESOLVE to G
```

If the difference is below the threshold, the evidence is genuinely mixed and the tool **keeps the ambiguity code**.

**Why the default is 20%:** At 20% difference, the dominant base has roughly 60% support and the minor base has 40%. Below this, you are approaching a true 50/50 mixture where calling one base would be misleading. Above this, the dominant base is clearly the majority and is what you would call if reviewing in IGV.

### 4. Warning checks (after the decision)

After the tool makes its base-calling decision, it checks three quality metrics. By default, these produce **warnings only** - they appear in the log but do not change the call. If you enable strict mode for a specific metric, warnings of that type will revert a RESOLVE decision back to KEEP.

---

## Quality control metrics

These three metrics mimic the checks you would perform manually in IGV. They help you identify positions where the base call might be unreliable even if the allele frequency looks clear.

### Strand balance

#### What it measures

Strand balance checks whether the dominant base is supported by reads from **both** the forward and reverse strand. A real variant should appear on both strands. An artifact (e.g., from a systematic sequencing error on one strand) tends to appear on only one strand.

#### How it is calculated

The tool counts how many forward-strand reads and how many reverse-strand reads support the dominant base, then computes:

```
strand_balance = min(forward, reverse) / max(forward, reverse)
```

#### How to interpret the number

| Strand balance | Interpretation |
|---------------|----------------|
| 0.8 - 1.0 | Excellent - nearly equal support from both strands |
| 0.5 - 0.8 | Good - some imbalance, usually not concerning |
| 0.1 - 0.5 | Moderate imbalance - worth reviewing in IGV |
| 0.0 - 0.1 | Severe bias - most reads on one strand only. Warning triggered. |

#### Diagram

```
Balanced (strand_balance = 0.85):

  Forward (->):  G G G G G G G G G G G G     (12 reads)
  Reverse (<-):  G G G G G G G G G G         (10 reads)

  min(12,10) / max(12,10) = 10/12 = 0.83 


Biased (strand_balance = 0.04):

  Forward (->):  G G G G G G G G G G G G G G G G G G G G G G G G  (24 reads)
  Reverse (<-):  G                                                   (1 read)

  min(24,1) / max(24,1) = 1/24 = 0.04 
```

#### Why it matters biologically

Strand bias can indicate:
- **PCR amplification artifacts** - errors introduced during PCR that get copied into many reads, but only on one strand of the original template.
- **Sequencing chemistry artifacts** - some sequencing platforms have strand-specific error profiles.
- **Damage artifacts** - degraded or damaged samples can produce strand-specific errors (e.g., oxidative damage causing G->T on one strand).

A position with 95% G but all G reads on the forward strand should be treated with suspicion, even though the allele frequency looks convincing.

---

### Homopolymer proximity

#### What it measures

A **homopolymer** is a stretch of identical bases in a row: `AAAA`, `CCCC`, `GGGGGG`. Homopolymer proximity checks whether an ambiguous position is inside or near such a stretch in the reference sequence.

#### Why homopolymers cause problems

Most sequencing platforms struggle with homopolymers. The signal for each base in a run of identical bases looks very similar, making it hard to count exactly how many there are. This leads to:

- **Insertions** - the sequencer reports more bases than are actually present
- **Deletions** - the sequencer reports fewer bases than are actually present
- **Mixed signals** - some reads get the count right, others don't, creating apparent ambiguity

This is especially pronounced on **Oxford Nanopore** sequencers, where the signal flows through a protein pore and identical bases produce nearly identical current levels.

#### How it is calculated

```
1. Look at the reference sequence in a window around the position
   (default: 5 bases on each side)

2. Find any run of 5 or more identical bases (configurable via `--homopolymer-min-length`)

3. Measure the distance:
   - If the site is inside the run -> distance = 0
   - Otherwise -> count bases between the site and the nearest edge of the run
```

#### Diagram

```
Reference sequence around position 150:

  Position: 145 146 147 148 149 150 151 152 153 154 155
  Base:       C   A   A   A   A   A   G   T   C   C   C

                  | homopolymer |
                  A   A   A   A   A  (length = 5)

  Position 150 is INSIDE the run -> distance = 0, warning = YES

  Position 151 (G) is 1 base away -> distance = 1, warning = YES
  (still within the window, still flagged)
```

#### How to interpret

| Homopolymer length | Distance | Concern level |
|-------------------|----------|---------------|
| 3 | 3-5 | Low - short run, not adjacent |
| 3-4 | 0-1 | Moderate - typical source of minor indel noise |
| 5+ | 0 | High - inside a long run, likely artifact territory |
| 5+ | 0, with indel evidence | Very high - classic homopolymer error |

The warning flag indicates that a homopolymer is present near the site. It does **not** mean the call is wrong - it means you should pay extra attention to indel counts at that position.

---

### Read-end enrichment

#### What it measures

Read-end enrichment checks whether the reads supporting a variant tend to place that variant near the **beginning or end** of the read, rather than in the middle.

#### Why read ends matter in amplicon workflows

In amplicon sequencing, each read starts at a **primer binding site**. The first and last ~10% of each read can contain:

- **Primer sequences** that were not fully trimmed
- **Chimeric artifacts** where the read jumped from one template to another during PCR
- **Lower quality bases** where the sequencer is ramping up or winding down

A real biological variant will appear at various positions within reads, because different reads start and end at slightly different places. An artifact at a primer boundary will cluster at the same position within reads.

#### How it is calculated

```
For each read covering the ambiguous position:
  1. Find where the ambiguous position falls within the read
  2. Define the "edge zone" as the first and last X% of the read
     (controlled by --read-end-edge-fraction, default 0.1 = 10%)
  3. If the position falls in an edge zone, count it as an edge read

read_end_enrichment_score = edge_reads / total_reads
```

#### Diagram

```
A read is 1000 bases long. Edge fraction = 0.1, so edge zone = first and last 10% (100 bases each).

  Read:  |----edge----|===========middle===========|----edge----|
         0          100                            900         1000

  If the ambiguous position falls at query position 50:
    -> In the edge zone -> counted as edge read

  If the ambiguous position falls at query position 500:
    -> In the middle -> NOT an edge read


Real variant (score = 0.15):
  Read 1:  ------X-----------    position 120/1000 (middle)
  Read 2:  --X----------------   position  40/1000 (edge) <-
  Read 3:  ----------X-------    position 500/1000 (middle)
  Read 4:  --------X---------    position 350/1000 (middle)
  Read 5:  ------------X-----    position 620/1000 (middle)
  Read 6:  -----X------------    position 150/1000 (middle)
  edge reads: 1 / total: 6 = 0.17 


Primer artifact (score = 0.90):
  Read 1:  X------------------   position  15/1000 (edge) <-
  Read 2:  X------------------   position  20/1000 (edge) <-
  Read 3:  -X-----------------   position  30/1000 (edge) <-
  Read 4:  X------------------   position  10/1000 (edge) <-
  Read 5:  ---X---------------   position 110/1000 (middle)
  edge reads: 4 / total: 5 = 0.80 
```

#### How to interpret

| Score | Interpretation |
|-------|---------------|
| 0.0 - 0.3 | Normal - variant is well-distributed across read positions |
| 0.3 - 0.6 | Slightly elevated - may be fine for short amplicons |
| 0.6 - 0.8 | Suspicious - review the position in IGV |
| 0.8 - 1.0 | Warning triggered - likely a primer or edge artifact |

**Important note for amplicon workflows:** Short amplicons (< 300 bp) naturally have a higher baseline read-end enrichment score because a larger fraction of the read is "edge." The default threshold of 0.8 is set conservatively to avoid false positives in typical amplicon panels. If you are seeing excessive false warnings with very short amplicons, consider raising the threshold.

---

## Strict mode: when warnings override decisions

By default, all three QC metrics (strand balance, homopolymer, read-end enrichment) produce **warnings only**. The warning appears in the log and QC report, but the base call is not changed. This lets you review the warnings and make your own judgment.

If you want the tool to automatically revert suspicious calls, you can enable **strict mode** for each metric independently:

| Flag | What it does |
|------|-------------|
| `--strict-strand-bias` | If strand balance is below threshold, keep the ambiguity code instead of resolving |
| `--strict-homopolymer` | If a homopolymer is nearby, keep the ambiguity code instead of resolving |
| `--strict-read-end` | If reads cluster at edges, keep the ambiguity code instead of resolving |

These flags are **independent**. You can enable any combination. For example, `--strict-homopolymer` alone will only revert calls near homopolymers - strand bias and read-end warnings remain informational.

**When a strict flag reverts a call**, the reason field explains exactly which warning caused it:

```
Reason: Reverted by strict mode: homopolymer(len=5,dist=0)
```

---

## Insertions and deletions (indels)

An indel is a position where reads show a **missing** base (deletion) or an **extra** base
(insertion) rather than a different one. Indels are handled separately from ambiguity codes,
and by a different part of the pipeline.

### Why counting reads is not enough

It is tempting to say "if most reads show a gap, it is a deletion". That does not work, and the
bundled test data shows why.

`barcode01` has exactly three positions where 30% or more of the reads show a deletion:

| Position | Reads showing a deletion |
|----------|--------------------------|
| NP 1086 | 80% |
| H9 675 | 46% |
| H9 292 | 45% |

One of these is real and two are alignment artifacts. Nothing measurable from a pileup tells
them apart - not the deletion percentage, not strand balance, not gap length, not mapping
quality, not read-end position, not homopolymer length. All three look alike on every one of
those, and the strongest signal of the three, the 80% one, is an artifact.

What distinguishes them is **realignment** - re-fitting the reads around the gap - and a pileup
has already thrown that information away. So DeGenRESOLVE does not try. It lets `bcftools`
propose indels with its consensus indel model, then judges those proposals.

### The reading frame test

A gene is read in three-letter chunks. Delete one letter and everything after it shifts, like a
sentence with a letter removed and no spaces to guide you - the rest becomes nonsense. That is
a **frameshift**, and in a virus it usually means a dead gene.

An indel, or a group of them, whose net length change is not a multiple of three would shift the
frame. DeGenRESOLVE rejects it and writes the reason to the log. This applies across the entire
segment - see *How it finds the gene* below for why it is not limited to the gene it can detect.

**But indels are judged in groups, not one at a time.** `barcode01` has two indels four bases
apart in the H9 gene: one base missing at 674, one base added at 678. Separately each is fatal -
a 560-amino-acid protein cut short at about 217. Together they cancel: the frame snaps back and
the protein is full length with a single amino acid changed.

`bcftools` looks at each indel alone and would apply both without knowing they are related.
Judging them together is what DeGenRESOLVE adds.

### Where IMF comes from

`bcftools` writes three numbers into the INFO column of every indel line in the VCF, and
DeGenRESOLVE reads them straight out. It does not recompute them.

| Tag | bcftools' own definition | In plain terms |
|-----|--------------------------|----------------|
| **DP** | Raw read depth | How many reads cover that spot |
| **IDV** | Maximum number of raw reads supporting an indel | How many of them actually show the gap |
| **IMF** | Maximum fraction of raw reads supporting an indel | What share that is |

**IMF is simply IDV divided by DP.** Nothing more. An IMF of 0.527 means 52.7% of the reads
carried the indel.

Here is the real line for the first indel in `barcode01`, from
`step_6_called_variants/barcode01_variants.vcf.gz`:

```
H9_NC_004908.1  674  .  GAA  GA  43.4663  .  INDEL;IDV=126;IMF=0.527197;DP=239;...;DP4=60,52,75,51;...
```

126 / 239 = 0.527. The `Change` column in the log shows this as `GAA->GA`: the reference reads
GAA and the sample reads GA, so one A is gone and **Net_nt** is `-1`. VCF always carries one
anchoring base to the left, which is why a single deleted base is written as three letters
becoming two. `A->AC` is the mirror image: one base gained, `+1`.

You can check IDV yourself without trusting it. `DP4` counts reads four ways - reference-forward,
reference-reverse, indel-forward, indel-reverse. Here 75 + 51 = 126, which is IDV exactly. That
holds for all five indels in this barcode:

| VCF line | Position | Change | DP4 | indel reads | IDV | DP | IMF |
|---|---|---|---|---|---|---|---|
| 4606 | H9:674 | GAA->GA | 60,52,**75,51** | 126 | 126 | 239 | 0.527 |
| 4611 | H9:678 | A->AC | 60,52,**75,50** | 125 | 125 | 238 | 0.525 |
| 12901 | PB1:776 | CG->C | 12,8,**6,9** | 15 | 15 | 35 | 0.429 |
| 12910 | PB1:783 | CA->CAA | 12,9,**6,7** | 13 | 13 | 35 | 0.371 |
| 14838 | PA:421 | GA->G | 20,24,**15,22** | 37 | 37 | 89 | 0.416 |

### The order the three tests run in

They are not weighed against each other. The first failure ends it:

1. **Depth.** If `DP` is below your Minimum Coverage Threshold, reject at once. IMF is never
   consulted. This is why the three rows above with DP of 35, 35 and 89 were rejected against a
   floor of 100 - their IMF values, some of them substantial, never entered into it.
2. **Support.** Apply your `indel_rules` bar to IMF.
3. **Reading frame.** Group the survivors and check the frame, as described above.

A rejection message always quotes the number that actually decided it, so you can tell which gate
closed: `coverage 89 < min_coverage 100` is a depth failure, not a support failure.

### How it finds the gene, and what that misses

There is no annotation file. DeGenRESOLVE reads the gene boundaries out of the reference
sequence itself: it translates each segment in all three reading frames, finds every stretch
running from a start codon (**M**) to a stop codon (**\***), and keeps the longest one. On the
bundled influenza panel this recovers all eight canonical proteins at exactly the right length -
PB2 759, PB1 757, PA 716, HA 560, NP 498, NA 469, M1 252, NS1 230 amino acids.

**It finds the primary product only.** Influenza's M and NS segments each encode a second protein
from a *spliced* mRNA - **M2** on the M segment, **NEP** (also called NS2) on NS. Splicing joins a
short first exon to a second exon sitting well past the end of the primary gene, so a
"longest ORF" rule cannot see it. **PB1-F2** and **PA-X** are likewise read in other frames.

This used to matter. The frame test was applied only *inside* the detected gene, and anything
landing outside it was accepted with no frame check at all. On the bundled references that left
an unguarded tail at the 3' end of exactly the two spliced segments:

| Segment | Primary gene | Formerly unchecked tail | What lives there |
|---------|--------------|-------------------------|------------------|
| MP_OP023633.1 | M1, nt 14-772 | nt 773-1002 (23% of segment) | M2 second exon, frame runs to nt 992 |
| NS_OP023561.1 | NS1, nt 15-707 | nt 708-865 (18% of segment) | NEP second exon, frame runs to nt 849 |

**The frame test now applies across the whole segment**, not just inside the detected gene. The
reason this one test is enough: a net length change that is a multiple of three preserves *every*
reading frame at once. So requiring it everywhere covers the primary product, both spliced
products, and the alternative-frame products together, without needing to know where any of them
are. It also closes a second gap - a segment where no gene could be detected at all used to
accept every indel unchecked.

The cost is that a genuine indel in a true UTR will be rejected if it is not a multiple of three.
UTRs are short (roughly 13-45 nt at each end of a segment) and untranslated, so nothing is lost
biologically; and at ONT depth an indel there is nearly always a homopolymer artifact. The one
real example in this repository is a poly-A run in an N1 3' UTR, `CAAAAAA->CAAAAAAA`.

**What DeGenRESOLVE still will not tell you** is *which* protein an indel would have damaged. It
enforces the frame; it does not name M2 or NEP in the log. If you need that, translate the
segment yourself around the position the log reports.

### Your rule

`indel_rules` controls how much read support an indel needs. It is checked against **IMF**, the
fraction of reads supporting the indel:

| Rule | Accepts when | When to use |
|------|--------------|-------------|
| **equal_or_more** (default) | IMF >= 0.50 - half the reads or more | Conservative, and the sensible default |
| **more_than** | IMF > 0.50 | Slightly stricter |
| **custom_percentage** | IMF >= X/100 | Set the bar wherever you need it |

An indel is applied only when **all three** hold: enough depth, your IMF rule satisfied, and the
reading frame intact.

### What you will actually see on hac data

If your reads are `hac`-basecalled - as most are - `bcftools` runs with indel calling switched
off, on bcftools' own recommendation for that basecaller. No indel is ever applied, and the log
says so plainly.

Deletion evidence is not hidden. Every column where 30% or more of reads show a deletion is
listed under **INDEL EVIDENCE (not acted upon)**. Those are the positions worth opening in IGV.
The percentage is deletions per read that survived the quality filter, so it is measured against
the same reads the rest of the log counts.

If you need them resolved rather than reported, the clean answer is to re-basecall with `sup`.

Failing that, **Force sup variant-calling profile** in the Configuration tab applies the sup flag
set to hac reads. Understand what you are asking for: the sup indel model earns its trust by
realigning, and it was tuned on sup reads. The same switch also changes `-Q` and `--max-BQ`, so
your SNV calls and ambiguity codes move too - a before/after comparison across this switch is not
an indel-only comparison. It is a diagnostic tool, not a substitute for re-basecalling.

---

## Base quality: which reads get a vote

Every base a sequencer produces carries a quality score - the machine's own estimate of how
likely that base is wrong. Q10 means roughly a 1-in-10 chance of error, Q20 a 1-in-100 chance.
Nanopore reads carry a lot of bases at the low end.

DeGenRESOLVE ignores bases below **Q5** (the *Minimum base quality* setting) when counting
evidence at an ambiguous position.

On `hac` reads `bcftools` uses the same floor, so both stages judge the same reads. On `sup`
reads bcftools drops its own floor to Q1, because `sup` quality values are better calibrated -
but it also *down-weights* the low-quality bases it lets in. DeGenRESOLVE counts reads rather
than weighting them, so it stays at Q5 on every basecaller: following bcftools down to Q1
without its weighting would be more permissive than bcftools, not equivalent. The counts stay
plain read counts so that any row of the log can be checked against IGV by eye.

Using one number for both matters more than it might seem. Suppose the tool called a position
using good reads only, then counted *all* reads - including ones the basecaller had already
judged unreliable - when deciding what the position really is. A minor variant that exists only
in bad reads could then push a position over the 20% line and get resolved as if it were real.
Low-quality bases on nanopore cluster in homopolymer runs, which are exactly the positions the
tool already treats with suspicion.

Two related points:

- **Why 5 and not something higher?** The threshold comes from the settings bcftools itself
  recommends for nanopore data, where it is paired with a cap that stops the tool from trusting
  any base more than Q30. Nanopore quality scores at the high end are optimistic, so the cap is
  what makes the low floor safe. The two work together; raising one without the other is not
  advisable.
- **Bases below Q5 are not deleted.** They stay in your FASTQ and BAM files. They just do not
  get a vote when the tool decides what a position is.

---

## When the consensus can contain insertions or deletions

On `hac` basecalls the final consensus is always the same length as the reference sequence. Positions that were
not covered appear as `N`; positions that were covered appear as a base or an ambiguity code.
What you will never see is an extra base inserted or a base removed.

This is deliberate, for two reasons.

The first is accuracy. Nanopore's characteristic error is the indel - reading a run of six
identical bases as five or seven. On reads basecalled with the standard `hac` model, indel
calls are not reliable enough to write into a consensus. This is not a DeGenRESOLVE opinion:
bcftools ships recommended settings per sequencing platform, and for nanopore its recommended
setting switches indel calling off. Only the settings for `sup` basecalling - the slow,
high-accuracy model - turn it back on.

The second is bookkeeping. The tool compares consensus position 1 to reference position 1,
position 2 to position 2, and so on. If an insertion were added at position 500, then
consensus position 501 would be reference position 500, 502 would be 501, and every ambiguity
after that point would be judged against the wrong reference base - quietly, with no error
message. Keeping the consensus reference-length keeps that comparison honest.

**Indel evidence is still reported.** Every column where 30% or more of reads show a deletion
is listed in the diagnostic log under INDEL EVIDENCE (not acted upon), whether or not anything
was applied. Nothing is silently discarded.

**On `sup` reads this section does not apply.** With `sup` basecalling, bcftools does call
indels, and an indel that passes your rule, the coverage floor and the reading-frame test is
applied - so the consensus can differ from the reference in length. The bookkeeping problem
above is handled by applying indels only after every ambiguity has been resolved, while the
position-for-position comparison is still valid.

---

## Every setting, in plain terms

This section lists every setting the software exposes: what it means, what the default is, and
what happens if you change it. Each entry names the GUI label and the command-line flag, so the
two interfaces can be matched up. Where a default comes from published work, `REFERENCES.md`
gives the citation; where it is an operational choice, this says so plainly.

### Words you will meet

| Term | Meaning |
|---|---|
| **base** | One letter of DNA: A, C, G or T. |
| **read** | One continuous stretch of DNA the sequencer produced, typically a few hundred to a few thousand bases. |
| **FASTQ** | The file the sequencer writes: the read's bases plus a quality score for each base. |
| **alignment / BAM** | The result of deciding where each read sits on the reference genome. A BAM file stores those placements. |
| **reference** | A known genome sequence used as a map to lay reads against. |
| **coverage / depth** | How many reads overlap one position. Depth 200 means 200 reads had something to say about that base. |
| **pileup** | The stack of reads at one position, viewed as a column. |
| **variant / VCF** | A place where the sample differs from the reference. A VCF file lists them. |
| **IUPAC code** | A single letter meaning "one of these bases", used when a position is genuinely mixed. `R` = A or G, `Y` = C or T, `N` = any. |
| **indel** | An insertion or deletion: extra bases present, or bases missing, relative to the reference. |
| **homopolymer** | A run of the same base repeated, e.g. `AAAAA`. Nanopore sequencers miscount the length of these. |
| **strand** | DNA has two complementary strands. A read comes from one or the other; seeing a variant on both is reassuring. |
| **consensus** | The single best-guess sequence for the sample, one letter per position. |

### The core decision settings

**Minimum Coverage Threshold**: `--min-coverage`, default **100**

How many usable reads a position needs before the software is willing to change anything there.
"Usable" means reads whose base passed the quality check; a position can have 400 reads but only
80 usable ones, and it is the 80 that count. Below the threshold the original letter is kept
untouched. *Raise it* for stricter, more conservative calling on deep data. *Lower it* if your
runs are shallow and you accept more risk. Cited in `REFERENCES.md`.

**Degeneracy Threshold**: `--min-percentage-diff`, default **20** (percent)

At a mixed position, how far ahead the leading base must be before it is declared the winner.
If A is 70% and G is 25%, the gap is 45 points, comfortably over 20, so A is called. If A is 51%
and G is 49%, the gap is 2 points, so the position stays ambiguous and keeps its IUPAC code.
*Raise it* to keep more positions ambiguous, *lower it* to resolve more of them. Cited.

**Ploidy**: GUI only, default **2**

Passed to the variant caller. Setting it to 2 tells the caller to consider that two different
bases might genuinely be present at one position, which is what produces IUPAC codes in the first
place. Setting it to 1 forces a single base everywhere and throws that information away. Cited.

**Call Mode**: GUI only, default **`-c` (consensus)**

Which of the variant caller's two algorithms to use. `-c` is the older model, appropriate for a
single viral population; `-m` handles several alternative alleles at one position. Cited.

**Filter Mode**: `--filter-mode`, default **`general`**

`influenza` reduces the output to the eight canonical influenza segments, picking the single
best-supported HA and NA subtype by read count. `general` keeps every segment that received
reads, which is what you want for a non-segmented virus or when you do not know the subtype.

### Quality-control checks

These do not change calls by default. They raise warnings you can read in the diagnostic log.
Each has a matching **strict** switch that turns the warning into a veto.

**Minimum Strand Balance Threshold**: `--strand-balance-threshold`, default **0.1**

DNA has two strands, and a real variant should be visible on both. This compares the smaller
strand count to the larger one for the winning base: 1.0 means perfectly even, 0.0 means one
strand only. Below the threshold, a warning is raised. **Operational default, not from the
literature** - on the 100-barcode influenza dataset the lowest value observed at any
well-covered position was 0.335, so 0.1 never fired. It is a safety net for grossly one-sided
evidence. If your libraries show more variable strand representation, 0.3-0.5 is a more active
setting. See `REFERENCES.md`.

**Homopolymer Minimum Length**: `--homopolymer-min-length`, default **5**

Nanopore sequencers are unreliable at counting long runs of the same base, so a position sitting
next to `AAAAA` deserves more suspicion than one in mixed sequence. This is the shortest run that
counts as a homopolymer. *Lower it* to flag more positions, *raise it* to flag only long runs.
Published work puts the sharp accuracy drop at around 10 bases, so 5 is deliberately cautious;
influenza references contain few runs longer than 6. Cited.

**Homopolymer Window**: `--homopolymer-window`, default **5**

How far either side of a position to look for such a run. With the default, a run up to 5 bases
away is reported, along with its true length and distance.

**Maximum Read-End Enrichment Threshold**: `--read-end-threshold`, default **0.8**

Reads are least accurate at their very ends, and in amplicon sequencing every read ends at the
same place, so errors there stack up across many reads and can look like a real variant. This
measures the fraction of reads carrying the *minority* base that have it near a read end. A
score near 1.0 means almost all the evidence sits in the least trustworthy part of the data.
The threshold is an **operational choice** placed at the 95th percentile of observed values
(median 0.033, 95th percentile 0.798), so it flags roughly the top 5%. The underlying artefact
is documented for amplicon data - see `REFERENCES.md`.

**Read-End Edge Fraction**: `--read-end-edge-fraction`, default **10%**

How much of each read counts as "the end". At 10%, the first and last 10% of a read are the edge
zone. Widening it on amplicon data would flag most of the amplicon, because the true read ends
coincide with the primers.

**Strict: strand bias / homopolymer / read-end**: GUI checkboxes, default **off**

Each turns its warning into a veto: a position that would have been resolved is instead left
ambiguous and the reason recorded. Off by default because the checks are advisory - they mark
positions for a human to look at, rather than making the decision for you.

### Base quality

**Minimum Base Quality**: GUI/config default **auto**; `--min-base-quality` default **5**

Every base carries the sequencer's own confidence score. This is the floor below which a base is
not allowed to vote. Two settings share the name and they are not the same number:

- In the GUI and the pipeline configuration file the default is **auto**. The pipeline reads the
  basecall model recorded in your reads and applies the pair the variant caller ships for that
  model: `-Q 5` with `--max-BQ 30` for **hac** (high-accuracy) reads, and `-Q 1` with
  `--max-BQ 35` for **sup** (super-accuracy) reads, which are reliable enough that lower-scoring
  bases still carry information.
- On the standalone consensus editor, `--min-base-quality` defaults to **5**. This is the
  refinement step's own floor and it is never taken below 5, even on sup data, because unlike
  the variant caller it counts every surviving base equally and has no way to down-weight a poor
  one. Following sup's `-Q 1` here would make the refinement step more permissive than the
  caller that fed it.

So on hac data both stages use Q5; on sup data the caller sees more reads than the refinement
step does, by design. Cited in `REFERENCES.md`.

**Force sup profile**: GUI checkbox, default **off**

Applies the super-accuracy settings whatever the reads say. Its main use is indel detection: the
high-accuracy profile switches indel calling off entirely, so this must be on to see indels at
all. It also changes the base-quality pair, so substitution calls shift with it. Whichever
profile ran is recorded in the run receipt.

**Depth per Site**: GUI only, default **10,000**

A ceiling on how many reads the variant caller examines at one position, to bound memory on very
deep data. Set high enough that it does not bite in normal use. Cited.

### Indels

**Indel Rule** and **Custom Percentage**: `--indel-insertions`, `--indel-deletions`,
`--indel-custom-percentage`, defaults **`equal_or_more`** and **50%**

**These no longer affect which indels are applied.** They are kept so that older configuration
files still load. Insertions and deletions used to be decided by counting them in the pileup;
that rule was withdrawn because a pileup count cannot tell a genuine indel from a misalignment.
Indels now come from the variant caller, which decides using realignment, and are then judged on
three things: how large a share of reads support the indel, whether depth clears the coverage
threshold, and whether a group of nearby indels changes the reading frame. An insertion and a
deletion that cancel out are treated differently from a lone frameshift.

### Housekeeping

**Enable Qualimap / NanoPlot**: GUI checkboxes, default **on**

Two optional quality reports: NanoPlot describes the raw reads, Qualimap describes the alignment.
Neither changes the consensus. Turn them off to save several minutes per barcode.

**Enable parallel processing / Threads**: default **on**, threads = detected CPU cores

How many barcodes to process at once. Each barcode is independent, so this scales nearly
linearly until you run out of cores or memory. It does not change results, only how long you
wait.

## Proving two runs agree

Every run writes a **receipt** for each barcode, at
`results/reports/<barcode>_receipt.txt`. It lists the settings actually used, the reference
file, the basecalling model your reads came from, the software versions, and a checksum for
each file the pipeline produced.

To check whether two runs - on two machines, or a month apart - produced the same result,
compare their receipts:

```
diff run_A/results/reports/barcode01_receipt.txt \
     run_B/results/reports/barcode01_receipt.txt
```

No differences means the two runs agree on every base. If the checksums differ, the lines above
them tell you why: a changed setting, a different reference file, or different software
versions. If none of those differ and the checksums still do, something unexpected has happened
and is worth investigating.

The receipt reports the basecalling model taken from your read headers, for example
`dna_r10.4.1_e8.2_400bps_hac@v4.3.0`. If reads from two different basecalling models are mixed
in one barcode the run stops, because the correct settings differ between them. If your reads
were basecalled with `sup`, the run warns you: the settings in use are the ones for `hac`, and
they will under-call indels on better data.

---

## When a run refuses to start

If you change a setting and re-run over an existing `results/` folder, the pipeline stops
before doing any work:

```
Error: results/ was produced with different settings than this run.
  < min_coverage=100
  > min_coverage=150
```

This is intentional. Because finished steps are normally skipped and reused, continuing here
would mix files made under the old setting with files made under the new one, and the report
would describe a configuration that only half the results were produced with. Either put the
setting back, or move `results/` aside and let the run start clean.

Changing how many barcodes run in parallel, or switching Qualimap and NanoPlot on or off, does
**not** trigger this - none of them can change a single base of the output.

---

## Understanding the parameters

### Core parameters

| Parameter | Default | What it controls |
|-----------|---------|-----------------|
| **Minimum coverage** (`--min-coverage`) | 100 | How many reads must cover a position before the tool will try to resolve it. Below this, the ambiguity is kept unchanged. **Raise this** if you want more conservative calls. **Lower this** if your amplicon coverage is low and you still want resolution. |
| **Minimum percentage difference** (`--min-percentage-diff`) | 20 | The minimum gap between the top base and second base (as a percentage of total standard bases). At 20%, this means the top base needs roughly 60% support to be called. **Raise this** for stricter calls. **Lower this** if you are comfortable resolving closer mixtures. |

### Variant call mode

This setting controls the `bcftools call` flag used during draft consensus generation. It determines both the variant calling model and which downstream consensus tool is used.

| Mode | Flag | Pipeline path | When to use |
|------|------|--------------|-------------|
| **Consensus Caller** | `-c` | `bcftools call -c` -> `vcfutils.pl vcf2fq` -> `seqtk` | **Default.** Standard biallelic model. Reliable for single-strain samples. `vcfutils.pl` automatically encodes zero-coverage positions as `N`. |
| **Multiallelic Caller** | `-m` | `bcftools call -m` -> `bcftools consensus --iupac-codes` + samtools depth mask | Use when you suspect genuine co-circulation of two or more alleles at the same position (e.g., mixed infections, co-infection). Handles tri-allelic sites correctly. Zero-coverage positions are masked as `N` using a coverage map from `samtools depth`. |

**Why two different downstream tools?** `vcfutils.pl vcf2fq` was written for the biallelic (`-c`) VCF format and does not correctly parse the multi-valued PL fields produced by `-m`. Using it with `-m` output produces Perl warnings and incorrect quality encoding for multiallelic sites. `bcftools consensus` is the current maintained replacement and handles both modes correctly, but requires an explicit coverage mask for `N`-masking at zero-coverage positions (which `vcfutils.pl` did implicitly).

For most influenza and single-strain ONT amplicon workflows, **Consensus Caller (`-c`) is sufficient and recommended**. Switch to Multiallelic (`-m`) only if your data contains evidence of co-infection or mixed-strain populations.

**Why `vcfutils.pl vcf2fq` rather than `bcftools consensus` for the `-c` path?**

`bcftools consensus` is the current maintained replacement for `vcfutils.pl` and supports both output formats (Danecek et al. 2021, PMID: 33590861). However, the two tools differ critically at **zero-coverage positions**:

- `vcfutils.pl vcf2fq` encodes zero-coverage positions as **`N`** - honest masking that signals "no read support exists at this position."
- `bcftools consensus --iupac-codes` silently copies the **reference base** into the consensus at zero-coverage positions - producing base calls that look supported but are not.

An internal comparison run on a DVG amplicon barcode (PRJNA1366758, PR8 H1N1, 5,000 MinION reads) confirmed this behaviour directly:

| Method | N bases (zero-coverage) | ACGT bases | Notes |
|--------|------------------------|------------|-------|
| `vcfutils.pl vcf2fq` | 1,953 | 388 | Honest N-masking at all zero-coverage positions |
| `bcftools consensus --iupac-codes` | 0 | 2,341 | Silently backfills zero-coverage positions with reference sequence |

The `bcftools consensus` output appears more complete - 2,341 ACGT bases vs 388 - but the additional bases are reference-filled positions with no read support. DeGenRESOLVE's resolution engine does not flag these as ambiguous and would pass them through unexamined into the refined consensus, creating a false sense of completeness. `vcfutils.pl vcf2fq` is therefore retained for the `-c` path because it is honest about missing data (Li H 2011, PMID: 21903627; Danecek et al. 2021, PMID: 33590861).

> Note: earlier drafts pointed to `comparison_run/COMPARISON_REPORT.txt` for full methodology
> and raw outputs. That file is not included in this bundle - the figures given above are the
> complete record of the comparison as distributed.

### Ploidy

| Parameter | Default | What it controls |
|-----------|---------|-----------------|
| **Ploidy** | 2 | Genome copy number assumed by `bcftools call --ploidy`. Controls whether mixed-allele sites are called as heterozygous. |

**Why ploidy 2 for a haploid virus?**

Although RNA viruses are biologically haploid within a single virion, ploidy 2 is required here for a bioinformatics reason: it allows `bcftools call` to make heterozygous genotype calls (GT = `0/1`) at sites where two alleles coexist in the sequenced population. These heterozygous calls are what `vcfutils.pl vcf2fq` encodes as IUPAC ambiguity codes - and those IUPAC codes are the input that DeGenRESOLVE's resolution engine examines and resolves.

With ploidy 1, `bcftools call` forces homozygous-only calls, suppressing nearly all mixed-allele sites. The result is a consensus with almost no IUPAC codes, leaving the resolution engine with nothing to process.

Empirical validation on the same barcode and BAM file, reprocessed under each setting (Danecek et al. 2021, PMID: 33590861; Li H 2011, PMID: 21903627):

| Ploidy | Call mode | IUPAC sites in draft consensus | After DeGenRESOLVE |
|--------|-----------|-------------------------------|-------------------|
| 1 | `-c` | 4 | - |
| 2 | `-c` | 336 | 274 |
| 2 | `-m` | 342-354 | - |

**Do not lower ploidy to 1** unless you have a specific reason (e.g., generating a majority-rules consensus with no ambiguity). The default of 2 is intentional and validated.

### QC thresholds

| Parameter | Default | What it controls |
|-----------|---------|-----------------|
| **Minimum strand balance threshold** (`--strand-balance-threshold`) | 0.1 | A value between 0 and 1. The strand balance at a position is calculated as `min(forward, reverse) / max(forward, reverse)`. A value of 1.0 means perfectly balanced; 0.0 means all reads are on one strand. When the strand balance falls **below** this threshold, a warning is triggered. The default 0.1 means a warning fires when fewer than 10% of the dominant-base reads come from the minority strand. **Raise this** (e.g., 0.3) if you want to flag more sites for review. This is a *minimum* - lower values are more permissive. |
| **Homopolymer minimum length** (`--homopolymer-min-length`) | 5 | The shortest homopolymer run that triggers a warning. Five identical bases in a row (`AAAAA`) is the default. **Lower this** to 3 if you want to flag even short runs. **Raise this** to 6+ if you only care about long homopolymers. |
| **Homopolymer window** (`--homopolymer-window`) | 5 | How many bases on each side of the ambiguous position to search for homopolymers. **Raise this** if you want to detect more distant runs. **Lower this** to only flag positions immediately adjacent to or inside a run. |
| **Maximum read-end enrichment threshold** (`--read-end-threshold`) | 0.8 | A value between 0 and 1. The read-end enrichment score is the fraction of reads **carrying the minority allele** that place that position near the beginning or end of the read. (Prior to this release the implementation counted every read overlapping the position regardless of which base it carried, making the score a property of the amplicon rather than of the variant; it now filters to the allele under suspicion, so scores are not comparable with logs from earlier runs.) When this score **exceeds** the threshold, a warning is triggered. The default 0.8 is conservative - 80% of reads must cluster at edges before a warning fires. **Lower this** (e.g., 0.5) if you want to flag more positions. This is a *maximum* - higher values are more permissive. |
| **Read-end edge fraction** (`--read-end-edge-fraction`) | 10% | What percentage of each read's beginning and end counts as the "edge zone." At 10%, the first 10% and last 10% of each read are edges. **Raise this** (e.g., 20%) to make the edge zone larger, which catches more subtle clustering. **Lower this** (e.g., 5%) for long reads where 10% is already a large region. |

### Strict mode flags

| Parameter | Default | What it controls |
|-----------|---------|-----------------|
| `--strict-strand-bias` | Off | When on, positions with strand bias warnings are not resolved - the ambiguity is preserved. |
| `--strict-homopolymer` | Off | When on, positions near homopolymers are not resolved. |
| `--strict-read-end` | Off | When on, positions with read-end enrichment are not resolved. |

---

## Influenza mode

When you use `--filter-mode influenza`, the tool activates special handling for influenza genome segments.

### What happens in influenza mode

1. **Segment filtering**: Only influenza-relevant segments are kept: HA (hemagglutinin), NA (neuraminidase), PB2, PB1, PA, NP, MP (matrix), and NS (non-structural). Other segments in your consensus file are ignored.

2. **Major subtype detection**: Influenza reference databases contain multiple subtypes - H1 through H18 and N1 through N11. Your sample is (usually) only one subtype. The tool examines how many reads mapped to each reference subtype and picks the **major H** and **major N** based on read counts.

3. **Output ordering**: The edited FASTA lists segments in a standard order: major H first, then major N, then PB2, PB1, PA, MP, NP, NS.

4. **Subtype exclusion**: If your consensus has both H4 and H11 segments (because reads mapped to both references), only the major one is included in the output. The minor subtype is dropped - it usually represents low-level cross-mapping, not a real mixed infection.

### Frequently asked questions about influenza mode

**Can I provide multiple reference sequences?**
Yes. Supply a multi-FASTA reference file containing all segments (e.g., H1 through H18, N1 through N11, PB2, PB1, PA, NP, MP, NS). The pipeline maps reads against all sequences and the consensus editor keeps only the relevant ones.

**Does the software analyze all segments together?**
Yes. All segments are processed in a single run. The pipeline maps reads to the full multi-segment reference, calls variants per segment, and produces one consensus per segment - no need to run separately for each segment.

**How does the tool choose the major HA and NA subtypes?**
It examines the BAM index statistics (mapped read counts per reference sequence). The HA and NA subtypes with the most mapped reads are selected as the major subtypes. All other HA/NA subtypes are excluded from the output.

**What about mixed infections or co-infections?**
If a sample contains two influenza subtypes, reads will map to both references. The tool picks the dominant subtype by read count and drops the minor one. If the mixture is roughly equal, the call may be unreliable - check the BAM index stats and consider running with `--major-h` / `--major-n` overrides if needed. The tool does not attempt to deconvolve co-infections into separate genomes.

**How are missing or low-coverage segments handled?**
If a segment has no mapped reads, it will not appear in the consensus. If a segment has reads but coverage is below the minimum threshold at ambiguous positions, those positions retain their IUPAC ambiguity codes. The QC report shows per-segment coverage statistics so you can identify underrepresented segments.

**How are multiple references with similar mapping quality handled?**
The tool does not use mapping quality - it uses total mapped read count per reference sequence. If two subtypes have similar read counts, the one with more reads wins. You can override with `--major-h` and `--major-n` if the automatic selection is wrong.

### Overriding auto-detection

If the tool picks the wrong major H or N (rare, but possible with unusual samples), you can override it:

```bash
python consensus_editor.py consensus.fasta reference.fasta \
  --filter-mode influenza \
  --major-h H5 \
  --major-n N1-V2
```

---

## How to read the QC report

The tool always produces two report files: a **JSON** file (machine-readable) and an **HTML** file (human-readable). Open the HTML file in any web browser.

### Overall summary

```
Total Sites Examined:              67
Resolved To Dominant Base:         63
Retained As Iupac:                  4
Converted To Indel:                 0
Retained Low Coverage:              0
Flagged Strand Bias:                0
Flagged Homopolymer:               31
Flagged Read End Enrichment:        5
```

**How to interpret this:**

- **67 sites examined** - your consensus had 67 degenerate bases across all segments.
- **63 resolved** - for 63 of those, the evidence clearly supported one base, and the tool resolved the ambiguity.
- **4 retained as IUPAC** - for 4 positions, the evidence was genuinely mixed (the top two bases were within 20% of each other), so the ambiguity code was kept.
- **0 converted to indel** - no indel proposed by bcftools in the VCF was accepted by `_adjudicate_indels()` (which judges IMF, coverage and reading frame). This is counted from the VCF after degeneracy resolution, **not** from raw pileup DEL/INS counts - that pileup rule was removed because it could not distinguish a real indel from an alignment artefact. It is 0 whenever `--vcf` was not supplied.
- **0 flagged for strand bias** - every resolved position had good support from both strands. This is typical for well-prepared amplicon libraries.
- **31 flagged for homopolymer** - 31 positions were near homopolymer runs. This is a **warning, not an error**. It means you should pay extra attention to these positions if reviewing manually. In this dataset, none of them were wrong - the calls were still made because strict mode was off.
- **5 flagged for read-end enrichment** - 5 positions had an elevated fraction of reads from read edges. Again, a warning for review.

### Coverage summary

```
Min:     78
Max:     4199
Median:  189
Mean:    807.4
```

This tells you about the coverage **at ambiguous positions only** (not across the whole genome). A median of 189 means most ambiguous sites had plenty of evidence. A minimum of 78 means even the worst-covered ambiguous site was above the default threshold of 40.

### Per-segment summary

This table shows the breakdown for each genome segment. Look for segments with low resolution rates - those may need manual review.

---

## Checking coverage and mapping in Qualimap

Before accepting any consensus output in **general filter mode**, open the Qualimap BAM QC report for that barcode and check two numbers: the **percentage of reads mapped** and the **mean coverage depth**. Together, these tell you whether you used the correct reference organism and whether your sequencing run yielded enough data to trust the consensus.

> **Where to find the report:** In the DeGenRESOLVE Results tab, select a barcode, then click the **≈ BAM QC** button to open the Qualimap HTML report in the viewer. Or click **Open Folder** -> `step_5_alignment_qc_qualimap/barcodeXX/` to browse it directly.

---

### Step 1 - Check the percentage of reads mapped

This is the first and most important check. It tells you whether your sample's reads are actually aligning to the reference genome you provided.

| % Reads Mapped | What it means | What to do |
|---|---|---|
| **> 80%** | Correct reference - reads recognise the genome | Proceed to Step 2 |
| **50 - 80%** | Possible strain mismatch or contamination | Try a closer reference strain or subtype; check for mixed species |
| **< 50%** | Wrong organism - reference does not match the sample | Do not proceed; re-identify the organism (BLAST the reads, run Kraken2) |
| **< 10%** | Gross mismatch or sample failure | Investigate extraction/library quality |

A typical correctly matched reference yields **70-90% mapped reads** (Wingett & Andrews 2018, PMID: 30254741). Values outside this range require investigation before you trust any downstream consensus.

```
Example - Qualimap summary block:
  Mapped reads:            1,942,816  /  2,289,000  (84.9%)   Proceed
  Mapped reads:              614,000  /  2,100,000  (29.2%)   Wrong organism
```

---

### Step 2 - Check mean coverage depth

Once you are confident the reads are mapping to the right organism, check whether there are enough of them to make reliable base calls.

| Mean Depth | Interpretation |
|---|---|
| **< 10×** | Insufficient - do not call consensus |
| **10 - 20×** | Marginal - consensus possible but SNP calls unreliable |
| **≥ 20×** | Minimum acceptable for reliable variant calling (Raven et al. 2020, PMID: 32228804) |
| **≥ 50×** | Recommended target for strain-level typing (Desai et al. 2013, PMID: 23593174) |
| **> 200×** | Diminishing returns; stacking artefacts possible at very high depths |

The DeGenRESOLVE default minimum coverage for consensus resolution is **100×** (configurable), which is deliberately conservative above the 60× empirical lower bound for accurate ONT viral consensus (Bull et al. 2020, PMID: 33298935).

---

### Step 3 - Check breadth of coverage

Mean depth alone can be misleading if coverage is uneven (e.g., a few positions with very high depth pulling up the mean while large regions are uncovered). Also check the **percentage of the reference genome covered at ≥ 20×** in the Qualimap coverage histogram.

| Breadth at ≥ 20× | Interpretation |
|---|---|
| **≥ 80%** | Acceptable - consistent with clinical WGS standards (Raven et al. 2020, PMID: 32228804) |
| **60 - 80%** | Patchy - some regions may have unreliable or absent consensus |
| **< 60%** | Poor - large portions of the genome are uncovered; consensus is unreliable |

---

### Combined decision

All three metrics must pass before you trust the consensus:

```
% reads mapped > 80%
    AND mean depth ≥ 20×
    AND ≥ 80% of genome at ≥ 20×
-> Correct species/strain confirmed, reliable consensus. Proceed.

% reads mapped > 80%, but mean depth < 20×
-> Correct organism, insufficient sequencing. Re-sequence or flag as low-quality.

% reads mapped 50-80%
-> Strain mismatch likely. Try a closer reference (different serotype, strain, clade).

% reads mapped < 50%
-> Wrong organism. Do not use this reference. Identify the organism first.
```

---

### Why this matters in general filter mode

In **influenza mode**, the tool automatically selects the best-matching HA and NA subtypes by read count, reducing the risk of a mismatch. In **general filter mode**, you supply the reference yourself - the pipeline will map your reads and call a consensus against whatever FASTA you provide, even if it is the wrong organism. Qualimap is your safeguard: low mapping rate or low coverage is the early warning that your reference needs to change before you interpret any consensus output.

**References:** García-Alcalde et al. 2012 (PMID: 22914218); Okonechnikov et al. 2016 (PMID: 26428292); Raven et al. 2020 (PMID: 32228804); Desai et al. 2013 (PMID: 23593174); Wingett & Andrews 2018 (PMID: 30254741); Petrackova et al. 2019 (PMID: 31552176).

---

## Practical guidance by platform

### Oxford Nanopore (MinION, GridION, PromethION)

Nanopore sequencing has a well-known weakness with homopolymers. The ionic current signal for identical consecutive bases is difficult to segment accurately.

**Recommended settings:**

```bash
--strict-homopolymer         # Automatically preserve ambiguity near homopolymers
--homopolymer-min-length 3   # Flag even short runs (the default is 5)
--homopolymer-window 5       # Check 5 bases on each side (default)
```

You may also want to raise the minimum coverage, since nanopore reads have higher per-read error rates:

```bash
--min-coverage 60
```

### Illumina (MiSeq, NextSeq, NovaSeq)

Illumina has excellent per-base accuracy but can show strand bias in certain sequence contexts (e.g., GGC motifs on some chemistry versions). Homopolymer issues are minimal for runs under ~8 bases.

**Recommended settings:**

```bash
--strict-strand-bias             # Guard against strand-specific artifacts
--strand-balance-threshold 0.2   # Slightly stricter than default
--homopolymer-min-length 6       # Only flag longer runs (Illumina handles short ones well)
```

### Amplicon sequencing (any platform)

Amplicon workflows use PCR primers that create defined start/end positions for reads. This means read-end enrichment naturally occurs at primer binding sites. If your primer trimming was incomplete, artifacts can appear at amplicon boundaries.

**Recommended settings:**

```bash
--strict-read-end             # Guard against untrimmed primer artifacts
--read-end-threshold 0.8      # Keep the conservative default
```

If you are using very short amplicons (< 300 bp), reads are mostly "edge" and the read-end metric becomes noisy. In that case:

```bash
--read-end-threshold 0.9          # Raise threshold to reduce false warnings
--read-end-edge-fraction 0.05     # Shrink the edge zone for short reads
```

### Conservative (maximum caution)

If you want the tool to only resolve positions where the evidence is overwhelming and there are no quality concerns at all:

```bash
python consensus_editor.py consensus.fasta reference.fasta \
  --min-coverage 100 \
  --min-percentage-diff 40 \
  --strict-strand-bias \
  --strict-homopolymer \
  --strict-read-end
```

This will resolve fewer positions but every resolution will be high-confidence.

### Permissive (maximum resolution)

If you want to resolve as many ambiguities as possible and will review the QC report manually afterward:

```bash
python consensus_editor.py consensus.fasta reference.fasta \
  --min-coverage 20 \
  --min-percentage-diff 10 \
  --diagnostic
```

This resolves more positions but some calls may be marginal. Use the diagnostic log to review any position you are uncertain about.
