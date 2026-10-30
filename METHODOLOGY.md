# Methodology

## What Is Measured

The ranking time (the "D3" loop) is node-equivalent. Each iteration does:

1. **Flat decode**: deserialize the `.flat`-encoded UPLC program.
2. **Evaluation**: run the decoded program with costing on.

Every VM uses the same parameters, in the timed loops and in the correctness check:

| Parameter | Value |
|---|---|
| Ledger language | PlutusV3 |
| Protocol version | 11 (builtin semantics variant E, `case` on builtin values enabled) |
| Cost model | The mainnet PlutusV3 cost model, 350 parameters ([`check/reference/mainnet-plutusv3-costmodel.json`](check/reference/mainnet-plutusv3-costmodel.json)). It equals the default PlutusV3 model of plutus 1.63.0.0, the version of the production node |
| Budget | Costing on: counting mode, or a restricting budget too large to run out |

Costing is part of the timed work, as on a node. The full parameter list and the reasons are in
[check/README.md](check/README.md#evaluation-parameters).

### Reuse rule

From [docs/IMAGE_CONTRACT.md](docs/IMAGE_CONTRACT.md):

- Built once, outside the timed loops: the cost model, the machine parameters and, if the VM's API
  allows reuse, a machine object. The ledger also caches its evaluation context.
- Fresh in every iteration: the flat decode (D3 loop only), the budget counter and the evaluation state.

### Eval-only column

A second loop (`<vm>-eval.csv`) evaluates a program that was decoded once before timing. The page
shows it next to the D3 time. Decoding is a large share of the D3 time for some VMs, so this
column shows the speed of the evaluator alone. The ranking uses the D3 time. The eval-only loop runs in the
same process as the D3 loop of the script, after it (see [Fairness rules](#fairness-rules), D14).

### Compiled VMs

The Scalus JIT compiles a script to JVM bytecode before it runs it. It decodes and compiles each
script once, before timing. Its timed loop evaluates the compiled script, so neither the flat
decode nor the compile step is timed. The page shows it with a "decode and compile excluded"
badge and a compile-time column (`<vm>-compile.csv`, the median of 3 compiles per script). So a
compiling VM has only an eval-only time. The report shows its time only as eval only: its
decode + eval cell is "–", it is not in the decode + eval ranking or the geometric-mean chart, and
its history ratio uses Haskell's eval-only time. Today the Scalus JIT is in the unranked
Experimental section (see [Inclusion rules](#inclusion-rules)).

### Cached decode

The published npm package `@lucid-evolution/uplc` 0.4.0 (the `aiken-wasm` row) caches the decoded
program, and it has no switch to turn the cache off. The harness uses the package as is. After the
first call, its timed loop does not decode the script again: it hashes the flat bytes, finds the
decoded program in the cache and evaluates it. So its time is hash + evaluation, an eval-only time
(the D3 and the eval-only files have the same rows). It cannot be timed on decode + eval without
changing its input, and the package is used as it is (D17). So, as for a compiling VM, the report
shows its time only as eval only (D21): its decode + eval cell is "–", it is not in the decode +
eval ranking, not a competitor in the penalty rule there, and not in the geometric-mean chart. It
is ranked on eval only, with a "decode cached (by the library)" badge, and the page says so next
to the decode + eval ranking.

## Inclusion Rules

A VM is ranked when it meets three rules:

1. It has a published release: a stable version on a package registry, or a release tag.
   Pre-releases, such as `-alpha` or `0.1.0-preNN` versions, do not count.
2. It has a downstream user today: a released project outside the VM's own repo that depends on it,
   for example a node, a wallet, an SDK or a dev tool. It need not be the project's default
   evaluator. The page lists each user with a proof link (`USED_BY` in `report/generate_report.py`).
3. It passes the [correctness gate](#correctness-gate).

A VM that caches the decoded program or compiles it ahead gets a badge, and it is ranked only on
eval only (D21: its decode runs outside the timed loop):

| Badge | Meaning | Example |
|---|---|---|
| decode and compile excluded | The decode and the compile run once per script, before timing | Scalus JIT |
| decode cached (by the library) | The library caches the decoded program; the harness cannot turn the cache off | Aiken WASM (`@lucid-evolution/uplc` 0.4.0) |

The page shows an unranked "Experimental" section (spec D22). It holds VMs that miss rule 1 or
rule 2. Each is pinned by full commit SHA, on any branch. Each row shows its reason:

| Reason | Meaning | Example |
|---|---|---|
| pre-release only | Only `-alpha` or `-preNN` versions; pinned to the newest pre-release tag | Chrysalis, Julc |
| no release | No tag or release; pinned to a `main` commit | Plutuz, amaru-uplc bytecode (fork) |
| no downstream user | A release, but no released project outside its repo depends on it | Scalus JIT, blaze-plutus |
| outdated | A built-in cost model from before protocol version 11 and no API for a cost model; badge "outdated cost model" (its ExUnits equal Haskell with that model) | llvm-uplc |

An experimental row never gets a rank. It is never a competitor in the penalty rule, and it has no
line in the history chart. The gate checks each of its scripts. A script that fails is marked
"failed check", and its time is left out of the row's geometric mean. A row with no passing
script, or without a check file, is listed as "failed check".

The README lists the VMs that are not included and the rule that each one fails.

## Test Data

89 flat-encoded Plutus scripts from the
[`plutus-use-cases`](https://github.com/input-output-hk/plutus-use-cases) test suite, in
`data/plutus_use_cases/`. They were compiled with
[Plinth (formerly Plutus Tx)](https://plutus.cardano.intersectmbo.org/docs/essential-concepts/plinth-and-plutus-core)
under its old name. They cover:

- Auction, Crowdfunding, Currency, Escrow
- Futures (settle, pay-out, increase-margin)
- Game state machines, Multisig state machines
- Ping-pong, Prism, Pubkey
- Stablecoin, Token account, Uniswap, Vesting
- `coop-*` and `guardrail-*` (UPLC 1.1.0)

File sizes range from about 2 KB to 13 KB. All VMs read the same files.

### PlutusV1-era scripts

78 of the 89 scripts are PlutusV1-era validators (UPLC 1.0.0). The other 11 (`coop-*`,
`guardrail-*`) are UPLC 1.1.0 programs that use `constr`/`case`. The benchmark evaluates all 89 as
PlutusV3 programs at protocol version 11. Plutus's own `validation` CEK benchmark
(`plutus-benchmark`, `BenchCek.hs`) does the same. A node would run the 78 older scripts as PlutusV1.

The PlutusV3 rule that a script must return `unit` (CIP-117) is not applied. The 78 PlutusV1-era
scripts return a non-unit term. The benchmark measures the evaluator, so the status is the
evaluation result only. The rule does not change the ExUnits.

## Correctness Gate

Before the timings of a VM are published, its results must equal Haskell plutus-core. Each image
writes `<vm>-check.csv` (`vm,script,status,cpu,mem`): one evaluation per script, with the
parameters above. [`check/gate.py`](check/gate.py) compares it with
[`check/reference/haskell-check.csv`](check/reference/haskell-check.csv).

There are two modes ([check/README.md](check/README.md#policy)):

- **Strict** (the default). The VM loads the mainnet cost model. Status, CPU and memory must equal
  the Haskell reference for every script. A VM without costing fails.
- **Badge.** For a VM whose API cannot take a cost model. The VM runs with the model it ships. It
  must equal Haskell evaluated with that model
  ([`check/reference/haskell-check-variant-c.csv`](check/reference/haskell-check-variant-c.csv)).
  The page then shows the VM with an "outdated cost model" badge.

A VM that fails is not ranked; the page lists it as "failed check". The mode of each VM is in
[`check/modes.conf`](check/modes.conf). Today every VM is strict.

## Why Native Benchmark Frameworks

Each VM is timed with a benchmark framework of its own language. The framework handles warm-up,
iteration count and outlier detection. The harness code that calls the VM is in `images/<vm>/`,
and the runner is `scripts/run-<vm>.sh`.

| VM | Framework | Warm-up and measurement (normal timing) |
|---|---|---|
| haskell | Criterion | Criterion's warm-up; about 5 s per script, Criterion's default (`timeLimit = 5`) |
| scalus-cek, scalus-jit, julc-java | JMH 1.37, shared runner (`scripts/jmh-run.sh`) | One 30 s warm-up iteration, three 5 s measurement iterations (`-wi 1 -w 30s -i 3 -r 5s`). One fork per method and script (`-f 1`) |
| aiken | Criterion.rs | Criterion.rs default warm-up, 5 s measurement |
| uplc-turbo | Criterion.rs | Criterion.rs default warm-up, 5 s measurement |
| plutigo | Go testing.B | Automatic `b.N` scaling, `-test.benchtime=5s` |
| blaze-v8, scalus-js, aiken-wasm | One shared loop (JMH shape, `images/node-base/time.mjs`), plain Node.js | Adaptive warm-up (5 to 30 s), three 5 s measurements (a JIT runtime, V8) |

### Shared base images of the JIT rows

Since 2026-10-27 the JVM rows and the JS rows each build on one base image:

- `images/jvm-base` (scalus-cek, scalus-jit, julc-java): Oracle GraalVM 25.4.4 is the JMH
  launcher and the forked benchmark JVM, JMH is 1.37 (`JMH_VERSION`), and one runner script
  (`scripts/jmh-run.sh`) holds the JMH options. `-Xss64m` stays only in scalus-jit. Before, the
  Scalus rows launched JMH on Temurin 21.
- `images/node-base` (blaze-v8, scalus-js, aiken-wasm): one Node.js, Node 24 LTS "Krypton"
  24.22.1 (`NODE_VERSION`, pinned by image digest), and one timing loop (`time.mjs`). Each row gives only its operation
  (`vm.mjs`; blaze: `pvb-vm.ts`, bundled with bun). Before, blaze-v8 ran its own copy of the loop
  under Vitest on the Node 22 of NodeSource, and the other two used the newest `node:22` image.
  So the JS rows also moved from Node 22 to Node 24: a newer V8.

So the numbers of these six rows can change from the run of 2026-10-27 on, with no change in
the VMs: a shared runtime and runner, and for the JS rows Node 24 instead of Node 22. Compare their history across that date with care.

### Warm-up of the JIT rows

The JIT runtimes (JVM, V8) compile hot code while it runs, so they must warm up before the
measurement. Each script and loop gets its own warm-up, then three rounds of 5 s.
`<vm>-warmup-used.csv` records the length of each warm-up
([docs/IMAGE_CONTRACT.md](docs/IMAGE_CONTRACT.md)).

The JS rows (blaze-v8, scalus-js, aiken-wasm) use an adaptive warm-up:

1. Run the timed operation in slices of 1 s, with the same round function as the measurement.
2. After each slice, stop when at least 5 s have passed and the last 5 slices are all within
   ±3 % of their median.
3. Stop at 30 s at the latest (the cap), steady or not.

The JMH rows (scalus-cek, scalus-jit, julc-java) use one JMH warm-up iteration of 30 s, the cap
(`-wi 1 -w 30s`). The JMH rows keep JMH's own warm-up iterations, at the 30 s cap. This change
from 20 s to 30 s (2026-10-23) made the Scalus CEK decode + eval time about 7 % faster: the JVM
settles on one of two speed levels for this row, and a 20 s warm-up often stopped on the slower one. JMH cannot
end its own warm-up early.

Why: the measurement must start in the steady state of each engine. A fixed 20 s warm-up could
not do that for every row. A trace run on the bench server (Hetzner ccx33, 1 s slices of a 20 s
warm-up) found the second from which every later slice stays within ±3 % of the median of the
last 5 slices:

| Row | Steady by second (median of the scripts) | 90th percentile |
|---|---|---|
| blaze-v8 | 2 | 8 |
| aiken-wasm | 7 | 13 |
| scalus-cek | 7 | 17 |
| scalus-js | 16 | more than 20 (3 of 10 scripts never) |
| scalus-jit | more than 20 (most scripts never) | more than 20 |

So a fixed 20 s was too short for some rows and longer than needed for others. The 5 s minimum
gives the window of 5 slices. The 30 s cap limits the run time. A capped warm-up is not steady by
the rule: the report can show it.

The JMH rows keep one fresh JVM per script (D14). scalus-cek forks one JVM per method (`-f 1`):
`bench` (D3), then `benchEval` (eval-only), each with its own warm-up. One JVM for both methods
(`-f 0`) made the D3 time 3 to 6 % faster on some scripts, so the fork stays
([`scripts/run-scalus-cek.sh`](scripts/run-scalus-cek.sh)).

`BENCH_TIMING=quick` uses one fixed short warm-up (0.5 s for the JS rows, 1 s for the JMH rows)
and a short measurement, for smoke tests only.

Trace mode (`BENCH_TRACE=1`, [docs/IMAGE_CONTRACT.md](docs/IMAGE_CONTRACT.md)) also writes the
time per operation of each 1 s warm-up slice to `<vm>-warmup.csv`. JMH then runs its 30 s of
warm-up as 30 iterations of 1 s (`-wi 30 -w 1s`). The measurement settings do not change, but
the measured time can: a local test of scalus-cek D3 measured about 8 % slower after
`-wi 30 -w 1s` than after `-wi 1 -w 30s`. Use trace runs to study the warm-up, not to compare
times.

The JS rows share one timing loop. A round runs operations back to back for a fixed time and
scores elapsed / ops, as JMH `avgt` does. scalus-js and aiken-wasm run it with plain `node`: the
harness is plain JavaScript, and the VM is an npm package that Node.js loads natively. The blaze
row runs it under Vitest. blaze has no built package in the image, so Vitest loads its TypeScript
sources (`src/cek`, `src/flat`) and transforms them. A bundle would give a different module shape
than the one blaze has been timed with so far.

There is no JSC row: every JS row runs on Node 24 LTS (V8), the common runtime for Cardano off-chain
code; one engine keeps the JS rows comparable.

## Fairness Rules

- **Same data**: all VMs decode the same 89 `.flat` files.
- **Same parameters**: PlutusV3, protocol version 11, the mainnet cost model, costing on.
- **Same machine, own cores**: each VM runs in its own Docker image on the same server. The full
  run uses 3 lanes: up to 3 VMs run at once, each on its own whole cores. Haskell runs alone. See
  [Hardware](#hardware).
- **Pinned versions**: `.env` pins each VM; `environment.txt` of each run records the image digests.
- **Same results**: the correctness gate proves that each published VM did the same work.

Decisions D13 to D17 of the
[design](docs/superpowers/specs/2026-10-21-lantr-vm-benchmark-design.md#0-decisions):

- **Warm-up (D13)**: the JIT runtimes (JVM, V8) warm up before three 5 s measurements. The JS
  rows use the adaptive warm-up (1 s slices, stop when the last 5 are within ±3 % of their median
  after at least 5 s, 30 s at most). The JMH rows use one JMH warm-up iteration of 30 s. See
  [Warm-up of the JIT rows](#warm-up-of-the-jit-rows). The ahead-of-time compiled VMs (Rust, Go,
  GHC) keep the defaults of their framework, with at least 5 s of measurement.
- **Process model (D14)**: every VM runs each script in a fresh process. No JIT profile, heap or
  allocator state carries over from one script to the next. The process runs both timed loops of
  its script: the D3 loop first, then the eval-only loop. scalus-cek is the exception: JMH forks
  one JVM per method, so its two loops run in two fresh JVMs. Each loop has its own warm-up and
  measurement with the rules above. So the D3 time is measured as in a process of its own, and
  the eval-only time comes from a process that has already run the D3 loop.
- **Compiled VMs (D15)**: the Scalus JIT row has a "decode and compile excluded" badge. Its timed
  loop runs the compiled script; the decode and the compile happen once per script, before timing.
  So its time is shown only as an eval-only time, never as a decode + eval time.
- **Runtime settings (D16)**: each VM runs with the settings that its project documents for
  production use. A VM without such documentation runs with the defaults of its runtime. The
  Scalus rows run on Oracle GraalVM 25.4 with no tuning flags; the JIT adds `-Xss64m`, which its
  call-depth limit needs. Tuning flags (compact object headers, inlining limits, code cache) gave
  no speed-up on GraalVM 25 in a test on 5 scripts (2026-10-24): CEK within ±2 %, JIT 2–5 % slower.
- **Inclusion rules (D17)**: a ranked VM has a published release, a downstream user today, and
  passes the gate. See [Inclusion rules](#inclusion-rules).

Host and noise measures ([`scripts/run-images.sh`](scripts/run-images.sh),
[`nix/runner.nix`](nix/runner.nix)):

- **Image pulls first**: all images are pulled, up to 4 at a time, before the first VM runs. No
  pull overlaps a timing.
- **CPU set**: on a Linux host every container runs on every CPU except the physical core of
  CPU 0 (`--cpuset-cpus`). That core stays free for the host (Docker, SSH, interrupts). On Docker
  Desktop (macOS) there is no CPU set: the containers run in a Linux VM, and its CPU 0 is not the
  host's.
- **No network**: every container runs with `--network none`.
- **Quiet host**: the bench server disables the logrotate and fstrim timers. Nix GC, Nix store
  optimisation and Docker auto-prune are off. Transparent huge pages are pinned to `madvise`.
- **Drift probe**: Haskell runs first. At the end of the run it runs again on 5 fixed scripts
  (`haskell-drift.csv`). The page shows the change, for example "Drift (Haskell, end vs start):
  +1.8 %". `drift.json` has the time of each script.
- **Noise record**: `environment.txt` records the CPU topology (`lscpu`), selected CPU flags, the
  THP mode, the kernel command line, cpufreq, the active systemd timers, the load average before
  each VM, and the steal time during each VM and during the whole run.

## Hardware

The monthly run uses a Hetzner Cloud dedicated-vCPU server, type `ccx43` (the default of
`run.yml`): AMD EPYC, 16 dedicated vCPUs (8 cores), 64 GB RAM. A new server is created for each
run. NixOS is installed on it from [`nix/runner.nix`](nix/runner.nix), with the CPU governor set to
`performance` (a KVM guest has no cpufreq driver, so this has no effect there). The server is
deleted after the run.

**Lanes.** The full run uses 3 lanes (`LANES=3`, the `lanes` input of `run.yml`). The host keeps the
core of CPU 0. The other physical cores split into 3 lanes of whole cores, and up to 3 VMs run at
once, each on its own lane. Haskell and the drift probe run alone, on lane 0. VMs on other lanes
share the memory bus and the last-level cache. We measured this on one ccx43: with 3 lanes the
geometric mean of each VM moved by -2.4 % to +0.9 % against one lane, within the noise. Only the
experimental Scalus JIT moved by +7 %. On 5 scripts the run time went from 31 to 12 min, so the
89 scripts take about 3.6 h instead of about 11 h. A run with one lane (a `ccx33` with `lanes` 1,
for example) is also a full run. Any other lane count, or a comma list (an A/B test), is a partial
run. `environment.txt` records the lanes, for example `lanes: 3 (lane0 2,3; lane1 4,5; lane2 6,7)`,
and the CPU, cores, memory and the noise data of each run (see [Fairness rules](#fairness-rules)).

**Server qualification.** Servers of one type are not equal. One ccx43 ran every VM 2.1x slower
than another ccx43, with the same CPU model and 0 % steal. Two good ccx33 servers agreed within
0.3 % on Haskell. So each run first checks its server. It times the Haskell image on 3 scripts
(`auction_1-1`, `coop-6`, `uniswap-1`; d3 loop, normal timing, the same docker flags and CPU set as
the run). It compares the geometric mean with the reference of the server type in
[`check/reference/host-reference.json`](check/reference/host-reference.json). A server more than
15 % slower than the reference is deleted, and a new one is created. After 3 slow servers the run
fails. A faster server passes. A server type without a reference skips the check, with a warning.
`environment.txt` records the result in the line `server qualification:`, for example
`pass, ratio 0.982, attempt 2 of 3, fsn1; rejected: nbg1 203.0.113.7 ratio 2.099; ...`. The job
summary shows every attempt.

The reference depends on the Haskell harness and its pins. When they change, refresh it from the
`haskell.csv` of a full run on a server that passed:

```bash
python3 scripts/hetzner/qualify.py reference results/<run>/haskell.csv ccx43 \
  --harness <sha> --measured <date> > /tmp/host-reference.json
mv /tmp/host-reference.json check/reference/host-reference.json
```

## Unified Output

All results are normalized to a common CSV schema:

```csv
vm,script,mean_ns,median_ns,min_ns,max_ns,stddev_ns,iterations
```

Times are in **nanoseconds**. The summary uses the **geometric mean** of the scripts that every VM
in a category ran successfully. The geometric mean handles the wide range of script sizes and is
not dominated by the largest scripts.

The history chart shows each VM's geometric mean divided by the Haskell geometric mean of the same
run. The ratio is less sensitive to hardware changes and to drift between runs than absolute times.

## Limitations

- **Different statistics**: each framework computes mean, median and standard deviation in its own
  way. Go testing.B reports only the mean time per operation.
  - JMH (scalus-cek, scalus-jit) reports the mean time per operation of each measurement iteration.
    `median_ns`, `min_ns`, `max_ns` and `stddev_ns` are over the 3 iteration means, not over single
    operations. `stddev_ns` is the sample standard deviation (n - 1). `iterations` is the number of
    measurement iterations. JMH's "Score Error" is a 99.9% confidence interval, so it is not used.
  - Criterion (haskell): `stddev_ns` is Criterion's standard deviation. `min_ns` and `max_ns` are the
    bounds of the bootstrap confidence interval of the mean. `iterations` is the number of samples
    when the run has Criterion's `--json` report, else 0 (the CSV and the log do not have it).
- **JIT warm-up**: the JVM and V8 compile hot code at run time. Their frameworks warm up first,
  but the execution model differs from ahead-of-time compiled VMs.
- **Cost model rebuilt per iteration**: some public APIs do not let a harness keep the cost model
  or machine parameters across evaluations. uplc-turbo builds its default cost model in every
  evaluation call, because the crate keeps the cost model types private. Aiken's machine takes the
  cost model by value, and the crate's evaluation entry point builds a new one per call.
  This work is in their timed loops. scalus-js builds its machine (`PlutusVM`) once and reuses it.
- **Memory use is not compared**: the VMs use different allocators and garbage collectors.
- **Docker overhead**: containers add a small overhead compared with bare metal. It applies to all VMs.

## Reproducing

Anyone with Docker can reproduce the results:

```bash
git clone https://github.com/lantr-io/plutus-vm-benchmark.git
cd plutus-vm-benchmark
scripts/images.sh build <vm>                    # for each VM
scripts/run-images.sh results/$(date +%F)       # or PULL=1 to use the published images
```

For the most consistent results, use a dedicated machine with no other workloads.

The monthly run is [`.github/workflows/run.yml`](.github/workflows/run.yml). It creates the server,
runs [`scripts/run-images.sh`](scripts/run-images.sh) on it with the published images, and commits
the results. Before the benchmark it checks the server (see
[Server qualification](#hardware)). A maintainer can start it by hand with a subset of VMs, scripts
and loops; such a partial run is never published.
