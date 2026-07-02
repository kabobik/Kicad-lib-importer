#!/bin/bash
# ============================================================================
# build_and_install_arch.sh - KiCad patch builder & installer for Arch Linux
# ============================================================================
#
# Builds KiCad from upstream source archives, applies local project patches, and
# installs the result over the Arch Linux KiCad package layout.
#
# If --version is not passed, the script uses the newest supported patch
# directory from patches/kicad-X.X.X. This allows installation on a machine where
# KiCad is not installed yet.
#
# Usage:
#   ./scripts/build_and_install_arch.sh
#   ./scripts/build_and_install_arch.sh --check
#   ./scripts/build_and_install_arch.sh --version 10.0.4 --rebuild
#   ./scripts/build_and_install_arch.sh --from-cache
#   ./scripts/build_and_install_arch.sh --build-only
#   ./scripts/build_and_install_arch.sh --restore
#
# ============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PATCHES_DIR="$PROJECT_DIR/patches"
CACHE_DIR="${CACHE_DIR:-$PROJECT_DIR/cache}"
SOURCE_CACHE_DIR="${SOURCE_CACHE_DIR:-$CACHE_DIR/sources}"
SRC_DIR="${SRC_DIR:-$PROJECT_DIR/kicad-src-arch}"
KICAD_REPO="${KICAD_REPO:-https://gitlab.com/kicad/code/kicad.git}"
KICAD_SOURCE_URL_TEMPLATE="${KICAD_SOURCE_URL_TEMPLATE:-https://gitlab.com/kicad/code/kicad/-/archive/%VERSION%/kicad-%VERSION%.tar.gz}"
JOBS=$(nproc 2>/dev/null || echo 4)
CACHE_FORMAT_VERSION=arch-1

# Arch KiCad package layout
KICAD_INSTALL_PREFIX="${KICAD_INSTALL_PREFIX:-/usr}"
KICAD_INSTALL_LIBDIR="${KICAD_INSTALL_LIBDIR:-lib}"
KICAD_DATA_DIR="${KICAD_DATA_DIR:-$KICAD_INSTALL_PREFIX/share/kicad}"
KICAD_LIBRARY_DATA_DIR="${KICAD_LIBRARY_DATA_DIR:-$KICAD_DATA_DIR}"
KICAD_DOCS_DIR="${KICAD_DOCS_DIR:-$KICAD_INSTALL_PREFIX/share/doc/kicad}"
KICAD_LIB_DIR="${KICAD_LIB_DIR:-$KICAD_INSTALL_PREFIX/lib}"
KICAD_USER_PLUGIN_DIR="${KICAD_USER_PLUGIN_DIR:-$KICAD_LIB_DIR/kicad/plugins}"
SYSTEM_BIN_DIR="/usr/bin"
SYSTEM_LIB_DIR="/usr/lib"
SYSTEM_SHARE_DIR="/usr/share"

ARCH_RUNTIME_PACKAGES=(kicad kicad-library kicad-library-3d)
ARCH_BUILD_PACKAGES=(
    base-devel
    cmake
    ninja
    git
    patch
    curl
    tar
    file
    pkgconf
    gettext
    python
    python-wxpython
    boost
    boost-libs
    swig
    mesa
    abseil-cpp
    cairo
    fontconfig
    freetype2
    glib2
    glm
    glu
    gtk3
    harfbuzz
    libgit2
    libsecret
    libspnav
    ngspice
    nng
    opencascade
    poppler
    poppler-glib
    protobuf
    unixodbc
    wayland
    webkit2gtk-4.1
    wxwidgets-common
    wxwidgets-gtk3
    zlib
    zstd
)

# Modes
MODE_CHECK=false
MODE_FROM_CACHE=false
MODE_REBUILD=false
MODE_RESTORE=false
MODE_BUILD_ONLY=false
KICAD_VERSION_OVERRIDE=""
PATCH_CHECK_SRC=""
PATCH_CHECK_TMP=""

cleanup_tmp() {
    [[ -n "${PATCH_CHECK_TMP:-}" && -d "$PATCH_CHECK_TMP" ]] && rm -rf -- "$PATCH_CHECK_TMP"
    return 0
}

trap cleanup_tmp EXIT

# Utilities
log()    { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()     { echo -e "${GREEN}[  OK]${NC} $*"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()    { echo -e "${RED}[FAIL]${NC} $*" >&2; }
die()    { err "$*"; exit 1; }
header() { echo -e "\n${BOLD}=== $* ===${NC}"; }
ask()    { echo -e "${YELLOW}[?]${NC} $*"; }

run_sudo() {
    if [[ -n "${SUDO_ASKPASS:-}" && ! -t 0 ]]; then
        sudo -A "$@"
    else
        sudo "$@"
    fi
}

sudo_atomic_copy() {
    local src="$1" dst="$2" tmp
    tmp="${dst}.tmp.$$"

    run_sudo mkdir -p "$(dirname "$dst")"
    run_sudo rm -f "$tmp"
    run_sudo cp -aP "$src" "$tmp"
    run_sudo mv -f "$tmp" "$dst"
}

show_help() {
    cat << 'EOF'
build_and_install_arch.sh - KiCad patch builder & installer for Arch Linux

USAGE:
  ./scripts/build_and_install_arch.sh [OPTIONS]

OPTIONS:
  -v, --version X.X.X  Use an explicit KiCad version
                       Default: newest patches/kicad-X.X.X directory
  --check              Dry-run: show plan and test patches, do not change system
  --from-cache         Install only from an existing staged cache
  --rebuild            Rebuild even when a matching cache exists
  --build-only         Build staged cache without installing into /usr
  --restore            Restore original Arch package files from backup
  --list-cache         List cached staged builds
  --clean-cache        Remove staged build caches, keep original backups
  -j, --jobs N         Build jobs, default: nproc
  -h, --help           Show this help

ENVIRONMENT:
  SRC_DIR                     Source tree path, default: ./kicad-src-arch
  CACHE_DIR                   Cache path, default: ./cache
  SOURCE_CACHE_DIR            Source archive cache, default: ./cache/sources
  KICAD_SOURCE_URL_TEMPLATE   Source archive URL template with %VERSION%
  KICAD_INSTALL_PREFIX        Runtime prefix, default: /usr
  KICAD_INSTALL_LIBDIR        Runtime libdir below prefix, default: lib

WHAT THE INSTALLER INSTALLS THROUGH PACMAN:
  kicad
  kicad-library       symbols, footprints, templates
  kicad-library-3d    3D models

EXAMPLES:
  ./scripts/build_and_install_arch.sh --check
  ./scripts/build_and_install_arch.sh
  ./scripts/build_and_install_arch.sh --version 10.0.4 --rebuild
  ./scripts/build_and_install_arch.sh --from-cache
  ./scripts/build_and_install_arch.sh --restore
EOF
}

check_arch_host() {
    command -v pacman >/dev/null 2>&1 || die "pacman not found. This script is for Arch Linux."
}

check_not_root() {
    if [[ $EUID -eq 0 ]]; then
        warn "The script is running as root. Prefer running it as a normal user."
        warn "sudo is requested only for pacman and /usr installation steps."
        echo ""
        ask "Continue anyway? [y/N]: "
        read -r answer
        [[ "${answer,,}" == "y" ]] || exit 1
    fi
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -v|--version)
                [[ $# -ge 2 ]] || die "$1 requires a version"
                KICAD_VERSION_OVERRIDE="$2"
                shift 2
                ;;
            --check)       MODE_CHECK=true; shift ;;
            --from-cache)  MODE_FROM_CACHE=true; shift ;;
            --rebuild)     MODE_REBUILD=true; shift ;;
            --build-only)  MODE_BUILD_ONLY=true; shift ;;
            --restore)     MODE_RESTORE=true; shift ;;
            --list-cache)  list_cache; exit 0 ;;
            --clean-cache) clean_cache; exit 0 ;;
            -j|--jobs)
                [[ $# -ge 2 ]] || die "$1 requires a number"
                JOBS="$2"
                shift 2
                ;;
            -h|--help)     show_help; exit 0 ;;
            *) die "Unknown argument: $1. Use --help." ;;
        esac
    done
}

normalize_pkg_version() {
    local ver="$1"
    ver="${ver#*:}"
    ver="${ver%%-*}"
    ver="${ver%%+*}"
    ver="${ver%%~*}"
    printf "%s\n" "$ver"
}

arch_installed_package_version() {
    local pkg="$1"
    pacman -Q "$pkg" 2>/dev/null | awk '{print $2}' || true
}

arch_repo_package_version() {
    local pkg="$1"
    pacman -Si "$pkg" 2>/dev/null | awk -F': ' '/^Version/ {print $2; exit}' || true
}

package_installed() {
    local pkg="$1"
    pacman -Qq "$pkg" >/dev/null 2>&1
}

report_arch_packages() {
    header "Arch packages"

    local pkg installed repo
    for pkg in "${ARCH_RUNTIME_PACKAGES[@]}"; do
        installed=$(arch_installed_package_version "$pkg")
        repo=$(arch_repo_package_version "$pkg")
        printf "  %-18s installed=%-18s repo=%s\n" "$pkg" "${installed:-no}" "${repo:-unknown}"
    done
    echo ""
}

install_arch_runtime_if_needed() {
    local target_version="$1"
    local missing=()
    local pkg

    for pkg in "${ARCH_RUNTIME_PACKAGES[@]}"; do
        package_installed "$pkg" || missing+=("$pkg")
    done

    local installed_kicad installed_norm
    installed_kicad=$(arch_installed_package_version kicad)
    installed_norm=""
    [[ -n "$installed_kicad" ]] && installed_norm=$(normalize_pkg_version "$installed_kicad")

    if [[ ${#missing[@]} -eq 0 ]]; then
        ok "Arch runtime packages are installed"
    else
        warn "Missing Arch runtime/library packages:"
        for pkg in "${missing[@]}"; do
            echo "    - $pkg"
        done
    fi

    if [[ -n "$installed_norm" && "$installed_norm" != "$target_version" ]]; then
        warn "Installed Arch kicad package is $installed_norm, target patched build is $target_version"
        warn "The staged build will replace KiCad binaries/libs after the base package is present."
    fi

    if [[ ${#missing[@]} -gt 0 ]]; then
        log "Installing KiCad base package and official libraries through pacman..."
        run_sudo pacman -S --needed "${ARCH_RUNTIME_PACKAGES[@]}"
    else
        log "Refreshing official KiCad library packages through pacman --needed..."
        run_sudo pacman -S --needed kicad-library kicad-library-3d
    fi

    ok "Arch KiCad base/libraries are present"
}

check_build_deps() {
    header "Build dependencies"

    local -A tool_pkgs=(
        [cmake]=cmake
        [ninja]=ninja
        [g++]=base-devel
        [git]=git
        [patch]=patch
        [python3]=python
        [curl]=curl
        [tar]=tar
        [strip]=base-devel
        [file]=file
        [pkg-config]=pkgconf
    )

    local missing_tools=()
    local missing_pkgs=()
    local cmd pkg

    for cmd in "${!tool_pkgs[@]}"; do
        command -v "$cmd" >/dev/null 2>&1 || missing_tools+=("${tool_pkgs[$cmd]}")
    done

    for pkg in "${ARCH_BUILD_PACKAGES[@]}"; do
        package_installed "$pkg" || missing_pkgs+=("$pkg")
    done

    local all_missing=("${missing_tools[@]}" "${missing_pkgs[@]}")
    if [[ ${#all_missing[@]} -eq 0 ]]; then
        ok "All build dependencies are installed"
        return
    fi

    local unique_missing=()
    local seen=" "
    for pkg in "${all_missing[@]}"; do
        [[ "$seen" == *" $pkg "* ]] && continue
        seen+="$pkg "
        unique_missing+=("$pkg")
    done

    warn "Missing packages (${#unique_missing[@]}):"
    for pkg in "${unique_missing[@]}"; do
        echo "    - $pkg"
    done
    echo ""

    ask "Install missing build dependencies through pacman? [Y/n]: "
    read -r answer
    if [[ "${answer,,}" == "n" ]]; then
        die "Install manually: sudo pacman -S --needed ${unique_missing[*]}"
    fi

    run_sudo pacman -S --needed "${unique_missing[@]}"
    ok "Build dependencies are installed"
}

detect_binary_kicad_version() {
    if command -v kicad-cli >/dev/null 2>&1; then
        local ver
        ver=$(kicad-cli version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
        [[ -n "$ver" ]] && echo "$ver" && return
    fi

    if command -v kicad >/dev/null 2>&1; then
        local ver
        ver=$(kicad --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
        [[ -n "$ver" ]] && echo "$ver" && return
    fi

    echo ""
}

detect_restore_version() {
    local installed ver
    installed=$(arch_installed_package_version kicad)
    if [[ -n "$installed" ]]; then
        normalize_pkg_version "$installed"
        return
    fi

    ver=$(detect_binary_kicad_version)
    [[ -n "$ver" ]] && echo "$ver" && return

    echo ""
}

latest_supported_patch_version() {
    local versions=()
    local d

    while IFS= read -r -d '' d; do
        if compgen -G "$d/*.patch" >/dev/null 2>&1 || compgen -G "$d/*.diff" >/dev/null 2>&1; then
            versions+=("$(basename "$d" | sed 's/^kicad-//')")
        fi
    done < <(find "$PATCHES_DIR" -maxdepth 1 -type d -name 'kicad-*' -print0 2>/dev/null)

    [[ ${#versions[@]} -gt 0 ]] || return 1
    printf "%s\n" "${versions[@]}" | sort -V | tail -1
}

report_default_version_context() {
    local version repo_version repo_norm installed installed_norm
    version="$1"

    log "No --version passed; using newest supported patch set: $version"

    repo_version=$(arch_repo_package_version kicad)
    if [[ -n "$repo_version" ]]; then
        repo_norm=$(normalize_pkg_version "$repo_version")
        if [[ "$repo_norm" != "$version" ]]; then
            warn "Arch repo kicad is $repo_norm, newest local patch set is $version"
            warn "Proceeding with $version because that is the newest version supported by this repo."
        fi
    fi

    installed=$(arch_installed_package_version kicad)
    if [[ -n "$installed" ]]; then
        installed_norm=$(normalize_pkg_version "$installed")
        if [[ "$installed_norm" != "$version" ]]; then
            warn "Installed Arch kicad is $installed_norm; target patched build is $version"
        fi
    fi

}

find_patch_dir() {
    local version="$1"
    local exact="$PATCHES_DIR/kicad-$version"

    if [[ -d "$exact" ]] \
       && { compgen -G "$exact/*.patch" >/dev/null 2>&1 \
            || compgen -G "$exact/*.diff" >/dev/null 2>&1; }; then
        echo "$exact"
        return 0
    fi

    local available=()
    local d
    while IFS= read -r -d '' d; do
        available+=("$(basename "$d" | sed 's/^kicad-//')")
    done < <(find "$PATCHES_DIR" -maxdepth 1 -type d -name 'kicad-*' -print0 | sort -z)

    warn "No patch directory for KiCad $version." >&2
    if [[ ${#available[@]} -gt 0 ]]; then
        warn "Available versions:" >&2
        for d in "${available[@]}"; do
            echo "    - $d" >&2
        done
    fi

    [[ -t 0 ]] || return 1
    echo "" >&2
    ask "Use patches from another version? [enter version or empty to cancel]: " >&2
    read -r choice
    [[ -z "$choice" ]] && return 1

    local fallback="$PATCHES_DIR/kicad-$choice"
    [[ -d "$fallback" ]] || die "Patch version not found: $choice"
    warn "Using patches from $choice for KiCad $version; compatibility is not guaranteed." >&2
    echo "$fallback"
}

list_patches() {
    local patch_dir="$1"
    find "$patch_dir" -maxdepth 1 \( -name "*.patch" -o -name "*.diff" \) | sort
}

compute_hash() {
    local patch_dir="$1"
    {
        echo "cache_format=$CACHE_FORMAT_VERSION"
        echo "platform=arch"
        echo "install_prefix=$KICAD_INSTALL_PREFIX"
        echo "install_libdir=$KICAD_INSTALL_LIBDIR"
        echo "kicad_data=$KICAD_DATA_DIR"
        echo "kicad_library_data=$KICAD_LIBRARY_DATA_DIR"
        echo "kicad_docs=$KICAD_DOCS_DIR"
        echo "kicad_lib=$KICAD_LIB_DIR"
        echo "kicad_user_plugin=$KICAD_USER_PLUGIN_DIR"
        echo "source_url_template=$KICAD_SOURCE_URL_TEMPLATE"
        list_patches "$patch_dir" | while IFS= read -r patch_file; do
            echo "patch=$(basename "$patch_file")"
            cat "$patch_file"
        done
    } | md5sum | awk '{print $1}' | head -c 12
}

cache_install_dir() {
    local version="$1" hash="$2"
    echo "$CACHE_DIR/kicad-arch-${version}-${hash}"
}

cache_original_dir() {
    local version="$1"
    echo "$CACHE_DIR/kicad-arch-${version}-original"
}

list_cache() {
    header "Cached Arch builds ($CACHE_DIR)"
    local found=false
    local meta dir built size

    for meta in "$CACHE_DIR"/kicad-arch-*/.meta; do
        [[ -f "$meta" ]] || continue
        found=true
        dir="$(dirname "$meta")"
        built=$(grep '^built=' "$meta" | cut -d= -f2-)
        size=$(du -sh "$dir" 2>/dev/null | cut -f1)
        printf "  %-38s  %-25s  %s\n" "$(basename "$dir")" "${built:-?}" "${size:-?}"
    done

    echo ""
    for dir in "$CACHE_DIR"/kicad-arch-*-original; do
        [[ -d "$dir" ]] || continue
        found=true
        printf "  %-38s  original Arch package files\n" "$(basename "$dir")"
    done

    $found || echo "  (empty)"
}

clean_cache() {
    header "Clean Arch build cache"
    local removed=0
    local dir

    for dir in "$CACHE_DIR"/kicad-arch-*; do
        [[ -d "$dir" ]] || continue
        [[ "$dir" != *"-original" ]] || continue
        rm -rf "$dir"
        ((removed+=1))
        ok "Removed: $(basename "$dir")"
    done

    if [[ $removed -eq 0 ]]; then
        echo "  (nothing to remove)"
    else
        ok "Removed builds: $removed"
    fi
}

source_archive_path() {
    local version="$1"
    echo "$SOURCE_CACHE_DIR/kicad-$version.tar.gz"
}

source_archive_url() {
    local version="$1"
    echo "${KICAD_SOURCE_URL_TEMPLATE//%VERSION%/$version}"
}

assert_safe_source_dir() {
    local src="$1"

    [[ -n "$src" ]] || die "SRC_DIR is empty"
    [[ "$src" != "/" ]] || die "Refusing SRC_DIR=/"
    [[ "$src" != "$PROJECT_DIR" ]] || die "Refusing to use project root as SRC_DIR"

    case "$src" in
        "$PROJECT_DIR"/kicad-src|"$PROJECT_DIR"/kicad-src-*|"$PROJECT_DIR"/kicad-src-arch) ;;
        *)
            die "SRC_DIR is outside the expected project area: $src"
            ;;
    esac
}

download_source_archive() {
    local version="$1"
    local archive url
    archive=$(source_archive_path "$version")

    mkdir -p "$SOURCE_CACHE_DIR"

    if [[ -f "$archive" ]] && tar -tzf "$archive" >/dev/null 2>&1; then
        ok "Source archive already exists: $archive"
        return
    fi

    url=$(source_archive_url "$version")
    log "Downloading KiCad $version sources:"
    log "$url"

    rm -f "$archive.tmp"
    curl -L --fail --show-error --progress-bar --output "$archive.tmp" "$url"
    tar -tzf "$archive.tmp" >/dev/null 2>&1 || die "Downloaded archive is damaged: $archive.tmp"
    mv -f "$archive.tmp" "$archive"
    ok "Source archive downloaded: $archive"
}

prepare_source() {
    local version="$1"

    header "KiCad sources $version"
    assert_safe_source_dir "$SRC_DIR"

    local archive tmp_dir extracted
    archive=$(source_archive_path "$version")
    download_source_archive "$version"
    tmp_dir=$(mktemp -d "$PROJECT_DIR/.source-unpack-arch.XXXXXX")

    log "Unpacking archive..."
    tar -xzf "$archive" -C "$tmp_dir"

    extracted="$tmp_dir/kicad-$version"
    [[ -d "$extracted" ]] || die "Archive does not contain kicad-$version"

    if [[ -d "$SRC_DIR" ]]; then
        warn "Removing old source tree: $SRC_DIR"
        rm -rf -- "$SRC_DIR"
    fi

    mv "$extracted" "$SRC_DIR"
    rm -rf -- "$tmp_dir"
    printf "%s\n" "$version" > "$SRC_DIR/.kicad_source_version"
    ok "Sources ready: $SRC_DIR"
}

source_dir_version() {
    local src="$1"
    [[ -f "$src/.kicad_source_version" ]] || return 1
    tr -d '[:space:]' < "$src/.kicad_source_version"
}

prepare_patch_check_source() {
    local version="$1"
    local check_src="$SRC_DIR"

    if [[ -d "$check_src" && "$(source_dir_version "$check_src" 2>/dev/null || true)" == "$version" ]]; then
        log "Dry-run uses current source tree: $check_src"
        PATCH_CHECK_SRC="$check_src"
        PATCH_CHECK_TMP=""
        return
    fi

    header "Dry-run sources KiCad $version"
    download_source_archive "$version"

    PATCH_CHECK_TMP=$(mktemp -d /tmp/kicad-arch-patch-check.XXXXXX)
    log "Unpacking to temporary directory: $PATCH_CHECK_TMP"
    tar -xzf "$(source_archive_path "$version")" -C "$PATCH_CHECK_TMP"

    PATCH_CHECK_SRC="$PATCH_CHECK_TMP/kicad-$version"
    [[ -d "$PATCH_CHECK_SRC" ]] || die "Archive does not contain kicad-$version"
}

apply_patches() {
    local src="$1" patch_dir="$2" dry="${3:-false}"

    header "Patches $(basename "$patch_dir")"

    local patches=()
    local patch_file
    while IFS= read -r patch_file; do
        patches+=("$patch_file")
    done < <(list_patches "$patch_dir")

    [[ ${#patches[@]} -gt 0 ]] || die "No patches in $patch_dir"

    log "Found patches: ${#patches[@]}"
    echo ""

    for patch_file in "${patches[@]}"; do
        local name
        name=$(basename "$patch_file")
        printf "  ${DIM}%-56s${NC} " "$name"

        local check_args=(-p1 --directory="$src" --dry-run)
        local apply_args=(-p1 --directory="$src" --forward)

        if patch "${check_args[@]}" < "$patch_file" >/dev/null 2>&1; then
            if $dry; then
                echo -e "${GREEN}ok${NC}"
            elif patch "${apply_args[@]}" < "$patch_file" >/dev/null 2>&1; then
                echo -e "${GREEN}ok${NC}"
            else
                echo -e "${RED}fail${NC}"
                patch "${apply_args[@]}" < "$patch_file" 2>&1 | tail -10 || true
                die "Patch passed dry-run but failed to apply: $name"
            fi
        elif patch -R -p1 --directory="$src" --dry-run < "$patch_file" >/dev/null 2>&1; then
            echo -e "${YELLOW}already applied${NC}"
        elif $dry; then
            echo -e "${RED}fail${NC}"
            warn "Patch is incompatible: $name"
        else
            echo -e "${RED}fail${NC}"
            patch -p1 --directory="$src" --dry-run < "$patch_file" 2>&1 | tail -10 || true
            die "Patch failed: $name"
        fi
    done
    echo ""
}

build_kicad() {
    local src="$1" stage_dir="$2"

    header "Build KiCad"
    log "Source:    $src"
    log "Prefix:    $KICAD_INSTALL_PREFIX"
    log "Data:      $KICAD_DATA_DIR"
    log "Libdir:    $KICAD_LIB_DIR"
    log "Staging:   $stage_dir"
    log "Jobs:      $JOBS"
    echo ""

    local build_dir="$src/build"
    local configure_log="$build_dir/configure.log"
    local build_log="$build_dir/build.log"
    local install_log="$build_dir/install.log"

    rm -rf "$build_dir"
    mkdir -p "$build_dir"

    log "Configuring CMake..."
    set +e
    cmake -S "$src" -B "$build_dir" \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX="$KICAD_INSTALL_PREFIX" \
        -DCMAKE_INSTALL_LIBDIR="$KICAD_INSTALL_LIBDIR" \
        -DKICAD_DATA="$KICAD_DATA_DIR" \
        -DKICAD_LIBRARY_DATA="$KICAD_LIBRARY_DATA_DIR" \
        -DKICAD_DOCS="$KICAD_DOCS_DIR" \
        -DKICAD_PLUGINS="$KICAD_DATA_DIR/plugins" \
        -DKICAD_DEMOS="$KICAD_DATA_DIR/demos" \
        -DKICAD_TEMPLATE="$KICAD_LIBRARY_DATA_DIR/template" \
        -DKICAD_LIB="$KICAD_LIB_DIR" \
        -DKICAD_USER_PLUGIN="$KICAD_USER_PLUGIN_DIR" \
        -DKICAD_SCRIPTING_WXPYTHON=ON \
        -DKICAD_USE_OCC=ON \
        -DKICAD_SPICE=ON \
        -DKICAD_BUILD_I18N=ON \
        -DKICAD_BUILD_QA_TESTS=OFF \
        -DKICAD_USE_CMAKE_FINDPROTOBUF=ON \
        -GNinja \
        2>&1 | tee "$configure_log" | grep -E "(CMake Warning|CMake Error|-- Build|-- Install|-- Configuring|-- Generating|error:)"
    local cmake_status=${PIPESTATUS[0]}
    set -e
    [[ $cmake_status -eq 0 ]] || { tail -120 "$configure_log"; die "CMake configure failed. Log: $configure_log"; }
    ok "CMake configured"

    log "Building KiCad. This can take a while..."
    local start=$SECONDS
    set +e
    cmake --build "$build_dir" -j "$JOBS" 2>&1 | \
        tee "$build_log" | \
        awk '/^\[/ { if( NR % 80 == 0 ) print } /FAILED|error:|undefined reference|fatal:/ { print }'
    local build_status=${PIPESTATUS[0]}
    set -e
    [[ $build_status -eq 0 ]] || { tail -160 "$build_log"; die "Build failed. Log: $build_log"; }
    local elapsed=$(( SECONDS - start ))
    ok "Build finished in $(( elapsed / 60 ))m $(( elapsed % 60 ))s"

    log "Installing into staging cache..."
    rm -rf "$stage_dir$KICAD_INSTALL_PREFIX"
    set +e
    DESTDIR="$stage_dir" cmake --install "$build_dir" 2>&1 | tee "$install_log" | grep -v "^-- Up-to-date"
    local install_status=${PIPESTATUS[0]}
    set -e
    [[ $install_status -eq 0 ]] || { tail -120 "$install_log"; die "Staging install failed. Log: $install_log"; }
    ok "Installed into: $stage_dir$KICAD_INSTALL_PREFIX"

    log "Stripping ELF binaries and libraries..."
    while IFS= read -r -d '' file_path; do
        file "$file_path" | grep -q "ELF" && strip --strip-unneeded "$file_path" || true
    done < <(find "$stage_dir$KICAD_INSTALL_PREFIX" -type f \( -name "*.kiface" -o -name "*.so" -o -name "*.so.*" \
        -o -name "kicad" -o -name "kicad-cli" -o -name "eeschema" -o -name "pcbnew" \
        -o -name "gerbview" -o -name "pcb_calculator" -o -name "pl_editor" \
        -o -name "bitmap2component" \) -print0)
    ok "Stripping done"
}

find_system_kicad() {
    local bin
    bin=$(command -v kicad 2>/dev/null || true)
    if [[ -n "$bin" && -f "$bin" ]]; then
        dirname "$bin"
        return
    fi

    if [[ -x "$SYSTEM_BIN_DIR/kicad" || -d "$SYSTEM_BIN_DIR" ]]; then
        echo "$SYSTEM_BIN_DIR"
        return
    fi

    echo ""
}

backup_abs_path() {
    local backup_dir="$1" abs_path="$2"
    local dst="$backup_dir/root$abs_path"

    [[ -e "$abs_path" || -L "$abs_path" ]] || return 0
    [[ -e "$dst" || -L "$dst" ]] && return 0

    mkdir -p "$(dirname "$dst")"
    cp -aP "$abs_path" "$dst"
}

backup_originals() {
    local version="$1" cache_install="$2"
    local backup_dir stage_root cache_bin cache_lib cache_plugins cache_share

    backup_dir=$(cache_original_dir "$version")
    stage_root="$cache_install$KICAD_INSTALL_PREFIX"
    cache_bin="$stage_root/bin"
    cache_lib="$stage_root/$KICAD_INSTALL_LIBDIR"
    cache_plugins="$cache_lib/kicad/plugins"
    cache_share="$stage_root/share"

    header "Backup original Arch package files"
    mkdir -p "$backup_dir/root"

    local file_path name rel dir_path count

    if [[ -d "$cache_bin" ]]; then
        log "Backing up binaries from $SYSTEM_BIN_DIR"
        for file_path in "$cache_bin"/*; do
            [[ -e "$file_path" || -L "$file_path" ]] || continue
            name=$(basename "$file_path")
            backup_abs_path "$backup_dir" "$SYSTEM_BIN_DIR/$name"
        done
    fi

    if [[ -d "$cache_lib" ]]; then
        log "Backing up KiCad shared libraries from $SYSTEM_LIB_DIR"
        for file_path in "$cache_lib"/libki*.so*; do
            [[ -e "$file_path" || -L "$file_path" ]] || continue
            name=$(basename "$file_path")
            backup_abs_path "$backup_dir" "$SYSTEM_LIB_DIR/$name"
        done
    fi

    if [[ -d "$cache_plugins" ]]; then
        log "Backing up KiCad plugins from $SYSTEM_LIB_DIR/kicad/plugins"
        while IFS= read -r -d '' file_path; do
            rel="${file_path#"$cache_plugins"/}"
            backup_abs_path "$backup_dir" "$SYSTEM_LIB_DIR/kicad/plugins/$rel"
        done < <(find "$cache_plugins" \( -type f -o -type l \) -print0)
    fi

    while IFS= read -r -d '' file_path; do
        rel="${file_path#"$stage_root"/}"
        backup_abs_path "$backup_dir" "$KICAD_INSTALL_PREFIX/$rel"
    done < <(find "$stage_root/lib" -path '*/site-packages/*' \( -type f -o -type l \) -print0 2>/dev/null || true)

    if [[ -d "$cache_share/kicad" ]]; then
        log "Backing up KiCad share resources"
        while IFS= read -r -d '' dir_path; do
            name=$(basename "$dir_path")
            backup_abs_path "$backup_dir" "$SYSTEM_SHARE_DIR/kicad/$name"
        done < <(find "$cache_share/kicad" -mindepth 1 -maxdepth 1 -type d -print0)
    fi

    count=$(find "$backup_dir/root" \( -type f -o -type l \) | wc -l)
    ok "Backed up $count files to $backup_dir"
}

collect_install_files() {
    local cache_install="$1"
    local stage_root="$cache_install$KICAD_INSTALL_PREFIX"
    local cache_bin="$stage_root/bin"
    local cache_lib="$stage_root/$KICAD_INSTALL_LIBDIR"
    local cache_plugins="$cache_lib/kicad/plugins"

    INSTALL_BIN_FILES=()
    INSTALL_LIB_FILES=()
    INSTALL_PLUGIN_FILES=()
    INSTALL_PYTHON_FILES=()
    INSTALL_SHARE_DIRS=()

    local file_path dir_path

    if [[ -d "$cache_bin" ]]; then
        for file_path in "$cache_bin"/*; do
            [[ -e "$file_path" || -L "$file_path" ]] && INSTALL_BIN_FILES+=("$file_path")
        done
    fi

    if [[ -d "$cache_lib" ]]; then
        for file_path in "$cache_lib"/libki*.so*; do
            [[ -e "$file_path" || -L "$file_path" ]] && INSTALL_LIB_FILES+=("$file_path")
        done
    fi

    if [[ -d "$cache_plugins" ]]; then
        while IFS= read -r -d '' file_path; do
            INSTALL_PLUGIN_FILES+=("$file_path")
        done < <(find "$cache_plugins" \( -type f -o -type l \) -print0 | sort -z)
    fi

    while IFS= read -r -d '' file_path; do
        INSTALL_PYTHON_FILES+=("$file_path")
    done < <(find "$stage_root/lib" -path '*/site-packages/*' \( -type f -o -type l \) -print0 2>/dev/null | sort -z || true)

    if [[ -d "$stage_root/share/kicad" ]]; then
        while IFS= read -r -d '' dir_path; do
            INSTALL_SHARE_DIRS+=("$(basename "$dir_path")")
        done < <(find "$stage_root/share/kicad" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)
    fi
}

install_from_cache() {
    local cache_install="$1"
    local stage_root="$cache_install$KICAD_INSTALL_PREFIX"
    local cache_lib="$stage_root/$KICAD_INSTALL_LIBDIR"
    local cache_plugins="$cache_lib/kicad/plugins"
    local cache_share="$stage_root/share"

    header "Install into Arch system"

    [[ -d "$stage_root/bin" ]] || die "Invalid or old cache format: $cache_install"

    collect_install_files "$cache_install"

    log "Binaries:       ${#INSTALL_BIN_FILES[@]} -> $SYSTEM_BIN_DIR"
    log "Shared libs:    ${#INSTALL_LIB_FILES[@]} -> $SYSTEM_LIB_DIR"
    log "Plugins:        ${#INSTALL_PLUGIN_FILES[@]} -> $SYSTEM_LIB_DIR/kicad/plugins"
    log "Python files:   ${#INSTALL_PYTHON_FILES[@]} -> /usr/lib/python*/site-packages"
    log "share/kicad:    ${#INSTALL_SHARE_DIRS[@]} directories"
    echo ""

    local file_path name rel dir_name
    for file_path in "${INSTALL_BIN_FILES[@]}"; do printf "  bin/%s\n" "$(basename "$file_path")"; done
    for file_path in "${INSTALL_LIB_FILES[@]}"; do printf "  lib/%s\n" "$(basename "$file_path")"; done
    for file_path in "${INSTALL_PLUGIN_FILES[@]}"; do printf "  plugin/%s\n" "${file_path#"$cache_plugins"/}"; done
    for file_path in "${INSTALL_PYTHON_FILES[@]}"; do printf "  %s\n" "${file_path#"$stage_root"/}"; done
    for dir_name in "${INSTALL_SHARE_DIRS[@]}"; do printf "  share/kicad/%s/\n" "$dir_name"; done
    echo ""

    if $MODE_CHECK; then
        warn "(dry-run) Installation skipped"
        return
    fi

    for file_path in "${INSTALL_BIN_FILES[@]}"; do
        name=$(basename "$file_path")
        echo "'$file_path' -> '$SYSTEM_BIN_DIR/$name'"
        sudo_atomic_copy "$file_path" "$SYSTEM_BIN_DIR/$name"
    done

    for file_path in "${INSTALL_LIB_FILES[@]}"; do
        name=$(basename "$file_path")
        echo "'$file_path' -> '$SYSTEM_LIB_DIR/$name'"
        sudo_atomic_copy "$file_path" "$SYSTEM_LIB_DIR/$name"
    done

    if [[ ${#INSTALL_PLUGIN_FILES[@]} -gt 0 ]]; then
        run_sudo mkdir -p "$SYSTEM_LIB_DIR/kicad/plugins"
        for file_path in "${INSTALL_PLUGIN_FILES[@]}"; do
            rel="${file_path#"$cache_plugins"/}"
            sudo_atomic_copy "$file_path" "$SYSTEM_LIB_DIR/kicad/plugins/$rel"
        done
    fi

    for file_path in "${INSTALL_PYTHON_FILES[@]}"; do
        rel="${file_path#"$stage_root"/}"
        sudo_atomic_copy "$file_path" "$KICAD_INSTALL_PREFIX/$rel"
    done

    if [[ ${#INSTALL_SHARE_DIRS[@]} -gt 0 ]]; then
        run_sudo mkdir -p "$SYSTEM_SHARE_DIR/kicad"
        for dir_name in "${INSTALL_SHARE_DIRS[@]}"; do
            run_sudo mkdir -p "$SYSTEM_SHARE_DIR/kicad/$dir_name"
            run_sudo cp -a "$cache_share/kicad/$dir_name/." "$SYSTEM_SHARE_DIR/kicad/$dir_name/"
        done
    fi

    if [[ ${#INSTALL_LIB_FILES[@]} -gt 0 || ${#INSTALL_PLUGIN_FILES[@]} -gt 0 ]]; then
        run_sudo ldconfig
    fi

    ok "Installation finished"
}

restore_originals() {
    local version="$1"
    local backup_dir root rel src dst count=0

    backup_dir=$(cache_original_dir "$version")
    root="$backup_dir/root"

    header "Restore original Arch package files for KiCad $version"

    [[ -d "$root" ]] || die "Backup not found: $backup_dir"

    while IFS= read -r -d '' src; do
        rel="${src#"$root"/}"
        dst="/$rel"
        echo "'$src' -> '$dst'"
        sudo_atomic_copy "$src" "$dst"
        ((count+=1))
    done < <(find "$root" \( -type f -o -type l \) -print0 | sort -z)

    [[ $count -gt 0 ]] || die "Backup contains no files"
    run_sudo ldconfig || true
    ok "Restored files: $count"
}

verify_installation() {
    local expected_version="$1"

    header "Verification"

    local cli
    cli=$(command -v kicad-cli 2>/dev/null || true)
    [[ -n "$cli" ]] || cli="$SYSTEM_BIN_DIR/kicad-cli"

    if [[ ! -x "$cli" ]]; then
        warn "kicad-cli not found; skipping functional checks"
        return
    fi
    ok "kicad-cli: $cli"

    local verify_home
    verify_home=$(mktemp -d /tmp/kicad-arch-verify.XXXXXX)
    mkdir -p "$verify_home/config" "$verify_home/cache" "$verify_home/data"

    local cli_version
    cli_version=$(env XDG_CONFIG_HOME="$verify_home/config" \
        XDG_CACHE_HOME="$verify_home/cache" \
        XDG_DATA_HOME="$verify_home/data" \
        "$cli" version 2>&1 | tail -1 || true)

    if [[ "$cli_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
        ok "kicad-cli version: $cli_version"
        if [[ -n "$expected_version" && "$cli_version" != "$expected_version"* ]]; then
            rm -rf "$verify_home"
            die "Expected KiCad $expected_version, got: $cli_version"
        fi
    else
        warn "Could not read kicad-cli version confidently: $cli_version"
    fi

    local bad=0 file_path
    for file_path in "$SYSTEM_BIN_DIR"/*.kiface; do
        [[ -f "$file_path" ]] || continue
        if ! file "$file_path" | grep -q "ELF"; then
            err "Broken kiface: $(basename "$file_path")"
            ((bad+=1))
        fi
    done
    if [[ $bad -eq 0 ]]; then
        ok "All .kiface files are valid ELF files"
    else
        die "$bad damaged .kiface files"
    fi

    local symbol_count=0 footprint_count=0 model_count=0 resource_errors=0
    [[ -d "$SYSTEM_SHARE_DIR/kicad/symbols" ]] \
        && symbol_count=$(find "$SYSTEM_SHARE_DIR/kicad/symbols" -maxdepth 1 -type f -name '*.kicad_sym' | wc -l)
    [[ -d "$SYSTEM_SHARE_DIR/kicad/footprints" ]] \
        && footprint_count=$(find "$SYSTEM_SHARE_DIR/kicad/footprints" -mindepth 1 -maxdepth 1 -type d -name '*.pretty' | wc -l)
    [[ -d "$SYSTEM_SHARE_DIR/kicad/3dmodels" ]] \
        && model_count=$(find "$SYSTEM_SHARE_DIR/kicad/3dmodels" -mindepth 1 -maxdepth 1 -type d -name '*.3dshapes' | wc -l)

    if [[ $symbol_count -gt 50 ]]; then
        ok "Symbol libraries: $symbol_count"
    else
        err "Too few symbol libraries: $symbol_count"
        ((resource_errors+=1))
    fi

    if [[ $footprint_count -gt 50 ]]; then
        ok "Footprint libraries: $footprint_count"
    else
        err "Too few footprint libraries: $footprint_count"
        ((resource_errors+=1))
    fi

    if [[ $model_count -gt 50 ]]; then
        ok "3D model libraries: $model_count"
    else
        err "Too few 3D model libraries: $model_count"
        ((resource_errors+=1))
    fi

    local common_lib
    common_lib=$(find "$SYSTEM_LIB_DIR" -maxdepth 1 -name 'libkicommon.so*' -type f 2>/dev/null | sort -V | tail -1)
    if [[ -n "$common_lib" && -f "$common_lib" ]]; then
        if grep -a -q "$CACHE_DIR" "$common_lib"; then
            err "libkicommon contains a cache path; runtime resources may be wrong"
            ((resource_errors+=1))
        elif grep -a -q "$KICAD_DATA_DIR" "$common_lib"; then
            ok "Runtime data path: $KICAD_DATA_DIR"
        else
            warn "Could not confirm runtime data path in $(basename "$common_lib")"
        fi
    fi

    local tests_dir test_file result
    tests_dir="$PROJECT_DIR/tests/fixtures"
    test_file="$tests_dir/Attiny-test.SchLib"
    if [[ -f "$test_file" ]]; then
        printf "  %-44s " "Altium import (Attiny-test.SchLib)..."
        result=$(env XDG_CONFIG_HOME="$verify_home/config" \
            XDG_CACHE_HOME="$verify_home/cache" \
            XDG_DATA_HOME="$verify_home/data" \
            "$cli" sym upgrade "$test_file" -o /dev/null --force 2>&1) || true
        if echo "$result" | grep -qiE "(error|crash|exception|Unable to convert)"; then
            echo -e "${RED}fail${NC}"
            warn "Output: $(echo "$result" | grep -iE "(error|crash|exception|Unable to convert)" | head -3)"
        else
            echo -e "${GREEN}ok${NC}"
        fi
    fi

    rm -rf "$verify_home"
    [[ $resource_errors -eq 0 ]] || die "KiCad resource verification failed"
    ok "Verification finished"
}

save_cache_meta() {
    local cache_dir="$1" version="$2" hash="$3" patch_dir="$4"
    cat > "$cache_dir/.meta" << EOF
version=$version
patches_hash=$hash
patch_dir=$patch_dir
cache_format=$CACHE_FORMAT_VERSION
platform=arch
install_prefix=$KICAD_INSTALL_PREFIX
install_libdir=$KICAD_INSTALL_LIBDIR
kicad_data=$KICAD_DATA_DIR
kicad_library_data=$KICAD_LIBRARY_DATA_DIR
kicad_docs=$KICAD_DOCS_DIR
kicad_lib=$KICAD_LIB_DIR
kicad_user_plugin=$KICAD_USER_PLUGIN_DIR
source_url_template=$KICAD_SOURCE_URL_TEMPLATE
built=$(date -Iseconds)
builder=$(gcc --version 2>/dev/null | head -1)
jobs=$JOBS
host=$(hostname)
patches=$(list_patches "$patch_dir" | xargs -I{} basename {} | tr '\n' ',')
EOF
}

main() {
    parse_args "$@"
    check_arch_host
    check_not_root

    echo -e "${BOLD}"
    echo "============================================================"
    echo "          KiCad Patch Builder & Installer for Arch"
    echo "============================================================"
    echo -e "${NC}"

    local version
    if [[ -n "$KICAD_VERSION_OVERRIDE" ]]; then
        version="$KICAD_VERSION_OVERRIDE"
        log "Version set explicitly: $version"
    elif $MODE_RESTORE; then
        log "Detecting installed KiCad version for restore..."
        version=$(detect_restore_version)
        [[ -n "$version" ]] || die "KiCad version not detected. Use --version X.X.X --restore"
        ok "Detected KiCad $version"
    else
        version=$(latest_supported_patch_version) || die "No patches/kicad-X.X.X directories found"
        report_default_version_context "$version"
    fi

    if $MODE_RESTORE; then
        restore_originals "$version"
        exit 0
    fi

    local patch_dir
    patch_dir=$(find_patch_dir "$version") || die "Patches for KiCad $version not found"
    ok "Patches: $patch_dir"

    local hash
    hash=$(compute_hash "$patch_dir")
    log "Patch set hash: $hash"

    local cache_install
    cache_install=$(cache_install_dir "$version" "$hash")

    if [[ -d "$cache_install" ]] && ! $MODE_REBUILD; then
        echo ""
        ok "Cache found: $cache_install"
        if [[ -f "$cache_install/.meta" ]]; then
            grep -E "^(built|patches)=" "$cache_install/.meta" | while IFS='=' read -r key value; do
                printf "  %-10s %s\n" "$key:" "$value"
            done
        fi
        echo ""

        if ! $MODE_FROM_CACHE && ! $MODE_CHECK; then
            ask "Use cache? [Y/n]: "
            read -r answer
            [[ "${answer,,}" == "n" ]] && MODE_REBUILD=true
        fi
    fi

    if $MODE_FROM_CACHE && [[ ! -d "$cache_install" ]]; then
        die "Cache not found: $cache_install"
    fi

    if $MODE_CHECK; then
        header "Install plan (dry-run)"
        echo "  KiCad version:  $version"
        echo "  Patches:        $patch_dir"
        echo "  Patch hash:     $hash"
        echo "  Cache:          $cache_install"
        [[ -d "$cache_install" ]] && echo "  Cache status:   ready" || echo "  Cache status:   build needed"
        echo ""

        report_arch_packages
        prepare_patch_check_source "$version"
        apply_patches "$PATCH_CHECK_SRC" "$patch_dir" true

        warn "Dry-run finished. Run without --check to build/install."
        exit 0
    fi

    if $MODE_BUILD_ONLY; then
        log "build-only mode: pacman runtime packages and /usr installation are not changed"
    else
        install_arch_runtime_if_needed "$version"
    fi

    if [[ ! -d "$cache_install" ]] || $MODE_REBUILD; then
        [[ -d "$cache_install" ]] && rm -rf "$cache_install"
        mkdir -p "$cache_install"

        check_build_deps
        prepare_source "$version"
        apply_patches "$SRC_DIR" "$patch_dir" false
        build_kicad "$SRC_DIR" "$cache_install"
        save_cache_meta "$cache_install" "$version" "$hash" "$patch_dir"
    else
        ok "Using cache; rebuild is not needed"
    fi

    if $MODE_BUILD_ONLY; then
        ok "Build saved in cache: $cache_install"
        echo ""
        echo "Install from cache:"
        echo "  ./scripts/build_and_install_arch.sh --version $version --from-cache"
        echo ""
        exit 0
    fi

    local system_kicad
    system_kicad=$(find_system_kicad)
    [[ -n "$system_kicad" ]] || die "System KiCad bin directory not found"
    log "System KiCad bin directory: $system_kicad"

    backup_originals "$version" "$cache_install"
    install_from_cache "$cache_install"
    verify_installation "$version"

    echo ""
    echo -e "${GREEN}${BOLD}============================================================${NC}"
    echo -e "${GREEN}${BOLD}  KiCad $version patches installed on Arch Linux${NC}"
    echo -e "${GREEN}${BOLD}============================================================${NC}"
    echo ""
    echo "Restore:"
    echo "  ./scripts/build_and_install_arch.sh --version $version --restore"
    echo "Cache:"
    echo "  ./scripts/build_and_install_arch.sh --list-cache"
    echo ""
}

main "$@"
