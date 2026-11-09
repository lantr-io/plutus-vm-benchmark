# check=skip=InvalidDefaultArgInFrom
# amaru-uplc (Amaru), AST walker (Rust / Criterion). docs/IMAGE_CONTRACT.md.

ARG AMARU_UPLC_RUST_VERSION

# =============================================================================
# Build stage
# =============================================================================
FROM rust:${AMARU_UPLC_RUST_VERSION}-bookworm AS build

# Keep peak memory low when other images build at the same time.
ARG CARGO_BUILD_JOBS=2
ENV CARGO_BUILD_JOBS=${CARGO_BUILD_JOBS}

WORKDIR /src

# The harness uses the released amaru-uplc crate directly. It keeps the benchmark independent of
# the Amaru workspace while retaining the same PV11/default-cost-model evaluation path.
COPY images/amaru-uplc/Cargo.toml /src/Cargo.toml
COPY images/amaru-uplc/Cargo.lock /src/Cargo.lock
COPY images/amaru-uplc/use_cases.rs /src/use_cases.rs

# The pinned Amaru workspace uses fat LTO and one codegen unit for release builds. Keep those
# settings explicit and apply them to the bench profile too.
ENV CARGO_PROFILE_RELEASE_LTO=true \
    CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 \
    CARGO_PROFILE_BENCH_LTO=true \
    CARGO_PROFILE_BENCH_CODEGEN_UNITS=1

# The check: rustc built the crate and linked the bench binary with fat LTO and one codegen unit.
RUN { cargo build -v --release --bench use_cases --manifest-path crates/amaru-uplc/Cargo.toml \
        > /tmp/build.log 2>&1 || { tail -50 /tmp/build.log; exit 1; }; } \
    && grep -E -- '--crate-name use_cases ' /tmp/build.log > /tmp/bench.log \
    && grep -q -E -- '-C lto( |=fat )' /tmp/bench.log && grep -q -- '-C codegen-units=1' /tmp/bench.log \
    && grep -E -- '--crate-name amaru_uplc ' /tmp/build.log | grep -q -- '-C codegen-units=1'

RUN bench_bin=$(find /src/target/release -type f -perm /111 -name 'use_cases-*' ! -name '*.d' | head -1) \
    && test -n "$bench_bin" && cp "$bench_bin" /src/use_cases-bin

# =============================================================================
# Runtime stage
# =============================================================================
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 procps \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /src/use_cases-bin /bench/amaru-uplc/bin/use_cases
RUN ! ldd /bench/amaru-uplc/bin/use_cases | grep 'not found'

COPY parsers/ /bench/parsers/
COPY scripts/image-entry.sh scripts/run-amaru-uplc.sh /bench/scripts/

ENV PVB_VM=amaru-uplc
WORKDIR /bench
ENTRYPOINT ["bash", "/bench/scripts/image-entry.sh"]
