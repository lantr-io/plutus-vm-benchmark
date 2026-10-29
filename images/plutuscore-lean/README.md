# PlutusCoreBlaster (Lean native)

The image builds the upstream `bench_cek` executable with Lean 4.24.0. The source commit, Lean
release and Lean-blaster dependency commit are all pinned in `.env`. No Z3 process, Lean
elaboration or `#prep_uplc` runs in the benchmark operation.

Evaluation uses the library's compiled-in variant E semantics and cost model (PlutusV3,
protocol version 11). The library's model matches the mainnet Haskell reference on all 89
scripts. The image remains in strict gate mode; it must continue to match on each rebuild.
There is no runtime cost-model loader. A mainnet model update may require an upstream release.

`scripts/run-plutuscore-lean.sh` reads only `$BENCH_DATA_DIR`, supports all three loops and
`BENCH_TIMING=quick`, and runs one process per script. The native executable emits CSV rows
directly, so there is no framework-specific parser.

- D3: Flat decode directly from the raw bytes, then costed CEK evaluation on every iteration.
  No decode cache or expansion of the entire input into a list of bits.
- Eval: decode once before timing, then costed CEK evaluation on every iteration.
- Check: one evaluation, reporting CEK status and total CPU/memory ExUnits, startup included.
  No arguments are applied, and the ledger unit-result rule is not imposed.

Each timed loop warms up for five iterations and measures at least 50 iterations and at least
5 seconds (quick: 1 second). Individual iterations are timed with Lean's monotonic nanosecond
clock. Mean, median, min, max and sample standard deviation include every sample. Status and
both costs are consumed and compared with the initial evaluation outside each timer. File I/O
and process startup are outside timing. Every evaluation has fresh state and cost accounting.

The executable uses a 100,000,000-step safety limit. An exhausted limit, decode failure or crash
is a failed script, not a successful timing or a synthetic CEK error with reference costs.

This integration is proposed as an unranked experimental entry. PlutusCoreBlaster has no
stable release tag yet, and a released downstream user satisfying the inclusion policy has
not been established. Before ranking, pin a stable release containing the runner and provide
the downstream dependency evidence. Admission to the experimental line-up needs maintainer
review; this proposal does not relax the ranking rules.

The development pin includes a direct byte-array Flat reader, a fused native CEK loop with
eager costing and combined continuation frames, diagnostic profiling, and native FFIs for
all six hashes and Ed25519. The CEK compiler replacements have kernel-checked equivalence
proofs; the new Flat reader is checked against the independent list decoder by complete AST
and rejection comparisons. The image runs 4,409 generated and malformed parser cases during
the build, without evaluating fuzzed programs.

SHA-256, Blake2b and Ed25519 use libsodium; SHA3, Keccak
and RIPEMD use vendored crypton C. The image builds and runs the 343-case native/reference
crypto conformity suite. libsodium is installed at runtime and the crypton license is included
at `/usr/share/doc/plutuscore-lean/crypton-LICENSE`. Secp256k1 and BLS still use Lean.
