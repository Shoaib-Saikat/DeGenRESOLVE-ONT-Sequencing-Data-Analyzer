#!/bin/bash
# Check for the coordinate guard in combined_consensus_script.sh (-m path).
# Run with: bash tests/test_coordinate_guard.sh
#
# consensus_editor.py maps consensus position i onto reference position i.
# -c path: vcfutils.pl vcf2fq pads uncovered positions with N starting at position 1,
#          so the mapping survives 5' gaps, internal gaps and 3' truncation. Verified
#          on barcode09 PB2: 2292 bases, first 1557 all N, 735 covered bases at their
#          correct offsets. Nothing to guard.
# -m path: bcftools consensus APPLIES indels, changing length and shifting every base
#          after one. That is the case this guard catches.
set -u
fail=0

# Same python the guard runs: report segments whose consensus length != reference.
lencheck() { # fai fasta
  python3 -c "
import sys
ref = {}
for line in open(sys.argv[1]):
    f = line.split('\t'); ref[f[0]] = int(f[1])
name, n, out = None, 0, []
def flush():
    if name is not None and ref.get(name) is not None and n != ref[name]:
        out.append('  %s consensus=%d reference=%d' % (name, n, ref[name]))
for line in open(sys.argv[2]):
    if line.startswith('>'):
        flush(); name = line[1:].split()[0]; n = 0
    else:
        n += len(line.strip())
flush()
print('\n'.join(out))
" "$1" "$2"
}

d=$(mktemp -d); trap 'rm -rf "$d"' EXIT
printf 'SEG_A\t20\t0\t20\t21\nSEG_B\t10\t0\t10\t11\n' > "$d/ref.fai"

check() { # name expectation fasta_body
  local name="$1" want="$2" out
  printf '%s\n' "$3" > "$d/cons.fa"
  out=$(lencheck "$d/ref.fai" "$d/cons.fa")
  if [ "$want" = pass ] && [ -n "$out" ]; then
    echo "FAIL $name: expected pass, flagged:"; echo "$out"; fail=1
  elif [ "$want" = flag ] && [ -z "$out" ]; then
    echo "FAIL $name: expected flag, passed"; fail=1
  else
    echo "ok   $name"
  fi
}

check "lengths match reference" pass \
  ">SEG_A
AAAAAAAAAAAAAAAAAAAA
>SEG_B
CCCCCCCCCC"

check "insertion applied (longer)" flag \
  ">SEG_A
AAAAAAAAAAAAAAAAAAAAAAA
>SEG_B
CCCCCCCCCC"

check "deletion applied (shorter)" flag \
  ">SEG_A
AAAAAAAAAAAAAAAA
>SEG_B
CCCCCCCCCC"

check "one bad among good" flag \
  ">SEG_A
AAAAAAAAAAAAAAAAAAAA
>SEG_B
CCCCCCCCCCCC"

check "unknown segment ignored" pass \
  ">SEG_A
AAAAAAAAAAAAAAAAAAAA
>SEG_B
CCCCCCCCCC
>SEG_UNKNOWN
GGG"

[ $fail -eq 0 ] && echo "coordinate guard: all checks passed"
exit $fail
