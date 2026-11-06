//! Criterion timing of every script, both loops in one process.
//!
//! `PVB_LOOPS` (comma list, default `d3`) selects the loops. For each script
//! they run in this order:
//!
//! - `d3`: flat decode + eval per iteration (spec D3, `aiken.csv`). One
//!   top-level benchmark named after the script, so Criterion writes
//!   `<CRITERION_HOME>/<script>/new/estimates.json`.
//! - `eval`: eval only (`aiken-eval.csv`). The program is decoded once before
//!   timing; each iteration evaluates a clone of it on a new machine with a new
//!   budget. The clone is made in Criterion's untimed setup (`iter_batched`).
//!   Benchmark `eval/<script>`, so Criterion writes
//!   `<CRITERION_HOME>/eval/<script>/new/estimates.json`.
//!
//! In both loops the result is dropped inside the timed routine, as in the
//! amaru-uplc harness. `parsers/parse_criterion.py` reads `<CRITERION_HOME>`
//! for d3 (it skips the `eval` dir, which has no estimates of its own) and
//! `<CRITERION_HOME>/eval` for eval.
//!
//! Warm-up and measurement time come from the command line
//! (scripts/run-aiken.sh); scripts/run-aiken.sh runs one process per script.
//! A loop prints `PVB_LOOP <loop> <script>` before it starts
//! (`parsers/fill_failures.py --loop`). A script that fails its first
//! evaluation is printed as `EVAL_FAIL: <script>` and not timed.

use aiken_bench::{data_dir, decode, decode_and_eval, eval, scripts, silence_panics};
use criterion::{BatchSize, Criterion};
use std::hint::black_box;

fn main() {
    silence_panics();
    let loops = std::env::var("PVB_LOOPS").unwrap_or_else(|_| "d3".to_string());
    let loops: Vec<&str> = loops.split(',').map(str::trim).collect();
    let mut c = Criterion::default().configure_from_args();

    for (name, bytes) in scripts(&data_dir()) {
        match decode_and_eval(&bytes) {
            Ok(r) if r.result.is_ok() => {}
            Ok(r) => {
                println!("EVAL_FAIL: {name} ({:?})", r.result.err());
                continue;
            }
            Err(e) => {
                println!("EVAL_FAIL: {name} (decode: {e})");
                continue;
            }
        }
        if loops.contains(&"d3") {
            println!("PVB_LOOP d3 {name}");
            c.bench_function(&name, |b| {
                b.iter(|| drop(black_box(decode_and_eval(black_box(&bytes)))))
            });
        }
        if loops.contains(&"eval") {
            println!("PVB_LOOP eval {name}");
            // The first evaluation succeeded, so decoding does too.
            let program = decode(&bytes).expect("decode");
            let mut group = c.benchmark_group("eval");
            group.bench_function(&name, |b| {
                b.iter_batched(
                    || program.clone(),
                    |p| drop(black_box(eval(black_box(p)))),
                    BatchSize::SmallInput,
                )
            });
            group.finish();
        }
    }

    c.final_summary();
}
