# Патчи KiCad

## kicad-9.0.7/

Серия из 5 патчей в формате `git format-patch`. Применяются последовательно.

| Файл | Затрагивает | Описание |
|------|-------------|----------|
| `0001-smooth-drag-zoom.patch` | `wx_view_controls.cpp` | Фиксирует курсор мыши при drag-zoom (средняя кнопка) |
| `0002-altium-null-byte.patch` | `altium_binary_parser.cpp` | Краш при импорте Altium .SchLib с бинарными PinFrac-блоками. **Upstream в 9.0.8.** |
| `0003-auto-bus-entry.patch` | `sch_line_wire_bus_tool.cpp` | Авто-конвертация 45° wire→bus entry при подключении к шине |
| `0004-group-by-column.patch` | 9 файлов eeschema | Группировка элементов по колонке в дереве библиотек |
| `0005-auto-bus-entry-posture-fix.patch` | `sch_line_wire_bus_tool.cpp` | Доработка 0003: правильный posture=true для авто bus entry |

Применить все:
```bash
./scripts/build_and_install_ubuntu.sh --version 9.0.7
```

## kicad-9.0.8/

| Файл | Описание |
|------|----------|
| `local-patches-combined.diff` | Combined diff: 0001 + 0003 + 0004 + 0005 (без altium-null-byte — он уже в upstream) |

## kicad-10.0.4/

Тематическая серия патчей. Файл `series` задаёт порядок применения и является
единственным источником этого порядка для установщиков.

| Файл | Описание |
|------|----------|
| `0001-gost-font-interline.patch` | Фикс расчёта interline для GOST/outline-шрифтов |
| `0002-library-tree-group-by-column.patch` | Группировка symbol/footprint library tree по выбранной колонке |
| `0003-smooth-drag-zoom.patch` | Фиксация курсора при drag-zoom |
| `0004-bus-entry-size-properties.patch` | Поля Size X/Y в properties bus entry |
| `0005-auto-bus-entry.patch` | Авто-конвертация 45° wire-сегмента в bus entry |
| `0006-database-empty-reference-field.patch` | Не затирать Reference пустым значением из database library |
| `0007-project-tree-extra-files.patch` | Показывать lib-table, `.kicad_dbl` и JSON-файлы в Project Tree |
| `0008-schematic-page-background.patch` | Отдельный слой цвета фона листа схемы |
| `0009..0018` | Боковая панель символов и доработки дерева библиотек |

Проверить совместимость:
```bash
./scripts/build_and_install_ubuntu.sh --version 10.0.4 --check
```

Собрать в кэш без установки:
```bash
./scripts/build_and_install_ubuntu.sh --version 10.0.4 --build-only --rebuild
```

Установить из кэша:
```bash
./scripts/build_and_install_ubuntu.sh --version 10.0.4 --from-cache --update-libraries
```

Собрать и установить одним шагом:
```bash
./scripts/build_and_install_ubuntu.sh --version 10.0.4 --rebuild --update-libraries
```

## kicad-10.0.5/

Проверенная серия для KiCad 10.0.5 переиспользует совместимые файлы патчей
10.0.4 через свой `series`. Патч `0001-gost-font-interline.patch` исключён:
соответствующий расчёт interline уже изменён upstream в 10.0.5. Патчи
`0002..0018` последовательно применяются к чистому архиву 10.0.5.

```bash
# Arch Linux
./scripts/build_and_install_arch.sh --version 10.0.5 --check
./scripts/build_and_install_arch.sh --version 10.0.5 --build-only --rebuild
./scripts/build_and_install_arch.sh --version 10.0.5 --from-cache

# Debian / Ubuntu
./scripts/build_and_install_ubuntu.sh --version 10.0.5 --check
./scripts/build_and_install_ubuntu.sh --version 10.0.5 --build-only --rebuild
./scripts/build_and_install_ubuntu.sh --version 10.0.5 --from-cache --update-libraries
```

## standalone/

Самостоятельные патчи, не привязанные к конкретной версии.

| Файл | Описание | Совместимость |
|------|----------|---------------|
| `gost-font-multiline.patch` | Integer truncation в `GetInterline()` для GOST-шрифтов | 9.0.7, 9.0.8 |
| `bus-entry-size-properties.patch` | Поля Size X/Y в Properties диалоге bus entry | 9.0.7 |
