# Guidance for coding agents

## What this repo is

A reproducible benchmark of Plutus (UPLC) evaluators. Each VM is one Docker image
(`ghcr.io/lantr-io/pvb-<vm>`). Each image times a flat decode + evaluation of 89 scripts
(PlutusV3, protocol version 11, mainnet cost model). A correctness gate compares each VM with
Haskell plutus-core. Results go to `results/<date>/` and to the page `docs/index.html`.
Read `README.md`, `METHODOLOGY.md` and `docs/IMAGE_CONTRACT.md` first.

## Layout

- `.env` – pins of every VM (release SHA or tag) and toolchain versions.
- `images/<vm>/Dockerfile` – one image per VM. `images/scalus` (`scalus-cek`, `scalus-jit`) and
  `images/scalus` (`scalus-cek`, `scalus-jit`) serves two VMs (header `# pvb-vms:`).
- `scripts/run-<vm>.sh` – per-VM runner, the default command of its image.
- `scripts/image-entry.sh` – entry point of every image: switches, data selection, exit code.
- `scripts/images.sh` – `list`, `tag`, `build` the images.
- `scripts/run-images.sh` – runs images one at a time, then gate, normalize and report.
- `scripts/run-variants.sh` – runs `run-images.sh` once per line of a variants file
  (`scripts/variants/`) on one server, for A/B tests of settings; `run.yml` input `variants`.
- `check/` – correctness gate (`gate.py`, tests in `test_gate.py`) and the Haskell reference.
- `parsers/` – one normalizer per benchmark framework; `normalize.py` merges the CSVs.
- `report/` – `unified.csv` to `report.md` and `docs/index.html`.
- `nix/`, `flake.nix` – NixOS config of the bench server. `scripts/hetzner/` – create, use, delete it.
- `.github/workflows/` – `images.yml` (build, push), `run.yml` (monthly and manual run),
  `sweep.yml` (delete old servers), `provision-test.yml`.

## Image contract and switches

See `docs/IMAGE_CONTRACT.md`. An image reads `/bench/data/plutus_use_cases/*.flat` and writes to
`/results`. Switches: `BENCH_SCRIPTS` (regex on the script name), `BENCH_LOOPS` (`d3`, `eval`,
`check`), `BENCH_TIMING` (`normal`, `quick`). `BENCH_QUICK=1` means quick timing and 5 scripts.

```bash
BENCH_SCRIPTS='auction_1-1|uniswap-1' BENCH_LOOPS=d3,check BENCH_TIMING=quick \
  scripts/run-images.sh /tmp/subset plutigo aiken
BENCH_LOOPS=check scripts/run-images.sh /tmp/check amaru-uplc
```

## Add or bump a VM

- Bump: change the pin in `.env` to a release. The image tag changes, so `images.yml` rebuilds
  only that image. Run the check on all 89 scripts before you commit.
- Add: `images/<vm>/Dockerfile`, `scripts/run-<vm>.sh` and a parser in `parsers/` if the
  framework is new. Follow `docs/IMAGE_CONTRACT.md`. `normalize.py` needs no edit.
- A VM joins only with a downstream user today (a released project outside its repo that depends
  on it; add it with a proof link to `USED_BY` in `report/generate_report.py`), a stable release
  and a passing gate (README, "Not included"). Update the README VM table and `report/` labels.

## Gotchas

- Host `python3` may be too old. `run-images.sh` uses it only if it is 3.10+; else it runs
  the parsers, gate and report in `python:3.12-slim`.
- `run-images.sh` rewrites `docs/index.html`. After a local run, restore it:
  `git checkout docs/index.html`.
- `results/partial-*`, `results/quick-*` and `results/local-*` are git-ignored. Use them for
  local runs.
- Never commit secrets (Hetzner token, SSH keys). They live only in GitHub environments.
- The Hetzner bench server runs only through `run.yml`. Do not run `scripts/hetzner/` by hand.
- Publish only full runs (all VMs, all scripts, normal timing). Never commit a subset run to
  `results/<date>/`.

## Commits

Conventional Commits (`feat:`, `fix:`, `docs:`, `build:`, `chore:`), optional scope such as
`docs(readme):`. No AI attribution: no `Co-Authored-By` trailers, no "Generated with" footers.
Stage files by name; never `git add -A`.
