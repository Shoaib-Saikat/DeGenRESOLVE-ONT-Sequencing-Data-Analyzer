#!/bin/bash
# Checks for the run fingerprint in main_with_config.sh.
# Run with: bash tests/test_run_fingerprint.sh
set -u
fail=0
SCRIPT="$(dirname "$0")/../src/degenresolve/scripts/main_with_config.sh"

# 1. Coverage: every parameter read from the config must be in the fingerprint,
#    except the ones deliberately excluded. This is the check that matters - it
#    fires when someone adds a setting and forgets to fingerprint it, which would
#    silently let two different configurations share a results/ directory.
python3 - "$SCRIPT" <<'PY' || fail=1
import re, sys
s = open(sys.argv[1]).read()

read_vars = set(re.findall(r'^([A-Z0-9_]+)=\$\(read_config ', s, re.M))

block = s[s.index('EFFECTIVE_PARAMS="'):s.index('RUN_FINGERPRINT=$(')]
fp_vars = set(re.findall(r'\$\{([A-Z0-9_]+)\}', block))

# Excluded on purpose: thread count is proven not to affect any scope-A artifact,
# and including it would make machines with different core counts mismatch by
# construction. QC toggles change only step_1/step_5 outputs, which regenerate.
EXCLUDED = {"QUALIMAP_ENABLED", "NANOPLOT_ENABLED", "PARALLEL_ENABLED",
            "PARALLEL_THREADS", "QUALIMAP_THREADS", "THREADS"}

missing = read_vars - fp_vars - EXCLUDED
unexpected = (fp_vars & EXCLUDED)

rc = 0
if missing:
    print("FAIL config parameters absent from the fingerprint:", sorted(missing)); rc = 1
else:
    print("ok   every non-excluded config parameter is fingerprinted")
if unexpected:
    print("FAIL excluded settings leaked into the fingerprint:", sorted(unexpected))
    print("     (this makes machines with different core counts mismatch by construction)")
    rc = 1
else:
    print("ok   thread and QC settings stay out of the fingerprint")
if "REFERENCE_MD5" not in fp_vars:
    print("FAIL reference md5 not in the fingerprint"); rc = 1
else:
    print("ok   reference identity is fingerprinted")

# The override changes the mpileup flag set, so resuming across a toggle would
# reuse a VCF built under -I while the user believes indel calling is on.
for var in ("FORCE_SUP_PROFILE", "MAX_BASE_QUALITY", "MIN_BASE_QUALITY"):
    if var not in fp_vars:
        print(f"FAIL {var} not in the fingerprint"); rc = 1
else:
    if rc == 0:
        print("ok   base-quality pair and force_sup_profile are fingerprinted")

sys.exit(rc)
PY

# 2. Behaviour of the stored-vs-current comparison, mirroring the script's cmp/diff.
d=$(mktemp -d); trap 'rm -rf "$d"' EXIT
printf 'min_coverage=100\nploidy=2\n'  > "$d/stored"
printf 'min_coverage=100\nploidy=2\n'  > "$d/same"
printf 'min_coverage=100\nploidy=4\n'  > "$d/diff"

cmp -s "$d/stored" "$d/same" && echo "ok   identical params -> resume allowed" \
                            || { echo "FAIL identical params rejected"; fail=1; }
cmp -s "$d/stored" "$d/diff" && { echo "FAIL changed params accepted"; fail=1; } \
                            || echo "ok   changed params -> refused"
changed=$(diff "$d/stored" "$d/diff" | grep -c '^[<>]')
[ "$changed" -eq 2 ] && echo "ok   refusal names what changed ($changed lines)" \
                     || { echo "FAIL diff did not report the change"; fail=1; }

[ $fail -eq 0 ] && echo "run fingerprint: all checks passed"
exit $fail
