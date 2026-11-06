// plutus-vm-benchmark harness for the released amaru-uplc crate. docs/IMAGE_CONTRACT.md, spec
// D3/D4/D11.
//
// Parameters (check/README.md, "Evaluation parameters"): PlutusV3, protocol version 11,
// counting mode (no limit), and the crate's default V3 cost model.
//
// Modes:
//   PVB_CHECK_OUT=<csv>  one evaluation per script, write vm,script,status,cpu,mem; no timing
//   otherwise            Criterion timing of the loops in PVB_LOOPS (comma list, default d3). For
//                        each script they run in this order:
//                        d3    flat decode + eval per iteration (amaru-uplc.csv); benchmark
//                              <name>, Criterion dir target/criterion/<name>/
//                        eval  evaluation only (amaru-uplc-eval.csv): the program is decoded once
//                              into its own arena before timing; each iteration evaluates it into
//                              a second arena, which is reset after every iteration. Each
//                              Program::eval call creates a fresh machine using ExBudget::max().
//                              Benchmark eval/<name>, Criterion dir target/criterion/eval/<name>/
//                        A loop prints "PVB_LOOP <loop> <name>" before it starts
//                        (parsers/fill_failures.py --loop). A script that fails its first
//                        evaluation prints "EVAL_FAIL: <name>" and is not timed.
// Warm-up and measurement time come from the command line (scripts/run-amaru-uplc.sh, which runs
// one process per script).
// PVB_DATA_DIR=<dir>: read the .flat files from <dir> instead of DATA_DIR (run-amaru-uplc.sh
// passes the selected scripts, $BENCH_DATA_DIR).

use amaru_kernel::{PlutusVersion, protocol_version::PROTOCOL_VERSION_11};
use amaru_uplc::{
    arena::Arena,
    binder::DeBruijn,
    flat,
    machine::{CostModel, ExBudget},
};
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
fn eval_once(
    arena: &Arena,
    bytes: &[u8],
    cost_model: &CostModel,
) -> Result<(i64, i64), (String, i64, i64)> {
    let (program, _) =
        flat::decode::<DeBruijn>(arena, bytes, PlutusVersion::V3, PROTOCOL_VERSION_11)
            .map_err(|e| (format!("decode: {e:?}"), 0, 0))?;
    let result = program.eval(arena, cost_model.clone(), ExBudget::max());
    let used = result.info.consumed_budget;
    if result.is_success() {
        Ok((used.cpu, used.mem))
    } else {
        Err((format!("{:?}", result.error()), used.cpu, used.mem))
    }
}

fn check(out: &str) {
    let cost_model = CostModel::v3();
    let mut arena = Arena::from_bump(Bump::with_capacity(1_048_576));
    let mut csv = String::from("vm,script,status,cpu,mem\n");
    for (name, bytes) in scripts() {
        let (status, cpu, mem) = match eval_once(&arena, &bytes, &cost_model) {
            Ok((cpu, mem)) => ("ok", cpu, mem),
            Err((msg, cpu, mem)) => {
                let msg: String = msg.chars().take(200).collect();
                println!("CHECK_FAIL: {name}: {msg}");
                ("error", cpu, mem)
            }
        };
        arena.reset();
        csv.push_str(&format!("amaru-uplc,{name},{status},{cpu},{mem}\n"));
    }
    fs::File::create(out)
        .and_then(|mut f| f.write_all(csv.as_bytes()))
        .unwrap_or_else(|e| panic!("cannot write {out}: {e}"));
}

fn bench(c: &mut Criterion, loops: &[&str]) {
    let cost_model = CostModel::v3();
    let mut arena = Arena::from_bump(Bump::with_capacity(10_485_760));
    for (name, bytes) in scripts() {
        // A panic inside b.iter would abort the whole run: evaluate once first, skip on failure.
        let first = eval_once(&arena, &bytes, &cost_model);
        arena.reset();
        if let Err((msg, _, _)) = first {
            let msg: String = msg.chars().take(200).collect();
            println!("EVAL_FAIL: {name}");
            println!("  {msg}");
            continue;
        }
        if loops.contains(&"d3") {
            println!("PVB_LOOP d3 {name}");
            let mut decode_arena = Arena::from_bump(Bump::with_capacity(10_485_760));
            let mut eval_arena = Arena::from_bump(Bump::with_capacity(10_485_760));
            c.bench_function(&name, |b| {
                b.iter(|| {
                    let (program, _) = flat::decode::<DeBruijn>(
                        &decode_arena,
                        &bytes,
                        PlutusVersion::V3,
                        PROTOCOL_VERSION_11,
                    )
                    .expect("decode");
                    let result = program.eval(&eval_arena, cost_model.clone(), ExBudget::max());
                    std::hint::black_box(result.is_success());
                    drop(result);
                    decode_arena.reset();
                    eval_arena.reset();
                })
            });
        }
        if loops.contains(&"eval") {
            println!("PVB_LOOP eval {name}");
            // The decoded program lives in its own arena for the whole benchmark of this script.
            let program_arena = Arena::from_bump(Bump::with_capacity(10_485_760));
            let (program, _) = flat::decode::<DeBruijn>(
                &program_arena,
                &bytes,
                PlutusVersion::V3,
                PROTOCOL_VERSION_11,
            )
            .expect("decode");
            let mut eval_arena = Arena::from_bump(Bump::with_capacity(10_485_760));
            let mut group = c.benchmark_group("eval");
            group.bench_function(&name, |b| {
                b.iter(|| {
                    let result = program.eval(&eval_arena, cost_model.clone(), ExBudget::max());
                    std::hint::black_box(result.is_success());
                    drop(result);
                    eval_arena.reset();
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
