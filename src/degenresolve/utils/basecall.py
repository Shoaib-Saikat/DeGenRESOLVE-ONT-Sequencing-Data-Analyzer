#!/usr/bin/env python3
"""Basecall model detection and input fingerprinting.

One implementation, two callers: the GUI reads barcode directories directly to
show the detected tier before a run, and the pipeline shells out to the
--awk-compat mode on the merged FASTQ. They must never disagree, because the
tier decides the mpileup flag set - see combined_consensus_script.sh.
"""

import glob
import gzip
import os
import re
import sys
from collections import Counter

MODEL_RE = re.compile(r'basecall_model_version_id=([^\s]+)')

# fast and unknown deliberately resolve to the hac flag set: it carries -I, so
# they cannot introduce a bad indel.
TIERS = (('sup', 'sup'), ('hac', 'hac'), ('fast', 'fast'))


def tier_for(model):
    """Map a basecall model version id onto a flag-set tier."""
    if not model:
        return 'unknown'
    low = model.lower()
    for needle, tier in TIERS:
        if needle in low:
            return tier
    return 'unknown'


def _open(path):
    return gzip.open(path, 'rt', errors='replace') if path.endswith('.gz') \
        else open(path, 'r', errors='replace')


def scan_models(paths):
    """Count basecall models across FASTQ files.

    Returns (models, total_reads). Header lines are every 4th line; a read with
    no model id is counted in total_reads but not in models, which is what makes
    'no id anywhere' distinguishable from 'mixed ids'.
    """
    models = Counter()
    total = 0
    for path in paths:
        try:
            with _open(path) as fh:
                for i, line in enumerate(fh):
                    if i % 4:
                        continue
                    total += 1
                    m = MODEL_RE.search(line)
                    if m:
                        models[m.group(1)] += 1
        except OSError:
            continue
    return models, total


def detect(paths):
    """Detection result for one barcode's FASTQ files."""
    models, total = scan_models(paths)
    model, count = models.most_common(1)[0] if models else ('unknown', 0)
    return {
        'model': model,
        'count': count,
        'total': total,
        'distinct': len(models),
        'tier': tier_for(model) if models else 'unknown',
        'models': dict(models),
    }


def barcode_files(barcode_dir):
    return sorted(glob.glob(os.path.join(barcode_dir, '*.fastq.gz')) +
                  glob.glob(os.path.join(barcode_dir, '*.fastq')))


def input_signature(barcode_dir):
    """Cheap fingerprint of a barcode's input files.

    stat-based rather than content-based: the merged FASTQ this would otherwise
    hash does not exist until step 1, which is too late to guard step 1. False
    positives only ever force a clean re-run, which is the safe direction.
    """
    files = barcode_files(barcode_dir)
    size = 0
    newest = 0
    for f in files:
        try:
            st = os.stat(f)
        except OSError:
            continue
        size += st.st_size
        newest = max(newest, int(st.st_mtime))
    return f"{len(files)}:{size}:{newest}"


def main(argv):
    """--awk-compat <fastq>: print 'model count total distinct' for the shell.

    Replaces the awk block that used to live in _clean_master_cmd_with_config.sh;
    the output shape is unchanged so the surrounding shell logic still applies.
    """
    if len(argv) >= 3 and argv[1] == '--awk-compat':
        r = detect([argv[2]])
        print(f"{r['model']} {r['count']} {r['total']} {r['distinct']}")
        return 0
    if len(argv) >= 3 and argv[1] == '--signature':
        print(input_signature(argv[2]))
        return 0
    if len(argv) >= 2:
        r = detect(barcode_files(argv[1]))
        print(f"{r['model']}\t{r['tier']}\t{r['count']}/{r['total']}\t"
              f"distinct={r['distinct']}\tsig={input_signature(argv[1])}")
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
