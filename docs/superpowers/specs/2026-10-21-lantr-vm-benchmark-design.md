# lantr Plutus VM benchmark – design

Status: approved 2026-10-21.

## 0. Decisions

| # | Decision | Choice |
|---|---|---|
| D1 | Purpose | Public, neutral comparison for library authors who choose an evaluator |
| D2 | Home | Standalone repo `lantr-io/plutus-vm-benchmark` (not a GitHub fork) with the full SAIB history and MIT credit. Page at `plutus-vm-bench.lantr.io` (GitHub Pages, CNAME at Namecheap). scalus.org links to it |
| D3 | What is timed | Node-equivalent: flat decode + evaluate with the mainnet cost model and costing on |
| D4 | Correctness gate | Result and ExUnits of every script must equal Haskell. A VM that fails is not published; the page lists it as "failed check" |
| D5 | Compiled VMs (Scalus JIT) | Same ranking as interpreters, with a "decode and compile excluded" badge (D15) and a compile-time column. Superseded by D17 for the Scalus JIT: it is in the Experimental section today; the badge and the compile-time column stay |
| D6 | PR automation | Bot opens version-bump PRs (`.env` only); they auto-merge on smoke + gate pass. Code PRs need human review; their CI has no secrets |
| D7 | Schedule | Monthly cron (skip if nothing merged since the last run) + manual button |
| D8 | Corpus | The existing 89 `plutus_use_cases` scripts. A mainnet PlutusV3 corpus is v2, as a separate ranking |
| D9 | Orchestration | GitHub Actions + `hcloud` CLI; NixOS installed on a fresh Ubuntu server by nixos-anywhere on each run |
| D10 | Older cost model | Where a VM API accepts a cost model, the harness passes the mainnet PlutusV3 model and D4 applies. Otherwise the row is published with an "outdated cost model" badge; the gate then requires ExUnits equal to Haskell under that VM's own semantics variant and model. Wrong results still hide the row |
| D11 | Gate parameters | PlutusV3, protocol version 11 (variant E), mainnet cost model, counting mode. CIP-117 unit-result rule not applied (78 PlutusV1-era scripts return a non-unit term) . The 89 scripts are PlutusV1-era; they are evaluated as PlutusV3 programs, like Plutus's own `validation` CEK benchmark (plutus-benchmark BenchCek.hs), and the page says so. Owner chose this over node-exact PlutusV1 rules (variant D), which would push the Scalus JIT to its CEK fallback |
| D12 | Pins | Release tags for every VM (Aiken v1.1.24, Scalus v1.4.1, plutus 1.70.0.0). Haskell follows the plutus-core version of the latest cardano-node release (today node 11.1.3 = plutus-core 1.70.0.0); the bump bot reads it from the node release notes. |
| D13 | Warm-up and measurement | JIT runtimes (JVM, V8): 20 s warm-up and three 5 s measurements. AOT runtimes (Rust, Go, GHC): the defaults of their benchmark framework, with at least 5 s of measurement |
| D14 | Process model | A fresh process per script for every VM. No JIT profile, heap or allocator state carries over between scripts. The d3 and eval loops of a script share that process (d3 first, each loop with its own warm-up and measurement), except JMH, which forks a JVM per loop |
| D15 | Scalus JIT badge | "decode and compile excluded": the timed loop runs the compiled script; the decode and the compile run once per script, before timing. Its time is an eval-only time (D21) |
| D16 | Runtime settings | Each VM runs with the settings its project documents for production use, else with the runtime defaults. Scalus must document its JVM flags in public |
| D17 | Inclusion rules | A ranked row needs (1) a published release: a stable version on a package registry, or a release tag; pre-releases such as `-alpha` or `0.1.0-preNN` do not count; (2) a downstream user today: a released project outside the VM's own repo that depends on it, default evaluator or not, listed with a proof link (`USED_BY`); (3) a pass of the correctness gate. A library that caches the decoded program or compiles it ahead gets a badge: Scalus JIT style "decode and compile excluded"; Aiken WASM "decode cached (by the library)". Such a VM is ranked only on eval only (D21). An unranked "Experimental" section (D22) shows rows that miss rule (1) or rule (2); among them are the Scalus JIT (the `scalus-uplc-jit-compiler` module is on Maven since Scalus 1.4.1, 2026-10-26, but has no downstream users yet) and blaze-plutus (2026-10-24: no project outside the Blaze repo depends on `@blaze-cardano/plutus`; Blaze uses `@blaze-cardano/vm`, Aiken uplc as WASM). Aiken WASM is ranked: the published npm package `@lucid-evolution/uplc` 0.4.0 used as is, built from colll78/aiken (aiken main plus fixes) |
| D18 | Server qualification | Servers of one Hetzner type differ: one ccx43 ran every VM 2.1x slower than another ccx43 (same CPU model AMD EPYC-Milan, 0 % steal); two good ccx33 servers agreed within 0.3 % on Haskell. So each run times the Haskell image on 3 scripts (`auction_1-1`, `coop-6`, `uniswap-1`; d3, normal timing, the run's docker flags and CPU set) right after the server install. It compares the geometric mean with the reference of the server type (`check/reference/host-reference.json`, harness b0d8a22, measured 2026-10-22). A ratio above 1.15 deletes the server and creates a new one, at most 3 servers, then the run fails. A faster server passes. No reference for the type: skip with a warning. The result goes to `environment.txt` and the job summary. Refresh the reference with `scripts/hetzner/qualify.py reference` when the Haskell harness changes |
| D19 | Full-run hardware | `ccx43` (16 dedicated vCPUs) with 3 lanes. Measured on one ccx43: with 3 lanes the geometric mean of each VM moved by -2.4 % to +0.9 % against one lane, within the noise; only the experimental Scalus JIT moved by +7 %. Run time on 5 scripts: 31 min to 12 min, about 3.6 h projected for 89 scripts. A full run has every VM, script and loop, normal timing, no trace, and 1 lane or the default 3 lanes; a comma list (A/B test) is always partial. A ccx33 with 1 lane stays possible. The Hetzner project limit must allow a ccx43 (16 vCPUs) |
| D20 | History noise band | The ratio of a VM to Haskell varies by up to about 5 % between two good servers. The history chart shows a change below 5 % as no change |
| D21 | Eval-only VMs | (2026-10-26) A VM whose decode runs outside its timed loop has only an eval-only time: one that compiles each script before timing (D15), and one whose library caches decoded programs with no off switch. It is never in the decode + eval ranking, is not a competitor in the penalty rule there, and is ranked only on eval only (if it meets D17). Its history ratio uses Haskell's eval-only time. Reason: `@lucid-evolution/uplc` caches decoded programs (`ProgramCache`, keyed by a hash of the bytes) and the cache cannot be turned off, so its "decode + eval" time is really hash + eval (`aiken-wasm.csv` equals `aiken-wasm-eval.csv`). It cannot be timed on decode + eval without changing the inputs, which D17 ("used as it is") forbids. One rule for every VM whose decode runs outside the timed loop. The page says so next to the decode + eval ranking |
| D22 | Experimental scope | (2026-10-26, changed 2026-10-30) The Experimental section shows any VM that misses D17 rule 1 (no stable release) or rule 2 (no downstream user). The VM need not be of the original SAIB line-up. Its pin is a commit or tag on any branch, by full commit SHA; by default the newest pre-release tag, else the newest `main` commit. A pin that can no longer be fetched (for example, a branch that was force-pushed) drops the row until it is re-pinned. The page shows the reason next to the row: "pre-release only", "no release", "no downstream user" or "outdated". An experimental row never gets a rank. It is never a competitor in the penalty rule. It has no line in the history chart. The gate checks each script of an experimental row. A script that fails the gate is marked "failed check" on its cell, and its time is left out of the row's geometric mean. The row itself stays. A row with no passing script, or without `<vm>-check.csv`, is listed as "failed check" (D4). A VM whose built-in cost model is outdated and that has no API for a cost model is shown with the D10 badge "outdated cost model" and the reason "outdated". Today: Chrysalis (`chrysalis`, `chrysalis-aot`), Julc (`julc-java`), Plutuz (`plutuz`), amaru-uplc bytecode mode (`uplc-turbo-bc`, a commit of the fork jonathanlim222/uplc), Scalus JIT and blaze-plutus. llvm-uplc (`llvm-uplc-jit`, outdated: variant C cost model, last commit 2026-04-16). Not OpShin (it fails rule 3) and not blaze-jsc. Reason: the SAIB benchmark showed these VMs, their authors and users want to see them, and new VMs get a place to show results before a release. The ranking stays for VMs that meet D17 |

### Line-up (rules: D17)

15 VMs. 7 are ranked, 8 are experimental (D22). The page calls `uplc-turbo` "amaru-uplc", the name of the pragma-org/uplc crate; the image ids stay:

| VM (image) | Language | Runtime | Status |
|---|---|---|---|
| Haskell plutus-core (`haskell`) | Haskell | GHC | Ranked |
| Scalus CEK (`scalus-cek`) | Scala | JVM (GraalVM) | Ranked |
| Scalus JIT (`scalus-jit`) | Scala | JVM (GraalVM) | Experimental: no downstream user yet; badge "decode and compile excluded" |
| Scalus.js (`scalus-js`) | Scala.js | Node (V8) | Ranked |
| Aiken (`aiken`) | Rust | native | Ranked |
| Aiken WASM, `@lucid-evolution/uplc` 0.4.0 (`aiken-wasm`) | Rust → WASM | Node (V8) | Ranked, badge "decode cached (by the library)" |
| amaru-uplc, Amaru (`uplc-turbo`) | Rust | native | Ranked |
| plutigo, Dingo (`plutigo`) | Go | native | Ranked |
| blaze-plutus (`blaze-v8`) | TypeScript | Node (V8) | Experimental: no downstream user yet |
| Chrysalis (`chrysalis`) | C# | .NET (JIT) | Experimental: pre-release only (NuGet `Chrysalis.Plutus` 1.7.14-alpha or newer) |
| Chrysalis AOT (`chrysalis-aot`) | C# | .NET (native AOT) | Experimental: pre-release only |
| Julc (`julc-java`) | Java | JVM | Experimental: pre-release only (`0.1.0-preNN`) |
| Plutuz (`plutuz`) | Zig | native | Experimental: no release (`main` commit) |
| amaru-uplc bytecode, fork jonathanlim222/uplc (`uplc-turbo-bc`) | Rust | native | Experimental: no release with the bytecode mode |
| llvm-uplc (`llvm-uplc-jit`) | C++ | native (LLVM JIT) | Experimental: outdated (variant C cost model, no cost-model API, last commit 2026-04-16); badges "outdated cost model", "decode and compile excluded" |

Dropped:

- OpShin uplc: rule 3. It fails the correctness gate at its latest release 1.3.3 (no `case` on
  builtin values, a protocol version 11 feature).
- blaze-jsc (blaze on Bun / JavaScriptCore), removed 2026-10-22: not a separate evaluator. Every JS
  row runs on Node 24 LTS (V8), the common runtime for Cardano off-chain code; one engine keeps the JS
  rows comparable. The row also cost about 1.8 h per run.

Aiken WASM returned 2026-10-22. It was removed on 2026-10-21, because `@lucid-evolution/uplc`
caches decoded programs with no off switch, so it cannot run the D3 loop as published. D17 ranks
such a library with a badge instead. The package is a published release (npm 0.4.0) and Lucid
Evolution uses it, so it meets the three rules. The harness uses the package as is.

## 1. Components

Repo `lantr-io/plutus-vm-benchmark`:

| Unit | Does | Change from today |
|---|---|---|
| `harness/<vm>/` + `scripts/run-<vm>.sh` | One harness per VM | Add `aiken`, `aiken-wasm`, `scalus-js`. Chrysalis, Julc, Plutuz, llvm-uplc and uplc-turbo-bc return as experimental (D22) |
| `.env` | Pins each VM to a SHA or tag | Haskell pinned to the plutus tag of the production node (today 1.63.0.0) |
| `images/` | One Docker image per VM, pushed to GHCR | Replaces the single image: a bump rebuilds one VM only |
| `check/` | Correctness gate: each VM writes result + ExUnits per script; the gate diffs them against Haskell | New |
| `parsers/`, `report/` | Outputs → `unified.csv` → HTML report | Add compile-time column, "decode and compile excluded" badge, history chart, drift note |
| `results/<date>/` | Git-tracked history with `environment.txt` and pins | Kept |
| `.github/workflows/` | `smoke.yml` (PRs, no secrets), `bump.yml` (bot), `run.yml` (monthly + manual) | New |

NixOS config of the bench server, in this repo (not in `infra`: `infra` is local-only and holds secrets,
so a workflow cannot fetch it; a public config also lets anyone rebuild the exact machine):

- `flake.nix` output `bench-runner` = `nix/runner.nix` + `nix/disko.nix`.
- Rootful Docker (compose needs `SYS_NICE`), CPU governor `performance`.
- Root SSH keys come from the Hetzner metadata service at boot (per-run key, nothing baked in).
- `bench-selfdestruct.timer`: 20 h after boot, deletes its own server through the Hetzner API.
- Quiet host: the logrotate and fstrim timers are off, transparent huge pages are pinned to
  `madvise`. `run-images.sh` gives each container CPUs 1 to N-1 (CPU 0 stays for the host) and no
  network.
- `scripts/hetzner/up.sh` creates an Ubuntu server and installs the config with
  `nixos-anywhere --build-on remote` (no x86_64-linux builder needed). `down.sh` deletes it,
  `sweep.sh` deletes servers older than 22 h.
- Hetzner has no official NixOS image. Install on each run costs ~5–10 min of a multi-hour run. If it
  becomes flaky, snapshot an installed server with `hcloud server create-image` and boot from that.

Hetzner: a separate project for the benchmark. One fixed CCX (dedicated vCPU) server type. The API token is
stored only in the `run.yml` GitHub environment, which only `main` can use.

Token blast radius:

- Hetzner Cloud tokens are scoped to one project. A leaked bench token cannot read or change other lantr
  projects (for example `sugarrush-demo`).
- Inside the bench project a Read & Write token can create and delete servers. Hetzner has no finer scope.
  Limit the damage: keep the project server limit low (do not request an increase), set a billing alert,
  and let `sweep.yml` delete stray servers.
- The self-destruct timer needs the token on the server. Store it as a root-only `0400` file outside the
  Nix store. Benchmark containers do not mount it, because they run third-party VM code.

## 2. Data flow

### Version bump (`bump.yml`, weekly)

1. For each VM, read the latest upstream release tag. Scalus uses the latest tag, not master.
2. If a pin changed, open a PR that changes only `.env`.
3. `smoke.yml` builds the changed image, times 5 scripts, and runs the gate on all 89 scripts.
4. Pass: auto-merge. Fail: label `needs-human`; the old pin stays.

### Monthly run (`run.yml`)

1. Skip if no merge happened since the last `results/` directory.
2. Build and push changed images to GHCR on GitHub runners (not on the paid server).
3. `scripts/hetzner/up.sh`: create an Ubuntu server (run ID as a label) and install NixOS with nixos-anywhere.
4. Over SSH: pull all images, write `environment.txt` (hardware and noise data), run the VMs one at
   a time (Haskell first), run Haskell again on 5 scripts (drift probe), run the gate.
5. Copy `results/<date>/` back to the workflow.
6. `hcloud server delete` in an `always()` step. The self-destruct timer is the backstop.
7. Build the report. Rows that fail the gate are left out and listed as "failed check".
8. Commit the results to `main` and deploy GitHub Pages.

### History

- The chart plots each VM's geometric mean divided by Haskell's from the same run. The ratio survives
  hardware changes and reduces the ~10% drift between runs.
- The table shows absolute µs for the latest run only.

Expected run time: 3–5 h for the full line-up (the 4-VM run took 1.5 h on an M3 Max). Measure on the first run.

## 3. Failure handling and cost guards

- One VM fails to build or run: its row shows "failed", the run still publishes the others.
- Gate fails for a VM in the monthly run: row hidden, listed as "failed check", issue opened automatically.
- Server cleanup has three layers:
  1. `always()` delete step in `run.yml`.
  2. `bench-selfdestruct.timer` on the server (20 h).
  3. A daily `sweep.yml` deletes any server in the bench project with a run label older than 22 h.
- SSH or image pull fails: retry once, then delete the server and fail the workflow.
- Hetzner has no hard spending cap. Set a billing alert on the project.

## 4. Testing

- Gate test: feed a VM output with one wrong ExUnits value; the gate must fail. Run this in `smoke.yml`.
- Each new harness (Aiken, Aiken WASM, Scalus.js) must pass the gate on all 89 scripts before it joins.
- Dry run of `run.yml` with a cheap shared-vCPU server type and 3 VMs; verify the server is gone afterwards.
- First real run: compare Haskell ratios with the M3 Max runs of 2026-10-11; flag differences above 20%.

## 5. Open questions

1. Exact CCX type (for example CCX33 vs CCX43). `up.sh` defaults to `ccx33`.
2. Cost model and language version for the 89 scripts under D3: every VM in the line-up must support it.
