#!/bin/bash
# Shared checks for the Arch and Debian/Ubuntu installers.

validate_build_args() {
    [[ -z "$KICAD_VERSION_OVERRIDE" || "$KICAD_VERSION_OVERRIDE" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-rc[0-9]+)?$ ]] \
        || die "Invalid KiCad version: $KICAD_VERSION_OVERRIDE"
    [[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || die "--jobs must be a positive integer"
    if $MODE_FROM_CACHE && { $MODE_REBUILD || $MODE_BUILD_ONLY; }; then
        die "--from-cache cannot be combined with --rebuild or --build-only"
    fi
    if $MODE_RESTORE && { $MODE_CHECK || $MODE_BUILD_ONLY || $MODE_FROM_CACHE || $MODE_REBUILD; }; then
        die "--restore cannot be combined with build/install/check modes"
    fi
}

cache_is_complete() {
    local cache_dir="$1" version="$2" hash="$3"
    [[ -f "$cache_dir/.meta" && -x "$cache_dir$KICAD_INSTALL_PREFIX/bin/kicad-cli" ]] || return 1
    grep -Fxq "version=$version" "$cache_dir/.meta" &&
        grep -Fxq "patches_hash=$hash" "$cache_dir/.meta" &&
        grep -Fxq "cache_format=$CACHE_FORMAT_VERSION" "$cache_dir/.meta"
}

runtime_data_path_is_cached() {
    # __FILE__ diagnostics may name cached dependency headers. Only a resource
    # directory in the cache indicates the old DESTDIR/runtime-prefix bug.
    LC_ALL=C strings "$1" | awk -v cache="$CACHE_DIR/" '
        index($0, cache) == 1 && /\/share\/kicad\/?$/ { found = 1 }
        END { exit !found }
    '
}

# The return status and actual output matter: a crash can produce no diagnostic,
# and a successful version query does not load the schematic editor's kiface.
verify_cli() {
    local cli="$1" expected_version="$2" library_dir="${3:-}" data_dir="${4:-$KICAD_DATA_DIR}"
    local verify_dir version fixture output
    [[ -x "$cli" ]] || { err "Missing executable: $cli"; return 1; }
    verify_dir=$(mktemp -d /tmp/kicad-cli-check.XXXXXX) || return 1
    local cli_env=(env LC_ALL=C
        "KICAD_STOCK_DATA_HOME=$data_dir"
        "XDG_CONFIG_HOME=$verify_dir/config"
        "XDG_CACHE_HOME=$verify_dir/cache"
        "XDG_DATA_HOME=$verify_dir/data")
    if [[ -n "$library_dir" ]]; then
        cli_env+=("LD_LIBRARY_PATH=$library_dir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}")
    fi

    if ! version=$("${cli_env[@]}" "$cli" version 2>"$verify_dir/stderr"); then
        cat "$verify_dir/stderr" >&2
        rm -rf -- "$verify_dir"
        err "kicad-cli version failed"
        return 1
    fi
    # Accept a build suffix, but never 10.0.70 or 10.0.7-rc1 for stable 10.0.7.
    if [[ "$version" != "$expected_version" && "$version" != "$expected_version"+* ]]; then
        rm -rf -- "$verify_dir"
        err "Expected KiCad $expected_version, got: $version"
        return 1
    fi
    ok "kicad-cli version: $version"

    for fixture in Attiny-test.SchLib test_bug_nullbyte.SchLib; do
        output="$verify_dir/${fixture%.SchLib}.kicad_sym"
        if ! "${cli_env[@]}" "$cli" sym upgrade "$PROJECT_DIR/tests/fixtures/$fixture" \
                -o "$output" --force >"$verify_dir/import.log" 2>&1 \
                || [[ ! -s "$output" ]] \
                || ! grep -q '(symbol ' "$output"; then
            cat "$verify_dir/import.log" >&2
            rm -rf -- "$verify_dir"
            err "Altium import failed: $fixture"
            return 1
        fi
        ok "Altium import: $fixture"
    done
    rm -rf -- "$verify_dir"
}
