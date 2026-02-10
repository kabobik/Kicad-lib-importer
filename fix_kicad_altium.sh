#!/bin/bash
# ============================================================================
# fix_kicad_altium.sh — Автоматический фикс бага импорта Altium .SchLib в KiCad
# ============================================================================
#
# Баг: ALTIUM_BINARY_PARSER::ReadProperties() некорректно обрезает trailing
#      null-byte из бинарных записей PinFrac, ломая zlib-данные при импорте.
# Фикс: одна строка в common/io/altium/altium_binary_parser.cpp
#
# Поддерживает:  KiCad stable (9.0.x) и nightly
# Кэширование:   собранные _eeschema.kiface сохраняются в ./cache/
# Тестирование:   автоматическая верификация на Attiny-test.SchLib
#
# Использование:
#   ./fix_kicad_altium.sh                  # Фикс всех найденных версий
#   ./fix_kicad_altium.sh --stable         # Только stable
#   ./fix_kicad_altium.sh --nightly        # Только nightly
#   ./fix_kicad_altium.sh --check          # Только проверка (без изменений)
#   ./fix_kicad_altium.sh --restore        # Откат из бэкапов
#   ./fix_kicad_altium.sh --list-cache     # Показать кэшированные фиксы
#   ./fix_kicad_altium.sh --clean-cache    # Очистить кэш
#
# Подробнее: ./fix_kicad_altium.sh --help
# ============================================================================

set -euo pipefail

# ── Цвета ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# ── Конфигурация ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KICAD_REPO="https://gitlab.com/kicad/code/kicad.git"
CACHE_DIR="${CACHE_DIR:-$SCRIPT_DIR/cache}"
BUILD_DIR="${BUILD_DIR:-/tmp/kicad-altium-fix}"
JOBS=$(nproc 2>/dev/null || echo 4)
TEST_FILE=""

# ── Утилиты ──
log()    { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()     { echo -e "${GREEN}[  OK]${NC} $*"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()    { echo -e "${RED}[FAIL]${NC} $*"; }
die()    { err "$*"; exit 1; }
header() { echo -e "\n${BOLD}━━━ $* ━━━${NC}"; }

# ── Кэш ──

cache_path_for() {
    echo "$CACHE_DIR/_eeschema.kiface.${1}"
}

cache_exists() {
    [[ -f "$(cache_path_for "$1")" ]]
}

cache_save() {
    local ref="$1" built_kiface="$2"
    mkdir -p "$CACHE_DIR"
    local dest
    dest=$(cache_path_for "$ref")
    local tmp="$dest.tmp.$$"
    cp "$built_kiface" "$tmp"
    strip "$tmp" 2>/dev/null || true
    mv "$tmp" "$dest"

    cat > "$dest.meta" << EOF
version=$ref
built=$(date -Iseconds)
size=$(stat -c%s "$dest")
md5=$(md5sum "$dest" | awk '{print $1}')
builder=$(gcc --version 2>/dev/null | head -1)
host=$(hostname)
EOF
    ok "Кэш: $(basename "$dest") ($(du -h "$dest" | cut -f1))"
}

list_cache() {
    header "Кэшированные фиксы ($CACHE_DIR)"
    if [[ ! -d "$CACHE_DIR" ]] || ! ls "$CACHE_DIR"/_eeschema.kiface.* &>/dev/null 2>&1; then
        echo "  (пусто)"
        return
    fi
    printf "  ${BOLD}%-20s %-10s %-12s %s${NC}\n" "Версия" "Размер" "Дата" "MD5"
    echo "  ──────────────────────────────────────────────────────────"
    for f in "$CACHE_DIR"/_eeschema.kiface.*; do
        [[ "$f" == *.meta ]] && continue
        local ver size date md5
        ver="${f##*kiface.}"
        size=$(du -h "$f" | cut -f1)
        date="?" ; md5="?"
        if [[ -f "$f.meta" ]]; then
            date=$(grep '^built=' "$f.meta" 2>/dev/null | cut -d= -f2 | cut -dT -f1)
            md5=$(grep '^md5=' "$f.meta" 2>/dev/null | cut -d= -f2 | head -c12)
        fi
        printf "  %-20s %-10s %-12s %s…\n" "$ver" "$size" "$date" "$md5"
    done
}

clean_cache() {
    if [[ -d "$CACHE_DIR" ]]; then
        local count
        count=$(find "$CACHE_DIR" -name "_eeschema.kiface.*" 2>/dev/null | wc -l)
        rm -f "$CACHE_DIR"/_eeschema.kiface.*
        ok "Удалено из кэша: $((count / 2)) версий"
    else
        echo "  Кэш не существует"
    fi
}

# ── Зависимости ──
check_build_deps() {
    local missing_cmds=()
    local -A cmd_to_pkg=([cmake]=cmake [ninja]=ninja-build [g++]=g++ [git]=git [strip]=binutils)
    for cmd in cmake ninja g++ git strip; do
        command -v "$cmd" &>/dev/null || missing_cmds+=("${cmd_to_pkg[$cmd]}")
    done
    [[ ${#missing_cmds[@]} -gt 0 ]] && \
        die "Не найдены: ${missing_cmds[*]}\nУстановите: sudo apt install ${missing_cmds[*]}"

    local dev_pkgs=(
        libwxgtk3.2-dev libglew-dev libglm-dev
        libcurl4-openssl-dev libssl-dev
        libboost-dev libboost-filesystem-dev libboost-locale-dev
        libngspice0-dev
        libocct-data-exchange-dev libocct-modeling-algorithms-dev libocct-visualization-dev
        libcairo2-dev libpixman-1-dev python3-dev swig
        protobuf-compiler libprotobuf-dev
        unixodbc-dev libsecret-1-dev libnng-dev
        libzstd-dev libgit2-dev libharfbuzz-dev libfontconfig-dev
        gettext zlib1g-dev
    )
    local missing=()
    for p in "${dev_pkgs[@]}"; do
        dpkg -s "$p" &>/dev/null || missing+=("$p")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        log "Устанавливаю ${#missing[@]} dev-пакетов..."
        sudo apt-get install -y "${missing[@]}" 2>&1 | tail -3
        ok "Зависимости установлены"
    fi
}

# ── Определение версий ──
detect_kicad_versions() {
    local versions=()
    if dpkg -s kicad &>/dev/null; then
        local ver kiface="/usr/bin/_eeschema.kiface"
        ver=$(dpkg-query -W -f='${Version}' kicad 2>/dev/null)
        [[ -f "$kiface" ]] && versions+=("stable|$(echo "$ver" | sed 's/~.*//')|$kiface|/usr/bin/kicad-cli|tag|")
    fi
    if dpkg -s kicad-nightly &>/dev/null; then
        local ver kiface="/usr/lib/kicad-nightly/bin/_eeschema.kiface"
        local ld="/usr/lib/kicad-nightly/lib/x86_64-linux-gnu"
        ver=$(dpkg-query -W -f='${Version}' kicad-nightly 2>/dev/null)
        if [[ -f "$kiface" ]]; then
            local commit
            commit=$(echo "$ver" | grep -oP '\+\K[a-f0-9]+' | head -1)
            if [[ -n "$commit" ]]; then
                versions+=("nightly|$commit|$kiface|/usr/lib/kicad-nightly/bin/kicad-cli|commit|$ld")
            else
                versions+=("nightly|$(echo "$ver" | sed 's/~.*//')|$kiface|/usr/lib/kicad-nightly/bin/kicad-cli|tag|$ld")
            fi
        fi
    fi
    echo "${versions[@]}"
}

# ── Тест ──
check_needs_fix() {
    local cli="$1" ld="${2:-}" test="$3" result
    if [[ -n "$ld" ]]; then
        result=$(LD_LIBRARY_PATH="$ld" "$cli" sym upgrade "$test" -o /dev/null --force 2>&1) || true
    else
        result=$("$cli" sym upgrade "$test" -o /dev/null --force 2>&1) || true
    fi
    echo "$result" | grep -q "Unable to convert"
}

# ── Клонирование ──
clone_source() {
    local ref="$1" ref_type="$2" src_dir="$3"
    if [[ -d "$src_dir/.git" ]]; then
        if [[ "$ref_type" == "tag" ]]; then
            local t; t=$(cd "$src_dir" && git describe --tags --exact-match 2>/dev/null || echo "")
            [[ "$t" == "$ref" ]] && { ok "Исходники $ref готовы"; return 0; }
        else
            local h; h=$(cd "$src_dir" && git rev-parse --short=10 HEAD 2>/dev/null || echo "")
            [[ "$h" == "${ref:0:10}" ]] && { ok "Исходники $ref готовы"; return 0; }
        fi
        rm -rf "$src_dir"
    fi
    if [[ "$ref_type" == "tag" ]]; then
        log "git clone --branch $ref ..."
        git clone --depth 1 --branch "$ref" "$KICAD_REPO" "$src_dir" 2>&1 | tail -3
    else
        log "git clone + fetch $ref ..."
        git clone --depth 1 "$KICAD_REPO" "$src_dir" 2>&1 | tail -3
        (cd "$src_dir" && git fetch --depth 1 origin "$ref" 2>&1 | tail -3 && git checkout FETCH_HEAD 2>&1 | tail -3)
    fi
    ok "Исходники: $(cd "$src_dir" && git log --oneline -1)"
}

# ── Патч ──
apply_fix() {
    local target="$1/common/io/altium/altium_binary_parser.cpp"
    [[ -f "$target" ]] || die "Файл не найден: $target"
    if grep -q '( hasNullByte && !isBinary )' "$target"; then
        ok "Фикс уже в исходниках"; return 0
    fi
    grep -q 'length - ( hasNullByte ? 1 : 0 )' "$target" || { warn "Строка с багом не найдена"; return 1; }
    sed -i 's/length - ( hasNullByte ? 1 : 0 )/length - ( ( hasNullByte \&\& !isBinary ) ? 1 : 0 )/' "$target"
    touch "$target"
    grep -q '( hasNullByte && !isBinary )' "$target" || die "sed не сработал!"
    ok "Патч применён"
}

# ── Сборка ──
build_kiface() {
    local src="$1" bld="$src/build"
    mkdir -p "$bld" && cd "$bld"
    if [[ ! -f build.ninja ]]; then
        log "cmake configure..."
        cmake .. -G Ninja \
            -DCMAKE_BUILD_TYPE=Release \
            -DKICAD_SCRIPTING_WXPYTHON=OFF \
            -DKICAD_IPC_API=ON \
            -DKICAD_BUILD_I18N=OFF \
            -DKICAD_BUILD_QA_TESTS=OFF \
            -DKICAD_USE_CMAKE_FINDPROTOBUF=ON \
            2>&1 | tail -5
        [[ -f build.ninja ]] || die "cmake не удался"
        ok "cmake OK"
    else
        cmake .. 2>&1 | tail -3
    fi
    log "ninja -j$JOBS ..."
    ninja -j"$JOBS" eeschema/_eeschema.kiface 2>&1 | tail -5
    [[ -f "$bld/eeschema/_eeschema.kiface" ]] || die "Сборка не удалась"
    ok "Собрано: $(du -h "$bld/eeschema/_eeschema.kiface" | cut -f1)"
    cd - >/dev/null
}

# ── Установка ──
install_kiface() {
    local src="$1" dst="$2" bak="${dst}.orig"
    [[ ! -f "$bak" ]] && { log "Бэкап → $bak"; sudo cp "$dst" "$bak"; } || ok "Бэкап есть"
    local tmp="/tmp/_eeschema.install.$$"
    cp "$src" "$tmp"
    file "$tmp" | grep -q "not stripped" && strip "$tmp"
    sudo cp "$tmp" "$dst" && rm -f "$tmp"
    ok "Установлен → $(basename "$dst")"
}

# ── Откат ──
restore_kiface() {
    local kiface="$1" bak="${kiface}.orig"
    if [[ -f "$bak" ]]; then
        sudo cp "$bak" "$kiface"
        ok "Восстановлен: $kiface"
    else
        warn "Бэкап не найден: $bak"
    fi
}

# ── Обработка версии ──
process_version() {
    local name="$1" ref="$2" kiface="$3" cli="$4" rtype="$5" ld="${6:-}"
    header "KiCad $name: $ref"

    # Нужен ли фикс?
    if [[ -n "$TEST_FILE" ]] && [[ -f "$TEST_FILE" ]]; then
        if ! check_needs_fix "$cli" "$ld" "$TEST_FILE"; then
            ok "Импорт уже работает — фикс не нужен"; return 0
        fi
        warn "Баг подтверждён"
    fi

    # Кэш?
    if cache_exists "$ref"; then
        local cached; cached=$(cache_path_for "$ref")
        log "Найден в кэше: $(basename "$cached") ($(du -h "$cached" | cut -f1))"
        install_kiface "$cached" "$kiface"
        if [[ -n "$TEST_FILE" ]] && [[ -f "$TEST_FILE" ]]; then
            if ! check_needs_fix "$cli" "$ld" "$TEST_FILE"; then
                ok "✓ Верификация OK (из кэша)"; return 0
            fi
            warn "Кэш несовместим — пересобираю..."
            rm -f "$cached" "$cached.meta"
        else
            return 0
        fi
    fi

    # Сборка
    check_build_deps
    local src="$BUILD_DIR/kicad-$name-$ref"
    clone_source "$ref" "$rtype" "$src"
    apply_fix "$src" || return 1
    build_kiface "$src"

    cache_save "$ref" "$src/build/eeschema/_eeschema.kiface"
    install_kiface "$(cache_path_for "$ref")" "$kiface"

    # Верификация
    if [[ -n "$TEST_FILE" ]] && [[ -f "$TEST_FILE" ]]; then
        if ! check_needs_fix "$cli" "$ld" "$TEST_FILE"; then
            ok "✓ Верификация OK"
        else
            err "✗ Верификация не пройдена"; return 1
        fi
    fi

    log "Удаляю исходники ($(du -sh "$src" | cut -f1))..."
    rm -rf "$src"
    ok "Исходники удалены, кэш сохранён"
}

# ── Help ──
show_help() {
    cat << 'HELPEOF'
┌──────────────────────────────────────────────────────────┐
│  fix_kicad_altium.sh — Фикс импорта Altium .SchLib      │
└──────────────────────────────────────────────────────────┘

Исправляет баг ReadProperties() в altium_binary_parser.cpp, из-за которого
KiCad некорректно обрезает trailing null-byte из бинарных PinFrac записей,
что приводит к ошибке импорта Altium .SchLib файлов.

ИСПОЛЬЗОВАНИЕ:
  ./fix_kicad_altium.sh [ОПЦИИ]

ДЕЙСТВИЯ (без опции — фикс всех версий):
  --stable            Фикс только stable (9.0.x)
  --nightly           Фикс только nightly
  --check             Проверка без изменений
  --restore           Откат к оригиналу из бэкапа
  --list-cache        Показать кэшированные сборки
  --clean-cache       Очистить кэш

НАСТРОЙКИ:
  --test-file FILE    Тестовый .SchLib файл
  --build-dir DIR     Директория сборки (по умолчанию /tmp/kicad-altium-fix)
  --cache-dir DIR     Директория кэша (по умолчанию ./cache/)
  -j, --jobs N        Потоки сборки (по умолчанию: все ядра)
  -h, --help          Эта справка

КЭШИРОВАНИЕ:
  Собранный _eeschema.kiface сохраняется в ./cache/ с привязкой к версии.
  При повторном запуске сборка пропускается — файл берётся из кэша (~30 сек
  вместо ~15 мин). Кэш переносим между машинами с одинаковой ОС.

ПРИМЕРЫ:
  ./fix_kicad_altium.sh --check            # Есть ли баг?
  ./fix_kicad_altium.sh --stable           # Исправить stable
  ./fix_kicad_altium.sh --list-cache       # Что в кэше?
  ./fix_kicad_altium.sh --restore          # Откатить изменения
HELPEOF
}

# ── Main ──
main() {
    local mode="fix" targets=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --stable)      targets+=("stable"); shift ;;
            --nightly)     targets+=("nightly"); shift ;;
            --all)         targets=(); shift ;;
            --restore)     mode="restore"; shift ;;
            --check)       mode="check"; shift ;;
            --list-cache)  mode="list-cache"; shift ;;
            --clean-cache) mode="clean-cache"; shift ;;
            --test-file)   TEST_FILE="$2"; shift 2 ;;
            --build-dir)   BUILD_DIR="$2"; shift 2 ;;
            --cache-dir)   CACHE_DIR="$2"; shift 2 ;;
            -j|--jobs)     JOBS="$2"; shift 2 ;;
            -h|--help)     show_help; exit 0 ;;
            *)             die "Неизвестно: $1  (--help)" ;;
        esac
    done

    echo -e "\n${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║  KiCad Altium .SchLib Import Fix                    ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"

    [[ "$mode" == "list-cache" ]]  && { list_cache; exit 0; }
    [[ "$mode" == "clean-cache" ]] && { clean_cache; exit 0; }

    local raw; raw=$(detect_kicad_versions)
    [[ -z "$raw" ]] && die "KiCad не найден"

    local versions=()
    for e in $raw; do
        local n; n=$(echo "$e" | cut -d'|' -f1)
        if [[ ${#targets[@]} -eq 0 ]] || printf '%s\n' "${targets[@]}" | grep -qx "$n"; then
            versions+=("$e")
        fi
    done
    [[ ${#versions[@]} -eq 0 ]] && die "Указанные версии не найдены"

    echo ""
    log "Найдено: ${#versions[@]} версий"
    for e in "${versions[@]}"; do
        local n r cm=""
        n=$(echo "$e" | cut -d'|' -f1); r=$(echo "$e" | cut -d'|' -f2)
        cache_exists "$r" && cm=" ${GREEN}[кэш]${NC}"
        echo -e "  • ${BOLD}$n${NC}: $r${cm}"
    done

    if [[ "$mode" == "restore" ]]; then
        echo ""
        for e in "${versions[@]}"; do restore_kiface "$(echo "$e" | cut -d'|' -f3)"; done
        ok "Восстановлено"; exit 0
    fi

    # Тестовый файл
    [[ -z "$TEST_FILE" ]] && {
        for c in "$SCRIPT_DIR/test/Attiny-test.SchLib" "$SCRIPT_DIR/Attiny-test.SchLib" "$(pwd)/Attiny-test.SchLib"; do
            [[ -f "$c" ]] && { TEST_FILE="$c"; break; }
        done
    }
    [[ -n "$TEST_FILE" ]] && [[ -f "$TEST_FILE" ]] && ok "Тест: $TEST_FILE" || { warn "Тестовый файл не найден"; TEST_FILE=""; }

    if [[ "$mode" == "check" ]]; then
        echo ""
        local bug=0
        for e in "${versions[@]}"; do
            local n cli ld r
            n=$(echo "$e" | cut -d'|' -f1); r=$(echo "$e" | cut -d'|' -f2)
            cli=$(echo "$e" | cut -d'|' -f4); ld=$(echo "$e" | cut -d'|' -f6)
            [[ -z "$TEST_FILE" ]] && { warn "$n: нет тестового файла"; continue; }
            if check_needs_fix "$cli" "$ld" "$TEST_FILE"; then
                local cm=""; cache_exists "$r" && cm=" → доступен в кэше!"
                err "$n: БАГ${cm}"; bug=1
            else ok "$n: OK"; fi
        done
        exit $bug
    fi

    # Fix
    mkdir -p "$BUILD_DIR"
    for e in "${versions[@]}"; do
        process_version \
            "$(echo "$e"|cut -d'|' -f1)" "$(echo "$e"|cut -d'|' -f2)" \
            "$(echo "$e"|cut -d'|' -f3)" "$(echo "$e"|cut -d'|' -f4)" \
            "$(echo "$e"|cut -d'|' -f5)" "$(echo "$e"|cut -d'|' -f6)"
    done

    echo -e "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ok "Готово!"
    echo "  Откат:  $0 --restore"
    echo "  Кэш:   $0 --list-cache"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

main "$@"
