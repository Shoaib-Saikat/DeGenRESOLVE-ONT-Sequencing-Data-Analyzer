# Changelog

## 1.0.0 - first public release

This is the first public release. It follows an audit of the whole codebase; the defects
listed below were found and fixed before release. They are recorded because **output
produced by pre-release builds of 1.0.0 is not comparable with output from this release**.
Several fixes change published QC figures, and one changes sequence content.

### Fixed: these change reported numbers

- **Coverage breadth was structurally 100%.** `samtools depth` ran without `-a`, so the
  depth file contained no zero-depth rows and the report could not compute breadth or
  zero-coverage. Every barcode showed "Breadth ≥ 1× 100.0%" and "Zero Coverage 0"
  regardless of the real result. The reporter now also detects a depth file written the old
  way and reports `indeterminate` rather than republishing a false 100%.
  (`_clean_master_cmd_with_config.sh`, `html_reporter.parse_coverage`)

- **Homopolymer detection had an effective radius of 1 base, not 5**, and clipped reported
  run length at `2*window+1`. The scan region was sliced at `pos ± window`, truncating runs
  at the boundary; a true 20-mer poly-A was reported as length 11, and a site two bases past
  a 5-mer was reported as having no homopolymer at all, exactly the positions most prone to
  ONT indel artefacts. (`consensus_editor.compute_homopolymer_metrics`)

- **The read-end enrichment score counted every read overlapping a position**, not reads
  carrying the variant, making it a property of the amplicon rather than of the variant. It
  now filters to the minority allele. **Scores are not comparable with earlier runs**, and
  `strict_read_end` reverts calls on this metric. (`consensus_editor.compute_read_end_enrichment`)

- **Quality-filtered depth was computed and discarded.** The report published raw pileup
  depth as "Coverage" while `min_coverage` was judged against base-quality-filtered depth,
  numbers that can differ several-fold. Both are now published, as `Coverage` and
  `Usable_Coverage`. (`consensus_editor`, `SiteMetrics`)

- **"Resolved to Insertion" was always 0.** The report parser searched the per-site table
  for a string no code path emits. The reporter now reads the consensus editor's QC JSON and
  falls back to log scraping only for older runs. (`html_reporter`)

- **Segment-level report rows could be dropped or mis-attributed** because the per-segment
  regex required a trailing "Resolution rate:" line that is omitted for segments with zero
  degeneracies. (`html_reporter`)

- **Residual ambiguity counted only the literal base `N`**, reporting zero remaining
  ambiguity for sequences full of R/Y/S/W/K/M, the tool's actual output. GC% now excludes
  ambiguous positions from its denominator. (`html_reporter.parse_consensus_fasta`)

- **The influenza segment table counted secondary alignments.** minimap2 ran without
  `--secondary=no` against a 37-record cross-reactive panel, so one read produced hits on
  several subtypes, percentages summed past 100%, and a single-subtype sample could look
  like a mixed infection. Consensus calling was never affected: pysam's `all` stepper
  already excludes secondary alignments, so no base changes from this fix.
  (`_clean_master_cmd_with_config.sh`)

- **A barcode with a missing or unreadable diagnostic log was published as
  "0 ambiguous / 0 resolved"**, the best-looking row in the summary, instead of N/A. A
  zero-byte consensus FASTA also counted as "Complete". (`html_reporter`)

- **Major_Base was fabricated as `A` at columns where no base passed the quality filter**,
  because all four bases were ranked including zero counts. (`get_pileup_statistics`)

### Fixed: this changes sequence content

- **Segments with no aligned reads were published as verbatim reference sequence.** The
  zero-coverage mask used `samtools depth -a`, which omits reference records that received
  no reads at all; `-aa` is required. With the 37-record panel a typical sample maps to ~8
  records, so ~29 segments were emitted from the reference into
  `results/step_7_draft_consensus/` as though they were sequencing data.
  (`combined_consensus_script.sh`)

- **A degenerate site could resolve to a base outside its own ambiguity code's allele set**.
  For example, majority `C` at a site called `R` (A/G). The code's allele set was looked up and never
  consulted. Such sites are now kept and flagged as an allele-set conflict rather than
  silently resolved, since they represent disagreement between the variant caller and the
  pileup. (`consensus_editor`)

- **vcf2fq's low-confidence soft-mask was destroyed** by an unconditional `.upper()`, so
  positions with depth < 3 or quality < 10 were published as confident calls. The mask is now
  preserved for every position the editor did not positively resolve. (`consensus_editor`)

  **This is the most visible change in the release.** Consensus FASTAs now contain lowercase
  bases where support was thin. No base identity changed - only the case. On the demo data
  `barcode01` is 0.3% lowercase and `barcode09` is 60.2%, information that was previously
  invisible. If a downstream tool or archive submission requires uppercase, convert with
  `seqtk seq -U` and report the masked fraction alongside. See "Reading the consensus FASTA"
  in README.md.

### Fixed: reliability

- Quitting or stopping mid-run left the entire pipeline running as a detached orphan.
  Stop now escalates SIGTERM → SIGKILL across the process group, a watchdog observes the
  stop flag during quiet phases instead of only between output lines, and close waits for
  the pool to drain. Cancellation is reported as cancellation, not as analysis failure.
- Changing the input directory mid-run replaced the processor object, orphaning the stop
  flag the running worker polls; this is now refused while a run is live.
- The GUI could not load the config the pipeline itself writes (`TypeError: unhashable
  type: 'dict'`). Both the flat and nested schemas are now accepted, by the GUI and by the
  CLI, and any fallback is announced rather than silently applied.
- A saved degeneracy threshold of 1% reloaded as 100%, inverting the resolution rule.
- `set -e` without `pipefail` discarded the exit status of the left side of
  `samtools view | samtools sort`, so a truncated BAM passed silently to later stages.
- A barcode job killed before writing its status line was never noticed; a run in which
  every job died reported success.
- The reproducibility receipt hashed command output, so a missing artefact recorded the md5
  of the empty string, indistinguishable from a real checksum.
- A resume that needed to rebuild the BAM set the step counter such that the rebuild was
  skipped, and the job then died on the missing file.
- Malformed JSON raised `TypeError` from the error handler instead of the intended
  `JSONDecodeError`, naming no file.
- Subprocess output was decoded as strict UTF-8; one stray byte aborted a healthy run.
- The HTML reports performed no escaping at all.
- The shared cross-sample summary was written non-atomically from every parallel barcode.

### Changed

- `setup.py` now declares `python_requires>=3.10`. The consensus editor uses PEP 604
  `str | None` annotations evaluated at import; 3.8/3.9 never worked despite being advertised.
- External tool versions are checked at validation time. bcftools 1.21 is a hard floor:
  the sup profile passes `--indels-cns` and `--max-BQ`.
- The headless consensus-editor CLI no longer imports PyQt5, so it runs on a server with no
  GUI stack.
- `MANIFEST.in` added; an sdist previously failed to build because `setup.py` reads
  `requirements.txt` at build time and nothing shipped it.
- Documentation corrected throughout: `--min-coverage` (40 → 100), `--homopolymer-min-length`
  (3 → 5), `--homopolymer-window` (10 → 5), every GUI spinner range, the decision-engine
  flowchart (which still described a removed pileup-based indel branch), the Coverage /
  Major_AF% / Strand_Balance column definitions, and the warning-token names.
- `--major-h` / `--major-n` now actually override subtype selection instead of only
  reordering output, and accept the documented bare form (`H5`) as well as full record names.

### Known limitations

- The test suite covers pure functions and the two shell guards. It does not execute the
  pipeline end to end; use `test_data/` for that.
- pytest is not included in the packed environment. `pip install pytest` to run the suite.
- Qualimap requires Java, bundled in the offline environment.
