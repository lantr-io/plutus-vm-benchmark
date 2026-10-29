// plutus-vm-benchmark harness for Amaru UPLC (image id uplc-turbo). Replaces
// crates/amaru-uplc/benches/use_cases/main.rs
// of the pinned repo (images/uplc-turbo/Dockerfile). docs/IMAGE_CONTRACT.md, spec D3/D4/D11.
//
// Parameters (check/README.md, "Evaluation parameters"): PlutusV3, protocol version 11,
// counting mode (no limit), mainnet PlutusV3 cost model.
//
// Cost model: the timed loop uses Program::eval_version_budget(V3), which selects the default
// protocol 11 cost model. The check also evaluates every script with the mainnet parameter array
// through CostModel::new and reports any difference as COSTMODEL_DRIFT and an error row.
//
// Modes:
//   PVB_CHECK_OUT=<csv>  one evaluation per script, write vm,script,status,cpu,mem; no timing
//   otherwise            Criterion timing of the loops in PVB_LOOPS (comma list, default d3). For
//                        each script they run in this order:
//                        d3    flat decode + eval per iteration (uplc-turbo.csv); benchmark
//                              <name>, Criterion dir target/criterion/<name>/
//                        eval  evaluation only (uplc-turbo-eval.csv): the program is decoded once
//                              into its own arena before timing; each iteration evaluates it into
//                              a second arena, which is reset after every iteration. The machine
//                              and its budget are new on every call (Program::eval_version_budget).
//                              Benchmark eval/<name>, Criterion dir target/criterion/eval/<name>/
//                        A loop prints "PVB_LOOP <loop> <name>" before it starts
//                        (parsers/fill_failures.py --loop). A script that fails its first
//                        evaluation prints "EVAL_FAIL: <name>" and is not timed.
// Warm-up and measurement time come from the command line (scripts/run-uplc-turbo.sh, which runs
// one process per script).
// PVB_COSTMODEL=<file>: the mainnet PlutusV3 array, one integer per line (run-uplc-turbo.sh).
// PVB_DATA_DIR=<dir>: read the .flat files from <dir> instead of DATA_DIR (run-uplc-turbo.sh
// passes the selected scripts, $BENCH_DATA_DIR).

use amaru_kernel::{protocol_version::PROTOCOL_VERSION_11, PlutusVersion};
use amaru_uplc::{arena::Arena, binder::DeBruijn, flat, machine::{CostModel, ExBudget}};
use bumpalo::Bump;
use criterion::Criterion;
use std::{fs, io::Write, path::PathBuf};

const DATA_DIR: &str = "benches/use_cases/plutus_use_cases";
fn scripts() -> Vec<(String, Vec<u8>)> {
    let dir = std::env::var("PVB_DATA_DIR").unwrap_or_else(|_| DATA_DIR.to_string());
    let mut paths: Vec<PathBuf> = fs::read_dir(&dir)
        .unwrap_or_else(|e| panic!("cannot read {dir}: {e}"))
        .map(|e| e.unwrap().path())
        .filter(|p| p.is_file() && p.extension().is_some_and(|x| x == "flat"))
        .collect();
    paths.sort();
    paths
        .into_iter()
        .map(|p| {
            let name = p.file_stem().unwrap().to_str().unwrap().to_string();
            (name, fs::read(&p).unwrap())
        })
        .collect()
}

/// One evaluation as in the timed loop. Ok((cpu, mem)) or Err((message, cpu, mem)).
fn eval_once(arena: &Arena, bytes: &[u8]) -> Result<(i64, i64), (String, i64, i64)> {
    let (program, _) = flat::decode::<DeBruijn>(arena, bytes, PlutusVersion::V3, PROTOCOL_VERSION_11)
        .map_err(|e| (format!("decode: {e:?}"), 0, 0))?;
    let result = program.eval_version_budget(arena, PlutusVersion::V3, ExBudget::max());
    let used = result.info.consumed_budget;
    match result.term {
        Ok(_) => Ok((used.cpu, used.mem)),
        Err(e) => Err((format!("{e:?}"), used.cpu, used.mem)),
    }
}

/// The same evaluation with the mainnet array passed in.
fn eval_mainnet(arena: &Arena, bytes: &[u8], cost_model: &[i64]) -> Option<(bool, i64, i64)> {
    let (program, _) =
        flat::decode::<DeBruijn>(arena, bytes, PlutusVersion::V3, PROTOCOL_VERSION_11).ok()?;
    let result = program.eval(
        arena,
        CostModel::new(PlutusVersion::V3, PROTOCOL_VERSION_11, cost_model),
        ExBudget::max(),
    );
    let used = result.info.consumed_budget;
    Some((result.term.is_ok(), used.cpu, used.mem))
}

fn load_cost_model() -> Vec<i64> {
    let path = std::env::var("PVB_COSTMODEL").expect("set PVB_COSTMODEL");
    let values: Vec<i64> = fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("cannot read {path}: {e}"))
        .split_whitespace()
        .map(|s| s.parse().unwrap())
        .collect();
    assert_eq!(values.len(), 350, "{path}: expected the 350 PlutusV3 parameters");
    values
}

fn check(out: &str) {
    let cost_model = load_cost_model();
    let mut arena = Arena::from_bump(Bump::with_capacity(1_048_576));
    let mut csv = String::from("vm,script,status,cpu,mem\n");
    for (name, bytes) in scripts() {
        let (mut status, cpu, mem) = match eval_once(&arena, &bytes) {
            Ok((cpu, mem)) => ("ok", cpu, mem),
            Err((msg, cpu, mem)) => {
                let msg: String = msg.chars().take(200).collect();
                println!("CHECK_FAIL: {name}: {msg}");
                ("error", cpu, mem)
            }
        };
        arena.reset();
        let mainnet = eval_mainnet(&arena, &bytes, &cost_model);
        arena.reset();
        if mainnet != Some((status == "ok", cpu, mem)) {
            println!(
                "COSTMODEL_DRIFT: {name}: default V3 model gives ({status}, {cpu}, {mem}), \
                 mainnet array gives {mainnet:?}"
            );
            status = "error";
        }
        csv.push_str(&format!("uplc-turbo,{name},{status},{cpu},{mem}\n"));
    }
    fs::File::create(out)
        .and_then(|mut f| f.write_all(csv.as_bytes()))
        .unwrap_or_else(|e| panic!("cannot write {out}: {e}"));
}

fn bench(c: &mut Criterion, loops: &[&str]) {
    let mut arena = Arena::from_bump(Bump::with_capacity(1_048_576));
    for (name, bytes) in scripts() {
        // A panic inside b.iter would abort the whole run: evaluate once first, skip on failure.
        let first = eval_once(&arena, &bytes);
        arena.reset();
        if let Err((msg, _, _)) = first {
            let msg: String = msg.chars().take(200).collect();
            println!("EVAL_FAIL: {name}");
            println!("  {msg}");
            continue;
        }
        if loops.contains(&"d3") {
            println!("PVB_LOOP d3 {name}");
            c.bench_function(&name, |b| {
                b.iter(|| {
                    let (program, _) = flat::decode::<DeBruijn>(
                        &arena,
                        &bytes,
                        PlutusVersion::V3,
                        PROTOCOL_VERSION_11,
                    )
                    .expect("decode");
                    let result =
                        program.eval_version_budget(&arena, PlutusVersion::V3, ExBudget::max());
                    std::hint::black_box(result.term.is_ok());
                    arena.reset();
                })
            });
        }
        if loops.contains(&"eval") {
            println!("PVB_LOOP eval {name}");
            // The decoded program lives in its own arena for the whole benchmark of this script.
            let program_arena = Arena::from_bump(Bump::with_capacity(1_048_576));
            let (program, _) = flat::decode::<DeBruijn>(
                &program_arena,
                &bytes,
                PlutusVersion::V3,
                PROTOCOL_VERSION_11,
            )
            .expect("decode");
            let mut group = c.benchmark_group("eval");
            group.bench_function(&name, |b| {
                b.iter(|| {
                    let result =
                        program.eval_version_budget(&arena, PlutusVersion::V3, ExBudget::max());
                    std::hint::black_box(result.term.is_ok());
                    drop(result);
                    arena.reset();
                })
            });
            group.finish();
        }
    }
}

fn main() {
    if let Ok(out) = std::env::var("PVB_CHECK_OUT") {
        check(&out);
        return;
    }
    let loops = std::env::var("PVB_LOOPS").unwrap_or_else(|_| "d3".to_string());
    let loops: Vec<&str> = loops.split(',').map(str::trim).collect();
    let mut c = Criterion::default().configure_from_args();
    bench(&mut c, &loops);
    c.final_summary();
}
