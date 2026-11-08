# KiCad Local Patches

Коллекция патчей для KiCad с автоматической сборкой и установкой.  
Актуальная серия — **KiCad 10.0.8** (выпуск от 30 октября 2026): 20 патчей,
включая исправление падения при добавлении библиотеки с открытым редактором.
Сохранены серии для 9.0.7, 9.0.8, 10.0.1–10.0.5 и 10.0.7.
[Миграция, исправление и результаты проверок](patches/kicad-10.0.8/README.md).

## Патчи

| Патч | Версия | Статус | Описание |
|------|--------|--------|----------|
| `0001-smooth-drag-zoom` | 9.0.7 | ✅ работает | Фиксирует курсор при drag-zoom (средняя кнопка мыши) |
| `0002-altium-null-byte` | 9.0.7 | ⬆️ upstream в 9.0.8 | Фикс краша при импорте Altium `.SchLib` с бинарными блоками |
| `0003-auto-bus-entry` | 9.0.7 | ✅ работает | Авто-конвертация 45° wire в bus entry |
| `0004-group-by-column` | 9.0.7 | ✅ работает | Группировка по колонке в дереве библиотек |
| `0005-auto-bus-entry-posture-fix` | 9.0.7 | ✅ работает | Исправление posture для авто bus entry |
| `local-patches-combined` | 9.0.8 | ✅ работает | Все патчи кроме altium-null-byte (уже в upstream) |
| `0002..0018` | 10.0.5 | ✅ сборка | Полная серия локальных патчей; `0001` уже реализован upstream |
| `0002..0020` | 10.0.7 | Историческая серия | 19 патчей; исправление кириллических обозначений добавлено после последней сборки |
| `0002..0021` | 10.0.8 | Собрана и установлена (Arch) | 20 патчей; защита объектов кэша от удаления во время обновления дерева |
| `gost-font-multiline` | standalone | ✅ работает | Фикс integer truncation в `GetInterline()` для GOST-шрифтов |
| `bus-entry-size-properties` | standalone | ✅ работает | Size X/Y в properties bus entry |

## Быстрый старт

### Debian / Ubuntu

```bash
# 1. Посмотреть план (ничего не меняет)
./scripts/build_and_install_ubuntu.sh --check

# 2. Собрать и установить (первый раз — 30-60 мин)
./scripts/build_and_install_ubuntu.sh

# 3. Повторная установка — из кэша (секунды)
./scripts/build_and_install_ubuntu.sh --from-cache

# 4. Откат к оригинальному KiCad
./scripts/build_and_install_ubuntu.sh --restore
```
## Клиентский массовый KiCad-маппинг

Скрипт `scripts/kicad_mapping.py` предназначен для массовой правки EDA-Core
из клиентского окружения KiCad. Параметры подключения он умеет читать из
`.kicad_dbl` (`source.connection_string`), поэтому отдельный серверный `.env`
не обязателен. Файл подключения ищется автоматически: `KICAD_DBL_PATH`,
`${KICAD_LIB_DIR_USER}/eda-core.kicad_dbl`, пути из `kicad_common.json`, затем
типовые пользовательские директории KiCad. Если в файле KiCad указан read-only
пользователь, для записи переопределите пользователя и пароль через
`DB_USER` / `DB_PASSWORD` или `--db-user` / `--db-password`.

```bash
# Один раз подготовить Python-драйвер PostgreSQL
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# Проверить, какое подключение будет использовано
./scripts/kicad_mapping.py connection

# Сначала посмотреть выборку: резисторы 0603
./scripts/kicad_mapping.py filter -c "Резисторы" -t 0603 --no-output

# Массово прописать symbol, footprint и KiCad Reference override
./scripts/kicad_mapping.py apply \
  -c "Резисторы" -t 0603 \
  --symbol "Ki-Resistors:R-0,05" \
  --footprint "Ki-Resistors:R_0603" \
  --reference-prefix R

# Более гибкие поля поиска и предварительный прогон без записи
./scripts/kicad_mapping.py apply \
  --filter category=Резисторы \
  --filter tolerance=1% \
  --set symbol=Device:R \
  --set footprint=Resistor_SMD:R_0603_1608Metric \
  --dry-run
```

Поле `reference_prefix` в базе попадает в KiCad как `Reference`; его же можно
задавать алиасами `--reference` или `--designator`. Список поддерживаемых полей:

```bash
./scripts/kicad_mapping.py fields
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
./scripts/build_and_install_arch.sh --version 10.0.8 --rebuild

# 4. Повторная установка из кэша
./scripts/build_and_install_arch.sh --from-cache

# 5. Откат к оригинальным файлам Arch-пакета
./scripts/build_and_install_arch.sh --restore
```

## Обновление до KiCad 10.0.8

Оба установщика без `--version` выбирают новейшую поддержанную стабильную
серию — сейчас 10.0.8. Если подходящего бинарного кэша ещё нет, сначала
выполните сборку. `--from-cache` не пересобирает старый кэш 10.0.7.

### Arch Linux

```bash
# Проверить, что локальные патчи ложатся на чистую 10.0.8
./scripts/build_and_install_arch.sh --version 10.0.8 --check

# Собрать 10.0.8 с локальными патчами в кэш без установки
nice -n 10 ionice -c 2 -n 7 ./scripts/build_and_install_arch.sh --version 10.0.8 --build-only --rebuild -j "$(nproc)"

# Установить уже собранный кэш поверх текущего KiCad
./scripts/build_and_install_arch.sh --version 10.0.8 --from-cache

# Либо одним шагом: собрать и установить поверх текущего KiCad
./scripts/build_and_install_arch.sh --version 10.0.8 --rebuild
```

Сборка использует все доступные потоки (`nproc`); `nice` и `ionice` в примере
понижают её приоритет, чтобы она уступала ресурсы интерактивным приложениям.
Без `-j` установщик также выбирает `nproc` автоматически.

На Arch скрипт проверяет пакеты через `pacman`, собирает staged-дерево с layout
`/usr/lib` и после установки сверяет `kicad-cli version` с целевой версией.
Пакеты ставятся через `pacman -Syu --needed`: обновляются базы и предлагается
полное обновление системы с обычным подтверждением pacman. Это предотвращает
загрузку удалённых версий из устаревшей базы (HTTP 404). После обновления
зависимостей кэш проверяется повторно до копирования в `/usr`; если он больше
не запускается, установщик остановится и предложит `--rebuild`.

### Защита локальной сборки Arch от замены

Установщик заменяет файлы системного пакета `kicad` файлами сборки с патчами.
Обычное обновление этого пакета через pacman возвращает официальные бинарники.
После успешной установки и проверки Arch-установщик спрашивает:
`Block system updates of the kicad package? [y/N]`. При ответе `y`, `yes` или `да`
он добавляет отдельную строку `IgnorePkg = kicad` в `[options]` файла
`/etc/pacman.conf`. Pacman объединяет повторные директивы `IgnorePkg`, поэтому
существующие исключения, комментарии и подключённые файлы сохраняются.
Перед заменой проверяется конфигурация и создаётся резервная копия рядом:
`/etc/pacman.conf.before-kicad-pin-*`. Эти копии сохраняются для ручного отката;
удаляйте ненужные копии после проверки настройки.

Enter, отказ или конец ввода оставляют конфигурацию без изменений. Если KiCad
уже исключён из обновлений (в том числе маской), повторный вопрос не задаётся.
Без интерактивного stdin, а также при `--check`, `--build-only` и `--restore`
блокировка не предлагается. Ошибка записи блокировки сообщается отдельно и
не отменяет успешную установку. Откат бинарников не снимает уже установленную
блокировку.

При ручной настройке можно добавить `kicad` в существующий `IgnorePkg`:

```ini
IgnorePkg = cursor-bin kicad
```

Проверка действующей настройки:

```bash
pacman-conf IgnorePkg
```

Блокируется автоматическое обновление только `kicad`; библиотеки символов,
посадочных мест и 3D-моделей продолжают обновляться. Явную переустановку
`kicad` через pacman подтверждать только при намеренном переходе на официальную
сборку. Для снятия блокировки удалите из `IgnorePkg` только слово `kicad`.

Исключение пакета не фиксирует версии его системных зависимостей. Если после
их обновления сохранённая сборка перестала загружать `.kiface`, пересоберите
ту же серию под текущие зависимости; установщик проверяет загрузку редактора
через импорт тестовых библиотек до замены системных файлов.

### Debian / Ubuntu

```bash
# Проверить серию на чистом архиве 10.0.8
./scripts/build_and_install_ubuntu.sh --version 10.0.8 --check

# Собрать в кэш без установки
./scripts/build_and_install_ubuntu.sh --version 10.0.8 --build-only --rebuild

# Установить подготовленный кэш и обновить официальные библиотеки
./scripts/build_and_install_ubuntu.sh --version 10.0.8 --from-cache --update-libraries

# Либо собрать и установить одним шагом
./scripts/build_and_install_ubuntu.sh --version 10.0.8 --rebuild --update-libraries
```

На Debian/Ubuntu установщик проверяет пакеты через `dpkg`/`apt` и использует
multiarch-layout `/usr/lib/<triplet>`.

## Как работает build_and_install_ubuntu.sh

1. **Выбирает** новейшую поддержанную стабильную серию или `--version`; для `--restore` определяет установленную пакетную версию
2. **Находит** папку `patches/kicad-X.X.X/` с патчами для этой версии
3. **Вычисляет** хэш набора патчей → проверяет кэш `cache/kicad-X.X.X-HASH/`
4. **Если кэш есть** → предлагает установить за секунды
5. **Если кэша нет**:
   - скачивает официальный архив исходников KiCad и распаковывает его в `kicad-src/`
   - последовательно применяет патчи после проверки каждого через `patch --dry-run`
   - собирает (`cmake --build -j$(nproc)`)
   - сохраняет результат в кэш
6. **Проверяет сборку**: точную версию CLI и импорт обоих тестовых `.SchLib`; только после успеха записывает `.meta` готового кэша
7. **Делает бэкап** оригинальных системных файлов (`cache/kicad-X.X.X-original/`)
8. **Устанавливает** из кэша в системную директорию KiCad (требует `sudo`)

## Кэш сборки и очистка

По умолчанию кэш хранится в каталоге `cache/` в корне этого репозитория.
Готовые сборки, скачанные архивы, распакованные исходники и промежуточные
файлы компиляции занимают место отдельно:

| Каталог | Содержимое |
| --- | --- |
| `cache/kicad-arch-<версия>-<хэш>/` | Готовые сборки Arch для установки через `--from-cache` |
| `cache/kicad-<версия>-<хэш>/` | Готовые сборки Debian/Ubuntu |
| `cache/*-original/` | Резервные копии системных файлов для отката |
| `cache/sources/` | Скачанные архивы исходников |
| `kicad-src-arch/` | Распакованные исходники Arch; включает вложенный каталог `build/` |
| `kicad-src/` | Распакованные исходники Debian/Ubuntu; включает вложенный каталог `build/` |
| `kicad-src-audit/`, `kicad-src-upstream/` | Дополнительные копии исходников для анализа; могут содержать свои сборки |
| `kicad-src-arch/build/` | Промежуточные файлы компиляции Arch |
| `kicad-src/build/` | Промежуточные файлы компиляции Debian/Ubuntu |

Все команды ниже выполняются из корня репозитория, после завершения сборки
и установки.

```bash
# Посмотреть готовые сборки Arch
./scripts/build_and_install_arch.sh --list-cache

# Удалить все кэшированные сборки Arch, включая последнюю версию
./scripts/build_and_install_arch.sh --clean-cache
```

Очистка Arch удаляет каталоги `cache/kicad-arch-*`, кроме `*-original`.
Установленный KiCad и резервные копии сохраняются. Для следующей установки
через `--from-cache` потребуется заново подготовить сборку.

Распакованные исходники, промежуточные файлы и архивы эта команда не удаляет.
Их можно очистить отдельно:

```bash
# Удалить промежуточные файлы компиляции — выберите свою платформу
rm -rf -- kicad-src-arch/build  # Arch
rm -rf -- kicad-src/build       # Debian/Ubuntu

# Либо удалить всё дерево исходников вместе с вложенной сборкой
rm -rf -- kicad-src-arch        # Arch
rm -rf -- kicad-src             # Debian/Ubuntu

# Удалить дополнительные копии для анализа, если они больше не нужны
rm -rf -- kicad-src-audit kicad-src-upstream

# При необходимости удалить скачанные архивы исходников
rm -f -- cache/sources/kicad-*.tar.gz
```

Удаление только `build/` оставляет распакованные исходники на диске.
Удаление всего дерева исходников сохраняет установленный KiCad и готовые
сборки в `cache/`; для `--from-cache` исходники не нужны. Перед удалением
дерева перенесите нужные локальные изменения в патчи. При следующей сборке
установщик заново распакует исходники, а при отсутствии архива скачает его.

Посмотреть размеры всех основных каталогов:

```bash
du -sh cache/* kicad-src kicad-src-* kicad-build-src 2>/dev/null

# Отдельно оценить промежуточные файлы внутри деревьев исходников
du -sh kicad-src/build kicad-src-*/build 2>/dev/null
```

Размер дерева исходников уже включает его `build/`: эти два значения
не нужно складывать при подсчёте общего места.

Если при запуске задавались `CACHE_DIR`, `SOURCE_CACHE_DIR` или `SRC_DIR`,
используйте соответствующие пути. Для `--list-cache` и `--clean-cache`
передайте то же значение `CACHE_DIR`, что использовалось при сборке.

## Структура проекта

```
patches/
  kicad-9.0.7/          # серия патчей для 9.0.7 (5 штук)
  kicad-9.0.8/          # combined diff для 9.0.8
  kicad-10.0.4/         # общие файлы патчей для ветки 10.0.x
  kicad-10.0.5/         # проверенный порядок патчей для 10.0.5
  kicad-10.0.7/         # предыдущая серия; 19 патчей
  kicad-10.0.8/         # актуальная серия; 20 патчей, включая library reload fix
  standalone/           # независимые патчи (gost, bus-entry)
scripts/
  build_and_install_ubuntu.sh       # Debian/Ubuntu: патч → сборка → установка
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

- **ОС:** Ubuntu / Debian (`scripts/build_and_install_ubuntu.sh`) или Arch Linux (`scripts/build_and_install_arch.sh`)
- **KiCad:** для Debian/Ubuntu — установленный системный KiCad либо явный `--version`; для Arch — необязательно, установщик сам ставит `kicad`, `kicad-library`, `kicad-library-3d`
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
