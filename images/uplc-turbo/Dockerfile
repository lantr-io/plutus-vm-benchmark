# check=skip=InvalidDefaultArgInFrom
# uplc-turbo (Amaru), AST walker (Rust / Criterion). docs/IMAGE_CONTRACT.md.

ARG AMARU_UPLC_RUST_VERSION

# =============================================================================
# Build stage
# =============================================================================
FROM rust:${AMARU_UPLC_RUST_VERSION}-bookworm AS build

ARG AMARU_UPLC_REPO
ARG AMARU_UPLC_SHA
# Keep peak memory low when other images build at the same time.
ARG CARGO_BUILD_JOBS=2
ENV CARGO_BUILD_JOBS=${CARGO_BUILD_JOBS}

RUN git clone "$AMARU_UPLC_REPO" /src \
    && cd /src && git checkout "$AMARU_UPLC_SHA"

WORKDIR /src

# Our harness replaces the upstream use_cases bench (PV 11, continues after a failing script,
# PVB_CHECK_OUT check mode). See the header of images/uplc-turbo/use_cases.rs.
COPY images/uplc-turbo/use_cases.rs /src/crates/amaru-uplc/benches/use_cases/main.rs

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

RUN bench_bin=$(find /src/target/release -type f -perm /111 -name 'use_cases-*' | head -1) \
    && test -n "$bench_bin" && cp "$bench_bin" /src/use_cases-bin

# =============================================================================
# Runtime stage
# =============================================================================
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 procps \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /src/use_cases-bin /bench/uplc-turbo/bin/use_cases
COPY --from=build /src/crates/amaru-uplc/benches /bench/uplc-turbo/crates/amaru-uplc/benches
RUN ! ldd /bench/uplc-turbo/bin/use_cases | grep 'not found'

COPY check/reference/mainnet-plutusv3-costmodel.json /bench/mainnet-plutusv3-costmodel.json
COPY parsers/ /bench/parsers/
COPY scripts/image-entry.sh scripts/run-uplc-turbo.sh /bench/scripts/

ENV PVB_VM=uplc-turbo
WORKDIR /bench
ENTRYPOINT ["bash", "/bench/scripts/image-entry.sh"]
