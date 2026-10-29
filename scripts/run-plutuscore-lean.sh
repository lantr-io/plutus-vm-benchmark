#!/bin/bash
# PlutusCoreBlaster: native Lean CEK benchmark. images/plutuscore-lean/README.md.
# pvb-loops: d3 eval check
set -uo pipefail

VM=plutuscore-lean
RUN_DIR="$1"
DATA_DIR="${BENCH_DATA_DIR:-/bench/data/plutus_use_cases}"
BENCH=/bench/plutuscore-lean/bench_cek
RAW="$RUN_DIR/$VM-raw.log"
loop() { [[ ",${BENCH_LOOPS:-d3,eval,check}," == *",$1,"* ]]; }

{
    echo "PlutusCoreBlaster (Lean native) @${PLUTUSCORE_LEAN_SHA:-unknown}"
    echo "BENCH_LOOPS=${BENCH_LOOPS:-d3,eval,check} BENCH_TIMING=${BENCH_TIMING:-normal}"
} | tee "$RAW"

if loop check; then
    echo 'vm,script,status,cpu,mem' > "$RUN_DIR/$VM-check.csv"
    for flat in "$DATA_DIR"/*.flat; do
        name=$(basename "$flat" .flat)
        # One process per script: a crash, decode failure or exhausted step limit leaves
        # an explicit failed row. Never invent ExUnits for an incomplete evaluation.
        if row=$("$BENCH" check "$flat" 2>>"$RAW"); then
            echo "$row" >> "$RUN_DIR/$VM-check.csv"
        else
            echo "$VM,$name,error,," >> "$RUN_DIR/$VM-check.csv"
        fi
    done
fi

MEASURE_MS=5000
[[ "${BENCH_TIMING:-normal}" == quick ]] && MEASURE_MS=1000
LOOPS=()
if loop d3; then LOOPS+=(d3); fi
if loop eval; then LOOPS+=(eval); fi

if [[ ${#LOOPS[@]} -gt 0 ]]; then
    for flat in "$DATA_DIR"/*.flat; do
        name=$(basename "$flat" .flat)
        ( echo "--- $name: process $BASHPID"
          exec "$BENCH" time "$flat" "$(IFS=,; echo "${LOOPS[*]}")" "$MEASURE_MS" ) \
            2>&1 | tee -a "$RAW" || true
    done
    write_loop() {
        local which="$1" output="$2"
        echo 'vm,script,mean_ns,median_ns,min_ns,max_ns,stddev_ns,iterations' > "$output"
        # The native executable already writes escaped rows in the common CSV schema.
        sed -n "s/^PVB_RESULT $which //p" "$RAW" >> "$output"
        python3 /bench/parsers/fill_failures.py "$output" "$DATA_DIR" "$VM" "$RAW" --loop "$which"
    }
    if loop d3; then write_loop d3 "$RUN_DIR/$VM.csv"; fi
    if loop eval; then write_loop eval "$RUN_DIR/$VM-eval.csv"; fi
fi
