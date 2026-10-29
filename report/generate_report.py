#!/usr/bin/env python3
"""Generate markdown and HTML comparison reports from unified.csv.

Usage: generate_report.py [--write-index] <run-dir>
Writes <run-dir>/report.md and <run-dir>/index.html. With --write-index, also writes the same page
to <repo>/docs/index.html, the published page: only run.yml sets it, for a published run. Then it
also writes docs/robots.txt, docs/sitemap.xml and docs/og.png (the link-preview image, a headless
Chrome screenshot; without Chrome the committed og.png stays).

Reads from the run dir:
- unified.csv            timings of every VM
- gate.json              correctness verdicts (check/gate.py). When present, a VM with verdict
                         "fail" or without a verdict is hidden and listed as "failed check"; a VM
                         with verdict "badge" is shown with an "outdated cost model" badge. Old runs
                         without gate.json are shown as they are
- <vm>-compile.csv       compile time per script (vm,script,compile_ns), for VMs that compile
                         before they run: "decode and compile excluded" badge and a
                         compile-time column. Such a VM decodes and compiles each script once,
                         before timing, so its timed loop is eval only: it has no decode + eval
                         time. Its time is shown only as an eval-only time (from <vm>-eval.csv, or
                         its D3 rows if the run has no <vm>-eval.csv). It is not in the decode +
                         eval ranking, the penalty rule, the geometric-mean chart or the
                         per-script fastest; its history ratio uses Haskell's eval-only time
- <vm>-eval.csv          eval-only timing (program decoded once before the timed loop): an "eval
                         only" column next to the D3 time and its geometric mean. The ranking
                         stays on the D3 time
A VM in EXPERIMENTAL that passes the gate is shown in its own "Experimental" section with its
numbers, but it is not ranked: not in the summary ranking, not a competitor in the penalty rule,
not in "vs fastest" or the per-script fastest. A compiling VM that is not in EXPERIMENTAL is
shown there too (COMPILING_REASON): it has no decode + eval time to rank.
A VM in DECODE_CACHED (its library caches decoded programs and cannot be told not to) times hash +
eval in its D3 loop, not decode + eval. It stays ranked, but only on eval only, like a compiling
VM: no decode + eval time, not in that ranking, not a competitor in the penalty rule.
- drift.json             the drift probe (parsers/normalize.py): Haskell at the end of the run
                         vs the start, shown as a note
- ../<date>/             earlier runs next to this one, for the history chart: each VM's geometric
                         mean divided by Haskell's from the same run. Only runs with gate.json count
"""

from __future__ import annotations

import base64
import csv
import datetime
import glob
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from html import escape

VM_ORDER = [
    "haskell", "scalus-jit", "scalus-cek", "scalus-js",
    "aiken", "aiken-wasm", "uplc-turbo",
    "plutigo", "blaze-jsc", "blaze-v8",
    "chrysalis", "chrysalis-aot", "julc-java", "plutuz", "llvm-uplc-jit", "uplc-turbo-bc",
]

# The header logo in report/template.html, a file in docs/.
LOGO = "lantr-logo-dark.png"
# The published site: docs/index.html and its static files.
DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

# {n}: the number of scripts of the run.
DISCLOSURE = (
    "The {n} scripts are PlutusV1-era programs. Every VM evaluates them as PlutusV3 programs at "
    "protocol version 11 with the mainnet cost model, like Plutus's own `validation` CEK benchmark; "
    "the node would run them as PlutusV1."
)

# One note per VM, shown on its card and in report.md. Markdown links [text](url) only.
VM_NOTES = {
    "aiken": "Aiken v1.1.24 copies the CEK environment on every lambda application (quadratic in "
             "recursion depth). aiken main fixes it (PRs "
             "[#1451](https://github.com/aiken-lang/aiken/pull/1451), "
             "[#1452](https://github.com/aiken-lang/aiken/pull/1452): coop-6 92 ms -> 1.2 ms), "
             "but no release contains the fix yet.",
    "aiken-wasm": "Built from [colll78/aiken](https://github.com/colll78/aiken) (aiken main plus "
                  "fixes), which includes the CEK fixes that v1.1.24 lacks.",
}

# Badges for the way a VM is timed, besides the gate and compile badges: {vm: {text, title}}. The
# title explains the badge (HTML tooltip, a note in report.md).
VM_BADGES = {
    # images/aiken-wasm/README.md
    "aiken-wasm": {
        "text": "decode cached (by the library)",
        "title": "The library caches the decoded program by a hash of the flat bytes. After the first "
                 "call (in the warm-up), the timed loop runs hash + evaluation, without the decode. "
                 "Its eval-only time is the same loop.",
    },
}

# VMs that are run, gated and shown with their numbers, but not ranked (spec D17): {vm: reason}.
EXPERIMENTAL = {
    "blaze-v8": "not ranked: no released project outside the Blaze repo depends on @blaze-cardano/plutus "
                "yet; Blaze itself evaluates scripts with @blaze-cardano/vm (Aiken uplc as WASM) (spec D17)",
    "blaze-jsc": "not ranked: no released project outside the Blaze repo depends on @blaze-cardano/plutus "
                 "yet; Blaze itself evaluates scripts with @blaze-cardano/vm (Aiken uplc as WASM) (spec D17)",
    "scalus-jit": "not ranked: the JIT module is published (Maven, since Scalus 1.4.1) but has no "
                  "downstream users yet (spec D17)",
    "julc-java": "not ranked: only pre-releases (0.1.0-preNN), and no downstream users yet (spec D22)",
    "chrysalis": "not ranked: only pre-releases on NuGet (Chrysalis.Plutus -alpha); the one stable "
                 "version, 1.7.1, is unlisted (spec D22)",
    "chrysalis-aot": "not ranked: only pre-releases on NuGet (Chrysalis.Plutus -alpha); the one stable "
                     "version, 1.7.1, is unlisted (spec D22)",
    "plutuz": "not ranked: no release (no tags or releases on GitHub), pinned to a main commit (spec D22)",
    "uplc-turbo-bc": "not ranked: no release has the bytecode mode; it is in the fork jonathanlim222/uplc "
                     "(closed PR pragma-org/uplc#47), pinned to a commit (spec D22)",
    "llvm-uplc-jit": "not ranked: outdated. Its built-in cost model is variant C (before protocol "
                     "version 11; divideInteger c11 549, mainnet 960), no API takes a cost model, and "
                     "its last commit is from 2026-04-16. No release (spec D22)",
}

# The short visible reason of each EXPERIMENTAL VM (spec D22): next to its "experimental" badge,
# in the summary table and the VM list. The long reason above is the tooltip and the card text.
EXPERIMENTAL_TAG = {
    "blaze-v8": "no downstream user",
    "blaze-jsc": "no downstream user",
    "scalus-jit": "no downstream user",
    "julc-java": "pre-release only",
    "chrysalis": "pre-release only",
    "chrysalis-aot": "pre-release only",
    "plutuz": "no release",
    "uplc-turbo-bc": "no release",
    "llvm-uplc-jit": "outdated",
}


def experimental_badge(vm: str) -> str:
    """The text of the experimental badge: "experimental: <short reason>"."""
    tag = EXPERIMENTAL_TAG.get(vm)
    return f"experimental: {tag}" if tag else "experimental"


# Run-to-run noise of a ratio to Haskell (spec D20): two good servers of the same type gave ratios
# up to ~5 % apart per VM (geometric mean over the scripts). A smaller change between two runs is
# "no change". The page gets it as REPORT.noise_band.
NOISE_BAND = 0.05

# The badge of a VM with <vm>-compile.csv (Scalus JIT): its timed loop runs the compiled script,
# so neither the flat decode nor the compile step is in its time.
COMPILE_BADGE = "decode and compile excluded"
# Why a compiling VM has no decode + eval time (summary tables, tooltips).
NO_D3_NOTE = "compiled once before timing, see the compile column"
# The "not ranked" reason of a compiling VM that is not in EXPERIMENTAL.
COMPILING_REASON = "not ranked: it compiles each script once before timing, so it has no decode + eval time"
# VMs whose library caches decoded programs, with no way to turn the cache off (spec D15, D17): the
# D3 loop decodes once, then each iteration hashes the bytes and evaluates the cached program. So
# their time is shown only as eval only, as a compiling VM's; they stay ranked on eval only.
# {vm: the visible line next to the decode + eval ranking}
DECODE_CACHED = {
    "aiken-wasm": "Aiken WASM caches decoded programs inside the library, so its time is shown as eval only.",
}
# Why a decode-cached VM has no decode + eval time (summary tables, tooltips).
NO_D3_CACHED_NOTE = "the library caches decoded programs, so only an eval-only time"


def no_d3_note(vm: str) -> str:
    """Why the VM has no decode + eval time: it compiles before timing, or caches the decode."""
    return NO_D3_CACHED_NOTE if vm in DECODE_CACHED else NO_D3_NOTE


def d3_ranked(present_vms) -> list[str]:
    """The ranked VMs that have a decode + eval time: the decode + eval ranking and the
    competitors of the penalty rule. A decode-cached VM is ranked on eval only."""
    return [vm for vm in present_vms if vm not in DECODE_CACHED]

VM_LABELS = {
    "uplc-turbo": "amaru-uplc (Rust)",
    "plutigo": "Plutigo (Go)",
    "blaze-jsc": "blaze-plutus (TypeScript / Bun JSC)",
    "blaze-v8": "blaze-plutus (TypeScript / Node V8)",
    "haskell": "plutus-core (Haskell / GHC)",
    "scalus-cek": "Scalus CEK (Scala / JVM)",
    "scalus-jit": "Scalus JIT (Scala / JVM)",
    "scalus-js": "Scalus.js CEK (Scala.js / Node V8)",
    "aiken": "Aiken uplc (Rust)",
    "aiken-wasm": "Aiken uplc WASM (Rust → WASM / Node V8)",
    "julc-java": "Julc Java CEK (Java / JVM)",
    "chrysalis": "Chrysalis (C# / .NET JIT)",
    "chrysalis-aot": "Chrysalis AOT (C# / .NET AOT)",
    "plutuz": "Plutuz (Zig)",
    "uplc-turbo-bc": "amaru-uplc BC (fork) (Rust)",
    "llvm-uplc-jit": "llvm-uplc JIT (C++ / LLVM)",
}


# What each VM is, for the "VMs in this benchmark" list: implementation language, runtime and
# execution model. The model uses the page's words (template.html engineCode).
VM_FACTS = {
    "haskell": {"lang": "Haskell", "runtime": "GHC", "model": "Interpreter (CEK)"},
    "scalus-jit": {"lang": "Scala", "runtime": "GraalVM", "model": "JIT compiler (UPLC → JVM bytecode)"},
    "scalus-cek": {"lang": "Scala", "runtime": "GraalVM", "model": "Interpreter (CEK)"},
    "scalus-js": {"lang": "Scala.js", "runtime": "Node (V8)", "model": "Interpreter (CEK)"},
    "aiken": {"lang": "Rust", "runtime": "native", "model": "Interpreter (CEK)"},
    "aiken-wasm": {"lang": "Rust → WASM", "runtime": "Node (V8)", "model": "Interpreter (CEK)"},
    "uplc-turbo": {"lang": "Rust", "runtime": "native", "model": "Interpreter (AST walker)"},
    "plutigo": {"lang": "Go", "runtime": "native", "model": "Interpreter (CEK)"},
    "blaze-jsc": {"lang": "TypeScript", "runtime": "Bun (JSC)", "model": "Interpreter (CEK)"},
    "blaze-v8": {"lang": "TypeScript", "runtime": "Node (V8)", "model": "Interpreter (CEK)"},
    "julc-java": {"lang": "Java", "runtime": "GraalVM", "model": "Interpreter (CEK)"},
    "chrysalis": {"lang": "C#", "runtime": ".NET 10 (JIT)", "model": "Interpreter (CEK)"},
    "chrysalis-aot": {"lang": "C#", "runtime": ".NET 10 (NativeAOT)", "model": "Interpreter (CEK)"},
    "plutuz": {"lang": "Zig", "runtime": "native", "model": "Interpreter (CEK)"},
    "uplc-turbo-bc": {"lang": "Rust", "runtime": "native", "model": "Bytecode VM (UPLC → bytecode)"},
    "llvm-uplc-jit": {"lang": "C / C++", "runtime": "native (LLVM 22 LLJIT)", "model": "JIT compiler (UPLC → native code)"},
}

# Where each VM comes from. The pinned version is read from .env at the repo root (env: the .env
# key, pattern: a regex whose group 1 is the version, matched on "<value> # <comment>"); version
# and tag are the fallback when .env has no match. release: the release or source link ({tag}, {sha}).
_SCALUS_REPO = "https://github.com/scalus3/scalus"
_BLAZE_REPO = "https://github.com/butaneprotocol/blaze-cardano"
VM_SOURCES = {
    "haskell": {
        "repo": "https://github.com/IntersectMBO/plutus", "home": "https://plutus.cardano.intersectmbo.org",
        "env": "HASKELL_SHA", "pattern": r"release (\d+(?:\.\d+)+)", "tag": "1.70.0.0",
        "release": "https://github.com/IntersectMBO/plutus/releases/tag/{tag}"},
    "scalus-jit": {
        "repo": _SCALUS_REPO, "home": "https://scalus.org",
        "env": "SCALUS_SHA", "pattern": r"#\s*(v\d+(?:\.\d+)+)", "tag": "v1.4.1",
        "release": _SCALUS_REPO + "/releases/tag/{tag}"},
    "scalus-cek": {
        "repo": _SCALUS_REPO, "home": "https://scalus.org",
        "env": "SCALUS_VERSION", "pattern": r"^(\d+(?:\.\d+)+)", "tag": "1.4.1", "version": "v{tag}",
        "release": _SCALUS_REPO + "/releases/tag/v{tag}"},
    "scalus-js": {
        "repo": _SCALUS_REPO, "home": "https://scalus.org",
        "env": "SCALUS_JS_VERSION", "pattern": r"^(\d+(?:\.\d+)+)", "tag": "1.4.1", "version": "scalus {tag} (npm)",
        "release": _SCALUS_REPO + "/releases/tag/v{tag}"},
    "aiken": {
        "repo": "https://github.com/aiken-lang/aiken", "home": "https://aiken-lang.org",
        "env": "AIKEN_SHA", "pattern": r"#\s*(v\d+(?:\.\d+)+)", "tag": "v1.1.24",
        "release": "https://github.com/aiken-lang/aiken/releases/tag/{tag}"},
    "aiken-wasm": {
        "repo": "https://github.com/Anastasia-Labs/lucid-evolution",
        "home": "https://anastasia-labs.github.io/lucid-evolution/",
        "env": "LUCID_UPLC_VERSION", "pattern": r"^(\d+(?:\.\d+)+)", "tag": "0.4.0",
        "version": "@lucid-evolution/uplc {tag}",
        "release": "https://github.com/Anastasia-Labs/lucid-evolution/releases/tag/@lucid-evolution/uplc@{tag}"},
    "uplc-turbo": {
        "repo": "https://github.com/pragma-org/amaru", "home": None,
        "env": "AMARU_UPLC_VERSION", "pattern": r"^(\d+(?:\.\d+)+)", "tag": "0.4.0",
        "version": "amaru-uplc {tag}", "sha_env": "AMARU_UPLC_SHA",
        "release": "https://github.com/pragma-org/amaru/tree/{sha}/crates/amaru-uplc"},
    "plutigo": {
        "repo": "https://github.com/blinklabs-io/plutigo", "home": None,
        "env": "PLUTIGO_SHA", "pattern": r"#\s*(v\d+(?:\.\d+)+)", "tag": "v0.10.0",
        "release": "https://github.com/blinklabs-io/plutigo/releases/tag/{tag}"},
    "blaze-jsc": {
        "repo": _BLAZE_REPO, "home": "https://blaze.butane.dev",
        "env": "BLAZE_SHA", "pattern": r"@blaze-cardano/plutus (\d+(?:\.\d+)+)", "tag": "0.1.1",
        "version": "@blaze-cardano/plutus {tag}",
        "release": _BLAZE_REPO + "/releases/tag/@blaze-cardano/plutus@{tag}"},
    "blaze-v8": {
        "repo": _BLAZE_REPO, "home": "https://blaze.butane.dev",
        "env": "BLAZE_SHA", "pattern": r"@blaze-cardano/plutus (\d+(?:\.\d+)+)", "tag": "0.1.1",
        "version": "@blaze-cardano/plutus {tag}",
        "release": _BLAZE_REPO + "/releases/tag/@blaze-cardano/plutus@{tag}"},
    "julc-java": {
        "repo": "https://github.com/bloxbean/julc", "home": None,
        "env": "JULC_VERSION", "pattern": r"^(\d+\.\d+\.\d+-pre\d+)", "tag": "0.1.0-pre19", "version": "v{tag}",
        "release": "https://github.com/bloxbean/julc/releases/tag/v{tag}"},
    "chrysalis": {
        "repo": "https://github.com/SAIB-Inc/Chrysalis", "home": None,
        "env": "CHRYSALIS_VERSION", "pattern": r"^(\S+)", "tag": "1.7.14-alpha", "version": "Chrysalis.Plutus {tag} (NuGet)",
        "release": "https://www.nuget.org/packages/Chrysalis.Plutus/{tag}"},
    "chrysalis-aot": {
        "repo": "https://github.com/SAIB-Inc/Chrysalis", "home": None,
        "env": "CHRYSALIS_VERSION", "pattern": r"^(\S+)", "tag": "1.7.14-alpha", "version": "Chrysalis.Plutus {tag} (NuGet)",
        "release": "https://www.nuget.org/packages/Chrysalis.Plutus/{tag}"},
    # No release: the pin is a main commit; the version is its short SHA, linked to the commit.
    "plutuz": {
        "repo": "https://github.com/utxo-company/plutuz", "home": None,
        "env": "PLUTUZ_SHA", "pattern": r"^([0-9a-f]{7})", "tag": "33b812d", "version": "main {tag}",
        "release": "https://github.com/utxo-company/plutuz/commit/{tag}"},
    "uplc-turbo-bc": {
        "repo": "https://github.com/jonathanlim222/uplc", "home": None,
        "env": "UPLC_TURBO_BC_SHA", "pattern": r"^([0-9a-f]{7})", "tag": "069cef5", "version": "fork {tag}",
        "release": "https://github.com/jonathanlim222/uplc/commit/{tag}"},
    "llvm-uplc-jit": {
        "repo": "https://github.com/SeungheonOh/llvm-uplc", "home": None,
        "env": "LLVM_UPLC_SHA", "pattern": r"^([0-9a-f]{7})", "tag": "6bcef67", "version": "main {tag}",
        "release": "https://github.com/SeungheonOh/llvm-uplc/commit/{tag}"},
}

# The downstream users of each VM (spec D17): released projects outside the VM's own repo that
# depend on it, default evaluator or not. (name, kind, project url, proof url); the proof is a
# dependency line or the project's docs. A VM without one is shown in Experimental, not ranked.
USED_BY = {
    "haskell": [
        ("cardano-node", "node", "https://github.com/IntersectMBO/cardano-node",
         "https://github.com/IntersectMBO/cardano-ledger/blob/master/eras/alonzo/impl/cardano-ledger-alonzo.cabal#L112")],
    "scalus-cek": [
        ("Hydrozoa", "L2", "https://github.com/cardano-hydrozoa/hydrozoa",
         "https://github.com/cardano-hydrozoa/hydrozoa/blob/main/build.sbt#L171"),
        ("Bifrost", "bridge", "https://github.com/FluidTokens/ft-bifrost-bridge",
         "https://github.com/lantr-io/binocular/blob/main/build.sbt#L147"),
        ("Cardano Client Lib", "SDK", "https://github.com/bloxbean/cardano-client-lib",
         "https://github.com/bloxbean/cardano-client-lib/blob/master/docs/content/integrations/scalus-integration-api.mdx#L35"),
        ("Yaci Store", "indexer", "https://github.com/bloxbean/yaci-store",
         "https://github.com/bloxbean/yaci-store/blob/main/gradle/libs.versions.toml#L7"),
        ("Yaci DevKit", "dev tool", "https://github.com/bloxbean/yaci-devkit",
         "https://github.com/bloxbean/yaci-devkit/blob/main/docs/pages/services.mdx#L31")],
    "scalus-js": [
        ("Lucid Evolution", "SDK", "https://github.com/Anastasia-Labs/lucid-evolution",
         "https://github.com/Anastasia-Labs/lucid-evolution/blob/main/packages/scalus-uplc/package.json#L39"),
        ("MeshJS", "SDK", "https://github.com/MeshJS/mesh",
         "https://github.com/MeshJS/mesh/blob/main/packages/mesh-core-cst/package.json#L56"),
        ("Evolution SDK", "SDK", "https://github.com/IntersectMBO/evolution-sdk",
         "https://github.com/IntersectMBO/evolution-sdk/blob/main/packages/scalus-uplc/package.json#L41")],
    "aiken": [
        ("Aiken", "compiler", "https://aiken-lang.org",
         "https://github.com/aiken-lang/aiken/blob/main/crates/aiken-project/Cargo.toml#L54"),
        ("Blaze SDK", "SDK", "https://github.com/butaneprotocol/blaze-cardano",
         "https://github.com/butaneprotocol/blaze-cardano/blob/main/packages/blaze-uplc/wasm/Cargo.toml#L15")],
    "aiken-wasm": [
        ("Lucid Evolution", "SDK", "https://github.com/Anastasia-Labs/lucid-evolution",
         "https://github.com/Anastasia-Labs/lucid-evolution/blob/main/packages/lucid/package.json#L63")],
    "uplc-turbo": [
        ("Amaru", "node", "https://github.com/pragma-org/amaru",
         "https://github.com/pragma-org/amaru/blob/main/Cargo.toml#L147")],
    "plutigo": [
        ("Dingo", "node", "https://github.com/blinklabs-io/dingo",
         "https://github.com/blinklabs-io/dingo/blob/main/go.mod#L24")],
}


def read_env(path: str) -> dict[str, str]:
    """{KEY: "<value> # <comment>"} of a .env file; {} if it is missing."""
    out: dict[str, str] = {}
    if not os.path.isfile(path):
        return out
    with open(path) as f:
        for line in f:
            key, sep, rest = line.strip().partition("=")
            if sep and key and not key.startswith("#"):
                out[key.strip()] = rest.strip()
    return out


def vm_links(env: dict[str, str]) -> dict[str, dict]:
    """{vm: {repo, home, release, version, used_by}} for every VM in VM_SOURCES. The tag comes from
    the .env pin when its pattern matches, else from VM_SOURCES."""
    out = {}
    for vm, s in VM_SOURCES.items():
        if vm == "uplc-turbo" and "AMARU_UPLC_VERSION" not in env and "UPLC_TURBO_SHA" in env:
            # Existing result directories keep the original pragma-org/uplc pin in pins.env.
            s = {
                "repo": "https://github.com/pragma-org/uplc", "home": None,
                "env": "UPLC_TURBO_SHA",
                "pattern": r"#\s*(amaru-uplc-v\d+(?:\.\d+)+)",
                "tag": "amaru-uplc-v0.4.0", "version": "{tag}",
                "release": "https://github.com/pragma-org/uplc/releases/tag/{tag}",
            }
        m = re.search(s["pattern"], env.get(s["env"], ""))
        tag = m.group(1) if m else s["tag"]
        sha = env.get(s.get("sha_env", ""), "").split("#", 1)[0].strip()
        out[vm] = {
            "repo": s["repo"],
            "home": s["home"],
            "release": s["release"].format(tag=tag, sha=sha),
            "version": s.get("version", "{tag}").format(tag=tag),
            "used_by": [{"name": n, "kind": k, "url": u, "proof": p} for n, k, u, p in USED_BY.get(vm, [])],
        }
    return out


def load_vm_links(run_dir: str) -> dict[str, dict]:
    """vm_links of the run's pins: <run>/pins.env (the .env the run used, copied by run-images.sh),
    else the .env at the repo root (older runs), so a re-rendered page shows the run's versions."""
    pins = os.path.join(run_dir, "pins.env")
    if not os.path.isfile(pins):
        pins = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    return vm_links(read_env(pins))


def vm_anchor(vm: str) -> str:
    """The id of a VM's row in "VMs in this benchmark"."""
    return "vm-" + re.sub(r"[^a-z0-9-]", "-", vm.lower())


def md_links_to_html(text: str) -> str:
    """Escaped text with markdown links [text](https://...) as links (as noteLine in the page)."""
    return re.sub(r"\[([^\]]+)\]\((https:[^)\s]+)\)",
                  r'<a href="\2" target="_blank" rel="noopener">\1</a>', html.escape(text, quote=False))


def vm_list_badges(vm: str, gate: dict | None, hidden: dict[str, str], compile_ns) -> list[tuple[str, str, str]]:
    """[(css class, text, title)] of a VM in the VM list."""
    out = []
    if vm in hidden:
        out.append(("failed", "failed check", hidden[vm]))
    elif gate is not None and gate["vms"].get(vm, {}).get("verdict") == "badge":
        out.append(("outdated", "outdated cost model",
                    "The VM cannot load the mainnet cost model; its ExUnits equal Haskell with the model the VM ships"))
    if vm in EXPERIMENTAL:
        out.append(("exp", experimental_badge(vm), EXPERIMENTAL[vm]))
    if vm in VM_BADGES:
        out.append(("timing", VM_BADGES[vm]["text"], VM_BADGES[vm]["title"]))
    if vm in compile_ns:
        out.append(("compile", COMPILE_BADGE, "Each script is decoded and compiled once, before the timed loop"))
    return out


def vm_list_order(data, scripts, present_vms, experimental, hidden) -> list[str]:
    """Ranked VMs fastest first (the penalised geometric mean, as the page's bars), then the
    experimental ones, then the ones that failed the check."""
    d3 = d3_ranked(present_vms)
    geo = compute_geo_means(data, scripts, d3)
    ranked = sorted(d3, key=lambda vm: (geo.get(vm) or float("inf"), vm))
    cached = [vm for vm in present_vms if vm not in d3]
    failed = sorted(hidden, key=lambda v: (VM_ORDER.index(v) if v in VM_ORDER else 99, v))
    return ranked + cached + list(experimental) + failed


def _ext(url: str, text: str) -> str:
    return f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{html.escape(text)}</a>'


def _short(url: str) -> str:
    """https://github.com/a/b -> a/b; https://x.org/ -> x.org"""
    u = url.split("://", 1)[-1].rstrip("/")
    return u[len("github.com/"):] if u.startswith("github.com/") else u


def vm_list_html(order: list[str], links: dict[str, dict], gate, hidden, compile_ns) -> str:
    """The rows of "VMs and toolchains" (static HTML, one table row per VM, id vm-<key>). The page
    fills the toolchain cell (.vml-tc) from its VM metadata."""
    rows = []
    for vm in order:
        facts = VM_FACTS.get(vm, {"lang": "", "runtime": "", "model": ""})
        link = links.get(vm)
        name = html.escape(VM_LABELS.get(vm, vm))
        meta = ", ".join(html.escape(x) for x in (facts["lang"], facts["runtime"], facts["model"]) if x)
        key = re.sub(r"[^a-z0-9-]", "-", vm.lower())
        cells = []
        version = _ext(link["release"], link["version"]) if link else "&ndash;"
        if link:
            cells.append(f'<span class="vml-k">source</span> {_ext(link["repo"], _short(link["repo"]))}')
            if link["home"]:
                cells.append(f'<span class="vml-k">home</span> {_ext(link["home"], _short(link["home"]))}')
        badges = "".join(f'<span class="vm-badge {c}" title="{html.escape(t)}">{html.escape(x)}</span>'
                         for c, x, t in vm_list_badges(vm, gate, hidden, compile_ns))
        note = f'<div class="vml-note">{md_links_to_html(VM_NOTES[vm])}</div>' if vm in VM_NOTES else ""
        cls = ' class="failed"' if vm in hidden else ' class="exp"' if vm in EXPERIMENTAL else ""
        badge_html = f'<span class="vm-badges">{badges}</span>' if badges else ""
        link_html = "".join(f"<span>{c}</span>" for c in cells) or "&ndash;"
        users = (link or {}).get("used_by") or []
        used_html = "".join(
            f'<span class="vml-user">{_ext(u["url"], u["name"])} <span class="vml-kind">{html.escape(u["kind"])}</span>'
            f' {_ext(u["proof"], "proof")}</span>' for u in users) or '<span class="vml-none">none yet</span>'
        rows.append(
            f'<tr{cls} id="{vm_anchor(vm)}">'
            f'<td><span class="vml-title"><span class="vsw" style="background:var(--vm-{key}, var(--vm-other))"></span>{name}</span>'
            f'<span class="vml-sub">{meta}</span><span class="vml-tc" data-vm="{html.escape(vm)}"></span></td>'
            f'<td>{version}</td>'
            f'<td class="vml-links">{link_html}</td>'
            f'<td class="vml-used">{used_html}</td>'
            f'<td>{badge_html}{note}</td></tr>')
    return "\n".join(rows)


def vm_list_markdown(order: list[str], links: dict[str, dict], gate, hidden, compile_ns) -> list[str]:
    """The VM list of report.md: a markdown table with links."""
    lines = ["## VMs in this benchmark", "",
             "| VM | Language | Runtime | Execution model | Version | Source | Home | Used by | Badges | Note |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for vm in order:
        facts = VM_FACTS.get(vm, {"lang": "", "runtime": "", "model": ""})
        link = links.get(vm)
        version = f'[{link["version"]}]({link["release"]})' if link else "-"
        repo = f'[{_short(link["repo"])}]({link["repo"]})' if link else "-"
        home = f'[{_short(link["home"])}]({link["home"]})' if link and link["home"] else "-"
        used_by = ", ".join(f'[{u["name"]}]({u["url"]}) ({u["kind"]})' for u in link["used_by"]) if link and link["used_by"] else "-"
        badges = ", ".join(x for _, x, _ in vm_list_badges(vm, gate, hidden, compile_ns)) or "-"
        note = VM_NOTES.get(vm, "-").replace("|", "\\|")
        lines.append(f'| {VM_LABELS.get(vm, vm)} | {facts["lang"]} | {facts["runtime"]} | {facts["model"]} | '
                     f'{version} | {repo} | {home} | {used_by} | {badges} | {note} |')
    return lines


def fmt_ns(ns: int) -> str:
    """Format nanoseconds into human-readable string."""
    if ns >= 1_000_000_000:
        return f"{ns / 1e9:.2f} s"
    if ns >= 1_000_000:
        return f"{ns / 1e6:.2f} ms"
    if ns >= 1_000:
        return f"{ns / 1e3:.2f} us"
    return f"{ns} ns"


def geometric_mean(values: list[float]) -> float:
    """Compute geometric mean of positive values."""
    if not values:
        return 0
    log_sum = sum(math.log(v) for v in values if v > 0)
    return math.exp(log_sum / len(values))


def load_data(run_dir: str):
    """Load unified.csv and return (data, scripts, present_vms, env_info)."""
    unified_path = os.path.join(run_dir, "unified.csv")
    if not os.path.isfile(unified_path):
        print("Error: unified.csv not found", file=sys.stderr)
        sys.exit(1)

    data: dict[str, dict[str, int]] = defaultdict(dict)
    with open(unified_path) as f:
        for row in csv.DictReader(f):
            vm = row["vm"]
            script = row["script"]
            mean_ns = int(row["mean_ns"])
            data[script][vm] = mean_ns

    scripts = sorted(data.keys())
    found = {vm for s in scripts for vm in data[s]}
    present_vms = [vm for vm in VM_ORDER if vm in found] + sorted(found - set(VM_ORDER))

    env_path = os.path.join(run_dir, "environment.txt")
    env_info = ""
    if os.path.isfile(env_path):
        with open(env_path) as f:
            env_info = f.read().strip()

    return data, scripts, present_vms, env_info


def load_gate(run_dir: str) -> dict | None:
    """The gate verdicts of the run, or None for a run without gate.json (old format)."""
    path = os.path.join(run_dir, "gate.json")
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        gate = json.load(f)
    return gate if isinstance(gate.get("vms"), dict) else None


def gate_split(gate: dict | None, vms: list[str]) -> tuple[list[str], dict[str, str]]:
    """(shown VMs, {hidden VM: reason}). Without gate.json every VM is shown."""
    if gate is None:
        return list(vms), {}
    shown, hidden = [], {}
    for vm in vms:
        v = gate["vms"].get(vm)
        if v is None:
            hidden[vm] = f"no {vm}-check.csv"
        elif v.get("verdict") == "fail":
            hidden[vm] = v.get("reason", "failed")
        else:
            shown.append(vm)
    return shown, hidden


def load_compile(run_dir: str) -> dict[str, dict[str, int]]:
    """{vm: {script: compile_ns}} from every <vm>-compile.csv of the run."""
    out: dict[str, dict[str, int]] = {}
    for path in sorted(glob.glob(os.path.join(run_dir, "*-compile.csv"))):
        with open(path) as f:
            for row in csv.DictReader(f):
                try:
                    ns = int(float(row["compile_ns"]))
                except (KeyError, TypeError, ValueError):
                    continue
                if ns > 0:
                    out.setdefault(row["vm"], {})[row["script"]] = ns
    return out


def load_eval(run_dir: str) -> dict[str, dict[str, int]]:
    """{vm: {script: mean_ns}} from every <vm>-eval.csv of the run (successful rows only)."""
    out: dict[str, dict[str, int]] = {}
    for path in sorted(glob.glob(os.path.join(run_dir, "*-eval.csv"))):
        with open(path) as f:
            for row in csv.DictReader(f):
                try:
                    ns = int(float(row["mean_ns"]))
                except (KeyError, TypeError, ValueError):
                    continue
                if ns > 0:
                    out.setdefault(row["vm"], {})[row["script"]] = ns
    return out


def ratio_to_haskell(data: dict[str, dict[str, int]], vm: str) -> float | None:
    """Geometric mean of vm/haskell over the scripts where both have a timing."""
    logs = [math.log(t[vm] / t["haskell"]) for t in data.values()
            if t.get(vm, 0) > 0 and t.get("haskell", 0) > 0]
    return math.exp(sum(logs) / len(logs)) if logs else None


def load_drift(run_dir: str) -> dict | None:
    """drift.json of the run (parsers/normalize.py), or None."""
    path = os.path.join(run_dir, "drift.json")
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        drift = json.load(f)
    return drift if isinstance(drift.get("percent"), (int, float)) else None


def drift_text(drift: dict | None) -> str:
    if drift is None:
        return ""
    vm = "Haskell" if drift.get("vm") == "haskell" else drift.get("vm", "?")
    return (f"Drift ({vm}, end vs start): {drift['percent']:+.1f} % over {len(drift.get('scripts', {}))} "
            f"scripts. The run timed Haskell again at its end; this is the change of its time.")


def load_history(run_dir: str) -> dict:
    """Ratio to Haskell per VM for every run next to run_dir that has gate.json (new format).

    A run counts only if Haskell passed its gate there; a VM that failed the gate in a run has no
    point for that run. An EXPERIMENTAL VM has a line too; the page draws it dashed and marks it.
    A VM with <vm>-compile.csv in a run has only an eval-only time there: its point is its eval
    time divided by Haskell's eval-only time (haskell-eval.csv), never by Haskell's decode + eval
    time. Without haskell-eval.csv the point is missing. Such VMs are listed in "eval_only".
    """
    parent = os.path.dirname(os.path.abspath(run_dir))
    runs: list[str] = []
    series: dict[str, list[float | None]] = {}
    eval_only: set[str] = set()
    for d in sorted(os.listdir(parent)):
        rd = os.path.join(parent, d)
        gate = load_gate(rd)
        unified = os.path.join(rd, "unified.csv")
        if gate is None or not os.path.isfile(unified):
            continue
        data: dict[str, dict[str, int]] = defaultdict(dict)
        with open(unified) as f:
            for row in csv.DictReader(f):
                data[row["script"]][row["vm"]] = int(row["mean_ns"])
        vms = sorted({vm for t in data.values() for vm in t})
        shown, _ = gate_split(gate, vms)
        if "haskell" not in shown:
            continue
        idx = len(runs)
        runs.append(d)
        # Eval-only VMs of the run: compiling ones, and decode-cached ones (DECODE_CACHED).
        compiling = set(load_compile(rd)) | (set(DECODE_CACHED) & set(shown))
        evals = load_eval(rd) if compiling else {}
        eval_only |= compiling & set(shown)

        def ratio(vm):
            if vm not in compiling:
                return ratio_to_haskell(data, vm)
            # Eval vs eval: the VM's eval time (its D3 rows if it has no -eval.csv) / Haskell's.
            if "haskell" not in evals:
                return None
            own = evals.get(vm) or {s: t[vm] for s, t in data.items() if t.get(vm, 0) > 0}
            return ratio_to_haskell({s: {vm: own.get(s, 0), "haskell": evals["haskell"].get(s, 0)}
                                     for s in own}, vm)

        point = {vm: ratio(vm) for vm in shown}
        for vm in shown:
            if point[vm] is not None:
                series.setdefault(vm, [None] * idx)
        for vm in series:
            series[vm].append(point.get(vm))
    order = {vm: i for i, vm in enumerate(VM_ORDER)}
    return {"runs": runs,
            "series": {vm: series[vm] for vm in sorted(series, key=lambda v: (order.get(v, 99), v))},
            "eval_only": sorted(eval_only & set(series))}


def compute_geo_means(data, scripts, present_vms):
    """Compute geometric means with penalty for missing scripts.

    When a VM hasn't implemented a benchmark script, it gets assigned
    the score of the slowest competitor on that script. This prevents
    VMs from gaming the leaderboard by selectively skipping slow tests.
    """
    geo_means: dict[str, float] = {}

    for vm in present_vms:
        values = []
        for s in scripts:
            t = data[s].get(vm, 0)
            if t > 0:
                values.append(t)
            else:
                # Missing or failed: assign the slowest successful time
                # from any other VM on this script
                worst = max(
                    (data[s].get(other_vm, 0) for other_vm in present_vms if other_vm != vm),
                    default=0,
                )
                if worst > 0:
                    values.append(worst)
                # If no VM has a result for this script, skip it entirely

        geo_means[vm] = geometric_mean(values)

    return geo_means


def experimental_geo_mean(data, scripts, ranked: list[str], vm: str) -> float:
    """Geometric mean of an EXPERIMENTAL VM, with the penalty rule against the ranked VMs only."""
    return compute_geo_means(data, scripts, ranked + [vm])[vm]


def exp_reason_md(vm: str) -> str:
    """The Reason cell of report.md: the short reason in bold, then the long one."""
    tag = EXPERIMENTAL_TAG.get(vm)
    return (f"**{tag}**. " if tag else "") + unranked_reason(vm)


def unranked_reason(vm: str) -> str:
    """Why a shown VM is not ranked: its EXPERIMENTAL reason, else the compiling-VM reason."""
    return EXPERIMENTAL.get(vm, COMPILING_REASON)


def eval_geo(eval_ns, vm: str) -> float:
    """Geometric mean of the VM's eval-only times, or 0."""
    ev = eval_ns.get(vm)
    return geometric_mean(list(ev.values())) if ev else 0


def badge_text(vm: str) -> str:
    """The VM_BADGES text in parentheses, or ''."""
    return f" ({VM_BADGES[vm]['text']})" if vm in VM_BADGES else ""


def generate_markdown(run_dir: str, data, scripts, present_vms, experimental, env_info, gate, hidden,
                      compile_ns, eval_ns, history, drift) -> None:
    """Generate report.md. present_vms are the ranked VMs; experimental the shown, unranked ones."""
    d3_vms = d3_ranked(present_vms)
    geo_means = compute_geo_means(data, scripts, d3_vms)
    all_vms = present_vms + experimental
    eval_only = set(compile_ns) | (set(DECODE_CACHED) & set(all_vms))

    fastest_geo = min(geo_means.values()) if geo_means else 1

    lines = []
    lines.append("# Plutus VM Benchmark Results")
    lines.append("")
    date = os.path.basename(run_dir)
    lines.append(f"**Date:** {date}")
    lines.append("")

    if env_info:
        lines.append("## Environment")
        lines.append("```")
        lines.append(env_info)
        lines.append("```")
        lines.append("")

    lines.append(f"*{DISCLOSURE.format(n=len(scripts))}*")
    lines.append("")
    if drift:
        lines.append(f"*{drift_text(drift)}*")
        lines.append("")

    lines.append("## Summary (geometric mean across all scripts)")
    lines.append("")
    lines.append("*Note: VMs that fail or skip a script are assigned the slowest competitor's time for that script.*")
    if compile_ns:
        lines.append(f"*A compiling VM's timed loop runs the compiled script (\"{COMPILE_BADGE}\": the "
                     "decode and the compile run once per script, before timing). So it has only an "
                     "eval-only time: its Geo Mean (decode + eval) is \"–\" and it is not ranked. "
                     "The Compile column is the geometric mean of the compile time over the scripts.*")
    if eval_ns:
        lines.append("*Geo Mean: flat decode + evaluation (the ranking). Eval only: evaluation of a "
                     "program decoded before the timed loop, geometric mean over its scripts.*")
    for vm in all_vms:
        if vm in DECODE_CACHED:
            lines.append(f"*{DECODE_CACHED[vm]} It is not in the decode + eval ranking; it is ranked "
                         "on eval only (Geo Mean \"–\").*")
        if vm in VM_BADGES:
            lines.append(f"*{VM_LABELS.get(vm, vm)}, \"{VM_BADGES[vm]['text']}\": {VM_BADGES[vm]['title']}*")
    lines.append("")
    lines.append("| VM | Language | Geo Mean | vs Fastest | Eval only | Compile | Check |")
    lines.append("|---|---|---|---|---|---|---|")

    sorted_vms = sorted(d3_vms, key=lambda vm: geo_means.get(vm, float("inf"))) + \
        [vm for vm in present_vms if vm not in d3_vms]
    for vm in sorted_vms:
        label = VM_LABELS.get(vm, vm)
        lang = label.split("(")[-1].rstrip(")") if "(" in label else ""
        geo = geo_means.get(vm, 0)
        ratio = geo / fastest_geo if fastest_geo > 0 else 0
        comp = compile_ns.get(vm)
        comp_cell = f"{fmt_ns(int(geometric_mean(list(comp.values()))))} ({COMPILE_BADGE})" if comp else "-"
        ev = eval_ns.get(vm)
        eval_cell = fmt_ns(int(geometric_mean(list(ev.values())))) if ev else "-"
        geo_cell, ratio_cell = (fmt_ns(int(geo)), f"{ratio:.2f}x") if geo > 0 else ("-", "-")
        if vm in DECODE_CACHED:
            geo_cell, ratio_cell = "–", "eval only"
        lines.append(f"| **{label}**{badge_text(vm)} | {lang} | {geo_cell} | {ratio_cell} | {eval_cell} | "
                     f"{comp_cell} | {check_label(gate, vm)} |")

    if experimental:
        lines.append("")
        lines.append("### Experimental")
        lines.append("")
        lines.append("Run, gated and shown, but not ranked: not in the table above, not a competitor "
                     "in the penalty rule. Geo Mean uses the penalty rule against the ranked VMs. "
                     f"Geo Mean \"–\" ({NO_D3_NOTE}): the VM has only an eval-only time.")
        lines.append("")
        lines.append("| VM | Language | Geo Mean | Eval only | Compile | Check | Reason |")
        lines.append("|---|---|---|---|---|---|---|")
        for vm in experimental:
            label = VM_LABELS.get(vm, vm)
            lang = label.split("(")[-1].rstrip(")") if "(" in label else ""
            comp = compile_ns.get(vm)
            comp_cell = f"{fmt_ns(int(geometric_mean(list(comp.values()))))} ({COMPILE_BADGE})" if comp else "-"
            ev = eval_ns.get(vm)
            eval_cell = fmt_ns(int(geometric_mean(list(ev.values())))) if ev else "-"
            if comp:
                # No decode + eval time: the penalty rule would invent one from the other VMs.
                geo_cell = "–"
            else:
                geo = experimental_geo_mean(data, scripts, d3_vms, vm)
                geo_cell = fmt_ns(int(geo)) if geo > 0 else "-"
            lines.append(f"| **{label}**{badge_text(vm)} | {lang} | {geo_cell} | {eval_cell} | {comp_cell} | "
                         f"{check_label(gate, vm)} | {exp_reason_md(vm)} |")

    if hidden:
        lines.append("")
        lines.append("### Failed check")
        lines.append("")
        lines.append("Not ranked: the result or the ExUnits differ from Haskell (check/README.md).")
        lines.append("")
        lines.append("| VM | Reason |")
        lines.append("|---|---|")
        for vm in sorted(hidden, key=lambda v: (VM_ORDER.index(v) if v in VM_ORDER else 99, v)):
            lines.append(f"| {VM_LABELS.get(vm, vm)} | {hidden[vm]} |")

    notes = [vm for vm in sorted_vms + experimental if vm in VM_NOTES]
    if notes:
        lines.append("")
        lines.append("### Notes")
        lines.append("")
        for vm in notes:
            lines.append(f"- **{VM_LABELS.get(vm, vm)}**: {VM_NOTES[vm]}")

    if history["runs"]:
        lines.append("")
        lines.append("### History (speed relative to Haskell plutus-core, same run; higher is faster)")
        lines.append("")
        lines.append("| VM | " + " | ".join(history["runs"]) + " | Change vs previous run |")
        lines.append("|---|" + "---|" * (len(history["runs"]) + 1))
        for vm, values in history["series"].items():
            cells = [speed_text(v) if v is not None else "-" for v in values]
            cells.append("reference" if vm == "haskell" else history_change_text(values))
            tags = (["experimental"] if vm in EXPERIMENTAL else []) + \
                (["eval only"] if vm in history.get("eval_only", []) else [])
            tag = f" ({', '.join(tags)})" if tags else ""
            lines.append(f"| {VM_LABELS.get(vm, vm)}{tag} | " + " | ".join(cells) + " |")
        lines.append("")
        if history.get("eval_only"):
            lines.append("A VM marked \"eval only\" has no decode + eval time (it compiles each script "
                         "before timing, or its library caches the decode): its ratio is its eval-only "
                         "time divided by Haskell's eval-only time.")
            lines.append("")
        lines.append(f"Servers of the same type differ: ratios to Haskell move up to about "
                     f"{NOISE_BAND * 100:.0f} % between two runs on different servers, so a change under "
                     f"{NOISE_BAND * 100:.0f} % is shown as no change.")

    # Count scripts per VM
    lines.append("")
    lines.append("### Script Coverage")
    lines.append("")
    lines.append("| VM | Passed | Failed | Missing | Total |")
    lines.append("|---|---|---|---|---|")
    for vm in sorted_vms + experimental:
        # A compiling VM's successful times are in eval_ns (see generate).
        success = (len(eval_ns.get(vm, {})) if vm in eval_only
                   else sum(1 for s in scripts if data[s].get(vm, 0) > 0))
        fail = sum(1 for s in scripts if data[s].get(vm, 0) < 0)
        missing = len(scripts) - success - fail
        tag = " (experimental)" if vm in EXPERIMENTAL else ""
        lines.append(f"| {VM_LABELS.get(vm, vm)}{tag} | {success} | {fail} | {missing} | {len(scripts)} |")

    lines.append("")

    lines.append("## Per-Script Results")
    lines.append("")
    # Each VM's D3 column, followed by its eval-only column if it has <vm>-eval.csv; a compiling VM
    # has only the eval-only column. The experimental VMs come last and are never the bold fastest.
    columns = [c for vm in all_vms for c in ([(vm, True)] if vm in eval_only
                                             else [(vm, False), (vm, True)] if vm in eval_ns
                                             else [(vm, False)])]
    header = "| Script |" + "|".join(
        f" {VM_LABELS.get(vm, vm)}{' (experimental)' if vm in EXPERIMENTAL else ''}"
        f"{' (eval only)' if ev else ''} " for vm, ev in columns) + "|"
    separator = "|---|" + "|".join("---" for _ in columns) + "|"
    lines.append(header)
    lines.append(separator)

    for script in scripts:
        row = f"| {script} |"
        script_times = {vm: data[script].get(vm, 0) for vm in all_vms}
        ranked_times = [script_times[vm] for vm in d3_vms if script_times[vm] > 0]
        fastest = min(ranked_times, default=0)

        for vm, ev in columns:
            if ev:
                e = eval_ns[vm].get(script, 0)
                row += f" {fmt_ns(e)} |" if e > 0 else " - |"
                continue
            t = script_times[vm]
            if t > 0:
                cell = fmt_ns(t)
                if vm not in EXPERIMENTAL and t == fastest and len(ranked_times) > 1:
                    cell = f"**{cell}**"
                row += f" {cell} |"
            elif t < 0:
                row += " FAIL |"
            else:
                row += " - |"
        lines.append(row)

    lines.append("")
    links = load_vm_links(run_dir)
    lines.extend(vm_list_markdown(vm_list_order(data, scripts, present_vms, experimental, hidden), links,
                                  gate, hidden, compile_ns))
    lines.append("")
    lines.append("---")
    harness = harness_commit(env_info)
    if harness:
        lines.append(f"Harness commit: [`{harness[:9]}`]({REPO_URL}/commit/{harness})")
        lines.append("")
    lines.append("*Plutus VM Benchmark – maintained by [Lantr](https://lantr.io) – Alexander Nemish. "
                 "Forked from [SAIB-Inc/cardano-plutus-vm-benchmark](https://github.com/SAIB-Inc/cardano-plutus-vm-benchmark) "
                 "by SAIB Inc. and contributors. MIT License, original work © 2025 SAIB Inc., © 2026 Lantr. "
                 "Source: [lantr-io/plutus-vm-benchmark](https://github.com/lantr-io/plutus-vm-benchmark)*")

    report = "\n".join(lines)
    report_path = os.path.join(run_dir, "report.md")
    with open(report_path, "w") as f:
        f.write(report)

    print(report)
    print(f"\nReport saved to: {report_path}", file=sys.stderr)


def check_label(gate: dict | None, vm: str) -> str:
    if gate is None:
        return "not checked"
    verdict = gate["vms"].get(vm, {}).get("verdict")
    return {"pass": "pass", "badge": "outdated cost model"}.get(verdict, "failed check")


REPO_URL = "https://github.com/lantr-io/plutus-vm-benchmark"


def speed_change(prev_ratio, ratio):
    """Change of speed between two time ratios (VM / Haskell): 0.5 -> 0.4 is +0.25 (25 % faster)."""
    return prev_ratio / ratio - 1


def history_change_text(values) -> str:
    """The change of the last point vs the VM's nearest earlier point, for the history table."""
    pts = [v for v in values if v is not None and v > 0]
    if values[-1] is None or len(pts) < 2:
        return "-"
    d = speed_change(pts[-2], pts[-1])
    if abs(d) < NOISE_BAND:
        return f"no change (within ±{NOISE_BAND * 100:.0f} % noise)"
    return f"{d * 100:+.0f} %"


def speed_text(ratio):
    """Time ratio VM / Haskell as speed text: 0.25 -> '4.0x faster', 2.5 -> '2.5x slower'."""
    if ratio <= 0:
        return "-"
    if abs(ratio - 1) < 0.01:
        return "1x (Haskell)"
    s = 1 / ratio
    return f"{s:.1f}x faster" if s > 1 else f"{ratio:.1f}x slower"


def harness_commit(env_info):
    """The harness commit of the run (environment.txt "harness: <sha>"), or None."""
    for line in (env_info or "").split("\n"):
        key, _, value = line.strip().partition(":")
        value = value.strip()
        if key.lower() == "harness" and value and value != "unknown":
            return value
    return None


def generate_html(run_dir: str, env_info: str, data, scripts, present_vms, experimental, gate, hidden,
                  compile_ns, eval_ns, history, drift, write_index: bool) -> None:
    """Generate <run_dir>/index.html from template + the timings of the shown VMs (ranked and
    experimental; the page leaves the experimental ones out of the ranking).

    With write_index, also <repo>/docs/index.html, the published page (run.yml sets it).
    """
    template_path = os.path.join(os.path.dirname(__file__), "template.html")

    if not os.path.isfile(template_path):
        print("Warning: report/template.html not found, skipping HTML generation", file=sys.stderr)
        return

    with open(template_path) as f:
        template = f.read()

    # Only the shown VMs: a hidden VM must not be a competitor in the penalty rule either.
    shown = set(present_vms) | set(experimental)
    links = load_vm_links(run_dir)
    vm_list = vm_list_html(vm_list_order(data, scripts, present_vms, experimental, hidden), links, gate,
                           hidden, compile_ns)
    with open(os.path.join(run_dir, "unified.csv")) as f:
        lines = f.read().strip().split("\n")
    # An eval-only VM's rows (compiling or decode-cached) leave the CSV: the page gets its times as
    # eval-only (REPORT.eval).
    eval_only = set(compile_ns) | set(DECODE_CACHED)
    csv_data = "\n".join([lines[0]] + [l for l in lines[1:]
                                       if l.split(",", 1)[0] in shown and l.split(",", 1)[0] not in eval_only])

    report = {
        # The shown VMs in VM_ORDER: a compiling VM has no row in the CSV.
        "vms": [vm for vm in VM_ORDER if vm in shown] + sorted(shown - set(VM_ORDER)),
        "gate": None if gate is None else {
            vm: {"verdict": v.get("verdict"), "mode": v.get("mode"), "reason": v.get("reason")}
            for vm, v in gate["vms"].items()},
        "hidden": hidden,
        "compile": {vm: s for vm, s in compile_ns.items() if vm in shown},
        "eval": {vm: s for vm, s in eval_ns.items() if vm in shown},
        "history": history,
        "noise_band": NOISE_BAND,
        "disclosure": DISCLOSURE.format(n=len(scripts)),
        "notes": {vm: n for vm, n in VM_NOTES.items() if vm in shown},
        "compile_badge": COMPILE_BADGE,
        "badges": {vm: b for vm, b in VM_BADGES.items() if vm in shown},
        "experimental": {vm: unranked_reason(vm) for vm in experimental},
        "experimental_tag": {vm: EXPERIMENTAL_TAG[vm] for vm in experimental if vm in EXPERIMENTAL_TAG},
        "no_d3_note": NO_D3_NOTE,
        # {vm: the visible line}: ranked on eval only, no decode + eval time (DECODE_CACHED).
        "decode_cached": {vm: t for vm, t in DECODE_CACHED.items() if vm in shown},
        "no_d3_cached_note": NO_D3_CACHED_NOTE,
        "drift": drift_text(drift),
        "drift_percent": drift["percent"] if drift else None,
        "run": os.path.basename(os.path.abspath(run_dir)),
        # {vm: {repo, home, release, version, used_by}}; the page links VM names to #vm-<key>.
        "links": {vm: l for vm, l in links.items() if vm in shown or vm in hidden},
    }
    # Safe inside <script>: no "</" can close the element.
    report_json = json.dumps(report, ensure_ascii=False).replace("</", "<\\/")

    # Build environment badge
    if env_info:
        env_badge = ""
        # environment.txt of run-images.sh has lowercase keys (cpu:, cores:, memory:).
        for line in env_info.split("\n"):
            key, _, value = line.strip().partition(":")
            key, value = key.lower(), value.strip()
            if key == "cpu":
                env_badge += f"<code>{value}</code>"
            elif key == "cores":
                env_badge += f" &middot; {value} cores"
            elif key in ("ram", "memory"):
                env_badge += f" &middot; {value}"
            elif key == "os":
                env_badge += f" &middot; {value}"
            elif key == "lanes":
                # "lanes: 3 (lane0 2,3,10,11; ...)": more than one lane ran VMs at the same time.
                n = value.split(" ", 1)[0]
                if n.isdigit() and int(n) > 1:
                    env_badge += f" &middot; {n} parallel lanes"
        date = os.path.basename(run_dir)
        env_badge += f" &middot; {date}"
    else:
        env_badge = os.path.basename(run_dir)

    harness = harness_commit(env_info)
    if harness:
        harness_link = f'<a href="{REPO_URL}/commit/{harness}"><code>{harness[:9]}</code></a>'
        env_badge += f' &middot; harness {harness_link}'
    else:
        harness_link = "unknown"

    page = (template.replace("{{CSV_DATA}}", csv_data).replace("{{ENV_BADGE}}", env_badge)
            .replace("{{HARNESS_LINK}}", harness_link)
            .replace("{{VM_LIST}}", vm_list)
            .replace("{{REPORT_JSON}}", report_json))
    seo = seo_parts(run_dir, data, scripts, present_vms, experimental, gate, eval_ns, compile_ns)
    page = page.replace("{{SEO_HEAD}}", seo["head"])
    for key in ("{{SEO_INTRO}}", "{{SEO_SUMMARY_SUB}}", "{{SEO_SUMMARY}}", "{{SEO_FAQ}}"):
        page = page.replace(key, seo[key])

    docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
    if write_index:
        html_path = os.path.join(docs_dir, "index.html")
        with open(html_path, "w") as f:
            f.write(page)
        print(f"HTML report saved to: {html_path}", file=sys.stderr)
        write_site_files(seo["rows"], seo["date"], len(scripts))

    # The run dir's copy has no docs/ next to it: embed the logo.
    with open(os.path.join(docs_dir, LOGO), "rb") as f:
        logo = "data:image/png;base64," + base64.b64encode(f.read()).decode()
    html_path = os.path.join(run_dir, "index.html")
    with open(html_path, "w") as f:
        f.write(page.replace(f'src="{LOGO}"', f'src="{logo}"').replace(seo["head"], seo["head_run"]))
    print(f"HTML report saved to: {html_path}", file=sys.stderr)


# --- Search engines and link previews --------------------------------------------------------
# Most numbers on the page are drawn by JavaScript. The helpers below add what a crawler reads
# without JavaScript: the <head> tags (description, canonical, Open Graph, JSON-LD), a static
# intro, a summary table and a FAQ. With --write-index, write_site_files also writes
# docs/robots.txt, docs/sitemap.xml and docs/og.png (the link-preview image).

SITE_URL = "https://plutus-vm-bench.lantr.io/"
RAW_URL = "https://raw.githubusercontent.com/lantr-io/plutus-vm-benchmark/main"
PAGE_TITLE = "Plutus VM Benchmark: Cardano smart contract evaluator speed"
# Committed static files in docs/. og.png is rewritten by write_site_files when Chrome is found.
FAVICON = "favicon.svg"
OG_IMAGE = "og.png"
OG_SIZE = (1200, 630)
KEYWORDS = [
    "Cardano", "Plutus", "UPLC", "Untyped Plutus Core", "Plutus VM", "smart contract",
    "CEK machine", "evaluator", "benchmark", "performance", "plutus-core", "Aiken", "Scalus",
    "blaze-plutus", "Plutigo", "amaru-uplc", "Chrysalis", "Julc", "Plutuz",
]


def run_date(run_dir: str) -> str:
    """YYYY-MM-DD of the run: the dir name (2026-03-16-0 -> 2026-03-16), else unified.csv's mtime."""
    name = os.path.basename(os.path.abspath(run_dir))[:10]
    try:
        return datetime.date.fromisoformat(name).isoformat()
    except ValueError:
        path = os.path.join(run_dir, "unified.csv")
        ts = os.path.getmtime(path) if os.path.isfile(path) else None
        return (datetime.date.fromtimestamp(ts) if ts else datetime.date.today()).isoformat()


def fmt_ns_html(ns: float) -> str:
    """fmt_ns with the page's micro sign."""
    return fmt_ns(int(ns)).replace(" us", " µs") if ns > 0 else "-"


def split_label(vm: str) -> tuple[str, str]:
    """VM_LABELS 'Scalus CEK (Scala / JVM)' -> ('Scalus CEK', 'Scala / JVM')."""
    label = VM_LABELS.get(vm, vm)
    if label.endswith(")") and " (" in label:
        name, _, lang = label[:-1].rpartition(" (")
        return name, lang
    return label, ""


def summary_rows(data, scripts, present_vms, experimental, gate, eval_ns, compile_ns) -> list[dict]:
    """One row per shown VM: the ranked ones fastest first (geo mean with the penalty rule, as in
    report.md and the page's overall ranking), then the experimental ones. A compiling VM has no
    decode + eval time: geo 0, "compiled" True. A decode-cached VM (DECODE_CACHED) comes after the
    ranked ones: ranked on eval only, no decode + eval time ("compiled" True, rank None)."""
    d3_vms = d3_ranked(present_vms)
    geo = compute_geo_means(data, scripts, d3_vms)
    ranked = sorted((vm for vm in d3_vms if geo.get(vm, 0) > 0), key=lambda vm: geo[vm])
    cached = [vm for vm in present_vms if vm not in d3_vms]
    fastest = geo[ranked[0]] if ranked else 0
    rows = []
    for vm in ranked + cached + experimental:
        exp = vm in experimental
        comp = vm in compile_ns or vm in cached
        g = 0 if comp else experimental_geo_mean(data, scripts, d3_vms, vm) if exp else geo[vm]
        name, lang = split_label(vm)
        rows.append({
            "vm": vm, "name": name, "lang": lang, "experimental": exp, "compiled": comp,
            "eval_only_ranked": vm in cached,
            "rank": None if exp or vm in cached else len(rows) + 1,
            "geo": g, "eval": eval_geo(eval_ns, vm),
            "ratio": g / fastest if (fastest > 0 and g > 0 and not exp) else None,
            "check": check_label(gate, vm),
        })
    return rows


def summary_html(rows: list[dict], n_scripts: int) -> str:
    """The static summary table (visible text, no JavaScript needed)."""
    out = ['    <div class="table-wrap"><table class="summary-table">',
           '      <thead><tr><th>#</th><th class="l">VM</th><th class="l">Language / runtime</th>'
           '<th>Decode + eval</th><th>Eval only</th><th>vs fastest</th><th class="l">Check</th></tr></thead>',
           '      <tbody>']
    for r in rows:
        check_cls = {"pass": "pass", "outdated cost model": "outdated"}.get(r["check"], "")
        rank = "–" if r["rank"] is None else str(r["rank"])
        ratio = ("not ranked" if r["experimental"] else "eval only" if r["eval_only_ranked"]
                 else f"{r['ratio']:.2f}×" if r["ratio"] else "-")
        name = escape(r["name"]) + (f" ({experimental_badge(r['vm'])})" if r["experimental"] else "")
        tr = '<tr class="exp">' if r["experimental"] else "<tr>"
        # A compiling VM: no decode + eval time ("–" with the reason as a tooltip).
        d3 = (f'<td title="{escape(no_d3_note(r["vm"]))}">–</td>' if r["compiled"]
              else f'<td>{fmt_ns_html(r["geo"])}</td>')
        out.append(f'        {tr}<td>{rank}</td>'
                   f'<td class="l vm">{name}</td><td class="l lang">{escape(r["lang"])}</td>'
                   f'{d3}<td>{fmt_ns_html(r["eval"])}</td><td>{ratio}</td>'
                   f'<td class="l {check_cls}">{escape(r["check"])}</td></tr>')
    out += ['      </tbody>', '    </table></div>',
            f'    <p class="summary-caption">Geometric mean of the time per script over the {n_scripts} '
            'scripts. <em>Decode + eval</em> is the ranking metric. A VM that fails or skips a script '
            'gets the slowest competitor\'s time for it. <em>Eval only</em> times a program that was '
            'decoded before the timed loop. A dash means that the run has no such time for the VM. '
            'A VM that compiles a script before it runs it decodes and compiles each script once, '
            'before timing. So it has only an eval-only time, and no decode + eval time. '
            'The VMs use different execution models, so compare VMs of the same model too '
            '(<a href="#exec-model">Execution Model</a>). Experimental VMs are shown, but not ranked.'
            + "".join(" " + escape(DECODE_CACHED[r["vm"]]) for r in rows if r["eval_only_ranked"])
            + '</p>']
    return "\n".join(out)


def languages(rows: list[dict]) -> str:
    """'Haskell, Scala, Rust and Go': the first word of each row's language, in row order."""
    langs: list[str] = []
    for r in rows:
        first = r["lang"].replace("→", "/").split("/")[0].strip()
        if first and first not in langs:
            langs.append(first)
    return ", ".join(langs[:-1]) + " and " + langs[-1] if len(langs) > 1 else "".join(langs)


def intro_html(rows: list[dict], n_scripts: int, date: str) -> str:
    n = len(rows)
    langs = languages(rows)
    return ("This benchmark compares the speed of <strong>Plutus virtual machines</strong> (UPLC "
            "evaluators), the programs that run Cardano smart contracts. Each VM decodes and evaluates "
            f"the same {n_scripts} Plutus scripts. A correctness gate checks every result and its "
            "execution units (ExUnits) against plutus-core, the Haskell CEK machine of the Cardano node. "
            f"This run of {date} has {n} evaluators" + (f", written in {escape(langs)}" if langs else "")
            + ". The <a href=\"#method\">method</a> and the "
            "<a href=\"https://github.com/lantr-io/plutus-vm-benchmark\">source</a> are open.")


def faq_items(rows: list[dict], n_scripts: int, date: str) -> list[tuple[str, str]]:
    """(question, answer HTML). The page and the FAQPage JSON-LD both use this list."""
    ranked = [r for r in rows if not r["experimental"] and r["geo"] > 0]
    if ranked:
        top = ranked[0]
        hs = next((r for r in ranked if r["vm"] == "haskell"), None)
        fastest = (f"In the run of {date}, {escape(top['name'])} ({escape(top['lang'])}) has the lowest "
                   f"decode + eval geometric mean of the ranked VMs: {fmt_ns_html(top['geo'])}.")
        if hs and hs is not top:
            fastest += (f" plutus-core, the Haskell CEK machine of the Cardano node, takes "
                        f"{fmt_ns_html(hs['geo'])} ({hs['ratio']:.2f}× the fastest time).")
        fastest += (" The VMs use different execution models (CEK interpreter, AST walker, JIT "
                    "compiler), so compare VMs of the same model too. Experimental VMs are not ranked.")
    else:
        fastest = f"The run of {date} has no ranked VM with a decode + eval time."
    return [
        ("What is a Plutus VM?",
         "A Plutus VM, or UPLC evaluator, runs Untyped Plutus Core (UPLC), the language of Cardano "
         "smart contracts. The Cardano node uses the CEK machine of plutus-core (Haskell) to validate "
         "scripts. Wallets, SDKs, emulators and other tools use their own evaluators to compute the "
         "script result and its execution units (ExUnits) before they submit a transaction."),
        ("What does this benchmark measure?",
         f"Each VM flat-decodes and evaluates {n_scripts} Plutus scripts from the plutus-use-cases test "
         "suite (auction, escrow, uniswap, stablecoin and others). The page shows the mean time per "
         "script and the geometric mean over all scripts. Each VM runs in its own Docker image on the "
         "same server type, one VM at a time. A VM is ranked only if its results and ExUnits equal "
         "Haskell plutus-core on every script."),
        ("Which Plutus VM is the fastest?", fastest),
        ("Why does the ranking include the decode time?",
         "A node decodes a script from its flat encoding before it evaluates it. For a script that the "
         "node has not seen, both steps take time. For some VMs the decode is a large share of the "
         "time (about 66 % for Haskell plutus-core), so the page also shows an eval-only time."),
        ("How often is the benchmark updated?",
         "A GitHub Actions workflow runs the full benchmark on the 1st of each month, and the "
         "maintainers start extra runs when a VM release changes. The workflow skips a scheduled run "
         f"when nothing changed. This page shows the run of {date}."),
        ("How can a VM join the benchmark?",
         "A ranked VM has a published release, a downstream user today, and passes the correctness "
         "gate. Open a pull request that adds a Docker image for the VM. Follow "
         "<a href=\"https://github.com/lantr-io/plutus-vm-benchmark/blob/HEAD/CONTRIBUTING.md\">"
         "CONTRIBUTING.md</a> and the <a href=\"https://github.com/lantr-io/plutus-vm-benchmark/blob/HEAD/"
         "docs/IMAGE_CONTRACT.md\">image contract</a>."),
    ]


def faq_html(items: list[tuple[str, str]]) -> str:
    return "\n".join(['    <div class="faq">']
                     + [f'      <div class="faq-item"><h3>{escape(q)}</h3><p>{a}</p></div>' for q, a in items]
                     + ['    </div>'])


def meta_description(rows: list[dict], n_scripts: int, date: str) -> str:
    return (f"Cardano Plutus VM benchmark: {len(rows)} UPLC smart contract evaluators, decode + eval "
            f"speed on {n_scripts} scripts, checked against the Haskell CEK machine. Run {date}.")


def json_ld(rows, items, run_dir: str, date: str, description: str, n_scripts: int) -> str:
    """schema.org graph: Organization, Person, WebSite, WebPage, Dataset, FAQPage."""
    run = os.path.basename(os.path.abspath(run_dir))
    org = {"@type": "Organization", "@id": "https://lantr.io/#organization", "name": "Lantr",
           "url": "https://lantr.io"}
    person = {"@type": "Person", "@id": SITE_URL + "#alexander-nemish", "name": "Alexander Nemish",
              "affiliation": {"@id": org["@id"]}}
    files = [("unified.csv", "text/csv", "Mean time per VM and script (decode + eval), in nanoseconds"),
             ("gate.json", "application/json", "Correctness gate verdict per VM"),
             ("report.md", "text/markdown", "The report of the run as Markdown tables")]
    distribution = [{"@type": "DataDownload", "name": f, "description": d, "encodingFormat": t,
                     "contentUrl": f"{RAW_URL}/results/{run}/{f}"}
                    for f, t, d in files if os.path.isfile(os.path.join(run_dir, f))]
    graph = [
        org, person,
        {"@type": "WebSite", "@id": SITE_URL + "#website", "url": SITE_URL, "name": "Plutus VM Benchmark",
         "inLanguage": "en", "publisher": {"@id": org["@id"]}},
        {"@type": "WebPage", "@id": SITE_URL + "#webpage", "url": SITE_URL, "name": PAGE_TITLE,
         "description": description, "inLanguage": "en", "dateModified": date,
         "isPartOf": {"@id": SITE_URL + "#website"}, "about": {"@id": SITE_URL + "#dataset"},
         "primaryImageOfPage": {"@type": "ImageObject", "url": SITE_URL + OG_IMAGE,
                                "width": OG_SIZE[0], "height": OG_SIZE[1]}},
        {"@type": "Dataset", "@id": SITE_URL + "#dataset", "url": SITE_URL,
         "name": "Plutus VM Benchmark: Cardano UPLC evaluator timings",
         "description": (f"Timings of {len(rows)} Plutus (UPLC) virtual machines, the evaluators of "
                         f"Cardano smart contracts, on the same {n_scripts} Plutus scripts: mean "
                         "flat decode + evaluation time and eval-only time per script, with a correctness "
                         "gate against the Haskell plutus-core CEK machine. Run of " + date + "."),
         "keywords": KEYWORDS, "inLanguage": "en", "isAccessibleForFree": True,
         "creator": [{"@id": org["@id"]}, {"@id": person["@id"]}], "publisher": {"@id": org["@id"]},
         "license": "https://opensource.org/licenses/MIT", "dateModified": date,
         "isBasedOn": "https://github.com/SAIB-Inc/cardano-plutus-vm-benchmark",
         "sameAs": "https://github.com/lantr-io/plutus-vm-benchmark",
         "measurementTechnique": "Each VM runs in its own Docker image with its native benchmark "
                                 "framework, one VM at a time, on the same server type",
         "variableMeasured": ["decode + eval time per script (ns)", "eval-only time per script (ns)",
                              "correctness gate verdict"],
         "distribution": distribution},
        {"@type": "FAQPage", "@id": SITE_URL + "#faq", "url": SITE_URL + "#faq",
         "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                        for q, a in items]},
    ]
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False).replace("</", "<\\/")


def seo_head(description: str, date: str, ld: str, published: bool, favicon: str) -> str:
    """The <head> tags after <title>. published: the page at SITE_URL (docs/index.html); else the
    copy in results/<run>/, which is not served on the site: noindex, no canonical."""
    og_image = f"{SITE_URL}{OG_IMAGE}?v={date}"
    alt = "Plutus VM Benchmark: decode + eval geometric mean of the fastest ranked Plutus VMs"
    d = escape(description)
    lines = [
        f'<meta name="description" content="{d}">',
        '<meta name="robots" content="index, follow">' if published else '<meta name="robots" content="noindex">',
    ]
    if published:
        lines.append(f'<link rel="canonical" href="{SITE_URL}">')
    lines += [
        '<meta name="author" content="Lantr, Alexander Nemish">',
        '<meta name="theme-color" content="#09090f">',
        f'<link rel="icon" type="image/svg+xml" href="{favicon}">',
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="Plutus VM Benchmark">',
        '<meta property="og:locale" content="en_US">',
        f'<meta property="og:title" content="{escape(PAGE_TITLE)}">',
        f'<meta property="og:description" content="{d}">',
        f'<meta property="og:url" content="{SITE_URL}">',
        f'<meta property="og:image" content="{og_image}">',
        f'<meta property="og:image:width" content="{OG_SIZE[0]}">',
        f'<meta property="og:image:height" content="{OG_SIZE[1]}">',
        f'<meta property="og:image:alt" content="{alt}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{escape(PAGE_TITLE)}">',
        f'<meta name="twitter:description" content="{d}">',
        f'<meta name="twitter:image" content="{og_image}">',
        f'<meta name="twitter:image:alt" content="{alt}">',
        f'<script type="application/ld+json">\n{ld}\n</script>',
    ]
    return "\n".join(lines)


def seo_parts(run_dir, data, scripts, present_vms, experimental, gate, eval_ns, compile_ns) -> dict:
    """The template placeholders, and the rows for write_site_files."""
    date = run_date(run_dir)
    rows = summary_rows(data, scripts, present_vms, experimental, gate, eval_ns, compile_ns)
    items = faq_items(rows, len(scripts), date)
    description = meta_description(rows, len(scripts), date)
    ld = json_ld(rows, items, run_dir, date, description, len(scripts))
    with open(os.path.join(DOCS_DIR, FAVICON), "rb") as f:
        favicon_uri = "data:image/svg+xml;base64," + base64.b64encode(f.read()).decode()
    return {
        "date": date, "rows": rows,
        "head": seo_head(description, date, ld, True, FAVICON),
        "head_run": seo_head(description, date, ld, False, favicon_uri),
        "{{SEO_INTRO}}": intro_html(rows, len(scripts), date),
        "{{SEO_SUMMARY_SUB}}": f"all VMs, geometric mean over {len(scripts)} scripts",
        "{{SEO_SUMMARY}}": summary_html(rows, len(scripts)),
        "{{SEO_FAQ}}": faq_html(items),
    }


def og_card_html(rows: list[dict], date: str, n_scripts: int) -> str:
    """The 1200x630 link-preview card: title and the five fastest ranked VMs. Without rows (the
    committed bootstrap image) a plain title card. System fonts only: no network."""
    ranked = [r for r in rows if not r["experimental"] and r["geo"] > 0][:5]
    bars = ""
    if ranked:
        fastest = ranked[0]["geo"]
        # Time relative to the fastest on a log axis, as the page's ranking draws it: longer is
        # slower, and the fastest VM keeps a short bar.
        lo = -0.3
        hi = math.log10(max(1.5, max(r["geo"] / fastest for r in ranked))) + 0.04
        for r in ranked:
            w = 100 * (math.log10(r["geo"] / fastest) - lo) / (hi - lo)
            bars += (f'<div class="row"><div class="n">{escape(r["name"])}<span>{escape(r["lang"])}</span></div>'
                     f'<div class="t"><div class="b" style="width:{w:.1f}%"></div></div>'
                     f'<div class="v">{fmt_ns_html(r["geo"])}</div></div>')
        sub = f"Decode + eval geometric mean, {n_scripts} scripts, run {date}. Shorter bar = faster."
    else:
        sub = "Cardano smart contract evaluators: decode + eval time, checked against plutus-core."
    logo = "file://" + os.path.join(DOCS_DIR, LOGO)
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ width:{OG_SIZE[0]}px; height:{OG_SIZE[1]}px; overflow:hidden; }}
body {{ background:#09090f; color:#e4e4ec; padding:56px 64px; display:flex; flex-direction:column;
  font-family:-apple-system,'Segoe UI','DejaVu Sans','Liberation Sans',Helvetica,Arial,sans-serif; }}
h1 {{ font-size:64px; font-weight:700; letter-spacing:-1px; }} h1 span {{ color:#8b78ef; }}
.sub {{ font-size:26px; color:#9494b0; margin:10px 0 36px; }}
.row {{ display:flex; align-items:center; gap:24px; height:62px; }}
.n {{ width:330px; font-size:28px; font-weight:600; white-space:nowrap; overflow:hidden; }}
.n span {{ display:block; font-size:18px; font-weight:400; color:#8484a2; }}
.t {{ flex:1; height:26px; }} .b {{ height:100%; background:#646FFF; border-radius:4px; }}
.v {{ width:150px; text-align:right; font-size:28px; font-variant-numeric:tabular-nums; }}
.big {{ font-size:34px; color:#AFAFE8; line-height:1.5; margin-top:20px; }}
.foot {{ margin-top:auto; display:flex; justify-content:space-between; align-items:center;
  font-size:24px; color:#8484a2; }} .foot img {{ height:44px; }}
</style></head><body>
<h1><span>Plutus</span> VM Benchmark</h1><div class="sub">{escape(sub)}</div>
{bars or '<div class="big">Haskell, Rust, Go, Scala and TypeScript UPLC evaluators,<br>timed on the same Plutus scripts.</div>'}
<div class="foot"><div>plutus-vm-bench.lantr.io</div><img src="{logo}" alt=""></div>
</body></html>"""


def find_chrome() -> str | None:
    for c in [os.environ.get("CHROME"), "google-chrome", "google-chrome-stable", "chromium",
              "chromium-browser", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]:
        path = c and (shutil.which(c) or (c if os.path.isfile(c) else None))
        if path:
            return path
    return None


def png_size(path: str) -> tuple[int, int] | None:
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def write_og_image(rows: list[dict], date: str, n_scripts: int) -> None:
    """docs/og.png from og_card_html with headless Chrome. Without Chrome (python:3.12-slim) or on
    any failure, keep the committed docs/og.png."""
    chrome = find_chrome()
    if not chrome:
        print("og.png: no Chrome found, docs/og.png not changed", file=sys.stderr)
        return
    with tempfile.TemporaryDirectory() as tmp:
        card, shot = os.path.join(tmp, "og.html"), os.path.join(tmp, "og.png")
        with open(card, "w") as f:
            f.write(og_card_html(rows, date, n_scripts))
        cmd = [chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
               "--force-device-scale-factor=1", f"--window-size={OG_SIZE[0]},{OG_SIZE[1]}",
               f"--screenshot={shot}", "file://" + card]
        try:
            subprocess.run(cmd, check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"og.png: Chrome failed ({e}), docs/og.png not changed", file=sys.stderr)
            return
        if not os.path.isfile(shot) or png_size(shot) != OG_SIZE:
            print(f"og.png: unexpected screenshot {png_size(shot) if os.path.isfile(shot) else None}, "
                  "docs/og.png not changed", file=sys.stderr)
            return
        shutil.copyfile(shot, os.path.join(DOCS_DIR, OG_IMAGE))
    print(f"og.png saved to: {os.path.join(DOCS_DIR, OG_IMAGE)}", file=sys.stderr)


def write_site_files(rows: list[dict], date: str, n_scripts: int) -> None:
    """docs/robots.txt, docs/sitemap.xml and docs/og.png for the published site. The sitemap lists
    the main page only: the per-run copies in results/ are not deployed (run.yml uploads docs/)."""
    with open(os.path.join(DOCS_DIR, "robots.txt"), "w") as f:
        f.write(f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}sitemap.xml\n")
    with open(os.path.join(DOCS_DIR, "sitemap.xml"), "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                f"  <url>\n    <loc>{SITE_URL}</loc>\n    <lastmod>{date}</lastmod>\n  </url>\n"
                "</urlset>\n")
    write_og_image(rows, date, n_scripts)


def generate(run_dir: str, write_index: bool = False) -> None:
    data, scripts, all_vms, env_info = load_data(run_dir)
    # A run without the d3 loop (BENCH_LOOPS) has an empty unified.csv: take the VMs and scripts
    # of the eval-only files too, so their column is shown.
    eval_all = load_eval(run_dir)
    found = set(all_vms) | set(eval_all)
    all_vms = [vm for vm in VM_ORDER if vm in found] + sorted(found - set(VM_ORDER))
    scripts = sorted(set(scripts) | {s for v in eval_all.values() for s in v})
    gate = load_gate(run_dir)
    shown_vms, hidden = gate_split(gate, all_vms)
    for s in scripts:
        for vm in hidden:
            data[s].pop(vm, None)
    compile_ns = {vm: v for vm, v in load_compile(run_dir).items() if vm in shown_vms}
    eval_ns = {vm: v for vm, v in eval_all.items() if vm in shown_vms}
    # A compiling VM decodes and compiles each script before timing: its timed loop is eval only.
    # A decode-cached VM (DECODE_CACHED) times hash + eval in its D3 loop. Either way the time is an
    # eval-only time (its D3 rows if it has no -eval.csv), never a decode + eval time, so its
    # successful D3 times leave data (a failure stays, for the script coverage).
    for vm in list(compile_ns) + [vm for vm in DECODE_CACHED if vm in shown_vms and vm not in compile_ns]:
        d3 = {s: data[s][vm] for s in scripts if data[s].get(vm, 0) > 0}
        if vm not in eval_ns and d3:
            eval_ns[vm] = d3
        for s in d3:
            del data[s][vm]
    # The gate first: an experimental VM that fails it is listed as "failed check". A compiling
    # VM has no decode + eval time to rank: it is shown with the experimental VMs.
    present_vms = [vm for vm in shown_vms if vm not in EXPERIMENTAL and vm not in compile_ns]
    experimental = [vm for vm in shown_vms if vm in EXPERIMENTAL or vm in compile_ns]
    history = load_history(run_dir)
    drift = load_drift(run_dir)
    generate_markdown(run_dir, data, scripts, present_vms, experimental, env_info, gate, hidden,
                      compile_ns, eval_ns, history, drift)
    generate_html(run_dir, env_info, data, scripts, present_vms, experimental, gate, hidden,
                  compile_ns, eval_ns, history, drift, write_index)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--write-index"]
    if len(args) != 1:
        print(f"Usage: {sys.argv[0]} [--write-index] <run-dir>", file=sys.stderr)
        sys.exit(1)
    generate(args[0], "--write-index" in sys.argv[1:])
