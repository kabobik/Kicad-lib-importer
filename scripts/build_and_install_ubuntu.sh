#!/bin/bash
# ============================================================================
# build_and_install.sh — Применение патчей KiCad, сборка и установка
# ============================================================================
#
# Определяет установленную версию KiCad, находит подходящие патчи,
# собирает и устанавливает поверх системного KiCad. Использует кэш
# собранных артефактов для быстрой повторной установки.
#
# Использование:
#   ./scripts/build_and_install.sh                    # авто-определение версии
#   ./scripts/build_and_install.sh --version 9.0.7    # явная версия
#   ./scripts/build_and_install.sh --check            # dry-run, ничего не меняет
#   ./scripts/build_and_install.sh --from-cache       # только из кэша (без сборки)
#   ./scripts/build_and_install.sh --rebuild          # пересобрать, игнорируя кэш
#   ./scripts/build_and_install.sh --build-only       # собрать в кэш без установки
#   ./scripts/build_and_install.sh --update-libraries # обновить официальные библиотеки KiCad через apt
#   ./scripts/build_and_install.sh -v 10.0.4 --rebuild # мягко обновить KiCad до 10.0.4
#   ./scripts/build_and_install.sh --restore          # откат к оригинальным файлам
#   ./scripts/build_and_install.sh --list-cache       # показать кэш
#   ./scripts/build_and_install.sh --clean-cache      # очистить кэш
#   ./scripts/build_and_install.sh -j 8               # потоки сборки
#
# ============================================================================

set -euo pipefail

# ── Цвета ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

# ── Пути ──────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PATCHES_DIR="$PROJECT_DIR/patches"
CACHE_DIR="${CACHE_DIR:-$PROJECT_DIR/cache}"
SOURCE_CACHE_DIR="${SOURCE_CACHE_DIR:-$CACHE_DIR/sources}"
SRC_DIR="${SRC_DIR:-$PROJECT_DIR/kicad-src}"
KICAD_REPO="${KICAD_REPO:-https://gitlab.com/kicad/code/kicad.git}"
KICAD_SOURCE_URL_TEMPLATE="${KICAD_SOURCE_URL_TEMPLATE:-https://gitlab.com/kicad/code/kicad/-/archive/%VERSION%/kicad-%VERSION%.tar.gz}"
JOBS=$(nproc 2>/dev/null || echo 4)
CACHE_FORMAT_VERSION=5
KICAD_INSTALL_PREFIX="${KICAD_INSTALL_PREFIX:-/usr}"
MULTIARCH="$(dpkg-architecture -qDEB_HOST_MULTIARCH 2>/dev/null || echo x86_64-linux-gnu)"
KICAD_INSTALL_LIBDIR="${KICAD_INSTALL_LIBDIR:-lib/$MULTIARCH}"
KICAD_DATA_DIR="${KICAD_DATA_DIR:-$KICAD_INSTALL_PREFIX/share/kicad}"
KICAD_LIBRARY_DATA_DIR="${KICAD_LIBRARY_DATA_DIR:-$KICAD_DATA_DIR}"
KICAD_DOCS_DIR="${KICAD_DOCS_DIR:-$KICAD_INSTALL_PREFIX/share/doc/kicad}"
KICAD_LIB_DIR="${KICAD_LIB_DIR:-$KICAD_INSTALL_PREFIX/$KICAD_INSTALL_LIBDIR}"
KICAD_USER_PLUGIN_DIR="${KICAD_USER_PLUGIN_DIR:-$KICAD_LIB_DIR/kicad/plugins}"
KICAD_BUILD_PYTHON="${KICAD_BUILD_PYTHON:-/usr/bin/python3}"
KICAD_AUTO_INSTALL_DEPS="${KICAD_AUTO_INSTALL_DEPS:-1}"
KICAD_AUTO_ADD_PPA="${KICAD_AUTO_ADD_PPA:-ask}"
SYSTEM_LIB_DIR="/usr/lib/$MULTIARCH"
SYSTEM_SHARE_DIR="/usr/share"
KICAD_OFFICIAL_LIBRARY_PACKAGES=(kicad-symbols kicad-footprints kicad-templates kicad-packages3d)

# ── Режимы ────────────────────────────────────────────────────────────────
MODE_CHECK=false        # dry-run
MODE_FROM_CACHE=false   # только из кэша
MODE_REBUILD=false      # игнорировать кэш
MODE_RESTORE=false      # откат
MODE_BUILD_ONLY=false   # собрать в кэш без установки
MODE_UPDATE_LIBRARIES=false # обновить official library packages через apt
KICAD_VERSION_OVERRIDE=""
PATCH_CHECK_SRC=""
PATCH_CHECK_TMP=""

cleanup_tmp() {
    [[ -n "${PATCH_CHECK_TMP:-}" && -d "$PATCH_CHECK_TMP" ]] && rm -rf -- "$PATCH_CHECK_TMP"
    return 0
}

trap cleanup_tmp EXIT

# ── Утилиты ───────────────────────────────────────────────────────────────
log()    { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()     { echo -e "${GREEN}[  OK]${NC} $*"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()    { echo -e "${RED}[FAIL]${NC} $*" >&2; }
die()    { err "$*"; exit 1; }
header() { echo -e "\n${BOLD}━━━ $* ━━━${NC}"; }
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

    run_sudo rm -f "$tmp"
    run_sudo cp -aP "$src" "$tmp"
    run_sudo mv -f "$tmp" "$dst"
}

resolve_build_python() {
    local py="$KICAD_BUILD_PYTHON"

    if [[ "$py" != */* ]]; then
        py=$(command -v "$py" 2>/dev/null || true)
    fi

    [[ -n "$py" && -x "$py" ]] || die "Python для сборки не найден: ${KICAD_BUILD_PYTHON:-<empty>}"
    echo "$py"
}

check_wxpython_for_build_python() {
    local py wx_version

    py=$(resolve_build_python)
    KICAD_BUILD_PYTHON="$py"

    if ! wx_version=$("$py" -c 'import wx; print(wx.version())' 2>&1); then
        warn "$wx_version"
        die "Python для CMake не видит wxPython: $py\nУстановите пакет python3-wxgtk4.0 или задайте KICAD_BUILD_PYTHON=/usr/bin/python3"
    fi

    ok "wxPython для CMake: $py ($wx_version)"
}

auto_install_deps_enabled() {
    case "${KICAD_AUTO_INSTALL_DEPS,,}" in
        0|false|no|n|off) return 1 ;;
        *) return 0 ;;
    esac
}

auto_add_ppa_answer() {
    case "${KICAD_AUTO_ADD_PPA,,}" in
        1|true|yes|y|on) echo "y" ;;
        0|false|no|n|off) echo "n" ;;
        *) echo "ask" ;;
    esac
}

kicad_release_ppa_name() {
    local version="$1" major minor rest

    IFS='.' read -r major minor rest <<< "$version"
    [[ "$major" =~ ^[0-9]+$ && "$minor" =~ ^[0-9]+$ ]] || return 1

    echo "ppa:kicad/kicad-${major}.${minor}-releases"
}

kicad_release_ppa_configured() {
    local version="$1" major minor rest ppa_path

    IFS='.' read -r major minor rest <<< "$version"
    [[ "$major" =~ ^[0-9]+$ && "$minor" =~ ^[0-9]+$ ]] || return 1

    ppa_path="kicad/kicad-${major}.${minor}-releases"
    grep -Rqs "$ppa_path" /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null
}

ensure_add_apt_repository() {
    if command -v add-apt-repository >/dev/null 2>&1; then
        return
    fi

    log "Устанавливаю software-properties-common для add-apt-repository..."
    run_sudo apt-get update -qq
    run_sudo apt-get install -y software-properties-common
}

offer_release_ppa_if_needed() {
    local version="$1" apt_ver ppa answer

    apt_ver=$(apt_version_for_package kicad "$version")
    if [[ -n "$apt_ver" ]]; then
        ok "apt видит KiCad $version: $apt_ver"
        return 0
    fi

    ppa=$(kicad_release_ppa_name "$version") || {
        warn "Не могу вывести имя KiCad release PPA из версии: $version"
        return 0
    }

    warn "apt не видит пакеты KiCad $version."
    warn "Без release PPA apt останется на другой ветке и будущий apt upgrade может перетереть staged-сборку."

    if kicad_release_ppa_configured "$version"; then
        warn "$ppa уже подключён, но apt всё равно не видит KiCad $version."
        warn "Продолжаю без изменения PPA."
        return 0
    fi

    answer=$(auto_add_ppa_answer)
    if [[ "$answer" == "ask" ]]; then
        if [[ -t 0 ]]; then
            ask "Добавить $ppa и выполнить apt-get update? [Y/n]: "
            read -r answer
            [[ -z "$answer" ]] && answer="y"
        else
            warn "Неинтерактивный запуск: $ppa не добавлен."
            warn "Для авто-добавления задайте KICAD_AUTO_ADD_PPA=1."
            return 0
        fi
    fi

    if [[ "${answer,,}" == "n" || "${answer,,}" == "no" ]]; then
        warn "$ppa не добавлен. Долгосрочной гарантии от перезаписи apt-пакетами нет."
        return 0
    fi

    ensure_add_apt_repository
    log "Добавляю $ppa..."
    run_sudo add-apt-repository -y "$ppa"
    log "Обновляю apt metadata..."
    run_sudo apt-get update

    apt_ver=$(apt_version_for_package kicad "$version")
    if [[ -n "$apt_ver" ]]; then
        ok "apt теперь видит KiCad $version: $apt_ver"
    else
        warn "$ppa добавлен, но KiCad $version всё ещё не найден в apt."
    fi
}

# ── Помощь ────────────────────────────────────────────────────────────────
show_help() {
    cat << 'EOF'
┌─────────────────────────────────────────────────────────────────────────┐
│           build_and_install.sh — KiCad patch builder & installer        │
└─────────────────────────────────────────────────────────────────────────┘

  Определяет версию установленного KiCad, находит патчи, собирает из
  исходников и устанавливает поверх системного KiCad.
  При повторном запуске с теми же патчами использует кэш (секунды вместо часов).

ИСПОЛЬЗОВАНИЕ:
  ./scripts/build_and_install.sh [ОПЦИИ]

ОПЦИИ:
  -v, --version X.X.X  Явно задать версию KiCad (по умолчанию: авто)
  --check              Dry-run: показать план, ничего не менять
  --from-cache         Установить из кэша без пересборки
  --rebuild            Принудительная пересборка (игнорировать кэш)
  --build-only         Собрать staged-кэш без установки в систему
  --update-libraries   Обновить official library packages KiCad через apt
  --restore            Откат к оригинальным системным файлам
  --list-cache         Показать доступные кэшированные сборки
  --clean-cache        Удалить все кэшированные сборки
  -j, --jobs N         Потоки сборки (по умолчанию: все ядра)
  -h, --help           Эта справка

ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ:
  KICAD_REPO   URL репозитория (по умолчанию: gitlab.com/kicad/code/kicad.git)
  SRC_DIR      Путь к исходникам KiCad (по умолчанию: ./kicad-src/)
  CACHE_DIR    Путь к кэшу (по умолчанию: ./cache/)
  SOURCE_CACHE_DIR
               Путь к кэшу исходных архивов (по умолчанию: ./cache/sources/)
  KICAD_SOURCE_URL_TEMPLATE
               URL-шаблон архива, %VERSION% заменяется версией KiCad
  KICAD_INSTALL_PREFIX
               Runtime prefix KiCad (по умолчанию: /usr)
  KICAD_INSTALL_LIBDIR
               Runtime libdir относительно prefix (по умолчанию: lib/<multiarch>)
  KICAD_BUILD_PYTHON
               Python для CMake/wxPython (по умолчанию: /usr/bin/python3)
  KICAD_AUTO_INSTALL_DEPS
               Автоустановка build-deps через apt: 1/0 (по умолчанию: 1)
  KICAD_AUTO_ADD_PPA
               Добавление KiCad release PPA: ask/1/0 (по умолчанию: ask)

ПРИМЕРЫ:
  ./scripts/build_and_install.sh --check         # что будет установлено?
  ./scripts/build_and_install.sh                 # полная сборка + установка
  ./scripts/build_and_install.sh --from-cache    # быстрая установка из кэша
  ./scripts/build_and_install.sh -v 10.0.4 --check
                                                # проверить патчи на чистой 10.0.4
  ./scripts/build_and_install.sh -v 10.0.4 --build-only --rebuild
                                                # собрать 10.0.4 в кэш без sudo
  ./scripts/build_and_install.sh -v 10.0.4 --from-cache --update-libraries
                                                # обновить библиотеки и поставить кэш
  ./scripts/build_and_install.sh -v 10.0.4 --rebuild
                                                # собрать и установить 10.0.4 с патчами
  ./scripts/build_and_install.sh --restore       # откат
  ./scripts/build_and_install.sh -v 9.0.7 -j 16 # явная версия, 16 потоков

EOF
}

# ── Установка базового KiCad из apt (если не установлен) ─────────────────
install_kicad_base_if_needed() {
    local version="$1"

    # Проверяем: есть ли уже установленный KiCad нужной версии
    local installed
    installed=$(dpkg-query -W -f='${Version}' kicad 2>/dev/null | sed 's/[+~].*//' | sed 's/-[0-9]*$//' || true)

    if [[ "$installed" == "$version" ]]; then
        ok "KiCad $version уже установлен"
        return
    fi

    if [[ -n "$installed" ]]; then
        warn "Установлен KiCad $installed, целевая сборка $version"
        warn "Базовый пакет apt не меняю: версия будет обновлена staged-сборкой из исходников."
        return
    else
        warn "KiCad не установлен"
    fi

    # Найти подходящую apt-версию
    local apt_ver
    apt_ver=$(apt_version_for_package kicad "$version")

    if [[ -z "$apt_ver" ]]; then
        warn "В apt нет точной версии $version. Устанавливаем кандидата..."
        apt_ver=""  # apt сам выберет
    fi

    log "Устанавливаю KiCad из apt (версия: ${apt_ver:-авто})..."

    local pkg_spec="kicad"
    [[ -n "$apt_ver" ]] && pkg_spec="kicad=${apt_ver}"

    run_sudo apt-get install -y \
        "$pkg_spec" \
        kicad-footprints \
        kicad-symbols \
        kicad-templates \
        kicad-packages3d \
        2>&1 | grep -E "^(Получение|Get|Распаковка|Unpacking|Настройка|Setting up|E:|Err:)" | head -60

    local new_installed
    new_installed=$(dpkg-query -W -f='${Version}' kicad 2>/dev/null || true)
    ok "KiCad установлен: $new_installed"
}

apt_version_for_package() {
    local pkg="$1" version="$2"

    apt-cache madison "$pkg" 2>/dev/null \
        | awk -F'|' '{gsub(/ /,"",$2); print $2}' \
        | grep "^${version}" \
        | head -1 \
        || true
}

installed_package_version() {
    local pkg="$1"

    dpkg-query -W -f='${Version}' "$pkg" 2>/dev/null || true
}

report_library_packages() {
    local version="$1"

    header "Official KiCad library packages"
    for pkg in "${KICAD_OFFICIAL_LIBRARY_PACKAGES[@]}"; do
        local installed available
        installed=$(installed_package_version "$pkg")
        available=$(apt_version_for_package "$pkg" "$version")

        if [[ -n "$available" ]]; then
            printf "  %-20s installed=%-24s target=%s\n" "$pkg" "${installed:-нет}" "$available"
        else
            printf "  %-20s installed=%-24s target=%s\n" "$pkg" "${installed:-нет}" "нет в apt для $version"
        fi
    done
    echo ""
}

update_library_packages_if_requested() {
    local version="$1"

    if ! $MODE_UPDATE_LIBRARIES; then
        return
    fi

    report_library_packages "$version"

    local specs=()
    for pkg in "${KICAD_OFFICIAL_LIBRARY_PACKAGES[@]}"; do
        local apt_ver
        apt_ver=$(apt_version_for_package "$pkg" "$version")

        if [[ -n "$apt_ver" ]]; then
            specs+=("$pkg=$apt_ver")
        else
            warn "Для $pkg нет apt-версии $version; пакет пропущен"
        fi
    done

    if [[ ${#specs[@]} -eq 0 ]]; then
        warn "Нет доступных apt library packages для KiCad $version"
        warn "Продолжаю установку собранного KiCad без обновления official library packages."
        return 0
    fi

    log "Обновляю official library packages через apt:"
    for spec in "${specs[@]}"; do
        echo "    $spec"
    done

    run_sudo apt-get install -y "${specs[@]}"
    ok "Official library packages обновлены"
}

# ── Проверка что не запущен как root ────────────────────────────────────
check_not_root() {
    if [[ $EUID -eq 0 ]]; then
        warn "Скрипт запущен от root. Запускайте без sudo:"
        warn "  ./scripts/build_and_install.sh"
        warn "sudo будет запрошен только для шага установки."
        echo ""
        ask "Продолжить всё равно? [y/N]: "
        read -r answer
        [[ "${answer,,}" == "y" ]] || exit 1
    fi
}

# ── Парсинг аргументов ────────────────────────────────────────────────────
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -v|--version)  KICAD_VERSION_OVERRIDE="$2"; shift 2 ;;
            --check)       MODE_CHECK=true; shift ;;
            --from-cache)  MODE_FROM_CACHE=true; shift ;;
            --rebuild)     MODE_REBUILD=true; shift ;;
            --build-only)  MODE_BUILD_ONLY=true; shift ;;
            --update-libraries) MODE_UPDATE_LIBRARIES=true; shift ;;
            --restore)     MODE_RESTORE=true; shift ;;
            --list-cache)  list_cache; exit 0 ;;
            --clean-cache) clean_cache; exit 0 ;;
            -j|--jobs)     JOBS="$2"; shift 2 ;;
            -h|--help)     show_help; exit 0 ;;
            *) die "Неизвестный аргумент: $1. Используйте --help." ;;
        esac
    done
}

# ── Определение версии KiCad ──────────────────────────────────────────────
detect_dpkg_kicad_version() {
    if dpkg -s kicad &>/dev/null 2>&1; then
        local ver
        ver=$(dpkg-query -W -f='${Version}' kicad 2>/dev/null | sed 's/[+~].*//' | sed 's/-[0-9]*$//')
        [[ -n "$ver" ]] && echo "$ver" && return
    fi

    echo ""
}

detect_binary_kicad_version() {
    if command -v kicad-cli &>/dev/null; then
        local ver
        ver=$(kicad-cli version 2>/dev/null | grep -oP '\d+\.\d+\.\d+' | head -1)
        [[ -n "$ver" ]] && echo "$ver" && return
    fi

    if command -v kicad &>/dev/null; then
        local ver
        ver=$(kicad --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+' | head -1)
        [[ -n "$ver" ]] && echo "$ver" && return
    fi

    local bin
    bin=$(find /usr/bin /usr/local/bin -name "kicad" -type f 2>/dev/null | head -1)
    if [[ -n "$bin" ]]; then
        local ver
        ver=$("$bin" --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+' | head -1)
        [[ -n "$ver" ]] && echo "$ver" && return
    fi

    echo ""
}

detect_kicad_version() {
    local ver
    ver=$(detect_binary_kicad_version)
    [[ -n "$ver" ]] && echo "$ver" && return

    detect_dpkg_kicad_version
}

detect_restore_version() {
    local ver
    ver=$(detect_dpkg_kicad_version)
    [[ -n "$ver" ]] && echo "$ver" && return

    detect_binary_kicad_version
}

# ── Поиск патчей для версии ───────────────────────────────────────────────
find_patch_dir() {
    local version="$1"
    local exact="$PATCHES_DIR/kicad-$version"

    if [[ -d "$exact" ]] && patch_dir_has_patches "$exact"; then
        echo "$exact"
        return 0
    fi

    # Ищем ближайшую версию
    local available=()
    while IFS= read -r -d '' d; do
        if patch_dir_has_patches "$d"; then
            available+=("$(basename "$d" | sed 's/kicad-//')")
        fi
    done < <(find "$PATCHES_DIR" -maxdepth 1 -name "kicad-*" -type d -print0 | sort -z)

    if [[ ${#available[@]} -eq 0 ]]; then
        return 1
    fi

    warn "Патчей для KiCad $version нет. Доступные версии:"
    for v in "${available[@]}"; do
        echo "    • $v"
    done
    echo ""
    ask "Использовать патчи от другой версии? [введите версию или Enter для отмены]: "
    read -r choice
    [[ -z "$choice" ]] && return 1

    local fallback="$PATCHES_DIR/kicad-$choice"
    [[ -d "$fallback" ]] || die "Версия $choice не найдена в $PATCHES_DIR"
    warn "Используем патчи от $choice для KiCad $version (совместимость не гарантирована!)"
    echo "$fallback"
}

# ── Список патчей в директории ────────────────────────────────────────────
list_patches() {
    local patch_dir="$1"
    local series_file="$patch_dir/series"

    if [[ -f "$series_file" ]]; then
        local entry

        while IFS= read -r entry; do
            entry="${entry%%#*}"
            entry="${entry#"${entry%%[![:space:]]*}"}"
            entry="${entry%"${entry##*[![:space:]]}"}"

            [[ -z "$entry" ]] && continue

            if [[ "$entry" = /* ]]; then
                printf '%s\n' "$entry"
            else
                printf '%s/%s\n' "$patch_dir" "$entry"
            fi
        done < "$series_file"
    else
        find "$patch_dir" -maxdepth 1 \( -name "*.patch" -o -name "*.diff" \) | sort
    fi
}

patch_dir_has_patches() {
    local patch_dir="$1"
    local patch_file
    local found=false

    while IFS= read -r patch_file; do
        [[ -n "$patch_file" ]] && found=true
    done < <(list_patches "$patch_dir")

    $found
}

# ── Хэш набора патчей ─────────────────────────────────────────────────────
compute_hash() {
    local patch_dir="$1"
    # Хэш от содержимого всех патчей + их порядка + формата кэша.
    # Старый формат собирался с CMAKE_INSTALL_PREFIX=cache/... и ломал
    # runtime-пути к /usr/share/kicad.
    {
        echo "cache_format=$CACHE_FORMAT_VERSION"
        echo "install_prefix=$KICAD_INSTALL_PREFIX"
        echo "install_libdir=$KICAD_INSTALL_LIBDIR"
        echo "kicad_data=$KICAD_DATA_DIR"
        echo "kicad_library_data=$KICAD_LIBRARY_DATA_DIR"
        echo "kicad_docs=$KICAD_DOCS_DIR"
        echo "kicad_lib=$KICAD_LIB_DIR"
        echo "kicad_user_plugin=$KICAD_USER_PLUGIN_DIR"
        echo "source_url_template=$KICAD_SOURCE_URL_TEMPLATE"
        list_patches "$patch_dir" | while IFS= read -r patch_file; do
            patch_name="${patch_file#$patch_dir/}"
            echo "patch=$patch_name"
            cat "$patch_file"
        done
    } | md5sum | awk '{print $1}' | head -c 12
}

# ── Путь к кэшу ───────────────────────────────────────────────────────────
cache_install_dir() {
    local version="$1" hash="$2"
    echo "$CACHE_DIR/kicad-${version}-${hash}"
}

cache_original_dir() {
    local version="$1"
    echo "$CACHE_DIR/kicad-${version}-original"
}

# ── Управление кэшем ──────────────────────────────────────────────────────
list_cache() {
    header "Кэшированные сборки ($CACHE_DIR)"
    local found=false

    for meta in "$CACHE_DIR"/kicad-*/.meta; do
        [[ -f "$meta" ]] || continue
        found=true
        local dir
        dir="$(dirname "$meta")"
        local built patches_hash size
        built=$(grep '^built=' "$meta" | cut -d= -f2-)
        patches_hash=$(grep '^patches_hash=' "$meta" | cut -d= -f2)
        size=$(du -sh "$dir" 2>/dev/null | cut -f1)
        printf "  %-35s  %s  %s\n" "$(basename "$dir")" "${built:-?}" "${size:-?}"
    done

    # Бэкапы оригиналов
    echo ""
    for d in "$CACHE_DIR"/kicad-*-original; do
        [[ -d "$d" ]] || continue
        found=true
        printf "  %-35s  (оригинальные системные файлы)\n" "$(basename "$d")"
    done

    $found || echo "  (кэш пуст)"
}

clean_cache() {
    header "Очистка кэша"
    local removed=0
    for d in "$CACHE_DIR"/kicad-*; do
        [[ -d "$d" ]] && [[ "$d" != *"-original" ]] || continue
        rm -rf "$d"
        ((removed++))
        ok "Удалён: $(basename "$d")"
    done
    [[ $removed -eq 0 ]] && echo "  (нечего удалять)" || ok "Удалено сборок: $removed"
}

# ── Определение пути установки системного KiCad ───────────────────────────
find_system_kicad() {
    local bin
    bin=$(command -v kicad 2>/dev/null || true)

    if [[ -n "$bin" && -f "$bin" ]]; then
        dirname "$bin"
        return
    fi

    # Ищем директорию с .kiface файлами, исключая backup/cache/original папки
    local kiface
    kiface=$(find /usr -maxdepth 6 \
        \( -name "eeschema.kiface" -o -name "_eeschema.kiface" \) \
        -not -path "*backup*" \
        -not -path "*original*" \
        -not -path "*cache*" \
        2>/dev/null | head -1)
    [[ -n "$kiface" ]] && dirname "$kiface" && return

    # fallback: стандартные пути (без backup-вариантов)
    for p in /usr/lib/x86_64-linux-gnu/kicad /usr/lib/kicad /usr/local/lib/kicad; do
        [[ -d "$p" ]] && [[ "$p" != *backup* ]] && echo "$p" && return
    done

    echo ""
}

# ── Проверка и установка зависимостей сборки ─────────────────────────────
check_build_deps() {
    # Инструменты сборки (проверяем по команде)
    local -A tool_pkgs=(
        [cmake]=cmake
        [ninja]=ninja-build
        [g++]=g++
        [git]=git
        [patch]=patch
        [python3]=python3
        [curl]=curl
        [tar]=tar
    )

    # Dev-библиотеки KiCad (проверяем через dpkg)
    local dev_pkgs=(
        libprotobuf-dev
        protobuf-compiler
        libwxgtk3.2-dev
        libwxgtk-webview3.2-dev
        libboost-all-dev
        libcairo2-dev
        libglew-dev
        libglu1-mesa-dev
        libcurl4-openssl-dev
        libssl-dev
        zlib1g-dev
        libpoppler-dev
        libpoppler-cpp-dev
        libpoppler-glib-dev
        libfontconfig-dev
        libfreetype-dev
        libharfbuzz-dev
        libglm-dev
        libspnav-dev
        python3-dev
        python3-wxgtk4.0
        swig
        libocct-modeling-algorithms-dev
        libocct-visualization-dev
        libocct-data-exchange-dev
        libngspice0-dev
        gettext
    )

    local missing_tools=()
    local missing_libs=()

    # Проверяем инструменты
    for cmd in "${!tool_pkgs[@]}"; do
        command -v "$cmd" &>/dev/null || missing_tools+=("${tool_pkgs[$cmd]}")
    done

    # Проверяем dev-библиотеки через dpkg
    for pkg in "${dev_pkgs[@]}"; do
        dpkg -s "$pkg" &>/dev/null 2>&1 || missing_libs+=("$pkg")
    done

    local all_missing=("${missing_tools[@]}" "${missing_libs[@]}")
    local unique_missing=()
    local seen=" "
    for p in "${all_missing[@]}"; do
        [[ "$seen" == *" $p "* ]] && continue
        seen+="$p "
        unique_missing+=("$p")
    done
    all_missing=("${unique_missing[@]}")

    if [[ ${#all_missing[@]} -eq 0 ]]; then
        ok "Все зависимости установлены"
        check_wxpython_for_build_python
        return
    fi

    warn "Отсутствуют пакеты (${#all_missing[@]}):"
    for p in "${all_missing[@]}"; do
        echo "    • $p"
    done
    echo ""

    if ! auto_install_deps_enabled; then
        die "Установите зависимости вручную:\n  sudo apt install ${all_missing[*]}"
    fi

    log "Автоматически устанавливаю зависимости через apt..."
    run_sudo apt-get update -qq

    local apt_log apt_status
    apt_log=$(mktemp /tmp/kicad-build-deps.XXXXXX.log)

    set +e
    run_sudo apt-get install -y --fix-missing "${all_missing[@]}" >"$apt_log" 2>&1
    apt_status=$?
    set -e

    grep -E "^(Get|Получение|Unpacking|Распаковка|Setting up|Настройка|E:|Err:)" "$apt_log" | head -80 || true
    if [[ $apt_status -ne 0 ]]; then
        tail -80 "$apt_log" >&2 || true
        rm -f "$apt_log"
        die "Не удалось установить зависимости:\n  sudo apt install ${all_missing[*]}"
    fi
    rm -f "$apt_log"

    ok "Зависимости установлены"
    check_wxpython_for_build_python
}

# ── Подготовка исходников ─────────────────────────────────────────────────
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

    [[ -n "$src" ]] || die "SRC_DIR пустой"
    [[ "$src" != "/" ]] || die "Нельзя использовать SRC_DIR=/"
    [[ "$src" != "$PROJECT_DIR" ]] || die "Нельзя удалять PROJECT_DIR как SRC_DIR"

    case "$src" in
        "$PROJECT_DIR"/kicad-src|"$PROJECT_DIR"/kicad-src-*) ;;
        *)
            die "SRC_DIR вне ожидаемой области проекта: $src\nЗадайте SRC_DIR внутри $PROJECT_DIR или подготовьте исходники вручную."
            ;;
    esac
}

download_source_archive() {
    local version="$1"
    local archive
    archive=$(source_archive_path "$version")

    mkdir -p "$SOURCE_CACHE_DIR"

    if [[ -f "$archive" ]] && tar -tzf "$archive" >/dev/null 2>&1; then
        ok "Архив исходников уже есть: $archive"
        return
    fi

    local url
    url=$(source_archive_url "$version")
    log "Скачиваю исходники KiCad $version:"
    log "$url"

    rm -f "$archive.tmp"
    curl -L --fail --show-error --progress-bar --output "$archive.tmp" "$url"
    tar -tzf "$archive.tmp" >/dev/null 2>&1 || die "Скачанный архив повреждён: $archive.tmp"
    mv -f "$archive.tmp" "$archive"
    ok "Архив скачан: $archive"
}

prepare_source() {
    local version="$1"

    header "Исходники KiCad $version"

    assert_safe_source_dir "$SRC_DIR"

    local archive tmp_dir extracted
    archive=$(source_archive_path "$version")
    download_source_archive "$version"
    tmp_dir=$(mktemp -d "$PROJECT_DIR/.source-unpack.XXXXXX")

    log "Распаковка архива..."
    tar -xzf "$archive" -C "$tmp_dir"

    extracted="$tmp_dir/kicad-$version"
    [[ -d "$extracted" ]] || die "В архиве не найдена директория kicad-$version"

    if [[ -d "$SRC_DIR" ]]; then
        warn "Удаляю старые исходники: $SRC_DIR"
        rm -rf -- "$SRC_DIR"
    fi

    mv "$extracted" "$SRC_DIR"
    rm -rf -- "$tmp_dir"
    printf "%s\n" "$version" > "$SRC_DIR/.kicad_source_version"
    ok "Исходники готовы: $SRC_DIR"
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
        log "Dry-run использует текущие исходники: $check_src"
        PATCH_CHECK_SRC="$check_src"
        PATCH_CHECK_TMP=""
        return
    fi

    header "Исходники для dry-run KiCad $version"
    download_source_archive "$version"

    PATCH_CHECK_TMP=$(mktemp -d /tmp/kicad-patch-check.XXXXXX)
    log "Распаковка во временный каталог: $PATCH_CHECK_TMP"
    tar -xzf "$(source_archive_path "$version")" -C "$PATCH_CHECK_TMP"

    PATCH_CHECK_SRC="$PATCH_CHECK_TMP/kicad-$version"
    [[ -d "$PATCH_CHECK_SRC" ]] || die "В архиве не найдена директория kicad-$version"
}

# ── Применение патчей ─────────────────────────────────────────────────────
apply_patches() {
    local src="$1" patch_dir="$2" dry="${3:-false}"

    header "Патчи $(basename "$patch_dir")"

    local patches=()
    while IFS= read -r p; do patches+=("$p"); done < <(list_patches "$patch_dir")

    [[ ${#patches[@]} -eq 0 ]] && die "Нет патчей в $patch_dir"

    log "Найдено патчей: ${#patches[@]}"
    echo ""

    for p in "${patches[@]}"; do
        local name
        name=$(basename "$p")
        printf "  ${DIM}%-50s${NC} " "$name"

        local check_args=(-p1 --directory="$src" --dry-run)
        local apply_args=(-p1 --directory="$src" --forward)

        if patch "${check_args[@]}" < "$p" &>/dev/null 2>&1; then
            if $dry; then
                echo -e "${GREEN}✓${NC}"
            elif patch "${apply_args[@]}" < "$p" &>/dev/null 2>&1; then
                echo -e "${GREEN}✓${NC}"
            else
                echo -e "${RED}✗${NC}"
                patch "${apply_args[@]}" < "$p" 2>&1 | tail -10 || true
                die "Патч прошёл dry-run, но не применился: $name"
            fi
        elif patch -R -p1 --directory="$src" --dry-run < "$p" &>/dev/null 2>&1; then
            echo -e "${YELLOW}уже применён${NC}"
        elif $dry; then
            echo -e "${RED}✗${NC}"
            warn "Патч несовместим: $name"
            warn "Возможно, версия KiCad не совпадает."
        else
            echo -e "${RED}✗${NC}"
            patch -p1 --directory="$src" --dry-run < "$p" 2>&1 | tail -10 || true
            die "Патч не применился: $name"
        fi
    done
    echo ""
}

# ── Сборка KiCad ─────────────────────────────────────────────────────────
build_kicad() {
    local src="$1" stage_dir="$2"

    header "Сборка KiCad"
    log "Источник:  $src"
    log "Prefix:    $KICAD_INSTALL_PREFIX"
    log "Data:      $KICAD_DATA_DIR"
    log "Libdir:    $KICAD_LIB_DIR"
    log "Staging:   $stage_dir"
    log "Потоки:    $JOBS"
    echo ""

    local build_dir="$src/build"
    local configure_log="$build_dir/configure.log"
    local build_log="$build_dir/build.log"
    local install_log="$build_dir/install.log"
    local build_python

    build_python=$(resolve_build_python)

    rm -rf "$build_dir"
    mkdir -p "$build_dir"

    log "Конфигурация CMake..."
    log "Python:    $build_python"
    set +e
    cmake -S "$src" -B "$build_dir" \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX="$KICAD_INSTALL_PREFIX" \
        -DCMAKE_INSTALL_LIBDIR="$KICAD_INSTALL_LIBDIR" \
        -DPYTHON_EXECUTABLE="$build_python" \
        -DPython_EXECUTABLE="$build_python" \
        -DPython3_EXECUTABLE="$build_python" \
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
    [[ $cmake_status -eq 0 ]] || { tail -120 "$configure_log"; die "CMake configure failed. Лог: $configure_log"; }
    ok "CMake настроен"

    log "Сборка (это займёт 30-60 минут)..."
    local start=$SECONDS
    set +e
    cmake --build "$build_dir" -j "$JOBS" 2>&1 | \
        tee "$build_log" | \
        awk '/^\[/ { if( NR % 80 == 0 ) print } /FAILED|error:|undefined reference|fatal:/ { print }'
    local build_status=${PIPESTATUS[0]}
    set -e
    [[ $build_status -eq 0 ]] || { tail -160 "$build_log"; die "Сборка не удалась. Лог: $build_log"; }
    local elapsed=$(( SECONDS - start ))
    ok "Сборка завершена за $(( elapsed / 60 ))м $(( elapsed % 60 ))с"

    log "Установка в staging-кэш..."
    rm -rf "$stage_dir$KICAD_INSTALL_PREFIX"
    set +e
    DESTDIR="$stage_dir" cmake --install "$build_dir" 2>&1 | tee "$install_log" | grep -v "^-- Up-to-date"
    local install_status=${PIPESTATUS[0]}
    set -e
    [[ $install_status -eq 0 ]] || { tail -120 "$install_log"; die "Staging install failed. Лог: $install_log"; }
    ok "Установлено в: $stage_dir$KICAD_INSTALL_PREFIX"

    log "Stripping символов (как в релизных пакетах Ubuntu)..."
    while IFS= read -r -d '' f; do
        file "$f" | grep -q "ELF" && strip --strip-unneeded "$f"
    done < <(find "$stage_dir$KICAD_INSTALL_PREFIX" -type f \( -name "*.kiface" -o -name "*.so" -o -name "*.so.*" \
        -o -name "kicad" -o -name "kicad-cli" -o -name "eeschema" -o -name "pcbnew" \
        -o -name "gerbview" -o -name "pcb_calculator" -o -name "pl_editor" \
        -o -name "bitmap2component" \) -print0)
    ok "Символы удалены (размер файлов уменьшен)"
}

# ── Резервная копия системных файлов KiCad ──────────────────────────
backup_originals() {
    local version="$1" system_kicad="$2" cache_install="${3:-}"
    local backup_dir
    backup_dir=$(cache_original_dir "$version")

    if [[ -d "$backup_dir" ]]; then
        ok "Резервная копия уже есть: $backup_dir"
        log "Досохраняю отсутствующие resource/plugin файлы, если они нужны..."
    else
        header "Резервная копия оригинальных файлов KiCad"
    fi

    mkdir -p "$backup_dir/bin" "$backup_dir/lib" "$backup_dir/plugins" \
             "$backup_dir/python" "$backup_dir/share/kicad"

    local stage_root cache_bin cache_lib cache_plugins cache_python cache_share

    if [[ -n "$cache_install" ]]; then
        stage_root="$cache_install$KICAD_INSTALL_PREFIX"
        cache_bin="$stage_root/bin"
        cache_lib="$stage_root/$KICAD_INSTALL_LIBDIR"
        [[ -d "$cache_lib" ]] || cache_lib="$stage_root/lib"
        cache_plugins="$cache_lib/kicad/plugins"
        cache_python="$stage_root/lib/python3/dist-packages"
        cache_share="$stage_root/share"
    else
        cache_bin=$(find "$CACHE_DIR" -maxdepth 3 -path "*/bin" -not -path "*original*" 2>/dev/null | head -1)
        cache_lib=$(find "$CACHE_DIR" -maxdepth 4 -path "*/$KICAD_INSTALL_LIBDIR" -not -path "*original*" 2>/dev/null | head -1)
        [[ -n "$cache_lib" ]] || cache_lib=$(find "$CACHE_DIR" -maxdepth 3 -path "*/lib" -not -path "*original*" 2>/dev/null | head -1)
        cache_plugins="$cache_lib/kicad/plugins"
        cache_python="$(dirname "$cache_lib")/python3/dist-packages"
        cache_share="$(dirname "$cache_lib")/share"
    fi

    # Бэкапим бинари из system_kicad (только то что есть в нашем кэше)
    if [[ -n "$cache_bin" && -d "$cache_bin" ]]; then
        log "Бэкап бинарей из: $system_kicad"
        for f in "$cache_bin"/*; do
            local name; name=$(basename "$f")
            [[ -f "$system_kicad/$name" && ! -e "$backup_dir/bin/$name" && ! -L "$backup_dir/bin/$name" ]] \
                && cp -v "$system_kicad/$name" "$backup_dir/bin/"
        done
    fi

    # Бэкапим shared libs (libkigal, libkicommon, libkiapi, libkicad_3dsg)
    log "Бэкап shared libs из: $SYSTEM_LIB_DIR"
    if [[ -n "$cache_lib" && -d "$cache_lib" ]]; then
        for f in "$cache_lib"/libki*.so*; do
            [[ -e "$f" || -L "$f" ]] || continue
            local name; name=$(basename "$f")
            [[ ( -e "$SYSTEM_LIB_DIR/$name" || -L "$SYSTEM_LIB_DIR/$name" )
                    && ! -e "$backup_dir/lib/$name" && ! -L "$backup_dir/lib/$name" ]] \
                && cp -av "$SYSTEM_LIB_DIR/$name" "$backup_dir/lib/"
        done
    fi

    if [[ -n "$cache_plugins" && -d "$cache_plugins" ]]; then
        log "Бэкап KiCad plugins из: $SYSTEM_LIB_DIR/kicad/plugins"
        while IFS= read -r -d '' f; do
            local rel="${f#$cache_plugins/}"
            local sys_file="$SYSTEM_LIB_DIR/kicad/plugins/$rel"
            local dst="$backup_dir/plugins/$rel"
            [[ -e "$sys_file" || -L "$sys_file" ]] || continue
            mkdir -p "$(dirname "$dst")"
            [[ ! -e "$dst" && ! -L "$dst" ]] && cp -av "$sys_file" "$dst"
        done < <(find "$cache_plugins" -type f -print0)
    fi

    if [[ -n "$cache_python" && -d "$cache_python" ]]; then
        log "Бэкап Python-модулей KiCad"
        for f in "$cache_python"/*; do
            [[ -e "$f" ]] || continue
            local name; name=$(basename "$f")
            local sys_file="/usr/lib/python3/dist-packages/$name"
            [[ -e "$sys_file" && ! -e "$backup_dir/python/$name" && ! -L "$backup_dir/python/$name" ]] \
                && cp -av "$sys_file" "$backup_dir/python/"
        done
    fi

    if [[ -n "$cache_share" && -d "$cache_share/kicad" ]]; then
        log "Бэкап KiCad share resources"
        local share_dirs=(internat resources schemas scripting template plugins)
        for d in "${share_dirs[@]}"; do
            [[ -d "$cache_share/kicad/$d" ]] || continue
            [[ -d "$SYSTEM_SHARE_DIR/kicad/$d" ]] || continue
            [[ -d "$backup_dir/share/kicad/$d" ]] && continue
            cp -av "$SYSTEM_SHARE_DIR/kicad/$d" "$backup_dir/share/kicad/"
        done
    fi

    local count
    count=$(find "$backup_dir" -type f | wc -l)
    ok "Сохранено $count файлов ($(du -sh "$backup_dir" | cut -f1))"
}

# ── Установка из кэша в систему ───────────────────────────────────────────
install_from_cache() {
    local cache_install="$1" system_kicad="$2"
    local stage_root="$cache_install$KICAD_INSTALL_PREFIX"

    header "Установка в систему"

    if [[ ! -d "$stage_root/bin" ]]; then
        die "Кэш старого формата или повреждён: $cache_install\nПересоберите: ./scripts/build_and_install.sh --rebuild"
    fi

    local cache_bin="$stage_root/bin"
    local cache_lib="$stage_root/$KICAD_INSTALL_LIBDIR"
    [[ -d "$cache_lib" ]] || cache_lib="$stage_root/lib"
    local cache_plugins="$cache_lib/kicad/plugins"
    local cache_python="$stage_root/lib/python3/dist-packages"
    local cache_share="$stage_root/share"

    [[ -d "$cache_bin" ]] || die "В кэше нет директории bin: $cache_bin"

    # Бинари и .kiface: ставим весь staged bin поверх системного /usr/bin.
    local bin_files=()
    for f in "$cache_bin"/*; do
        [[ -e "$f" || -L "$f" ]] && bin_files+=("$f")
    done
    [[ ${#bin_files[@]} -gt 0 ]] || die "В staged bin нет файлов: $cache_bin"

    # Shared libs: libki*.so* из cache/lib/ → /usr/lib/x86_64-linux-gnu/
    local lib_files=()
    if [[ -d "$cache_lib" ]]; then
        for f in "$cache_lib"/libki*.so*; do
            [[ -e "$f" || -L "$f" ]] || continue
            lib_files+=("$f")
        done
    fi

    local plugin_files=()
    if [[ -d "$cache_plugins" ]]; then
        while IFS= read -r -d '' f; do plugin_files+=("$f"); done < <(find "$cache_plugins" -type f -print0 | sort -z)
    fi

    local python_files=()
    if [[ -d "$cache_python" ]]; then
        for f in "$cache_python"/*; do [[ -e "$f" ]] && python_files+=("$f"); done
    fi

    local share_dirs=()
    if [[ -d "$cache_share/kicad" ]]; then
        while IFS= read -r -d '' d; do
            share_dirs+=("$(basename "$d")")
        done < <(find "$cache_share/kicad" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)
    fi

    log "Будет установлено бинарей:      ${#bin_files[@]} → $system_kicad"
    log "Будет установлено shared libs:  ${#lib_files[@]} → $SYSTEM_LIB_DIR"
    log "Будет установлено plugins:      ${#plugin_files[@]} → $SYSTEM_LIB_DIR/kicad/plugins"
    log "Будет установлено python:       ${#python_files[@]} → /usr/lib/python3/dist-packages"
    log "Будет обновлено share/kicad:    ${#share_dirs[@]} директорий"
    echo ""
    for f in "${bin_files[@]}"; do printf "  bin/%s\n" "$(basename "$f")"; done
    for f in "${lib_files[@]}"; do printf "  lib/%s\n" "$(basename "$f")"; done
    for f in "${plugin_files[@]}"; do printf "  plugin/%s\n" "${f#$cache_plugins/}"; done
    for f in "${python_files[@]}"; do printf "  python/%s\n" "$(basename "$f")"; done
    for d in "${share_dirs[@]}"; do printf "  share/kicad/%s/\n" "$d"; done
    echo ""

    if $MODE_CHECK; then
        warn "(dry-run) Установка пропущена"
        return
    fi

    for f in "${bin_files[@]}"; do
        echo "'$f' -> '$system_kicad/$(basename "$f")'"
        sudo_atomic_copy "$f" "$system_kicad/$(basename "$f")"
    done
    if [[ ${#lib_files[@]} -gt 0 ]]; then
        for f in "${lib_files[@]}"; do
            echo "'$f' -> '$SYSTEM_LIB_DIR/$(basename "$f")'"
            sudo_atomic_copy "$f" "$SYSTEM_LIB_DIR/$(basename "$f")"
        done
    fi
    if [[ ${#plugin_files[@]} -gt 0 ]]; then
        run_sudo mkdir -p "$SYSTEM_LIB_DIR/kicad/plugins"
        for f in "${plugin_files[@]}"; do
            local rel="${f#$cache_plugins/}"
            run_sudo mkdir -p "$SYSTEM_LIB_DIR/kicad/plugins/$(dirname "$rel")"
            sudo_atomic_copy "$f" "$SYSTEM_LIB_DIR/kicad/plugins/$rel"
        done
    fi
    if [[ ${#python_files[@]} -gt 0 ]]; then
        run_sudo mkdir -p /usr/lib/python3/dist-packages
        for f in "${python_files[@]}"; do
            sudo_atomic_copy "$f" "/usr/lib/python3/dist-packages/$(basename "$f")"
        done
    fi
    if [[ ${#share_dirs[@]} -gt 0 ]]; then
        run_sudo mkdir -p "$SYSTEM_SHARE_DIR/kicad"
        for d in "${share_dirs[@]}"; do
            run_sudo mkdir -p "$SYSTEM_SHARE_DIR/kicad/$d"
            run_sudo cp -a "$cache_share/kicad/$d/." "$SYSTEM_SHARE_DIR/kicad/$d/"
        done
    fi
    if [[ ${#lib_files[@]} -gt 0 || ${#plugin_files[@]} -gt 0 ]]; then
        run_sudo ldconfig
    fi
    ok "Установка завершена"
}

# ── Откат к оригинальным файлам ───────────────────────────────────────────
restore_originals() {
    local version="$1" system_kicad="$2"
    local backup_dir
    backup_dir=$(cache_original_dir "$version")

    header "Откат к оригинальным файлам KiCad $version"

    [[ -d "$backup_dir" ]] || die "Резервная копия не найдена: $backup_dir\nУстановите сначала хотя бы раз, чтобы создать бэкап."

    # Восстанавливаем бинари
    local bin_files=()
    mapfile -t bin_files < <(find "$backup_dir/bin" -type f 2>/dev/null | sort)
    if [[ ${#bin_files[@]} -gt 0 ]]; then
        log "Восстановление бинарей → $system_kicad"
        for f in "${bin_files[@]}"; do
            echo "'$f' -> '$system_kicad/$(basename "$f")'"
            sudo_atomic_copy "$f" "$system_kicad/$(basename "$f")"
        done
    fi

    # Восстанавливаем shared libs
    local lib_files=()
    mapfile -t lib_files < <(find "$backup_dir/lib" -type f 2>/dev/null | sort)
    if [[ ${#lib_files[@]} -gt 0 ]]; then
        log "Восстановление shared libs → $SYSTEM_LIB_DIR"
        for f in "${lib_files[@]}"; do
            echo "'$f' -> '$SYSTEM_LIB_DIR/$(basename "$f")'"
            sudo_atomic_copy "$f" "$SYSTEM_LIB_DIR/$(basename "$f")"
        done
        run_sudo ldconfig
    fi

    if [[ -d "$backup_dir/plugins" ]]; then
        local plugin_files=()
        mapfile -t plugin_files < <(find "$backup_dir/plugins" -type f 2>/dev/null | sort)
        if [[ ${#plugin_files[@]} -gt 0 ]]; then
            log "Восстановление plugins → $SYSTEM_LIB_DIR/kicad/plugins"
            for f in "${plugin_files[@]}"; do
                local rel="${f#$backup_dir/plugins/}"
                run_sudo mkdir -p "$SYSTEM_LIB_DIR/kicad/plugins/$(dirname "$rel")"
                sudo_atomic_copy "$f" "$SYSTEM_LIB_DIR/kicad/plugins/$rel"
            done
            run_sudo ldconfig
        fi
    fi

    if [[ -d "$backup_dir/python" ]]; then
        local python_files=()
        mapfile -t python_files < <(find "$backup_dir/python" -type f 2>/dev/null | sort)
        if [[ ${#python_files[@]} -gt 0 ]]; then
            log "Восстановление Python-модулей → /usr/lib/python3/dist-packages"
            for f in "${python_files[@]}"; do
                sudo_atomic_copy "$f" "/usr/lib/python3/dist-packages/$(basename "$f")"
            done
        fi
    fi

    if [[ -d "$backup_dir/share/kicad" ]]; then
        local share_dirs=()
        mapfile -t share_dirs < <(find "$backup_dir/share/kicad" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
        if [[ ${#share_dirs[@]} -gt 0 ]]; then
            log "Восстановление share/kicad resources"
            for d in "${share_dirs[@]}"; do
                local name; name=$(basename "$d")
                run_sudo mkdir -p "$SYSTEM_SHARE_DIR/kicad/$name"
                run_sudo cp -av "$d/." "$SYSTEM_SHARE_DIR/kicad/$name/"
            done
        fi
    fi

    [[ ${#bin_files[@]} -gt 0 || ${#lib_files[@]} -gt 0 || -d "$backup_dir/share/kicad" ]] || die "В бэкапе нет файлов"
    ok "Оригинальные файлы восстановлены"
}

# ── Верификация установки ─────────────────────────────────────────────────
verify_installation() {
    local system_kicad="$1" expected_version="${2:-}"

    header "Верификация"

    # 1. Проверяем что kicad-cli доступен
    local cli
    cli=$(command -v kicad-cli 2>/dev/null || find /usr/bin /usr/local/bin -name "kicad-cli" 2>/dev/null | head -1)
    if [[ -z "$cli" ]]; then
        warn "kicad-cli не найден, пропускаем функциональную проверку"
        return
    fi
    ok "kicad-cli: $cli"

    local verify_home
    verify_home=$(mktemp -d /tmp/kicad-verify.XXXXXX)
    mkdir -p "$verify_home/config" "$verify_home/cache" "$verify_home/data"
    local cli_env=( env
        XDG_CONFIG_HOME="$verify_home/config"
        XDG_CACHE_HOME="$verify_home/cache"
        XDG_DATA_HOME="$verify_home/data" )

    local cli_version
    cli_version=$("${cli_env[@]}" "$cli" version 2>&1 | tail -1 || true)
    if [[ "$cli_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
        ok "Версия kicad-cli: $cli_version"

        if [[ -n "$expected_version" && "$cli_version" != "$expected_version"* ]]; then
            die "После установки ожидалась версия $expected_version, но kicad-cli показывает: $cli_version"
        fi
    else
        warn "Не удалось уверенно прочитать версию kicad-cli: $cli_version"
    fi

    # 2. Проверяем что .kiface файлы — валидные ELF
    local bad=0
    for f in "$system_kicad"/*.kiface; do
        [[ -f "$f" ]] || continue
        if ! file "$f" | grep -q "ELF"; then
            err "Повреждён: $(basename "$f")"
            ((bad++))
        fi
    done
    [[ $bad -eq 0 ]] && ok "Все .kiface файлы — валидные ELF" || die "$bad повреждённых файлов после установки"

    # 2.5. Проверяем критичные runtime-ресурсы. Они поставляются отдельными
    # пакетами KiCad, но собранные бинарники обязаны искать их в /usr/share/kicad.
    local resource_errors=0

    if [[ -f "$SYSTEM_SHARE_DIR/kicad/internat/ru/kicad.mo" ]]; then
        ok "Локализации найдены: $SYSTEM_SHARE_DIR/kicad/internat"
    else
        err "Не найдены локализации KiCad: $SYSTEM_SHARE_DIR/kicad/internat"
        ((resource_errors++))
    fi

    local footprint_count=0 symbol_count=0
    [[ -d "$SYSTEM_SHARE_DIR/kicad/footprints" ]] \
        && footprint_count=$(find "$SYSTEM_SHARE_DIR/kicad/footprints" -mindepth 1 -maxdepth 1 -type d | wc -l)
    [[ -d "$SYSTEM_SHARE_DIR/kicad/symbols" ]] \
        && symbol_count=$(find "$SYSTEM_SHARE_DIR/kicad/symbols" -maxdepth 1 -type f -name '*.kicad_sym' | wc -l)

    if [[ $footprint_count -gt 50 ]]; then
        ok "Footprint libraries: $footprint_count"
    else
        err "Подозрительно мало footprint libraries: $footprint_count"
        ((resource_errors++))
    fi

    if [[ $symbol_count -gt 50 ]]; then
        ok "Symbol libraries: $symbol_count"
    else
        err "Подозрительно мало symbol libraries: $symbol_count"
        ((resource_errors++))
    fi

    local common_lib
    common_lib=$(find "$SYSTEM_LIB_DIR" -maxdepth 1 -name 'libkicommon.so*' -type f 2>/dev/null | sort -V | tail -1)

    if [[ -n "$common_lib" && -f "$common_lib" ]]; then
        if grep -a -q "$CACHE_DIR" "$common_lib"; then
            err "В libkicommon зашит путь к cache; KiCad будет искать ресурсы не в /usr/share/kicad"
            ((resource_errors++))
        elif grep -a -q "$KICAD_DATA_DIR" "$common_lib"; then
            ok "Runtime data path: $KICAD_DATA_DIR"
        else
            warn "Не удалось подтвердить runtime data path в $(basename "$common_lib")"
        fi
    fi

    [[ $resource_errors -eq 0 ]] || die "Проверка KiCad runtime-ресурсов не пройдена"

    # 3. Функциональный тест — импорт тестового файла
    local tests_dir
    tests_dir="$(dirname "$SCRIPT_DIR")/tests/fixtures"

    # Тест Altium-импорта (если есть файл)
    local test_file="$tests_dir/Attiny-test.SchLib"
    if [[ -f "$test_file" ]]; then
        printf "  %-40s " "Altium import (Attiny-test.SchLib)..."
        local result
        result=$("${cli_env[@]}" "$cli" sym upgrade "$test_file" -o /dev/null --force 2>&1) || true
        if echo "$result" | grep -qiE "(error|crash|exception|Unable to convert)"; then
            echo -e "${RED}✗${NC}"
            warn "Вывод: $(echo "$result" | grep -iE "(error|crash)" | head -3)"
            warn "Altium-импорт не работает. Откатите: ./scripts/build_and_install.sh --restore"
        else
            echo -e "${GREEN}✓${NC}"
        fi
    fi

    # Тест null-byte файла (специфичный баг)
    local nullbyte_file="$tests_dir/test_bug_nullbyte.SchLib"
    if [[ -f "$nullbyte_file" ]]; then
        printf "  %-40s " "Null-byte bug (test_bug_nullbyte.SchLib)..."
        local result
        result=$("${cli_env[@]}" "$cli" sym upgrade "$nullbyte_file" -o /dev/null --force 2>&1) || true
        if echo "$result" | grep -qiE "(error|crash|exception|out of range)"; then
            echo -e "${RED}✗${NC}"
            warn "Null-byte баг всё ещё присутствует или новая ошибка"
        else
            echo -e "${GREEN}✓${NC}"
        fi
    fi

    rm -rf "$verify_home"
    ok "Верификация завершена"
}


save_cache_meta() {
    local cache_dir="$1" version="$2" hash="$3" patch_dir="$4"
    cat > "$cache_dir/.meta" << EOF
version=$version
patches_hash=$hash
patch_dir=$patch_dir
cache_format=$CACHE_FORMAT_VERSION
install_prefix=$KICAD_INSTALL_PREFIX
install_libdir=$KICAD_INSTALL_LIBDIR
kicad_data=$KICAD_DATA_DIR
kicad_library_data=$KICAD_LIBRARY_DATA_DIR
kicad_docs=$KICAD_DOCS_DIR
kicad_lib=$KICAD_LIB_DIR
kicad_user_plugin=$KICAD_USER_PLUGIN_DIR
source_url_template=$KICAD_SOURCE_URL_TEMPLATE
multiarch=$MULTIARCH
built=$(date -Iseconds)
builder=$(gcc --version 2>/dev/null | head -1)
jobs=$JOBS
host=$(hostname)
patches=$(list_patches "$patch_dir" | while IFS= read -r patch_file; do
    printf '%s\n' "${patch_file#$patch_dir/}"
done | tr '\n' ',')
EOF
}

# ── Главный поток ─────────────────────────────────────────────────────────
main() {
    parse_args "$@"
    check_not_root

    if $MODE_BUILD_ONLY && $MODE_UPDATE_LIBRARIES; then
        die "--update-libraries несовместим с --build-only: сборка кэша не должна менять систему"
    fi

    echo -e "${BOLD}"
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║         KiCad Patch Builder & Installer                  ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    # ── 1. Определить версию ──
    local version
    if [[ -n "$KICAD_VERSION_OVERRIDE" ]]; then
        version="$KICAD_VERSION_OVERRIDE"
        log "Версия задана явно: $version"
    else
        if $MODE_RESTORE; then
            log "Определяю пакетную версию KiCad для отката..."
            version=$(detect_restore_version)
        else
            log "Определяю версию установленного KiCad..."
            version=$(detect_kicad_version)
        fi
        [[ -n "$version" ]] || die "KiCad не найден. Используйте --version X.X.X"
        ok "Найден KiCad $version"
    fi

    # ── 2. Откат ──
    if $MODE_RESTORE; then
        local system_kicad
        system_kicad=$(find_system_kicad)
        [[ -n "$system_kicad" ]] || die "Системная директория KiCad не найдена"
        restore_originals "$version" "$system_kicad"
        exit 0
    fi

    # ── 2.1. Проверить apt-источник целевой ветки KiCad ──
    if ! $MODE_CHECK && ! $MODE_BUILD_ONLY; then
        offer_release_ppa_if_needed "$version"
    fi

    # ── 2.5. Убедиться что базовый KiCad установлен ──
    if ! $MODE_CHECK && ! $MODE_BUILD_ONLY; then
        install_kicad_base_if_needed "$version"
    elif $MODE_BUILD_ONLY; then
        log "Режим build-only: базовый пакет apt и системная установка не изменяются"
    fi

    # ── 3. Найти патчи ──
    local patch_dir
    patch_dir=$(find_patch_dir "$version") || die "Патчи для KiCad $version не найдены"
    ok "Патчи: $patch_dir"

    # ── 4. Вычислить хэш ──
    local hash
    hash=$(compute_hash "$patch_dir")
    log "Хэш набора патчей: $hash"

    # ── 5. Проверить кэш ──
    local cache_install
    cache_install=$(cache_install_dir "$version" "$hash")

    if [[ -d "$cache_install" ]] && ! $MODE_REBUILD; then
        echo ""
        ok "Найден кэш: $cache_install"
        local meta="$cache_install/.meta"
        if [[ -f "$meta" ]]; then
            echo ""
            grep -E "^(built|patches)=" "$meta" | while IFS='=' read -r k v; do
                printf "  %-15s %s\n" "$k:" "$v"
            done
            echo ""
        fi

        if $MODE_FROM_CACHE || $MODE_CHECK; then
            : # продолжаем с кэшем
        else
            ask "Использовать кэш? [Y/n]: "
            read -r answer
            [[ "${answer,,}" == "n" ]] && MODE_REBUILD=true
        fi
    fi

    if $MODE_FROM_CACHE && [[ ! -d "$cache_install" ]]; then
        die "Кэш не найден: $cache_install\nСначала соберите: ./scripts/build_and_install.sh --version $version --build-only --rebuild"
    fi

    # ── 6. Показать план (dry-run) ──
    if $MODE_CHECK; then
        header "План установки (dry-run)"
        echo "  Версия KiCad:  $version"
        echo "  Патчи:         $patch_dir"
        echo "  Хэш патчей:    $hash"
        echo "  Кэш:           $cache_install"
        [[ -d "$cache_install" ]] && echo "  Состояние кэша: ГОТОВ" || echo "  Состояние кэша: нужна сборка"
        echo ""

        prepare_patch_check_source "$version"
        apply_patches "$PATCH_CHECK_SRC" "$patch_dir" true
        $MODE_UPDATE_LIBRARIES && report_library_packages "$version"
        [[ -n "$PATCH_CHECK_TMP" ]] && rm -rf -- "$PATCH_CHECK_TMP"

        warn "Dry-run завершён. Для реальной установки уберите --check"
        exit 0
    fi

    # ── 7. Определить системный путь KiCad ──
    local system_kicad
    if ! $MODE_BUILD_ONLY; then
        system_kicad=$(find_system_kicad)
        [[ -n "$system_kicad" ]] || die "Системная директория KiCad не найдена"
        log "Системный KiCad: $system_kicad"
    else
        system_kicad=""
    fi

    # ── 8. Собрать если нет в кэше ──
    if [[ ! -d "$cache_install" ]] || $MODE_REBUILD; then
        [[ -d "$cache_install" ]] && rm -rf "$cache_install"
        mkdir -p "$cache_install"

        check_build_deps
        prepare_source "$version"
        apply_patches "$SRC_DIR" "$patch_dir" false
        build_kicad "$SRC_DIR" "$cache_install"
        save_cache_meta "$cache_install" "$version" "$hash" "$patch_dir"
    else
        ok "Используем кэш (пересборка не нужна)"
    fi

    if $MODE_BUILD_ONLY; then
        ok "Сборка сохранена в кэше: $cache_install"
        echo ""
        echo "  Установка из кэша:"
        echo "    ./scripts/build_and_install.sh --version $version --from-cache"
        echo ""
        exit 0
    fi

    # ── 8.5. Обновить official library packages ──
    update_library_packages_if_requested "$version"

    # ── 9. Резервная копия ──
    backup_originals "$version" "$system_kicad" "$cache_install"

    # ── 10. Установка ──
    install_from_cache "$cache_install" "$system_kicad"

    # ── 11. Верификация ──
    verify_installation "$system_kicad" "$version"

    echo ""
    echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}${BOLD}  Патчи KiCad $version успешно установлены!${NC}"
    echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "  Откат:          ./scripts/build_and_install.sh --restore"
    echo "  Кэш:            ./scripts/build_and_install.sh --list-cache"
    echo ""
}

main "$@"
exit $?
