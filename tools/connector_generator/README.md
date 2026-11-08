# Connector Generator

Экспериментальный генератор регулярных символов разъемов KiCad.

Первый этап умеет:

- читать серии и точечные override из TOML;
- генерировать базовый body style `1`;
- сохранять ручные альтернативы body style `2+`;
- показывать diff или писать обновленный `.kicad_sym`.

Основной формат для массовой генерации:

```toml
[defaults.pin_labels]
show_pin_numbers = true
show_pin_names = false

[defaults.geometry]
body_fill = "background"

[[series]]
prefix = "Con"
rows = [1, 2, 3]
schemes = ["R", "S"]
reference = "X"
value = "XX"
display_name = "Разъем универсальный"
show_pin_numbers = true
show_pin_names = false
zero_pad_pins = 2
skip_single_row_non_row = true

[series.scheme_map]
R = "row"
S = "column"
Z = "column_snake"

[series.pins_per_row_by_rows]
"1" = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40]
"2" = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40]
"3" = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40]
```

`[[symbols]]` можно использовать для точечного переопределения отдельного символа.
Если `pins_per_row_by_rows` не задан, используется старый общий `pins_per_row`.

Запуск без записи:

```bash
python3 tools/connector_generator/connector_generator.py \
  --config tools/connector_generator/connectors.toml \
  --diff
```

Проверка, что файл уже соответствует конфигу:

```bash
python3 tools/connector_generator/connector_generator.py \
  --config tools/connector_generator/connectors.toml \
  --check
```

Запись в библиотеку:

```bash
python3 tools/connector_generator/connector_generator.py \
  --config tools/connector_generator/connectors.toml \
  --write
```

## Запуск из KiCad

Для запуска через меню KiCad установлен ActionPlugin:

```bash
./scripts/install_connector_generator_plugin.sh
```

После перезапуска KiCad:

```text
PCB Editor -> Tools -> External Plugins -> Generate Connector Symbols
```

В GUI основной сценарий:

1. Выбрать ряды, отдельные списки пинов для 1/2/3 рядов и схемы нумерации.
2. Нажать `Обновить список`.
3. Проверить таблицу пинов выбранного символа.
4. Нажать `Сгенерировать`.

Перед `--write` обязательно смотреть `git diff` в библиотечном репозитории.

Разбор строк и границ S-expression использует общий `tools/kicad_sexpr.py`;
владелец генерации и сохранения символов остаётся `connector_generator.py`.
