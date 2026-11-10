// plutus-vm-benchmark harness for uplc-turbo-bc, the bytecode VM of uplc-turbo. Replaces
// crates/uplc/benches/use_cases/main.rs of the pinned repo (images/uplc-turbo-bc/Dockerfile).
// docs/IMAGE_CONTRACT.md, spec D3/D4/D11. Model: images/uplc-turbo/use_cases.rs (the AST walker).
//
// The bytecode VM (amaru_uplc::bytecode) exists only in jonathanlim222/uplc (closed PR
// pragma-org/uplc#47). Each evaluation is: flat decode, compile the term to bytecode
// (bytecode::compiler::compile), run it (bytecode::vm::execute).
//
// Parameters (check/README.md, "Evaluation parameters"): PlutusV3, protocol version 11 (gated
// flat::decode), V3 builtin semantics, a budget too large to run out (ExBudget::max()), mainnet
// PlutusV3 cost model.
//
// Cost model: built once from the mainnet array (CostModel::initialize_cost_model) and passed by
// reference for every evaluation. The crate's CostModel::default() for V3 is not the mainnet
// model: its CPU budgets differ from the Haskell reference on every script. The pinned crate knows
// the first 297 PlutusV3 parameters only (cost_map.rs): with any other length it drops the bitwise
// builtins' parameters, and the costs of the later builtins are fixed in builtin_costs_v3.rs. So
// it gets the first 297 of the 350 mainnet values. The check (gate) proves the budgets equal
// Haskell's.
//
// Modes:
//   PVB_CHECK_OUT=<csv>  one evaluation per script, write vm,script,status,cpu,mem; no timing
//   otherwise            Criterion timing of the loops in PVB_LOOPS (comma list, default d3). For
//                        each script they run in this order:
//                        d3    flat decode + compile + execute per iteration (uplc-turbo-bc.csv);
//                              benchmark <name>, Criterion dir target/criterion/<name>/
//                        eval  execute only (uplc-turbo-bc-eval.csv): the program is decoded and
//                              compiled once into its own arena before timing; each iteration
//                              executes it into a second arena, which is reset after every
//                              iteration. The machine and its budget are new on every call.
//                              Benchmark eval/<name>, Criterion dir target/criterion/eval/<name>/
//                        A loop prints "PVB_LOOP <loop> <name>" before it starts
//                        (parsers/fill_failures.py --loop). A script that fails its first
//                        evaluation prints "EVAL_FAIL: <name>" and is not timed.
// Warm-up and measurement time come from the command line (scripts/run-uplc-turbo-bc.sh, which
// runs one process per script).
// PVB_COSTMODEL=<file>: the mainnet PlutusV3 array, one integer per line (run-uplc-turbo-bc.sh).
// PVB_DATA_DIR=<dir>: read the .flat files from <dir> instead of DATA_DIR (run-uplc-turbo-bc.sh
// passes the selected scripts, $BENCH_DATA_DIR).

use amaru_uplc::{
    arena::Arena,
    binder::DeBruijn,
    bytecode::{compiler, vm, CompiledProgram},
    flat,
    machine::{
        cost_model::builtin_costs::builtin_costs_v3::BuiltinCostsV3, BuiltinSemantics, CostModel,
        ExBudget, PlutusVersion,
    },
    program::Program,
};
use bumpalo::Bump;
use criterion::Criterion;
use std::{fs, io::Write, path::PathBuf};

const VM: &str = "uplc-turbo-bc";
const DATA_DIR: &str = "benches/use_cases/plutus_use_cases";
const PROTOCOL_MAJOR: u32 = 11;
// The PlutusV3 parameters the pinned crate maps (see the header).
const KNOWN_PARAMS: usize = 297;

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

fn decode<'a>(arena: &'a Arena, bytes: &[u8]) -> Result<&'a Program<'a, DeBruijn>, String> {
    flat::decode::<DeBruijn>(arena, bytes, PlutusVersion::V3, PROTOCOL_MAJOR)
        .map_err(|e| format!("decode: {e:?}"))
}

fn compile<'a>(program: &'a Program<'a, DeBruijn>) -> CompiledProgram<'a> {
    let v = program.version;
    compiler::compile((v.major(), v.minor(), v.patch()), program.term)
}

/// One run of a compiled program. Ok((cpu, mem)) or Err((message, cpu, mem)).
fn execute<'a>(
    arena: &'a Arena,
    compiled: &'a CompiledProgram<'a>,
    cost_model: &CostModel<BuiltinCostsV3>,
) -> Result<(i64, i64), (String, i64, i64)> {
    let result = vm::execute(
        arena,
        compiled,
        ExBudget::max(),
        cost_model,
        BuiltinSemantics::from(&PlutusVersion::V3),
    );
    let used = result.info.consumed_budget;
    match result.term {
        Ok(_) => Ok((used.cpu, used.mem)),
        Err(e) => Err((format!("{e:?}"), used.cpu, used.mem)),
    }
}

/// One evaluation as in the d3 loop: decode, compile, execute.
fn eval_once(
    arena: &Arena,
    bytes: &[u8],
    model: &CostModel<BuiltinCostsV3>,
) -> Result<(i64, i64), (String, i64, i64)> {
    let program = decode(arena, bytes).map_err(|e| (e, 0, 0))?;
    let compiled = compile(program);
    execute(arena, &compiled, model)
}

fn load_cost_model() -> CostModel<BuiltinCostsV3> {
    let path = std::env::var("PVB_COSTMODEL").expect("set PVB_COSTMODEL");
    let values: Vec<i64> = fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("cannot read {path}: {e}"))
        .split_whitespace()
        .map(|s| s.parse().unwrap())
        .collect();
    assert_eq!(values.len(), 350, "{path}: expected the 350 PlutusV3 parameters");
    CostModel::initialize_cost_model(&PlutusVersion::V3, &values[..KNOWN_PARAMS])
}

fn check(out: &str) {
    let model = load_cost_model();
    let mut arena = Arena::from_bump(Bump::with_capacity(1_048_576));
    let mut csv = String::from("vm,script,status,cpu,mem\n");
    for (name, bytes) in scripts() {
        let (status, cpu, mem) = match eval_once(&arena, &bytes, &model) {
            Ok((cpu, mem)) => ("ok", cpu, mem),
            Err((msg, cpu, mem)) => {
                let msg: String = msg.chars().take(200).collect();
                println!("CHECK_FAIL: {name}: {msg}");
                ("error", cpu, mem)
            }
        };
        arena.reset();
        csv.push_str(&format!("{VM},{name},{status},{cpu},{mem}\n"));
    }
    fs::File::create(out)
        .and_then(|mut f| f.write_all(csv.as_bytes()))
        .unwrap_or_else(|e| panic!("cannot write {out}: {e}"));
}

fn bench(c: &mut Criterion, loops: &[&str]) {
    let model = load_cost_model();
    let mut arena = Arena::from_bump(Bump::with_capacity(1_048_576));
    for (name, bytes) in scripts() {
        // A panic inside b.iter would abort the whole run: evaluate once first, skip on failure.
        let first = eval_once(&arena, &bytes, &model);
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
                    {
                        let program = decode(&arena, &bytes).expect("decode");
                        let compiled = compile(program);
                        let result = vm::execute(
                            &arena,
                            &compiled,
                            ExBudget::max(),
                            &model,
                            BuiltinSemantics::from(&PlutusVersion::V3),
                        );
                        std::hint::black_box(result.term.is_ok());
                    }
                    arena.reset();
                })
            });
        }
        if loops.contains(&"eval") {
            println!("PVB_LOOP eval {name}");
            // The decoded and compiled program lives in its own arena for the whole benchmark of
            // this script.
            let program_arena = Arena::from_bump(Bump::with_capacity(1_048_576));
            let program = decode(&program_arena, &bytes).expect("decode");
            let compiled = compile(program);
            let mut group = c.benchmark_group("eval");
            group.bench_function(&name, |b| {
                b.iter(|| {
                    {
                        let result = vm::execute(
                            &arena,
                            &compiled,
                            ExBudget::max(),
                            &model,
                            BuiltinSemantics::from(&PlutusVersion::V3),
                        );
                        std::hint::black_box(result.term.is_ok());
                    }
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
