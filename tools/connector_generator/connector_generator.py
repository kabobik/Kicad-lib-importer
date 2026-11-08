#!/usr/bin/env python3
"""Generate regular KiCad connector symbols while preserving manual variants."""

from __future__ import annotations

import argparse
import difflib
import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

# Shared span reader also serves PCB/schematic connectivity recovery.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.kicad_sexpr import matching_paren, read_quoted, skip_string  # noqa: E402


DEFAULT_SCHEME_MAP = {
    "R": "row",
    "S": "column",
    "Z": "column_snake",
}

REFERENCE_FIELD_Y = 1.25
VALUE_FIELD_BOTTOM_OFFSET = 2.5


@dataclass(frozen=True)
class Geometry:
    body_width: float = 20.0
    pin_pitch: float = 5.0
    pin_length: float = 2.5
    body_fill: str = "none"


@dataclass(frozen=True)
class SymbolSpec:
    name: str
    rows: int
    pins_per_row: int
    numbering: str
    reference: str = "X"
    value: str = "XX"
    display_name: str = ""
    show_pin_numbers: bool = True
    show_pin_names: bool = False
    geometry: Geometry = Geometry()


@dataclass(frozen=True)
class SeriesSpec:
    prefix: str
    rows: tuple[int, ...]
    pins_per_row: tuple[int, ...]
    pins_per_row_by_rows: dict[int, tuple[int, ...]] | None
    schemes: tuple[str, ...]
    scheme_map: dict[str, str]
    reference: str = "X"
    value: str = "XX"
    display_name: str = ""
    show_pin_numbers: bool = True
    show_pin_names: bool = False
    zero_pad_pins: int = 2
    skip_single_row_non_row: bool = True
    geometry: Geometry = Geometry()


@dataclass(frozen=True)
class SymbolBlock:
    name: str
    start: int
    end: int
    text: str


def fmt_num(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:g}"






def is_list_at(text: str, i: int, head: str) -> bool:
    token = f"({head}"
    return text.startswith(token, i) and (
        i + len(token) == len(text) or text[i + len(token)].isspace() or text[i + len(token)] == ")"
    )


def symbol_name_at(text: str, i: int) -> str:
    pos = i + len("(symbol")
    while pos < len(text) and text[pos].isspace():
        pos += 1
    if pos >= len(text) or text[pos] != '"':
        raise ValueError(f"symbol at offset {i} has no quoted name")
    name, _ = read_quoted(text, pos)
    return name




def find_symbol_blocks(text: str, target_depth: int) -> list[SymbolBlock]:
    blocks: list[SymbolBlock] = []
    depth = 0
    i = 0

    while i < len(text):
        ch = text[i]
        if ch == '"':
            i = skip_string(text, i)
            continue
        if ch == "(":
            if depth == target_depth and is_list_at(text, i, "symbol"):
                end = matching_paren(text, i)
                blocks.append(SymbolBlock(symbol_name_at(text, i), i, end, text[i:end]))
                i = end
                continue
            depth += 1
        elif ch == ")":
            depth -= 1
        i += 1

    return blocks


def find_list_blocks(text: str, head: str, target_depth: int) -> list[str]:
    blocks: list[str] = []
    depth = 0
    i = 0

    while i < len(text):
        ch = text[i]
        if ch == '"':
            i = skip_string(text, i)
            continue
        if ch == "(":
            if depth == target_depth and is_list_at(text, i, head):
                end = matching_paren(text, i)
                blocks.append(text[i:end])
                i = end
                continue
            depth += 1
        elif ch == ")":
            depth -= 1
        i += 1

    return blocks


def child_symbol_blocks(symbol_text: str) -> list[SymbolBlock]:
    return find_symbol_blocks(symbol_text, target_depth=1)


def child_style(symbol_name: str, parent_name: str) -> tuple[int, int] | None:
    prefix = parent_name + "_"
    if not symbol_name.startswith(prefix):
        return None

    suffix = symbol_name[len(prefix) :]
    parts = suffix.rsplit("_", 1)
    if len(parts) != 2:
        return None

    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def manual_children(existing_symbol_text: str | None, parent_name: str) -> list[str]:
    if not existing_symbol_text:
        return []

    out: list[str] = []
    for block in child_symbol_blocks(existing_symbol_text):
        style = child_style(block.name, parent_name)
        if style is None or style[1] >= 2:
            out.append("\t\t" + block.text)
    return out


def manual_variant_count(existing_symbol_text: str | None, parent_name: str) -> int:
    if not existing_symbol_text:
        return 0

    count = 0
    for block in child_symbol_blocks(existing_symbol_text):
        style = child_style(block.name, parent_name)
        if style is None or style[1] >= 2:
            count += 1
    return count


def existing_body_styles(existing_symbol_text: str | None) -> str | None:
    if not existing_symbol_text:
        return None

    blocks = find_list_blocks(existing_symbol_text, "body_styles", target_depth=1)
    if not blocks:
        return None
    return "\t\t" + blocks[0]


def pin_number(spec: SymbolSpec, row: int, index: int) -> int:
    scheme = spec.numbering

    if scheme == "row":
        return row * spec.pins_per_row + index + 1

    if scheme == "column":
        return index * spec.rows + row + 1

    if scheme == "column_snake":
        row_in_column = row if index % 2 == 0 else spec.rows - row - 1
        return index * spec.rows + row_in_column + 1

    raise ValueError(f"unsupported numbering scheme: {scheme}")


def pin_matrix(spec: SymbolSpec) -> list[list[int]]:
    return [
        [pin_number(spec, row, index) for row in range(spec.rows)]
        for index in range(spec.pins_per_row)
    ]


def format_pin_preview(spec: SymbolSpec) -> str:
    matrix = pin_matrix(spec)
    width = max(len(str(number)) for row in matrix for number in row)
    rows = ["  ".join(f"{number:>{width}}" for number in row) for row in matrix]
    return "\n".join(
        [
            f"{spec.name}",
            f"{spec.rows} ряд(а), {spec.pins_per_row} позиций, {spec.numbering}",
            "",
            *rows,
        ]
    )


def validate_numbers(spec: SymbolSpec) -> None:
    nums = [
        pin_number(spec, row, index)
        for row in range(spec.rows)
        for index in range(spec.pins_per_row)
    ]
    expected = list(range(1, spec.rows * spec.pins_per_row + 1))

    if sorted(nums) != expected:
        raise ValueError(
            f"{spec.name}: numbering {spec.numbering!r} produced {nums}, expected {expected}"
        )


def generate_property(
    name: str,
    value: str,
    x: float,
    y: float,
    size: float,
    hide: bool = True,
    justify: str | None = None,
    do_not_autoplace: bool = True,
) -> str:
    hide_line = "\n\t\t\t(hide yes)" if hide else ""
    justify_block = f"\n\t\t\t\t(justify {justify})" if justify else ""
    autoplace = "yes" if do_not_autoplace else "no"

    return (
        f'\t\t(property "{name}" "{value}"\n'
        f"\t\t\t(at {fmt_num(x)} {fmt_num(y)} 0)\n"
        "\t\t\t(show_name no)\n"
        f"\t\t\t(do_not_autoplace {autoplace})"
        f"{hide_line}\n"
        "\t\t\t(effects\n"
        "\t\t\t\t(font\n"
        f"\t\t\t\t\t(size {fmt_num(size)} {fmt_num(size)})\n"
        "\t\t\t\t)"
        f"{justify_block}\n"
        "\t\t\t)\n"
        "\t\t)"
    )


def generate_pin_label_settings(spec: SymbolSpec) -> list[str]:
    lines: list[str] = []

    if not spec.show_pin_numbers:
        lines += [
            "\t\t(pin_numbers",
            "\t\t\t(hide yes)",
            "\t\t)",
        ]

    if spec.show_pin_names:
        lines += [
            "\t\t(pin_names",
            "\t\t\t(offset 1)",
            "\t\t)",
        ]
    else:
        lines += [
            "\t\t(pin_names",
            "\t\t\t(hide yes)",
            "\t\t)",
        ]

    return lines


def generate_unit(spec: SymbolSpec, row: int) -> str:
    geo = spec.geometry
    height = spec.pins_per_row * geo.pin_pitch
    unit = row + 1
    lines: list[str] = [f'\t\t(symbol "{spec.name}_{unit}_1"']

    lines += [
        "\t\t\t(rectangle",
        "\t\t\t\t(start 0 0)",
        f"\t\t\t\t(end {fmt_num(geo.body_width)} -{fmt_num(height)})",
        "\t\t\t\t(stroke",
        "\t\t\t\t\t(width 0)",
        "\t\t\t\t\t(type solid)",
        "\t\t\t\t)",
        "\t\t\t\t(fill",
        f"\t\t\t\t\t(type {geo.body_fill})",
        "\t\t\t\t)",
        "\t\t\t)",
    ]

    for idx in range(1, spec.pins_per_row):
        y = idx * geo.pin_pitch
        lines += [
            "\t\t\t(polyline",
            "\t\t\t\t(pts",
            f"\t\t\t\t\t(xy 0 -{fmt_num(y)}) (xy {fmt_num(geo.body_width)} -{fmt_num(y)})",
            "\t\t\t\t)",
            "\t\t\t\t(stroke",
            "\t\t\t\t\t(width 0)",
            "\t\t\t\t\t(type solid)",
            "\t\t\t\t)",
            "\t\t\t\t(fill",
            "\t\t\t\t\t(type none)",
            "\t\t\t\t)",
            "\t\t\t)",
        ]

    lines += [
        "\t\t\t(polyline",
        "\t\t\t\t(pts",
        f"\t\t\t\t\t(xy 5 0) (xy 5 -{fmt_num(height)})",
        "\t\t\t\t)",
        "\t\t\t\t(stroke",
        "\t\t\t\t\t(width 0)",
        "\t\t\t\t\t(type solid)",
        "\t\t\t\t)",
        "\t\t\t\t(fill",
        "\t\t\t\t\t(type none)",
        "\t\t\t\t)",
        "\t\t\t)",
    ]

    for idx in range(spec.pins_per_row):
        number = str(pin_number(spec, row, idx))
        y = idx * geo.pin_pitch + geo.pin_pitch / 2
        lines += [
            f'\t\t\t(text "{number}"',
            f"\t\t\t\t(at 2.5 -{fmt_num(y)} 0)",
            "\t\t\t\t(effects",
            "\t\t\t\t\t(font",
            "\t\t\t\t\t\t(size 2.1844 2.1844)",
            "\t\t\t\t\t)",
            "\t\t\t\t)",
            "\t\t\t)",
        ]
        lines += [
            "\t\t\t(pin passive line",
            f"\t\t\t\t(at -{fmt_num(geo.pin_length)} -{fmt_num(y)} 0)",
            f"\t\t\t\t(length {fmt_num(geo.pin_length)})",
            f'\t\t\t\t(name "{number}"',
            "\t\t\t\t\t(effects",
            "\t\t\t\t\t\t(font",
            "\t\t\t\t\t\t\t(size 1.8 1.8)",
            "\t\t\t\t\t\t)",
            "\t\t\t\t\t)",
            "\t\t\t\t)",
            f'\t\t\t\t(number "{number}"',
            "\t\t\t\t\t(effects",
            "\t\t\t\t\t\t(font",
            "\t\t\t\t\t\t\t(size 1.8 1.8)",
            "\t\t\t\t\t\t)",
            "\t\t\t\t\t)",
            "\t\t\t\t)",
            "\t\t\t)",
        ]

    lines.append("\t\t)")
    return "\n".join(lines)


def generate_symbol(spec: SymbolSpec, existing_symbol_text: str | None = None) -> str:
    validate_numbers(spec)

    geo = spec.geometry
    height = spec.pins_per_row * geo.pin_pitch
    reference_y = REFERENCE_FIELD_Y
    value_y = -height - VALUE_FIELD_BOTTOM_OFFSET
    manual = manual_children(existing_symbol_text, spec.name)
    styles = existing_body_styles(existing_symbol_text) if manual else None

    lines: list[str] = [f'(symbol "{spec.name}"']
    if styles:
        lines.append(styles)

    lines += generate_pin_label_settings(spec)

    lines += [
        "\t\t(exclude_from_sim no)",
        "\t\t(in_bom yes)",
        "\t\t(on_board yes)",
        "\t\t(in_pos_files yes)",
        "\t\t(duplicate_pin_numbers_are_jumpers no)",
        generate_property("Reference", spec.reference, 0, reference_y, 2, hide=False, justify="left"),
        generate_property("Value", spec.value, 0, value_y, 2, hide=False, justify="left bottom"),
        generate_property("Footprint", "", 0, 0, 1.27, do_not_autoplace=False),
        generate_property("Datasheet", "", 0, 0, 1.27, do_not_autoplace=False),
        generate_property("Description", "", 0, 0, 1.27, do_not_autoplace=False),
    ]

    if spec.display_name:
        lines.append(
            generate_property(
                "Name",
                spec.display_name,
                5.5,
                1,
                1.8288,
                justify="left bottom",
                do_not_autoplace=False,
            )
        )

    for row in range(spec.rows):
        lines.append(generate_unit(spec, row))

    lines.extend(manual)
    lines.append("\t)")
    return "\n".join(lines)


def replace_top_level_symbols(library_text: str, replacements: dict[str, str]) -> str:
    blocks = find_symbol_blocks(library_text, target_depth=1)
    out: list[str] = []
    pos = 0
    replaced: set[str] = set()

    for block in blocks:
        out.append(library_text[pos : block.start])
        if block.name in replacements:
            out.append(replacements[block.name])
            replaced.add(block.name)
        else:
            out.append(block.text)
        pos = block.end

    out.append(library_text[pos:])
    result = "".join(out)

    missing = [name for name in replacements if name not in replaced]
    if missing:
        insert_at = result.rfind("\n)")
        if insert_at == -1:
            raise ValueError("cannot find library closing paren")
        addition = "\n" + "\n".join(replacements[name] for name in missing)
        result = result[:insert_at] + addition + result[insert_at:]

    return result


def int_list(values: object, field_name: str) -> tuple[int, ...]:
    if not isinstance(values, list):
        raise ValueError(f"{field_name} must be a list")
    return tuple(int(value) for value in values)


def str_list(values: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(values, list):
        raise ValueError(f"{field_name} must be a list")
    return tuple(str(value) for value in values)


def parse_geometry(data: dict) -> Geometry:
    defaults = data.get("defaults", {})
    geo_defaults = defaults.get("geometry", {})
    return Geometry(
        body_width=float(geo_defaults.get("body_width", 20.0)),
        pin_pitch=float(geo_defaults.get("pin_pitch", 5.0)),
        pin_length=float(geo_defaults.get("pin_length", 2.5)),
        body_fill=str(geo_defaults.get("body_fill", "none")),
    )


def default_pin_label_settings(data: dict) -> tuple[bool, bool]:
    defaults = data.get("defaults", {})
    pin_labels = defaults.get("pin_labels", {})
    return (
        bool(pin_labels.get("show_pin_numbers", True)),
        bool(pin_labels.get("show_pin_names", False)),
    )


def make_symbol_name(prefix: str, rows: int, pins_per_row: int, scheme_code: str, zero_pad: int = 2) -> str:
    pin_text = f"{pins_per_row:0{zero_pad}d}" if zero_pad > 0 else str(pins_per_row)
    return f"{prefix}-{rows}X-{pin_text}P-{scheme_code}"


def parse_series(
    item: dict,
    geometry: Geometry,
    default_show_pin_numbers: bool,
    default_show_pin_names: bool,
) -> SeriesSpec:
    scheme_map = dict(DEFAULT_SCHEME_MAP)
    scheme_map.update({str(key): str(value) for key, value in item.get("scheme_map", {}).items()})
    pins_by_rows = {
        int(rows): int_list(values, f"series.pins_per_row_by_rows.{rows}")
        for rows, values in item.get("pins_per_row_by_rows", {}).items()
    }

    return SeriesSpec(
        prefix=str(item.get("prefix", "Con")),
        rows=int_list(item.get("rows", []), "series.rows"),
        pins_per_row=int_list(item.get("pins_per_row", []), "series.pins_per_row"),
        pins_per_row_by_rows=pins_by_rows or None,
        schemes=str_list(item.get("schemes", ["R"]), "series.schemes"),
        scheme_map=scheme_map,
        reference=str(item.get("reference", "X")),
        value=str(item.get("value", "XX")),
        display_name=str(item.get("display_name", "")),
        show_pin_numbers=bool(item.get("show_pin_numbers", default_show_pin_numbers)),
        show_pin_names=bool(item.get("show_pin_names", default_show_pin_names)),
        zero_pad_pins=int(item.get("zero_pad_pins", 2)),
        skip_single_row_non_row=bool(item.get("skip_single_row_non_row", True)),
        geometry=geometry,
    )


def specs_from_series(series: SeriesSpec) -> list[SymbolSpec]:
    specs: list[SymbolSpec] = []

    for rows in series.rows:
        pin_values = series.pins_per_row
        if series.pins_per_row_by_rows is not None:
            pin_values = series.pins_per_row_by_rows.get(rows, ())
        if not pin_values:
            raise ValueError(f"no pins_per_row configured for {rows} row(s) in series {series.prefix!r}")

        for pins in pin_values:
            for scheme_code in series.schemes:
                numbering = series.scheme_map.get(scheme_code)
                if not numbering:
                    raise ValueError(f"unknown scheme code {scheme_code!r} in series {series.prefix!r}")
                if series.skip_single_row_non_row and rows == 1 and numbering != "row":
                    continue

                specs.append(
                    SymbolSpec(
                        name=make_symbol_name(
                            series.prefix,
                            rows,
                            pins,
                            scheme_code,
                            zero_pad=series.zero_pad_pins,
                        ),
                        rows=rows,
                        pins_per_row=pins,
                        numbering=numbering,
                        reference=series.reference,
                        value=series.value,
                        display_name=series.display_name,
                        show_pin_numbers=series.show_pin_numbers,
                        show_pin_names=series.show_pin_names,
                        geometry=series.geometry,
                    )
                )

    return specs


def parse_symbol(
    item: dict,
    geometry: Geometry,
    default_show_pin_numbers: bool,
    default_show_pin_names: bool,
) -> SymbolSpec:
    return SymbolSpec(
        name=item["name"],
        rows=int(item["rows"]),
        pins_per_row=int(item["pins_per_row"]),
        numbering=item["numbering"],
        reference=item.get("reference", "X"),
        value=item.get("value", "XX"),
        display_name=item.get("display_name", ""),
        show_pin_numbers=bool(item.get("show_pin_numbers", default_show_pin_numbers)),
        show_pin_names=bool(item.get("show_pin_names", default_show_pin_names)),
        geometry=geometry,
    )


def dedupe_specs(specs: list[SymbolSpec]) -> list[SymbolSpec]:
    by_name: dict[str, SymbolSpec] = {}
    order: list[str] = []

    for spec in specs:
        if spec.name not in by_name:
            order.append(spec.name)
        by_name[spec.name] = spec

    return [by_name[name] for name in order]


def load_config(config_path: Path) -> tuple[Path, list[SeriesSpec], list[SymbolSpec]]:
    config_path = config_path.expanduser().resolve()
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    library_path = Path(os.path.expandvars(data["library"]["path"])).expanduser()
    if not library_path.is_absolute():
        library_path = (config_path.parent / library_path).resolve()
    geometry = parse_geometry(data)
    show_pin_numbers, show_pin_names = default_pin_label_settings(data)
    series = [
        parse_series(item, geometry, show_pin_numbers, show_pin_names)
        for item in data.get("series", [])
    ]
    symbols = [
        parse_symbol(item, geometry, show_pin_numbers, show_pin_names)
        for item in data.get("symbols", [])
    ]
    return library_path, series, symbols


def load_specs(config_path: Path) -> tuple[Path, list[SymbolSpec]]:
    library_path, series, symbols = load_config(config_path)
    specs: list[SymbolSpec] = []

    for item in series:
        specs.extend(specs_from_series(item))
    specs.extend(symbols)

    return library_path, dedupe_specs(specs)


def generate_library(library_text: str, specs: list[SymbolSpec]) -> str:
    existing = {block.name: block.text for block in find_symbol_blocks(library_text, target_depth=1)}
    replacements = {
        spec.name: generate_symbol(spec, existing_symbol_text=existing.get(spec.name)) for spec in specs
    }
    return replace_top_level_symbols(library_text, replacements)


def unified_diff(old: str, new: str, old_name: str, new_name: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=old_name,
            tofile=new_name,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--write", action="store_true", help="overwrite library file")
    parser.add_argument("--check", action="store_true", help="fail if generated output differs")
    parser.add_argument("--diff", action="store_true", help="print unified diff")
    parser.add_argument("--output", type=Path, help="write generated library to another file")
    args = parser.parse_args(argv)

    library_path, specs = load_specs(args.config)
    library_text = library_path.read_text(encoding="utf-8")
    generated = generate_library(library_text, specs)

    if args.diff or args.check:
        diff = unified_diff(str(library_text), str(generated), str(library_path), "generated")
        if diff:
            sys.stdout.write(diff)

    if args.check:
        return 1 if library_text != generated else 0

    if args.output:
        args.output.write_text(generated, encoding="utf-8")
        return 0

    if args.write:
        library_path.write_text(generated, encoding="utf-8")
        return 0

    print(f"Generated {len(specs)} symbols from {args.config}. Use --diff, --output, or --write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
