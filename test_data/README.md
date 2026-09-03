# Demo dataset

Two real Oxford Nanopore influenza A barcodes, the reference panel they were called
against, and the two configuration files the software reads. Everything needed to run the
pipeline end to end immediately after install.

## Contents

| Path | What it is |
|------|------------|
| `fastq_pass/barcode01/` | 145 `.fastq.gz` files (~36 MB) |
| `fastq_pass/barcode09/` | 145 `.fastq.gz` files (~16 MB) |
| `reference/infA_references.fasta` | 37 records: 18 HA subtypes (H1–H18), 11 NA subtypes (N1–N11), and PB2, PB1, PA, NP, MP, NS |
| `pipeline_config.json` | Nested schema, written by the GUI worker and read by the CLI |
| `ont_analyzer_config.json` | Flat schema, the GUI's own persisted settings |

Both config schemas are shipped on purpose: the pipeline reads either one. Where a nested
key is absent it falls back to the flat equivalent and prints a note naming the
substitution, so a run never silently uses a parameter you did not choose.

## Running it

```bash
cd test_data
bash <install-prefix>/app/src/degenresolve/scripts/main_with_config.sh pipeline_config.json
```

Or point the GUI's input directory at `test_data/` and press Start.

Both barcodes run in parallel with the shipped config (`parallel.threads: 8`). Expect
roughly 10–25 minutes depending on the machine; NanoPlot and Qualimap dominate.

## What to expect

**This directory already contains a completed run.** `results/` and `log/` hold the output of the reference run so you can compare against it without waiting. The pipeline resumes from whatever it finds, and a barcode whose `results/step_8_refined_consensus/` FASTA already exists is reported as complete and skipped. To force a genuine end-to-end run, move the existing output aside first:

```bash
mv results results_reference && mv log log_reference
```

Output lands in `results/` (steps 1–8) and `log/`. The numbers a bench scientist should
read first are in `results/reports/<barcode>_summary_report.html`:

- **Breadth ≥ 1×** and **zero-coverage positions** are now computed from a
  `samtools depth -a` file, so they reflect real coverage. If you point this at output
  from an older pipeline version the report will say `indeterminate` rather than showing
  a falsely perfect 100%.
- **Coverage** and **Usable_Coverage** are both printed in the diagnostic log. The second
  is the base-quality-filtered depth that `min_coverage` is actually judged against, and
  it can be several-fold lower than the first.
- The influenza segment table counts **primary alignments only**, so the percentages are a
  real composition and a single-subtype sample does not appear mixed.

**Case in the consensus FASTA carries meaning: lowercase = low confidence** (depth < 3 or
quality < 10), preserved from vcf2fq. In this dataset `barcode01` comes out 0.3%
soft-masked and `barcode09` **60.2%** - use that to judge the sample before trusting its
sequence. Uppercase with `seqtk seq -U` before archive submission.

`reference/infA_references.fasta` uses the `H5_`/`N1_` naming convention. The `HA_`/`NA_`
convention used by the NCBI Influenza Virus Database is also accepted.
