<p align="center">
  <a href="https://lantr.io">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="docs/lantr-logo-dark.png">
      <source media="(prefers-color-scheme: light)" srcset="docs/lantr-logo.png">
      <img alt="Lantr" src="docs/lantr-logo.png" width="240">
    </picture>
  </a>
</p>

# Plutus VM Benchmark

Reproducible, cross-language benchmark of Plutus (UPLC) virtual machines, the evaluators that run
Cardano smart contracts.

Results: [Plutus VM Benchmark at plutus-vm-bench.lantr.io](https://plutus-vm-bench.lantr.io)

## Aim

Give a neutral, reproducible comparison of the Plutus/UPLC evaluators that people use today.
Library and node authors can use it to choose an evaluator.

## Goals

- **Node-equivalent timing.** Each iteration does a flat decode and an evaluation. The evaluation
  uses PlutusV3 semantics at protocol version 11, the mainnet PlutusV3 cost model, and costing on.
- **Correctness gate.** For every script, the result and the ExUnits of a VM must equal Haskell
  [plutus-core](https://github.com/IntersectMBO/plutus). A VM that fails is not ranked.
- **Released versions only, for the ranking.** Every ranked VM is pinned to a release in `.env`.
  Pre-releases, such as `-alpha` or `0.1.0-preNN` versions, do not count. An experimental VM is
  pinned by full commit SHA, on any branch: by default its newest pre-release tag, or a `main` commit.
- **Monthly runs on fixed hardware.** One Hetzner dedicated-vCPU server type (`ccx43`) runs every VM,
  up to 3 at once, each on its own CPU cores. Each run first checks that its server is not slow
  (server qualification, see [METHODOLOGY.md](METHODOLOGY.md#hardware)).
- **History.** Each run stays in `results/`. The page shows each VM's time relative to Haskell over time.

## Background

- [Cardano](https://cardano.org) is a proof-of-stake blockchain.
- [Plutus](https://plutus.cardano.intersectmbo.org/docs/) is the smart contract platform of Cardano
  ([IntersectMBO/plutus](https://github.com/IntersectMBO/plutus)).
- [UPLC (Untyped Plutus Core)](https://plutus.cardano.intersectmbo.org/docs/essential-concepts/plinth-and-plutus-core)
  is the on-chain language. Compilers such as
  [Plinth (formerly Plutus Tx)](https://plutus.cardano.intersectmbo.org/docs/essential-concepts/plinth-and-plutus-core),
  [Aiken](https://aiken-lang.org) and [Scalus](https://scalus.org) emit it.
- The node ([cardano-node](https://github.com/IntersectMBO/cardano-node)) evaluates a UPLC script
  with a CEK machine. The
  [Plutus Core specification](https://plutus.cardano.intersectmbo.org/resources/plutus-core-spec.pdf)
  defines the language and the CEK machine. A
  [cost model](https://plutus.cardano.intersectmbo.org/docs/delve-deeper/cost-model) charges each
  step and each builtin call in ExUnits (CPU and memory). The
  [Alonzo ledger specification](https://github.com/intersectmbo/cardano-ledger/releases/latest/download/alonzo-ledger.pdf)
  defines ExUnits and how the ledger uses the cost model.
- Many tools evaluate scripts, not only the node. Wallets and off-chain transaction builders, such
  as [Lucid Evolution](https://github.com/Anastasia-Labs/lucid-evolution) and
  [Blaze](https://github.com/butaneprotocol/blaze-cardano), evaluate each script to estimate fees.
  Test frameworks and emulators evaluate scripts in every test. Indexers evaluate scripts to report
  their costs. Alternative nodes such as [Amaru](https://github.com/pragma-org/amaru) and
  [Dingo](https://github.com/blinklabs-io/dingo) evaluate them to validate blocks. A faster evaluator
  makes all of these faster.

## Maintainers

Maintained by Lantr ([lantr.io](https://lantr.io)), Alexander Nemish.

## Acknowledgement

Forked from [SAIB-Inc/cardano-plutus-vm-benchmark](https://github.com/SAIB-Inc/cardano-plutus-vm-benchmark),
created by Clark Alesna ([SAIB Inc.](https://github.com/SAIB-Inc)) and contributors. Thank you for the
original harness, data set and methodology.

What changed:

- **Per-VM images on GHCR.** Each VM is its own Docker image (`ghcr.io/lantr-io/pvb-<vm>`). A version
  bump rebuilds only that image.
- **Correctness gate.** Each VM reports the result and the ExUnits of every script. The gate compares
  them with Haskell plutus-core ([check/README.md](check/README.md)).
- **Node-equivalent parameters.** Flat decode + evaluation with PlutusV3 semantics, protocol version 11,
  the mainnet cost model and costing on, for every VM.
- **Curated line-up.** A ranked VM has a published release, a downstream user today (a released
  project outside its own repo that depends on it), and passes the correctness gate. A VM that caches the decoded program or compiles it ahead gets a
  badge and is ranked only on eval only. An unranked [Experimental](#experimental) section shows VMs
  that have no stable release or no downstream user. See [Not included](#not-included).
- **Eval-only column.** A second timing evaluates a program decoded once before timing.
- **Automated monthly runs.** GitHub Actions creates a Hetzner server, installs NixOS on it, checks
  its speed against a stored Haskell reference, runs the benchmark and deletes the server. A slow
  server is replaced, up to 3 times.

## VMs Benchmarked

| Image | VM | Language | Benchmark framework | Project | Pinned version |
|---|---|---|---|---|---|
| `haskell` | plutus-core | Haskell | Criterion | [IntersectMBO/plutus](https://github.com/IntersectMBO/plutus) | [1.70.0.0](https://github.com/IntersectMBO/plutus/releases/tag/1.70.0.0) |
| `scalus-cek` | Scalus CEK | Scala / GraalVM 25 | JMH (`images/jvm-base`) | [scalus3/scalus](https://github.com/scalus3/scalus) | [v1.4.1](https://github.com/scalus3/scalus/releases/tag/v1.4.1) |
| `scalus-jit` | Scalus JIT (UPLC → JVM bytecode), [experimental](#experimental), not ranked | Scala / GraalVM 25 | JMH (`images/jvm-base`) | [scalus3/scalus](https://github.com/scalus3/scalus) | [v1.4.1](https://github.com/scalus3/scalus/releases/tag/v1.4.1) |
| `scalus-js` | Scalus.js | Scala.js / Node.js | shared Node.js loop (`images/node-base`) | [scalus3/scalus](https://github.com/scalus3/scalus) | npm `scalus` [1.4.1](https://github.com/scalus3/scalus/releases/tag/v1.4.1) |
| `aiken` | Aiken uplc | Rust | Criterion.rs | [aiken-lang/aiken](https://github.com/aiken-lang/aiken) | [v1.1.24](https://github.com/aiken-lang/aiken/releases/tag/v1.1.24) |
| `aiken-wasm` | Aiken uplc as WASM (Lucid Evolution), badge "decode cached (by the library)" | Rust → WASM / Node.js | shared Node.js loop (`images/node-base`) | [Anastasia-Labs/lucid-evolution](https://github.com/Anastasia-Labs/lucid-evolution/tree/main/packages/uplc) | npm `@lucid-evolution/uplc` [0.4.0](https://github.com/Anastasia-Labs/lucid-evolution/releases/tag/%40lucid-evolution%2Fuplc%400.4.0) |
| `uplc-turbo` | amaru-uplc (Amaru) | Rust | Criterion.rs | [pragma-org/amaru](https://github.com/pragma-org/amaru) | [`amaru-uplc` 0.4.0 (Amaru v10.11.20261022)](https://github.com/pragma-org/amaru/tree/ddd3fdfc1c01b29d09a4dd59f4ecd2872062153b/crates/amaru-uplc) |
| `plutigo` | Plutigo (Dingo) | Go | testing.B | [blinklabs-io/plutigo](https://github.com/blinklabs-io/plutigo) | [v0.10.0](https://github.com/blinklabs-io/plutigo/releases/tag/v0.10.0) |
| `blaze-v8` | blaze-plutus on Node (V8), [experimental](#experimental), not ranked | TypeScript | shared Node.js loop (`images/node-base`) | [butaneprotocol/blaze-cardano](https://github.com/butaneprotocol/blaze-cardano) | [@blaze-cardano/plutus 0.1.1](https://github.com/butaneprotocol/blaze-cardano/releases/tag/%40blaze-cardano%2Fplutus%400.1.1) |
| `chrysalis` | Chrysalis CEK, [experimental](#experimental), not ranked | C# / .NET 10 (JIT) | BenchmarkDotNet | [SAIB-Inc/Chrysalis](https://github.com/SAIB-Inc/Chrysalis) | NuGet `Chrysalis.Plutus` [1.7.14-alpha](https://www.nuget.org/packages/Chrysalis.Plutus/1.7.14-alpha) (pre-release) |
| `chrysalis-aot` | Chrysalis CEK, [experimental](#experimental), not ranked | C# / .NET 10 (NativeAOT) | BenchmarkDotNet | [SAIB-Inc/Chrysalis](https://github.com/SAIB-Inc/Chrysalis) | NuGet `Chrysalis.Plutus` [1.7.14-alpha](https://www.nuget.org/packages/Chrysalis.Plutus/1.7.14-alpha) (pre-release) |
| `julc-java` | Julc Java CEK, [experimental](#experimental), not ranked | Java / GraalVM 25 | JMH (`images/jvm-base`) | [bloxbean/julc](https://github.com/bloxbean/julc) | [v0.1.0-pre19](https://github.com/bloxbean/julc/releases/tag/v0.1.0-pre19) (pre-release) |
| `plutuz` | Plutuz CEK, [experimental](#experimental), not ranked | Zig | own timing loop | [utxo-company/plutuz](https://github.com/utxo-company/plutuz) | `main` [33b812d](https://github.com/utxo-company/plutuz/commit/33b812dbcf88f6851286e54cb93a4a443353f94c) (no release) |
| `uplc-turbo-bc` | amaru-uplc bytecode VM, [experimental](#experimental), not ranked | Rust | Criterion.rs | [jonathanlim222/uplc](https://github.com/jonathanlim222/uplc) (fork) | [069cef5](https://github.com/jonathanlim222/uplc/commit/069cef5684d57064d040ab498a5d2eac01e63275) (no release) |
| `llvm-uplc-jit` | llvm-uplc (UPLC → native code JIT), [experimental](#experimental), not ranked | C++ / LLVM 22 | own timing loop (uplcbench) | [SeungheonOh/llvm-uplc](https://github.com/SeungheonOh/llvm-uplc) | `main` [6bcef67](https://github.com/SeungheonOh/llvm-uplc/commit/6bcef67ce1995d232327f13d9080fe2f0261a55c) (no release) |

That is 15 VMs in 13 images: `scripts/images.sh list` prints them. The pins are in [`.env`](.env).

The `aiken-wasm` row times the published npm package `@lucid-evolution/uplc` 0.4.0 as is. The
package is built from [colll78/aiken](https://github.com/colll78/aiken): aiken main after v1.1.24,
plus fixes. The package caches the decoded program, and it has no switch to turn the cache off.
So after the first call its timed loop does not decode again. The row has the badge "decode
cached (by the library)".

The two Aiken rows run different code. Aiken v1.1.24 (`aiken`) copies the CEK environment on every
lambda application (quadratic in recursion depth). aiken main fixes it (PRs
[#1451](https://github.com/aiken-lang/aiken/pull/1451),
[#1452](https://github.com/aiken-lang/aiken/pull/1452): coop-6 92 ms -> 1.2 ms). The `aiken-wasm`
build contains both fixes. No Aiken release contains them yet.

### Experimental

These rows are not ranked (spec D22). Each one is a VM that has no
stable release, no downstream user, or an outdated cost model. The page shows the reason next to each row. They never get a
rank, they are not competitors in the penalty rule, and they have no line in the history chart.
The gate still checks every script: a script that fails is marked "failed check", and its time
is left out. A row with no passing script is listed as "failed check".

| Image | Why it is not ranked |
|---|---|
| `scalus-jit` | The `scalus-uplc-jit-compiler` module is published to Maven since Scalus v1.4.1, but it has no downstream users yet. Its timed loop runs the compiled script: badge "decode and compile excluded". So its time is shown only as an eval-only time. |
| `blaze-v8` | No released project outside the Blaze repo depends on `@blaze-cardano/plutus` 0.1.1. Blaze itself evaluates scripts with `@blaze-cardano/vm`, which wraps the Aiken `uplc` crate as WASM. It moves to the ranking when a project depends on it. |
| `chrysalis`, `chrysalis-aot` | Pre-release only. The NuGet package `Chrysalis.Plutus` has only `-alpha` versions (1.7.14-alpha or newer); the one stable version, 1.7.1, is unlisted. Pinned to the newest pre-release tag. |
| `julc-java` | Pre-release only (`0.1.0-preNN`). Pinned to the newest pre-release tag. |
| `plutuz` | No release: no tags or releases on GitHub. Pinned to a `main` commit. |
| `uplc-turbo-bc` | amaru-uplc bytecode mode. No release has it: the mode is only in the fork [jonathanlim222/uplc](https://github.com/jonathanlim222/uplc) (closed PR pragma-org/uplc#47). Pinned to a commit of the fork. |
| `llvm-uplc-jit` | Outdated. Its built-in cost model is from before protocol version 11 (variant C; for example `divideInteger` c11 549, mainnet 960), and it has no API that takes a cost model, so its row has the badge "outdated cost model": its ExUnits equal Haskell with that model. No release; its last commit is from 2026-04-16. It compiles each script before timing, so its time is eval only ("decode and compile excluded"). |

## Not included

A VM is ranked when it meets three rules:

1. It has a published release: a stable version on a package registry, or a release tag.
   Pre-releases, such as `-alpha` or `0.1.0-preNN` versions, do not count.
2. It has a downstream user today: a released project outside the VM's own repo that depends on it,
   for example a node, a wallet, an SDK or a dev tool. It need not be the project's default
   evaluator. The page lists each user with a proof link (`USED_BY` in `report/generate_report.py`).
3. It passes the correctness gate.

A VM that caches the decoded program, or compiles it ahead, gets a badge and is ranked only on eval
only: its decode runs outside the timed loop. A VM that misses rule 1 or rule 2 goes to
[Experimental](#experimental).

| Project | Rule that fails |
|---|---|
| [OpShin uplc](https://github.com/OpShin/uplc) | Rule 3. Fails the correctness gate at its latest release 1.3.3. It has no `case` on builtin values, a protocol version 11 feature. |

### How a VM can join

Meet the three rules above. Then open a pull request that adds an image. Follow
[CONTRIBUTING.md](CONTRIBUTING.md) and [docs/IMAGE_CONTRACT.md](docs/IMAGE_CONTRACT.md).

## What Is Measured

Each VM runs a flat decode and an evaluation of 89 Plutus scripts from the
[`plutus-use-cases`](https://github.com/input-output-hk/plutus-use-cases) test suite (auction,
escrow, uniswap, stablecoin and others). The scripts were compiled with Plinth under its old name, Plutus Tx.
All VMs read the same `.flat` files in `data/plutus_use_cases/`.

The 89 scripts are PlutusV1-era programs. Every VM evaluates them as PlutusV3 programs at protocol
version 11. Plutus's own `validation` CEK benchmark does the same. See [METHODOLOGY.md](METHODOLOGY.md).

## Results

The latest run is at [plutus-vm-bench.lantr.io](https://plutus-vm-bench.lantr.io). Each run is in
[`results/<date>/`](results/) with its hardware and image digests (`environment.txt`).

The directories in `results/` from before 2026-10 are SAIB-era runs. They used different VMs,
parameters and hardware. Do not compare them with the current runs.

## Quick Start

```bash
# Build one image locally (pins come from .env)
scripts/images.sh build uplc-turbo

# Run images one at a time, then write unified.csv, report.md and index.html into the run dir
scripts/run-images.sh results/$(date +%F) uplc-turbo plutigo

# Smoke test: first 5 scripts, short timing
BENCH_QUICK=1 scripts/run-images.sh /tmp/smoke uplc-turbo

# A subset: two scripts, D3 timing and check only, short timing
BENCH_SCRIPTS='auction_1-1|uniswap-1' BENCH_LOOPS=d3,check BENCH_TIMING=quick \
  scripts/run-images.sh /tmp/subset plutigo aiken

# Only the correctness check, all 89 scripts, every VM
BENCH_LOOPS=check scripts/run-images.sh /tmp/check

# The same on the bench server (GitHub Actions); a partial run is never published
gh workflow run run.yml -f vms="plutigo aiken" -f scripts='auction_.*' -f loops=eval -f timing=quick

# Use the published images instead of local builds (what the bench server does)
PULL=1 scripts/run-images.sh results/$(date +%F)
```

One image by hand:

```bash
docker run --rm --cap-add SYS_NICE \
  -v "$PWD/data:/bench/data:ro" -v "$PWD/results/<date>:/results" \
  ghcr.io/lantr-io/pvb-uplc-turbo:latest
```

Results are written to the results dir:

- `unified.csv` – all VMs, all scripts, nanosecond precision
- `report.md` – markdown comparison table with geometric means
- `gate.json` – the correctness verdict of each VM
- `<vm>.csv`, `<vm>-eval.csv`, `<vm>-check.csv` and `<vm>-raw.log` per VM
- `environment.txt` – the hardware, the switches, the image digests and the host noise data
- `haskell-drift.csv`, `drift.json` – the drift probe: Haskell again at the end of the run

See [docs/IMAGE_CONTRACT.md](docs/IMAGE_CONTRACT.md) for the interface every image follows and the
switches `BENCH_SCRIPTS` (regex on the script name), `BENCH_LOOPS` (`d3`, `eval`, `check`) and
`BENCH_TIMING` (`normal`, `quick`).

## Updating VM Versions

Change the pin of the VM in `.env` to a release. The image tag of that VM changes, so CI
(`.github/workflows/images.yml`) rebuilds only that image. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Project Structure

```
data/plutus_use_cases/    # 89 canonical .flat benchmark scripts
.env                      # Pinned VM versions and toolchain versions
images/<vm>/              # One Dockerfile and harness per VM (images/scalus and images/blaze serve two VMs each)
scripts/run-<vm>.sh       # Per-VM runner, the default command of its image
scripts/image-entry.sh    # Entry point of every image: switches, data selection, exit code
scripts/images.sh         # List, tag and build the images
scripts/run-images.sh     # Run the images, then gate, normalize and report
scripts/hetzner/          # Create, use and delete the bench server
check/                    # Correctness gate and the Haskell reference
parsers/                  # Output normalizers (one per framework)
report/                   # Unified CSV -> markdown/HTML report generator
docs/                     # GitHub Pages site (index.html), image contract, design notes
nix/, flake.nix           # NixOS config of the bench server
.github/workflows/        # images (build and push), run (monthly run), sweep, provision-test
results/                  # Git-tracked historical results
```

## Methodology

See [METHODOLOGY.md](METHODOLOGY.md) for what is measured, the correctness gate, warm-up, hardware
and limitations.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). Original work © 2025 SAIB Inc. © 2026 Lantr.
