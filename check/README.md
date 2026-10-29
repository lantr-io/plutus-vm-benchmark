# Correctness gate

Spec decision D4: the result and the ExUnits of every script must equal Haskell. A VM that fails is
not published.

## Policy

1. **Strict.** If the VM's API accepts a cost model, its harness loads the mainnet PlutusV3 model
   (`reference/mainnet-plutusv3-costmodel.json`) for the timed loop and the check. Status, cpu and
   mem must equal `reference/haskell-check.csv`. Verdict `pass` or `fail`.
2. **Badge.** If the API cannot take a cost model, the VM runs with the model it ships. Its row is
   published with an "outdated cost model" badge if status, cpu and mem equal Haskell evaluated with
   that model (`reference/haskell-check-variant-c.csv`). This still proves the VM did the same work.
   Verdict `badge`, or `fail` on any wrong status or mismatch. A badge VM that matches the strict
   reference gets `pass`.
3. A `fail` hides the row.

### Mode per VM

| VM | Mode | How the harness loads the mainnet model |
|---|---|---|
| haskell | strict | `gate-ref` path, or `HASKELL_SHA` at 1.63.0.0 (its compiled-in model = mainnet) |
| plutuscore-lean | strict | Upstream `bench_cek` uses the library's compiled-in variant E semantics and cost model, counting all costs including startup. It has no runtime model loader; its status and ExUnits must match the strict reference on all 89 scripts. |
| scalus-cek, scalus-jit | strict | The harness reads `reference/mainnet-plutusv3-costmodel.json` (copied into the image, path in `SCALUS_COST_MODEL`): `MachineParams.fromCostModels(CostModels(Map(PlutusV3.ordinal -> array)), PlutusV3, vanRossemPV)`, then `makePlutusV3VM(params, vanRossemPV)` (`images/scalus/harness/.../Harness.scala`) |
| uplc-turbo | strict | Ships the variant E numbers in `BuiltinCostsV3::default()` |
| plutigo | strict | `cek.NewEvalContext(lang.LanguageVersionV3, cek.ProtoVersion{Major: 11}, mainnetArray)` (`cek/eval_context.go:31`), then `cek.NewMachine(lang.LanguageVersionV3, 0, ctx)`. Takes the 350-value array (`lang/v3.go` has the V3 names up to PV11). The bench must stop taking the language from the program version |
| blaze (V8, JSC) | strict, harness work | `new CekMachine(undefined, costs)` (`machine.ts:68`) takes `costs: Record<DefaultFunction, BuiltinCostModel>`, a structured table, not the array. blaze has no parser, so the harness maps the array into the table (or overrides the five builtins that differ: `equalsByteString` cpu 30623/28755/75, `c11` = 960 in `divideInteger`, `quotientInteger`, `remainderInteger`, `modInteger`). Machine step costs are constants in `machine.ts`, equal to mainnet. If nobody writes the mapping: badge |

All four of plutigo, blaze, julc and opshin ship the same model: the plutus PlutusV3 variant C
defaults (`builtinCostModelC.json`, unchanged from 2024 to plutus 1.63.0.0, and the 16000/100
machine costs). Checked number by number for the 39 builtins the 89 scripts use; opshin's
2024-07-30 network file equals `builtinCostModelC.json` in every parameter (the BLS12-381 ones are
named differently and were not compared; the scripts do not use them). So one badge
reference is enough.

Two facts decide whether the strict path works:

- Cost function shapes do not matter here. Variant E changed the division shape to
  `above_and_below_diagonal`, and these VMs only have the C shape `const_above_diagonal`. With the
  mainnet numbers and the C shapes, Scalus gives the strict reference on all 89 scripts.
- The 11 UPLC 1.1.0 scripts (`coop-*`, `guardrail-*`) use `case` on builtin values (for example a
  `Bool`), a protocol version 11 feature. A VM without it fails these 11 in both modes. opshin has
  no case on builtin values (`machine.py:248`: "Scrutinized non-constr in case").

| File | What it is |
|---|---|
| `reference/haskell-check.csv` | The strict reference: `vm,script,status,cpu,mem` for the 89 scripts, from Haskell plutus 1.63.0.0 |
| `reference/haskell-check-variant-c.csv` | The badge reference: the same, with the variant C cost model |
| `reference/Dockerfile`, `reference/gate-ref/` | The Haskell program that produces the reference |
| `reference/regenerate.sh` | Rebuilds the image and rewrites both references |
| `reference/mainnet-plutusv3-costmodel.json` | The mainnet PlutusV3 cost model: `PlutusV3` (array), `PlutusV3Named` (name -> value) |
| `scalus-crosscheck.sc` | Independent cross-check of the reference with the released Scalus 1.4.0 CEK |
| `gate.py`, `test_gate.py` | The compare tool and its test |

## Evaluation parameters

Every VM evaluates every script with these parameters, in the timed loop and in the check
(`docs/IMAGE_CONTRACT.md`).

| Parameter | Value |
|---|---|
| Input | `data/plutus_use_cases/<script>.flat`: a flat-encoded, fully applied program. Evaluate its term; apply no arguments |
| Ledger language | PlutusV3 |
| Protocol version | 11 (`vanRossemPV`). This selects builtin semantics variant E and enables case on builtin types |
| Cost model | The mainnet PlutusV3 cost model: 350 parameters, mainnet epoch 662, protocol version 11.0 (`reference/mainnet-plutusv3-costmodel.json`) |
| Budget mode | Counting (no limit, add up the cost) or restricting with a budget too large to run out. On success both give the same numbers as the node's restricting mode |
| `status` | `ok` if the evaluation returns a term, `error` if it fails. The PlutusV3 ledger rule that the result must be `unit` (CIP-117) is **not** applied, see below |
| `cpu`, `mem` | The total ExUnits of one evaluation, including the machine startup cost |

Reuse rule (`docs/IMAGE_CONTRACT.md`): the cost model, the machine parameters and, if the VM's API
allows it, the machine object are built once, outside the timed loops. Every iteration makes a new
budget counter and a new evaluation state, and the D3 loop also decodes the flat file again. The
eval-only loop (`<vm>-eval.csv`) evaluates a program decoded once before timing. The check uses the
same objects for one evaluation per script.

The mainnet cost model is the same as the default PlutusV3 cost model of plutus 1.63.0.0 (variant E:
`builtinCostModelE.json` and `cekMachineCostsE.json`). Two checks show it:

- `gate-ref` evaluates every script with both and finds 0 differences (it exits 2 otherwise).
- In Scalus 1.4.0 the `MachineParams` built from the mainnet array are equal to the ones built from
  the two JSON files, and give the same ExUnits for all 89 scripts.

So "the latest PlutusV3 cost model that the VM ships" and "the mainnet cost model" are the same
numbers today. A VM that ships an older PlutusV3 default (variant C, before plutus 1.60) fails the
gate: C and E differ for `equalsByteString`, `divideInteger`, `modInteger`, `quotientInteger` and
`remainderInteger`.

### Why these parameters

- D3 asks for the node-equivalent evaluation. The production node (11.x) runs plutus 1.63.0.0 at
  protocol version 11, and mainnet scripts of today are PlutusV3.
- 11 of the 89 scripts (`coop-*`, `guardrail-*`) are UPLC 1.1.0 programs (`constr`/`case`). The
  other 78 are UPLC 1.0.0. PlutusV3 evaluates both.
- `gate-ref` uses the node's own code path: `PlutusLedgerApi.V3.mkEvaluationContext` over the
  on-chain array, then `evaluateTerm` at protocol version 11.
- No CIP-117 result check. 78 of the 89 scripts are PlutusV1-era validators: they return
  `delay (\x -> x)`, not `unit` (only the 11 UPLC 1.1.0 scripts return `unit`). The node would
  reject them as PlutusV3 scripts. The benchmark measures the evaluator, so `status` is the CEK
  result only. The check does not change `cpu` or `mem`: it runs after the evaluation. None of the
  audited VMs applies it in its evaluator.
- `gate-ref` is built with GHC 9.6.7 (latest 9.6, the series plutus 1.63.0.0 uses); `.env` has
  9.6.4 for the timing image. The GHC version does not change ExUnits.

## What the existing Haskell benchmark does

`scripts/run-haskell.sh` runs `plutus-benchmark:bench:validation` (`plutus-benchmark/validation/bench/BenchCek.hs`):

- Evaluation context: `mkEvalCtx PlutusV3 DefaultFunSemanticsVariantE`: the cost model compiled
  into plutus-core for variant E, through `mkDynEvaluationContext`.
- Budget mode: `restrictingEnormous` (costing on, with a budget too large to run out).
  `evaluateTerm` is called through `evaluateCekLikeInProd`. The protocol version argument is
  PlutusV1's (Alonzo), but the semantics variant is fixed to E, so it does not change the result.
- It times flat-decoded, name-converted terms; flat decoding is outside the timed loop.

At the current `.env` pin (`HASKELL_SHA=318c729`, 2026-03-10, before release 1.60.0.0) plutus-core has
no variant E files: `DataFilePaths.hs` maps variant E to `builtinCostModelC.json` and
`cekMachineCostsC.json`. So the Haskell timing today runs with the **old** PlutusV3 cost model. Its ExUnits would fail this
gate on all 89 scripts (measured with the C files in Scalus 1.4.0: every script uses at least one
of the five builtins above).

**Recommendation:** move `HASKELL_SHA` to the release tag 1.63.0.0
(`ac40fae4dea9dcad51b38a9c5c48148655cb13a2`), the plutus version of the production node. Release
1.63.0.0 exists in IntersectMBO/plutus (newer tags up to 1.69.0.0 exist, but the node does not use
them yet). Check the two `cabal.project` `sed` lines of the Haskell image at that tag: there the
flags line is `flags: +with-inline-r +with-cert`.

## Regenerate the reference

```bash
check/reference/regenerate.sh          # needs Docker; CABAL_JOBS=2 by default
```

The badge reference is `gate-ref ... variant-c`: semantics variant C with the variant C cost model
compiled into plutus-core 1.63.0.0, and case on builtin values enabled (as at protocol version 11).
Scalus 1.4.0 with `builtinCostModelC.json` gives the same file
(`scala-cli run check/scalus-crosscheck.sc -- data/plutus_use_cases variant-c`).

The first build compiles plutus-core and plutus-ledger-api (about 10 minutes in Docker on an
M-series Mac). To use a new cost model, update `reference/mainnet-plutusv3-costmodel.json`, for example from
`https://api.koios.rest/api/v1/cli_protocol_params` (`.costModels.PlutusV3`).

## Cross-check with Scalus

```bash
scala-cli run check/scalus-crosscheck.sc -- data/plutus_use_cases > /tmp/scalus-check.csv
python3 check/gate.py /tmp/scalus-check.csv
```

## Run the gate

```bash
python3 check/gate.py --json results/<date>/gate.json \
    --mode blaze-v8=badge:check/reference/haskell-check-variant-c.csv \
    results/<date>/*-check.csv
python3 -m unittest discover -s check -p 'test_*.py'
```

`--mode VM=strict` is the default; `--mode VM=badge:REFERENCE_CSV` selects the badge path for one
VM. Output: one line per VM (`PASS`/`BADGE`/`FAIL`, mode, reason, matching count, the first
mismatching scripts). The JSON has, per VM, `verdict` (`pass`|`badge`|`fail`), `mode`, `reference`,
`reason` and the full mismatch list; the top-level `ok` is false if any VM fails. Exit code 1 if any
VM fails, 2 on bad input. A row with empty `cpu`/`mem` fails
the VM as "no costing". A script that is in the reference but not in the VM's file fails as
"missing".

`--scripts SCRIPTS_FILE` (one name per line) compares only those scripts: a run of a subset
(`BENCH_SCRIPTS`, `BENCH_QUICK`, docs/IMAGE_CONTRACT.md) checks only the selected scripts, and
`scripts/run-images.sh` passes their names (`scripts.txt` in the run dir). A selected script that a
VM's file lacks still fails as "missing"; a name that is not in the reference is bad input.

## Audit of the existing harnesses (2026-10-21, pins in `.env`)

Does the timed loop run with costing on, and how does each VM get a `<vm>-check.csv`?

| VM | Timed loop | Parameters in the timed loop | ExUnits API | Recipe for `<vm>-check.csv` | Predicted gate result at the pin |
|---|---|---|---|---|---|
| haskell | Costing on (`restrictingEnormous`) | PlutusV3, variant E, compiled-in cost model. At the current pin E = the old C files: **fails the gate until `HASKELL_SHA` moves to 1.63.0.0** | `CekReport` cost: `CountingSt` with `counting` | Use `gate-ref` from this directory (same code path, same image base). Small | Fail on 89 at the current pin (variant C files); pass at 1.63.0.0 |
| scalus-cek | Costing on (`RestrictingBudgetSpender(ExUnits.enormous)`) | **`makePlutusV1VM(vanRossemPV)`**: mainnet PlutusV1 cost model, variant D. Must change to `makePlutusV3VM(vanRossemPV)` | `BudgetSpender.getSpentBudget` (`CountingBudgetSpender`) | Same loop with a `CountingBudgetSpender`, print `steps`/`memory` (see `scalus-crosscheck.sc`). Trivial | Fail (PlutusV1 cost model) until the harness uses `makePlutusV3VM`; Scalus 1.4.0 with V3 passes 89/89 |
| scalus-jit | **Costing off** (`NoBudgetSpender`, `JITBenchmark.scala:43`) | Mainnet PlutusV3, PV11 | Pass a `CountingBudgetSpender` to the compiled function, then `getSpentBudget` | Same call with a `CountingBudgetSpender`. Trivial. The timed loop must also switch to a real spender (D3) | Likely pass (mainnet V3 params, same as scalus-cek V3) |
| uplc-turbo | Costing on, capped at the transaction limit (`ExBudget::default()`, 14M mem / 10G cpu) | V3, built-in `BuiltinCostsV3::default()` | `EvalResult.info.consumed_budget` | Example binary: eval each file, print `consumed_budget.cpu/mem`. Small | Likely pass: its V3 table has the variant E constants |
| plutigo | Costing on, capped at the transaction limit (`DefaultExBudget`) | **Language taken from the program version**: UPLC 1.0.0 runs as V1, 1.1.0 as V2, variant B, protocol version 200; one `DefaultCostModel`. Must pass V3 explicitly | None; `Machine.ExBudget` is the remaining budget, spent = `DefaultExBudget - m.ExBudget` | Go test or main: decode, `NewMachine`, `Run`, subtract. Small | Fail: ships variant C constants only, and evaluates as V1/V2 |
| blaze (V8, JSC) | Costing on, unlimited budget (counting) | `DEFAULT_BUILTIN_COSTS`, "Default PlutusV3 (Conway era)" | `CekMachine.remainingBudget`, spent = `I64_MAX - remaining` | Existing CLI `bun scripts/eval.ts --flat -p f.flat` prints `cpu`/`mem`; loop over files. Trivial | Fail: ships variant C constants only |
| julc-java | Costing on, unlimited budget (`null` budget) | PlutusV3, `DefaultCostModel` | `EvalResult.budgetConsumed()`, `isSuccess()` | Single-file Java with the same `evaluate` call. Trivial | Fail: ships variant C constants only |
| opshin | Costing on, capped at the transaction limit (`default_budget()`) | V3 CEK and builtin cost models | `ComputationResult.cost` (budget minus remaining), `.result` holds the term or the exception | Python loop over `uplc.tools.eval`, status from `isinstance(r.result, Exception)`. Do not use the `uplc eval` CLI: it defaults to the PlutusV2 cost model. Trivial | Fail: ships variant C constants only (cost model files 2024-07-30) |

The prediction is for the default cost model at the pin. It comes from the constants in each pinned
repo: variant E has `equalsByteString` cpu 30623/28755/75 and `c11` = 960 in the division builtins,
variant C has 24548/29498/38 and 549. A VM with only C constants differs from the strict reference
on all 89 scripts (measured with the C files in Scalus 1.4.0). See [Mode per VM](#mode-per-vm) for
how each one loads the mainnet model instead.

Other findings:

- julc and opshin do not check the evaluation result in the timed loop (`EvalResult.Failure` and
  `.result` hold the error without a throw). A failing script would be timed as if it passed. The
  check closes this gap.
- uplc-turbo's bench calls `.expect` on the result, so one failing script stops the Criterion run;
  `run-uplc-turbo.sh` hides it with `|| true` and `fill_failures`.
- Flat decoding is inside the timed loop for uplc-turbo, plutigo, blaze and opshin, and outside it
  for haskell, scalus and julc. D3 asks for decode + evaluate.
- A cap at the transaction limit (14M mem / 10G cpu) does not change ExUnits for scripts that fit.
  All 89 scripts fit: the largest is `coop-3` with 2.15G cpu and 11.7M mem.
