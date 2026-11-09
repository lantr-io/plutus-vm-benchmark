#!/usr/bin/env bash
# Facts about the per-VM images (docs/IMAGE_CONTRACT.md), shared by local builds and CI.
#
#   scripts/images.sh list               every VM that has an image, one per line
#   scripts/images.sh bases              every base image (images/<base>/Dockerfile with a line
#                                        "# pvb-base"), one per line
#   scripts/images.sh dir <vm>           images/<dir> that holds the VM's Dockerfile
#   scripts/images.sh build-args <vm>    KEY=VALUE lines to pass as --build-arg (an ARG with a
#                                        default in the Dockerfile may be absent from .env)
#   scripts/images.sh tag <vm>           content hash: changes only when the VM's inputs change
#   scripts/images.sh build <vm> [docker build options...]
#                                        build ${IMAGE_PREFIX}<vm>:<tag> and :latest locally
#
# A Dockerfile serves the VM named like its directory, unless its header has a line
# "# pvb-vms: <vm> <vm>..." (one build shared by several VMs, for example scalus-cek and
# scalus-jit). Such a Dockerfile takes the build arg VM, which selects the default command.
#
# A base image (header line "# pvb-base", for example images/jvm-base) serves no VM. A VM
# Dockerfile uses it with "ARG JVM_BASE" + "FROM ${JVM_BASE}": the build arg <NAME>_BASE is the
# image of images/<name>-base, ${IMAGE_PREFIX}<name>-base:<tag>. The base tag is a build arg of
# the VM, so it is in the VM's tag: a change of the base rebuilds the VMs that use it.
#
# Written for bash 3.2 (macOS /bin/bash): no associative arrays, no mapfile.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_PREFIX="${IMAGE_PREFIX:-ghcr.io/lantr-io/pvb-}"

die() { echo "images.sh: $*" >&2; exit 1; }

is_base() { grep -q '^# pvb-base' "$REPO_ROOT/images/$1/Dockerfile"; }

# VMs served by images/<dir>/Dockerfile; none for a base image.
vms_of_dir() {
    local dockerfile="$REPO_ROOT/images/$1/Dockerfile"
    local declared
    is_base "$1" && return 0
    declared=$(sed -n 's/^# pvb-vms:[[:space:]]*//p' "$dockerfile" | head -1)
    if [[ -n "$declared" ]]; then echo "$declared" | tr ' ' '\n' | grep -v '^$'; else echo "$1"; fi
}

cmd_list() {
    local d
    for d in "$REPO_ROOT"/images/*/Dockerfile; do
        vms_of_dir "$(basename "$(dirname "$d")")"
    done
}

cmd_bases() {
    local d
    for d in "$REPO_ROOT"/images/*/Dockerfile; do
        d=$(basename "$(dirname "$d")")
        if is_base "$d"; then echo "$d"; fi
    done
}

# The base image a <NAME>_BASE build arg names: JVM_BASE -> jvm-base.
base_of_arg() { echo "$1" | tr 'A-Z_' 'a-z-'; }

cmd_dir() {
    local vm="$1" d
    if [[ -f "$REPO_ROOT/images/$vm/Dockerfile" ]] && is_base "$vm"; then echo "images/$vm"; return; fi
    for d in "$REPO_ROOT"/images/*/Dockerfile; do
        d=$(basename "$(dirname "$d")")
        if vms_of_dir "$d" | grep -qx "$vm"; then echo "images/$d"; return; fi
    done
    die "no image for VM '$vm'"
}

# Value of KEY in .env, without the inline "# comment" and surrounding blanks.
env_value() {
    sed -n "s/^$1=//p" "$REPO_ROOT/.env" | head -1 | sed 's/[[:space:]]#.*$//; s/[[:space:]]*$//'
}

cmd_build_args() {
    local vm="$1" dir arg value
    dir=$(cmd_dir "$vm")
    # ARG names are single words.
    # shellcheck disable=SC2013
    for arg in $(sed -n 's/^ARG[[:space:]]\{1,\}\([A-Z0-9_]\{1,\}\).*/\1/p' "$REPO_ROOT/$dir/Dockerfile" | sort -u); do
        if [[ "$arg" == VM ]]; then
            echo "VM=$vm"
            continue
        fi
        if [[ "$arg" == *_BASE ]]; then
            echo "$arg=${IMAGE_PREFIX}$(base_of_arg "$arg"):$(cmd_tag "$(base_of_arg "$arg")")"
            continue
        fi
        value=$(env_value "$arg")
        if [[ -z "$value" ]]; then
            # An ARG with a default in the Dockerfile ("ARG NAME=value") needs no .env value. The
            # Dockerfile is an input of the tag, so a changed default still changes the tag.
            grep -Eq "^ARG[[:space:]]+${arg}=" "$REPO_ROOT/$dir/Dockerfile" && continue
            die "$dir/Dockerfile declares ARG $arg without a default, and .env has no value for it"
        fi
        echo "$arg=$value"
    done
}

# Repo files the image is built from: its images/<dir>/ and every local COPY source.
input_files() {
    local dir="$1" src
    (
        cd "$REPO_ROOT"
        {
            find "$dir" -type f
            # COPY lines without --from=; drop flags and the destination (last word).
            grep -E '^COPY[[:space:]]' "$dir/Dockerfile" | grep -v -- '--from=' \
                | sed 's/^COPY[[:space:]]*//; s/--[a-z]*=[^[:space:]]*//g' \
                | awk '{ for (i = 1; i < NF; i++) print $i }' \
                | while read -r src; do
                    # $src may be a glob (COPY a/*.txt): unquoted on purpose.
                    # shellcheck disable=SC2086
                    if [[ -d "$src" ]]; then find "$src" -type f; else ls -1 $src; fi
                done
        } | sed 's|^\./||; s|/$||' | grep -v -e '__pycache__' -e '\.pyc$' -e '/target/' -e '^target/' | LC_ALL=C sort -u
    )
}

cmd_tag() {
    local vm="$1" dir f
    dir=$(cmd_dir "$vm")
    {
        cmd_build_args "$vm"
        for f in $(input_files "$dir"); do
            echo "$f $(git -C "$REPO_ROOT" hash-object "$f")"
        done
    } | git hash-object --stdin | cut -c1-12
}

cmd_build() {
    local vm="$1"; shift
    local dir tag args=() line
    dir=$(cmd_dir "$vm")
    tag=$(cmd_tag "$vm")
    while IFS= read -r line; do
        args+=(--build-arg "$line")
        # Build a base image first when it is not here yet.
        case "$line" in
            *_BASE=*)
                docker image inspect "${line#*=}" >/dev/null 2>&1 \
                    || cmd_build "$(base_of_arg "${line%%=*}")"
                ;;
        esac
    done < <(cmd_build_args "$vm")
    echo "Building ${IMAGE_PREFIX}${vm}:${tag} from $dir/Dockerfile" >&2
    docker build ${args[@]+"${args[@]}"} "$@" \
        -f "$REPO_ROOT/$dir/Dockerfile" \
        -t "${IMAGE_PREFIX}${vm}:${tag}" -t "${IMAGE_PREFIX}${vm}:latest" \
        "$REPO_ROOT"
}

[[ $# -ge 1 ]] || die "usage: $0 list | bases | dir <vm> | build-args <vm> | tag <vm> | build <vm> [options]"
case "$1" in
    list) cmd_list ;;
    bases) cmd_bases ;;
    dir) cmd_dir "${2:?vm}" ;;
    build-args) cmd_build_args "${2:?vm}" ;;
    tag) cmd_tag "${2:?vm}" ;;
    build) shift; vm="${1:?vm}"; shift; cmd_build "$vm" "$@" ;;
    *) die "unknown command '$1'" ;;
esac
