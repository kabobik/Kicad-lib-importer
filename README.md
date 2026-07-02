# KiCad Local Patches

Коллекция патчей для KiCad с автоматической сборкой и установкой.  
Патчи протестированы на **KiCad 9.0.7** и **9.0.8** (Debian/Ubuntu); для Arch Linux добавлен отдельный установщик.

## Патчи

| Патч | Версия | Статус | Описание |
|------|--------|--------|----------|
| `0001-smooth-drag-zoom` | 9.0.7 | ✅ работает | Фиксирует курсор при drag-zoom (средняя кнопка мыши) |
| `0002-altium-null-byte` | 9.0.7 | ⬆️ upstream в 9.0.8 | Фикс краша при импорте Altium `.SchLib` с бинарными блоками |
| `0003-auto-bus-entry` | 9.0.7 | ✅ работает | Авто-конвертация 45° wire в bus entry |
| `0004-group-by-column` | 9.0.7 | ✅ работает | Группировка по колонке в дереве библиотек |
| `0005-auto-bus-entry-posture-fix` | 9.0.7 | ✅ работает | Исправление posture для авто bus entry |
| `local-patches-combined` | 9.0.8 | ✅ работает | Все патчи кроме altium-null-byte (уже в upstream) |
| `local-patches-combined` | 10.0.4 | ✅ проверено | Локальный слой проекта, перебазированный на KiCad 10.0.4 |
| `gost-font-multiline` | standalone | ✅ работает | Фикс integer truncation в `GetInterline()` для GOST-шрифтов |
| `bus-entry-size-properties` | standalone | ✅ работает | Size X/Y в properties bus entry |

## Быстрый старт

### Debian / Ubuntu

```bash
# 1. Посмотреть план (ничего не меняет)
./scripts/build_and_install.sh --check

# 2. Собрать и установить (первый раз — 30-60 мин)
./scripts/build_and_install.sh

# 3. Повторная установка — из кэша (секунды)
./scripts/build_and_install.sh --from-cache

# 4. Откат к оригинальному KiCad
./scripts/build_and_install.sh --restore
```

### Arch Linux

```bash
# 1. Посмотреть план. Если --version не задан, берётся самая свежая
#    поддержанная версия из patches/kicad-X.X.X.
./scripts/build_and_install_arch.sh --check

# 2. Собрать и установить. Скрипт сам поставит базовый KiCad,
#    kicad-library и kicad-library-3d через pacman, если их нет.
./scripts/build_and_install_arch.sh

# 3. Явная версия
./scripts/build_and_install_arch.sh --version 10.0.4 --rebuild

# 4. Повторная установка из кэша
./scripts/build_and_install_arch.sh --from-cache

# 5. Откат к оригинальным файлам Arch-пакета
./scripts/build_and_install_arch.sh --restore
```

## Обновление до KiCad 10.0.4

```bash
# Проверить, что локальные патчи ложатся на чистую 10.0.4
./scripts/build_and_install.sh --version 10.0.4 --check

# Собрать 10.0.4 с локальными патчами в кэш без установки
./scripts/build_and_install.sh --version 10.0.4 --build-only --rebuild

# Установить уже собранный кэш поверх текущего KiCad.
# Флаг --update-libraries обновит official packages библиотек через apt,
# если для них доступна версия 10.0.4.
./scripts/build_and_install.sh --version 10.0.4 --from-cache --update-libraries

# Либо одним шагом: собрать и установить поверх текущего KiCad
./scripts/build_and_install.sh --version 10.0.4 --rebuild --update-libraries
```

При явном `--version` скрипт не требует, чтобы такая же версия уже была в apt:
если KiCad установлен, базовый пакет сохраняется, а фактическая версия обновляется
staged-сборкой из исходников. После установки `kicad-cli version` сверяется с
целевой версией.

## Как работает build_and_install.sh

1. **Определяет** версию установленного KiCad (`dpkg` / `kicad --version`)
2. **Находит** папку `patches/kicad-X.X.X/` с патчами для этой версии
3. **Вычисляет** хэш набора патчей → проверяет кэш `cache/kicad-X.X.X-HASH/`
4. **Если кэш есть** → предлагает установить за секунды
5. **Если кэша нет**:
   - клонирует исходники KiCad в `kicad-src/` (или сбрасывает на нужный тег)
   - проверяет совместимость патчей (`patch --dry-run`)
   - собирает (`cmake --build -j$(nproc)`)
   - сохраняет результат в кэш
6. **Делает бэкап** оригинальных системных файлов (`cache/kicad-X.X.X-original/`)
7. **Устанавливает** из кэша в системную директорию KiCad (требует `sudo`)

## Структура проекта

```
patches/
  kicad-9.0.7/          # серия патчей для 9.0.7 (5 штук)
  kicad-9.0.8/          # combined diff для 9.0.8
  kicad-10.0.4/         # combined diff для 10.0.4
  standalone/           # независимые патчи (gost, bus-entry)
scripts/
  build_and_install.sh       # Debian/Ubuntu: патч → сборка → установка
  build_and_install_arch.sh  # Arch Linux: pacman + /usr/lib layout
  fix_kicad_altium.sh   # устаревший скрипт (только altium-null-byte)
  apply_smooth_zoom_patch.sh  # устаревший скрипт (только smooth-zoom)
tests/
  fixtures/             # .SchLib и .kicad_sym файлы для тестирования
  repro/                # код воспроизведения багов
plugins/
  git-integration/      # Python-плагин: git-интеграция для библиотек KiCad
  library-panel/        # C++ прототип: панель библиотек в Project Manager
docs/
  bugs/                 # баг-репорты с анализом root cause
  research/             # исследования архитектуры KiCad
  reports/              # исторические отчёты о сборках
cache/                  # gitignored: собранные .kiface и бэкапы оригиналов
kicad-src/              # gitignored: исходники KiCad (скачиваются скриптом)
```

## Требования

- **ОС:** Ubuntu / Debian (`scripts/build_and_install.sh`) или Arch Linux (`scripts/build_and_install_arch.sh`)
- **KiCad:** для Debian/Ubuntu — установленный системный KiCad 9.0.x; для Arch — необязательно, установщик сам ставит `kicad`, `kicad-library`, `kicad-library-3d`
- **Для сборки:** `cmake`, `ninja-build`, `g++`, `git`, `patch`  
  + dev-пакеты KiCad (см. [официальный BUILD.md](https://gitlab.com/kicad/code/kicad/-/blob/master/BUILD.md))
- **`sudo`:** для записи в системную директорию KiCad

## Проблема с Altium-импортом (исторический контекст)

KiCad 9.0.7 падал при импорте некоторых Altium `.SchLib` с ошибкой `ALTIUM_BINARY_READER: out of range`.  
**Причина:** `ReadProperties()` безусловно обрезал trailing null-byte, ломая zlib-поток в PinFrac-блоках.  
**Фикс** (`0002-altium-null-byte`): добавить проверку `&& !isBinary` — **вошёл в KiCad 9.0.8 upstream**.  
Подробнее: [docs/bugs/altium-null-byte-bug.md](docs/bugs/altium-null-byte-bug.md)


## Структура репозитория

```
├── fix_kicad_altium.sh       # Основной скрипт
├── README.md                 # Документация
├── test/
│   └── Attiny-test.SchLib    # Тестовый файл (воспроизводит баг)
├── docs/
│   ├── KICAD_BUG_REPORT.md   # Детальный баг-репорт
│   ├── GITLAB_ISSUE_FORM.md  # Форма для GitLab issue
│   └── RESEARCH_REPORT.md    # Анализ архитектуры импорта
└── cache/                    # Кэш сборок (gitignored)
```

## Баг-репорт

Подробный анализ: [docs/KICAD_BUG_REPORT.md](docs/KICAD_BUG_REPORT.md)

GitLab issue (готовая форма): [docs/GITLAB_ISSUE_FORM.md](docs/GITLAB_ISSUE_FORM.md)

## Затронутые версии

- ✅ KiCad 9.0.7 — фикс проверен
- ✅ KiCad nightly (`6056c50227`) — баг подтверждён
- ⚠️  Скорее всего затронуты все 9.0.x и 8.0.x

## Лицензия

MIT
