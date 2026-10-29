# PlutusCoreBlaster: native Lean CEK interpreter. docs/IMAGE_CONTRACT.md.
FROM debian:bookworm-slim AS build

ARG PLUTUSCORE_LEAN_REPO
ARG PLUTUSCORE_LEAN_SHA
ARG PLUTUSCORE_LEAN_VERSION
ARG PLUTUSCORE_BLASTER_SHA

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git python3 build-essential libgmp-dev libsodium-dev pkg-config zstd \
    && rm -rf /var/lib/apt/lists/*

# Install the repository's exact Lean release, natively on amd64 or arm64.
RUN case "$(uname -m)" in \
      x86_64) platform=linux ;; \
      aarch64) platform=linux_aarch64 ;; \
      *) exit 1 ;; \
    esac \
    && mkdir -p /opt/lean \
    && curl -fsSL "https://github.com/leanprover/lean4/releases/download/v${PLUTUSCORE_LEAN_VERSION}/lean-${PLUTUSCORE_LEAN_VERSION}-${platform}.tar.zst" \
       | tar --zstd -x -C /opt/lean --strip-components=1
ENV PATH="/opt/lean/bin:${PATH}"

RUN git init -q /src \
    && git -C /src fetch --depth 1 "$PLUTUSCORE_LEAN_REPO" "$PLUTUSCORE_LEAN_SHA" \
    && git -C /src checkout -q FETCH_HEAD
WORKDIR /src
ENV LEAN_CC=/src/scripts/lean-cc.sh

# The upstream Lake file selects a development branch of Lean-blaster. Pin it too, so
# rebuilding this image cannot silently select a different dependency revision.
RUN test "$(cat lean-toolchain)" = "$PLUTUSCORE_LEAN_VERSION" \
    && sed -i "s/@ \"beta-lambda-cache-optimization\"/@ \"${PLUTUSCORE_BLASTER_SHA}\"/" lakefile.lean \
    && grep -q "$PLUTUSCORE_BLASTER_SHA" lakefile.lean \
    && lake update \
    && lake build bench_cek test_crypto_ffi test_flat_decode \
    && python3 scripts/test_crypto_ffi.py \
    && python3 scripts/test_flat_decode.py

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 procps libgmp10 libstdc++6 libsodium23 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /src/.lake/build/bin/bench_cek /bench/plutuscore-lean/bench_cek
COPY --from=build /src/Cryptograph/FFI/c/crypton/LICENSE /usr/share/doc/plutuscore-lean/crypton-LICENSE
RUN ! ldd /bench/plutuscore-lean/bench_cek | grep 'not found'
COPY parsers/fill_failures.py /bench/parsers/
COPY scripts/image-entry.sh scripts/run-plutuscore-lean.sh /bench/scripts/

ARG PLUTUSCORE_LEAN_SHA
ENV PLUTUSCORE_LEAN_SHA=${PLUTUSCORE_LEAN_SHA}
ENV PVB_VM=plutuscore-lean
WORKDIR /bench
ENTRYPOINT ["bash", "/bench/scripts/image-entry.sh"]
