# KiCad Altium .SchLib Import Fix

Автоматическое исправление бага импорта Altium Designer `.SchLib` файлов в KiCad.

## Проблема

KiCad (9.0.x, nightly) падает при импорте некоторых Altium `.SchLib` файлов с ошибкой:

```
ALTIUM_BINARY_READER: out of range
```

**Причина:** функция `ReadProperties()` в `altium_binary_parser.cpp` безусловно обрезает
trailing null-byte (`\0`) из всех записей. Для бинарных PinFrac записей этот байт является
частью zlib-потока данных. Его удаление ломает декомпрессию → исключение → аварийное завершение.

**Фикс:** одна строка — добавить проверку `&& !isBinary`:

```diff
- length - ( hasNullByte ? 1 : 0 )
+ length - ( ( hasNullByte && !isBinary ) ? 1 : 0 )
```

## Быстрый старт

```bash
# 1. Клонируйте репозиторий
git clone https://github.com/<user>/kicad-altium-fix.git
cd kicad-altium-fix

# 2. Проверьте, есть ли баг
./fix_kicad_altium.sh --check

# 3. Примените фикс
./fix_kicad_altium.sh --stable
```

## Использование

| Команда | Описание |
|---------|----------|
| `./fix_kicad_altium.sh` | Фикс всех найденных версий KiCad |
| `./fix_kicad_altium.sh --stable` | Фикс только stable (9.0.x) |
| `./fix_kicad_altium.sh --nightly` | Фикс только nightly |
| `./fix_kicad_altium.sh --check` | Проверка без изменений |
| `./fix_kicad_altium.sh --restore` | Откат к оригинальному файлу |
| `./fix_kicad_altium.sh --list-cache` | Показать кэшированные сборки |
| `./fix_kicad_altium.sh --clean-cache` | Очистить кэш |
| `./fix_kicad_altium.sh --help` | Справка |

## Как это работает

1. **Определение** — скрипт находит установленные KiCad (stable/nightly)
2. **Проверка** — тестирует импорт `test/Attiny-test.SchLib` через `kicad-cli`
3. **Кэш** — если для данной версии есть кэш, установка за секунды
4. **Сборка** — клонирует исходники точной версии, применяет патч, собирает только `_eeschema.kiface`
5. **Кэширование** — собранный файл сохраняется в `cache/` для повторного использования
6. **Установка** — заменяет системный `_eeschema.kiface` (бэкап в `.orig`)
7. **Верификация** — проверяет, что импорт теперь работает
8. **Очистка** — удаляет исходники (~1 ГБ), оставляя только кэш (~40 МБ)

## Кэширование

Собранный `_eeschema.kiface` сохраняется в директории `cache/` с привязкой к версии.
При повторном запуске сборка пропускается — файл устанавливается из кэша.

```bash
# Посмотреть кэш
./fix_kicad_altium.sh --list-cache

# Кэш переносим между машинами с одинаковой ОС и архитектурой
```

## Требования

- **ОС:** Ubuntu / Linux Mint / Debian (apt-based)
- **KiCad:** 9.0.x stable или nightly
- **Для сборки:** cmake, ninja, g++, git + dev-пакеты (скрипт установит автоматически)
- **sudo:** для замены системного файла

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
