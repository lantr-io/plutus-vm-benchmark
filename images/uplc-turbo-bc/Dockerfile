# check=skip=InvalidDefaultArgInFrom
# uplc-turbo-bc: the bytecode VM of uplc-turbo (Rust / Criterion). docs/IMAGE_CONTRACT.md.
# The bytecode VM lives only in a fork: jonathanlim222/uplc (closed PR pragma-org/uplc#47).

ARG RUST_VERSION

# =============================================================================
# Build stage
# =============================================================================
FROM rust:${RUST_VERSION}-bookworm AS build

ARG UPLC_TURBO_BC_REPO
ARG UPLC_TURBO_BC_SHA
# Keep peak memory low when other images build at the same time.
ARG CARGO_BUILD_JOBS=2
ENV CARGO_BUILD_JOBS=${CARGO_BUILD_JOBS}

RUN git clone "$UPLC_TURBO_BC_REPO" /src \
    && cd /src && git checkout "$UPLC_TURBO_BC_SHA"

WORKDIR /src

# Our harness replaces the upstream use_cases bench (PV 11, continues after a failing script,
# PVB_CHECK_OUT check mode). See the header of images/uplc-turbo-bc/use_cases.rs.
COPY images/uplc-turbo-bc/use_cases.rs /src/crates/uplc/benches/use_cases/main.rs

# Borrow &CostModel across iterations instead of cloning the full CostModel on every evaluation.
RUN sed -i \
        -e "s/pub struct Machine<'a, B: BuiltinCostModel, V: Eval<'a>>/pub struct Machine<'a, 'c, B: BuiltinCostModel, V: Eval<'a>>/" \
        -e "s/pub(crate) costs: CostModel<B>,/pub(crate) costs: \&'c CostModel<B>,/" \
        -e "s/impl<'a, B: BuiltinCostModel, V: Eval<'a>> Machine<'a, B, V>/impl<'a, 'c, B: BuiltinCostModel, V: Eval<'a>> Machine<'a, 'c, B, V>/" \
        -e "s/costs: CostModel<B>,/costs: \&'c CostModel<B>,/" \
        crates/uplc/src/machine/cek.rs \
    && sed -i \
        -e "s/impl<'a, B: BuiltinCostModel, V: Eval<'a>> Machine<'a, B, V>/impl<'a, 'c, B: BuiltinCostModel, V: Eval<'a>> Machine<'a, 'c, B, V>/" \
        crates/uplc/src/machine/runtime.rs \
    && sed -i \
        -e "s/cost_model: CostModel<B>,/cost_model: \&CostModel<B>,/" \
        -e "s/CostModel::<BuiltinCosts/\&CostModel::<BuiltinCosts/" \
        crates/uplc/src/program.rs \
    && sed -i \
        -e "s/costs: CostModel<B>,/costs: \&CostModel<B>,/" \
        -e "s/struct Vm<'a, 'b, B: BuiltinCostModel>/struct Vm<'a, 'b, 'c, B: BuiltinCostModel>/" \
        -e "s/machine: &'b mut Machine<'a, B, DeBruijn>,/machine: \&'b mut Machine<'a, 'c, B, DeBruijn>,/" \
        -e "s/impl<'a, 'b, B: BuiltinCostModel> Vm<'a, 'b, B>/impl<'a, 'b, 'c, B: BuiltinCostModel> Vm<'a, 'b, 'c, B>/" \
        crates/uplc/src/bytecode/vm.rs

# The release profile of Amaru, the node that ships this crate (spec D16): fat LTO and one codegen
# unit (pragma-org/amaru Cargo.toml:194-196 at a393a0b; its release binaries are built with
# `cargo build --release`, .github/workflows/release-begin.yml:202). The workspace of the pinned
# repo has no [profile] section, so the environment sets it. `cargo build --release` builds the
# bench with the release profile; the BENCH pair covers `cargo bench`.
ENV CARGO_PROFILE_RELEASE_LTO=true \
    CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 \
    CARGO_PROFILE_BENCH_LTO=true \
    CARGO_PROFILE_BENCH_CODEGEN_UNITS=1

# The check: rustc built the crate and linked the bench binary with fat LTO and one codegen unit.
RUN { cargo build -v --release --bench use_cases --manifest-path crates/uplc/Cargo.toml \
        > /tmp/build.log 2>&1 || { tail -50 /tmp/build.log; exit 1; }; } \
    && grep -E -- '--crate-name use_cases ' /tmp/build.log > /tmp/bench.log \
    && grep -q -E -- '-C lto( |=fat )' /tmp/bench.log && grep -q -- '-C codegen-units=1' /tmp/bench.log \
    && grep -E -- '--crate-name amaru_uplc ' /tmp/build.log | grep -q -- '-C codegen-units=1'

# =============================================================================
# Runtime stage
# =============================================================================
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 procps \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /src/target /bench/uplc-turbo-bc/target
COPY --from=build /src/crates/uplc/benches /bench/uplc-turbo-bc/crates/uplc/benches
COPY --from=build /src/crates/uplc/Cargo.toml /bench/uplc-turbo-bc/crates/uplc/Cargo.toml
COPY --from=build /src/Cargo.toml /bench/uplc-turbo-bc/Cargo.toml
COPY --from=build /src/Cargo.lock /bench/uplc-turbo-bc/Cargo.lock
RUN bin=$(find /bench/uplc-turbo-bc/target/release/deps -name 'use_cases-*' -type f ! -name '*.d' | head -1) \
    && test -n "$bin" && ! ldd "$bin" | grep 'not found'

COPY check/reference/mainnet-plutusv3-costmodel.json /bench/mainnet-plutusv3-costmodel.json
COPY parsers/ /bench/parsers/
COPY scripts/image-entry.sh scripts/run-uplc-turbo-bc.sh /bench/scripts/

ENV PVB_VM=uplc-turbo-bc
WORKDIR /bench
ENTRYPOINT ["bash", "/bench/scripts/image-entry.sh"]
