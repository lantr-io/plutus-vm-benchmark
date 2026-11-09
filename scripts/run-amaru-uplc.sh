#!/bin/bash
# amaru-uplc: timing and check (docs/IMAGE_CONTRACT.md). Called by image-entry.sh.
#
#   run-amaru-uplc.sh <results-dir>
#
# pvb-loops: d3 eval check
# Runs the loops of $BENCH_LOOPS over the scripts in $BENCH_DATA_DIR; $BENCH_TIMING=quick shortens
# the timing. The check covers the same scripts.
set -euo pipefail

RUN_DIR="$1"
DATA_DIR="${BENCH_DATA_DIR:-/bench/data/plutus_use_cases}"
loop() { [[ ",${BENCH_LOOPS:-d3,eval,check}," == *",$1,"* ]]; }
BENCH_DIR="/bench/amaru-uplc"

echo "amaru-uplc AST (Rust / Criterion)"

# The bench binary is our harness (images/amaru-uplc/use_cases.rs): PlutusV3, protocol version 11,
# counting mode and amaru-uplc's default V3 cost model. Two Criterion loops with the same settings:
# flat decode + eval per iteration (amaru-uplc.csv) and eval of a program decoded once
# (amaru-uplc-eval.csv).

# Criterion settings (spec D13), Criterion.rs 0.8.2 with its
# default warm-up (3 s) and measurement time (5 s), 100 samples, no plots.
TIMING=(--warm-up-time 3 --measurement-time 5)
if [[ "${BENCH_TIMING:-normal}" == quick ]]; then
    TIMING=(--warm-up-time 1 --measurement-time 1)
fi
echo "Criterion options: ${TIMING[*]} --noplot"

# Criterion writes its output below the image's working directory.
cd "$BENCH_DIR"

# Run Criterion benchmark (binary already compiled in build stage)
BENCH_BIN="$BENCH_DIR/bin/use_cases"
if [[ ! -x "$BENCH_BIN" ]]; then
    echo "ERROR: could not find use_cases benchmark binary" | tee "$RUN_DIR/amaru-uplc-raw.log"
    exit 1
fi

run_check() {
    # Spec D4: one evaluation per script with the timed loop's parameters.
    PVB_DATA_DIR="$DATA_DIR" PVB_CHECK_OUT="$RUN_DIR/amaru-uplc-check.csv" "$BENCH_BIN" 2>&1 \
        | tee "$RUN_DIR/amaru-uplc-check.log"
    echo "Wrote $RUN_DIR/amaru-uplc-check.csv"
}

# The timed loops. One process per script (spec D14), so no allocator state carries from one
# script to the next. The process runs the requested loops of its script, d3 first, then eval
# (PVB_LOOPS, images/amaru-uplc/use_cases.rs). It gets a data dir with only its script, because the
# harness evaluates every file of its data dir once before timing; so it defines only that
# script's benchmarks. Criterion writes the d3 loop to target/criterion/<name>/ and the eval loop
# to target/criterion/eval/<name>/.
RAW="$RUN_DIR/amaru-uplc-raw.log"
LOOPS=()
if loop d3; then LOOPS+=(d3); fi
if loop eval; then LOOPS+=(eval); fi

# parse_loop <loop> <csv> <criterion copy dir>: the Criterion results of one loop -> <csv>, a -1
# row for each failed script.
parse_loop() {
    local csv="$2" copy="$3" src=target/criterion
    [[ "$1" == eval ]] && src=target/criterion/eval

    # Collect failed scripts
    local failed
    failed=$(grep "^EVAL_FAIL:" "$RAW" | sed 's/EVAL_FAIL: //' | sort -u || true)

    # Copy Criterion JSON output (remove old copy first to avoid cp -r nesting)
    rm -rf "$copy"
    cp -r "$src" "$copy" 2>/dev/null || true
    # The d3 copy holds the eval dir too; parse_criterion.py skips it (no estimates of its own).

    # Parse criterion output, filtering out scripts that failed evaluation
    python3 /bench/parsers/parse_criterion.py "$copy" > "$csv.raw" || true

    # Filter: remove bogus timings for failed scripts, then add -1 entries
    FAILED="$failed" python3 - "$csv.raw" "$csv" <<'PY' || true
import os, sys
src, dst = sys.argv[1:3]
failed = set(os.environ.get("FAILED", "").split())
with open(src) as f:
    lines = f.readlines()
with open(dst, "w") as out:
    out.write(lines[0])  # header
    for line in lines[1:]:
        script = line.split(",")[1] if "," in line else ""
        if script not in failed:
            out.write(line)
    for script in sorted(failed):
        if script:
            out.write(f"amaru-uplc,{script},-1,-1,-1,-1,-1,0\n")
PY
    rm -f "$csv.raw"

    # Fill in -1 for any scripts that were given but produced no result
    python3 /bench/parsers/fill_failures.py "$csv" "$DATA_DIR" amaru-uplc "$RAW" --loop "$1"
}

if [[ ${#LOOPS[@]} -gt 0 ]]; then
    # Clear previous criterion output to avoid stale results
    rm -rf target/criterion
    : > "$RAW"
    work=$(mktemp -d /tmp/amaru-uplc-one.XXXXXX)
    for flat in "$DATA_DIR"/*.flat; do
        name=$(basename "$flat" .flat)
        mkdir -p "$work/$name"
        ln -sf "$flat" "$work/$name/"
        # $BASHPID is the pid of the subshell, which exec turns into the benchmark process.
        ( echo "--- $name: process $BASHPID"
          exec env PVB_LOOPS="$(IFS=,; echo "${LOOPS[*]}")" PVB_DATA_DIR="$work/$name" \
              UPLC_BENCH_MODE=ast "$BENCH_BIN" --bench --noplot "${TIMING[@]}" ) 2>&1 | tee -a "$RAW" || true
    done
    rm -rf "$work"
    if loop d3; then parse_loop d3 "$RUN_DIR/amaru-uplc.csv" "$RUN_DIR/criterion-output-ast"; fi
    if loop eval; then parse_loop eval "$RUN_DIR/amaru-uplc-eval.csv" "$RUN_DIR/criterion-output-eval"; fi
fi

if loop check; then run_check || echo "WARNING: amaru-uplc check failed" >&2; fi
