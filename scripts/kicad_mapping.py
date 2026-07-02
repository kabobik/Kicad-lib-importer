#!/usr/bin/env python3
"""Client-side bulk updater for EDA-Core KiCad database mappings."""
from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

TEXT_KIND = "text"
INT_KIND = "int"

SEARCH_FIELDS: dict[str, tuple[str, str, str]] = {
    "id": ('l."код_компонента"', INT_KIND, "ID компонента"),
    "component_id": ('l."код_компонента"', INT_KIND, "ID компонента"),
    "category": ('lt."ElementType"', TEXT_KIND, "Категория / ElementType"),
    "element_type": ('lt."ElementType"', TEXT_KIND, "Категория / ElementType"),
    "subtype": ('lst."ElementSubType"', TEXT_KIND, "Подтип / ElementSubType"),
    "element_subtype": ('lst."ElementSubType"', TEXT_KIND, "Подтип / ElementSubType"),
    "name": ('l."Name"', TEXT_KIND, "Name"),
    "comment": ('l."Comment"', TEXT_KIND, "Comment / номинал"),
    "value": ('l."Value"', TEXT_KIND, "Value"),
    "type": ('l."Type"', TEXT_KIND, "Type / корпус"),
    "package": ('l."Type"', TEXT_KIND, "Type / корпус"),
    "part_number": ('l."Part Number"', TEXT_KIND, "Part Number"),
    "mpn": ('l."Part Number"', TEXT_KIND, "Part Number"),
    "manufacturer": ('l."Manufacturer"', TEXT_KIND, "Manufacturer"),
    "description": ('l."Description"', TEXT_KIND, "Description"),
    "reference": ("l.reference_prefix", TEXT_KIND, "KiCad Reference override"),
    "reference_prefix": ("l.reference_prefix", TEXT_KIND, "KiCad Reference override"),
    "designator": ("l.reference_prefix", TEXT_KIND, "KiCad Reference override"),
    "symbol": ("m.symbol_name", TEXT_KIND, "KiCad Symbol"),
    "kicad_symbol": ("m.symbol_name", TEXT_KIND, "KiCad Symbol"),
    "footprint": ("m.footprint_name", TEXT_KIND, "KiCad Footprint"),
    "kicad_footprint": ("m.footprint_name", TEXT_KIND, "KiCad Footprint"),
}

UPDATABLE_LIBRARY_FIELDS: dict[str, tuple[str, str]] = {
    "reference": ("reference_prefix", "KiCad Reference override"),
    "reference_prefix": ("reference_prefix", "KiCad Reference override"),
    "designator": ("reference_prefix", "KiCad Reference override"),
    "name": ('"Name"', "Name"),
    "comment": ('"Comment"', "Comment"),
    "value": ('"Value"', "Value"),
    "type": ('"Type"', "Type / корпус"),
    "package": ('"Type"', "Type / корпус"),
    "part_number": ('"Part Number"', "Part Number"),
    "mpn": ('"Part Number"', "Part Number"),
    "manufacturer": ('"Manufacturer"', "Manufacturer"),
    "description": ('"Description"', "Description"),
    "tolerance": ('"Tolerance"', "Tolerance"),
    "power_voltage": ('"Power/Voltage"', "Power/Voltage"),
    "comp_file_name": ('"CompFileName"', "CompFileName"),
}

MAPPING_SET_ALIASES = {
    "symbol": "symbol",
    "kicad_symbol": "symbol",
    "footprint": "footprint",
    "kicad_footprint": "footprint",
}


@dataclass
class DbConfig:
    host: str = "localhost"
    port: int = 5432
    database: str = "altium_components"
    user: str = "postgres"
    password: str | None = None
    sslmode: str | None = None

    def as_psycopg(self) -> dict[str, Any]:
        config: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "user": self.user,
        }
        if self.password:
            config["password"] = self.password
        if self.sslmode:
            config["sslmode"] = self.sslmode
        return config


def split_odbc_connection_string(value: str) -> list[str]:
    """Split an ODBC string by semicolons, preserving semicolons in braces."""
    parts: list[str] = []
    buf: list[str] = []
    brace_depth = 0

    for char in value:
        if char == "{":
            brace_depth += 1
        elif char == "}" and brace_depth:
            brace_depth -= 1

        if char == ";" and brace_depth == 0:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
        else:
            buf.append(char)

    part = "".join(buf).strip()
    if part:
        parts.append(part)
    return parts


def parse_connection_string(value: str) -> dict[str, str]:
    items: dict[str, str] = {}
    for part in split_odbc_connection_string(value):
        key, sep, raw_value = part.partition("=")
        if not sep:
            continue
        key = key.strip().lower()
        parsed_value = raw_value.strip()
        if parsed_value.startswith("{") and parsed_value.endswith("}"):
            parsed_value = parsed_value[1:-1]
        items[key] = parsed_value
    return items


def config_from_kicad_dbl(path: Path) -> DbConfig:
    with path.expanduser().open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    source = data.get("source") or {}
    connection_string = source.get("connection_string") or ""
    dsn = source.get("dsn") or ""

    if not connection_string:
        raise SystemExit(
            f"{path} does not contain source.connection_string. "
            f"ODBC DSN '{dsn}' cannot be expanded by this script; pass DB_* env vars or --db-* options."
        )

    parsed = parse_connection_string(connection_string)
    password = parsed.get("pwd") or parsed.get("password") or None
    if password == "CHANGE_ME":
        password = None

    return DbConfig(
        host=parsed.get("server") or parsed.get("host") or "localhost",
        port=int(parsed.get("port") or 5432),
        database=parsed.get("database") or parsed.get("db") or "altium_components",
        user=parsed.get("uid") or parsed.get("user") or "postgres",
        password=password,
        sslmode=parsed.get("sslmode") or None,
    )


def version_sort_key(path: Path) -> tuple[int, ...]:
    parts: list[int] = []
    for item in path.parent.name.split("."):
        try:
            parts.append(int(item))
        except ValueError:
            parts.append(-1)
    return tuple(parts)


def kicad_common_config_paths() -> list[Path]:
    """Return KiCad common config files, newest version first where possible."""
    roots: list[Path] = []
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            roots.append(Path(appdata) / "kicad")
    elif sys.platform == "darwin":
        roots.append(Path.home() / "Library" / "Preferences" / "kicad")
    else:
        roots.append(Path.home() / ".config" / "kicad")

    paths: list[Path] = []
    for root in roots:
        if root.exists():
            paths.extend(root.glob("*/kicad_common.json"))
    return sorted(paths, key=version_sort_key, reverse=True)


def read_kicad_env_vars(config_path: Path) -> dict[str, str]:
    try:
        with config_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}

    values = data.get("environment", {}).get("vars", {})
    if not isinstance(values, dict):
        return {}
    return {str(key): str(value) for key, value in values.items() if value is not None}


def merged_kicad_env_vars() -> dict[str, str]:
    values: dict[str, str] = {}
    for config_path in reversed(kicad_common_config_paths()):
        values.update(read_kicad_env_vars(config_path))
    values.update({key: value for key, value in os.environ.items() if key.startswith("KI")})
    return values


def expand_kicad_vars(value: str, variables: dict[str, str] | None = None) -> str:
    variables = variables or merged_kicad_env_vars()

    def replace_braced(match: re.Match[str]) -> str:
        name = match.group(1)
        return variables.get(name, os.environ.get(name, match.group(0)))

    expanded = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace_braced, value)
    return os.path.expanduser(os.path.expandvars(expanded))


def iter_json_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from iter_json_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_json_strings(child)


def kicad_dbl_paths_from_common_config() -> list[Path]:
    variables = merged_kicad_env_vars()
    paths: list[Path] = []
    for config_path in kicad_common_config_paths():
        try:
            with config_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        for value in iter_json_strings(data):
            if ".kicad_dbl" in value:
                # Dialog history often stores the exact library path with KiCad vars.
                match = re.search(r"[^;:\n\r\t]*\.kicad_dbl", value)
                path_text = match.group(0) if match else value
                paths.append(Path(expand_kicad_vars(path_text, variables)))
    return paths


def kicad_user_library_dirs() -> list[Path]:
    variables = merged_kicad_env_vars()
    dirs: list[Path] = []
    for var_name in ("KICAD_LIB_DIR_USER", "KI_LIB"):
        value = variables.get(var_name)
        if value:
            dirs.append(Path(expand_kicad_vars(value, variables)))
    return dirs


def default_dbl_candidates() -> list[Path]:
    candidates: list[Path] = []

    env_path = os.environ.get("KICAD_DBL_PATH")
    if env_path:
        candidates.append(Path(env_path).expanduser())

    user_library_dirs = kicad_user_library_dirs()
    for lib_dir in user_library_dirs:
        candidates.extend(
            [
                lib_dir / "eda-core.kicad_dbl",
                lib_dir / "EDA-Core" / "eda-core.kicad_dbl",
            ]
        )

    candidates.extend(kicad_dbl_paths_from_common_config())

    candidates.extend(
        [
            REPO_ROOT / "eda-core.kicad_dbl",
            REPO_ROOT / "static" / "eda-core.kicad_dbl",
            Path.cwd() / "eda-core.kicad_dbl",
            Path.cwd() / "static" / "eda-core.kicad_dbl",
            Path.home() / ".local" / "share" / "KiCad" / "EDA-Core" / "eda-core.kicad_dbl",
            Path.home() / ".local" / "share" / "kicad" / "EDA-Core" / "eda-core.kicad_dbl",
            Path.home() / "Documents" / "KiCad" / "EDA-Core" / "eda-core.kicad_dbl",
        ]
    )

    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved not in seen:
            unique.append(resolved)
            seen.add(resolved)
    return unique


def default_dbl_search_dirs() -> list[Path]:
    dirs = kicad_user_library_dirs()
    seen: set[Path] = set()
    unique: list[Path] = []
    for directory in dirs:
        if directory not in seen:
            unique.append(directory)
            seen.add(directory)
    return unique


def sort_dbl_matches(paths: list[Path]) -> list[Path]:
    return sorted(
        paths,
        key=lambda path: (
            0 if "eda-core" in path.name.lower() else 1,
            len(path.parts),
            str(path).lower(),
        ),
    )


def find_default_dbl() -> Path | None:
    for candidate in default_dbl_candidates():
        if candidate.exists():
            return candidate
    for directory in default_dbl_search_dirs():
        if not directory.exists() or not directory.is_dir():
            continue
        matches = sort_dbl_matches(list(directory.rglob("*.kicad_dbl")))
        if matches:
            return matches[0]
    return None


def build_db_config(args: argparse.Namespace) -> DbConfig:
    dbl_path = args.dbl.expanduser() if args.dbl else find_default_dbl()
    config = config_from_kicad_dbl(dbl_path) if dbl_path else DbConfig()

    env_map = {
        "host": os.environ.get("DB_HOST"),
        "port": os.environ.get("DB_PORT"),
        "database": os.environ.get("DB_NAME"),
        "user": os.environ.get("DB_USER"),
        "password": os.environ.get("DB_PASSWORD"),
        "sslmode": os.environ.get("DB_SSLMODE"),
    }
    for field_name, value in env_map.items():
        if value:
            setattr(config, field_name, int(value) if field_name == "port" else value)

    cli_map = {
        "host": args.db_host,
        "port": args.db_port,
        "database": args.db_name,
        "user": args.db_user,
        "password": args.db_password,
        "sslmode": args.sslmode,
    }
    for field_name, value in cli_map.items():
        if value is not None:
            setattr(config, field_name, value)

    if args.prompt_password:
        config.password = getpass.getpass("DB password: ")
    return config


def maybe_reexec_with_project_venv() -> None:
    if os.environ.get("KICAD_MAPPING_REEXECED") == "1":
        return
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        return
    if Path(sys.executable).absolute() == venv_python.absolute():
        return
    try:
        os.environ["KICAD_MAPPING_REEXECED"] = "1"
        os.execv(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]])
    except OSError:
        return


def connect_db(args: argparse.Namespace):
    try:
        import psycopg2
    except ModuleNotFoundError as exc:
        maybe_reexec_with_project_venv()
        raise SystemExit(
            "Python package psycopg2 is required for database access.\n\n"
            "From this project directory run:\n"
            "  python3 -m venv .venv\n"
            "  .venv/bin/python -m pip install -r requirements.txt\n\n"
            "Then run the tool through the venv:\n"
            "  .venv/bin/python scripts/kicad_mapping.py filter -c \"Резисторы\" -t 0603 --no-output\n\n"
            "Alternatively install psycopg2-binary into the Python interpreter used by this script."
        ) from exc

    config = build_db_config(args)
    try:
        return psycopg2.connect(**config.as_psycopg())
    except psycopg2.OperationalError as exc:
        print(f"Database connection failed: {exc}", file=sys.stderr)
        print(
            f"Connection: host={config.host} port={config.port} "
            f"db={config.database} user={config.user}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


def normalize_field_name(name: str) -> str:
    return name.strip().lower().replace("-", "_")


def parse_key_value(value: str) -> tuple[str, str]:
    key, sep, raw_value = value.partition("=")
    if not sep:
        raise SystemExit(f"Expected FIELD=VALUE, got: {value}")
    key = normalize_field_name(key)
    if not key:
        raise SystemExit(f"Empty field name in: {value}")
    return key, raw_value


def parse_id_list(value: str) -> list[int]:
    ids: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_raw, end_raw = part.split("-", 1)
            start = int(start_raw)
            end = int(end_raw)
            if end < start:
                raise SystemExit(f"Invalid ID range: {part}")
            ids.extend(range(start, end + 1))
        else:
            ids.append(int(part))
    if not ids:
        raise SystemExit("ID list is empty")
    return sorted(set(ids))


def field_sql(field: str) -> tuple[str, str]:
    normalized = normalize_field_name(field)
    if normalized not in SEARCH_FIELDS:
        raise SystemExit(f"Unknown search field: {field}. Run 'fields' to see allowed names.")
    sql, kind, _ = SEARCH_FIELDS[normalized]
    return sql, kind


def add_contains_condition(clauses: list[str], params: list[Any], field: str, value: str) -> None:
    sql, kind = field_sql(field)
    if kind == INT_KIND:
        clauses.append(f"{sql} = %s")
        params.append(int(value))
    else:
        clauses.append(f"{sql} ILIKE %s")
        params.append(f"%{value}%")


def add_exact_condition(clauses: list[str], params: list[Any], field: str, value: str) -> None:
    sql, kind = field_sql(field)
    clauses.append(f"{sql} = %s")
    params.append(int(value) if kind == INT_KIND else value)


def add_starts_condition(clauses: list[str], params: list[Any], field: str, value: str) -> None:
    sql, kind = field_sql(field)
    if kind == INT_KIND:
        clauses.append(f"{sql} = %s")
        params.append(int(value))
    else:
        clauses.append(f"{sql} ILIKE %s")
        params.append(f"{value}%")


def build_where(args: argparse.Namespace) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if getattr(args, "ids", None):
        clauses.append('l."код_компонента" = ANY(%s)')
        params.append(parse_id_list(args.ids))

    if getattr(args, "category", None):
        add_contains_condition(clauses, params, "category", args.category)
    if getattr(args, "type", None):
        add_exact_condition(clauses, params, "type", args.type)
    if getattr(args, "subtype", None):
        add_contains_condition(clauses, params, "subtype", args.subtype)

    for raw in getattr(args, "filter", []) or []:
        field, value = parse_key_value(raw)
        add_contains_condition(clauses, params, field, value)

    for raw in getattr(args, "exact", []) or []:
        field, value = parse_key_value(raw)
        add_exact_condition(clauses, params, field, value)

    for raw in getattr(args, "starts", []) or []:
        field, value = parse_key_value(raw)
        add_starts_condition(clauses, params, field, value)

    for raw_field in getattr(args, "empty", []) or []:
        sql, kind = field_sql(raw_field)
        if kind == INT_KIND:
            clauses.append(f"{sql} IS NULL")
        else:
            clauses.append(f"({sql} IS NULL OR {sql} = '')")

    if not clauses and not getattr(args, "all", False):
        raise SystemExit("Specify at least one filter, or pass --all intentionally.")

    return " AND ".join(clauses) if clauses else "1=1", params


def fetch_components(cur, args: argparse.Namespace) -> tuple[list[str], list[tuple[Any, ...]]]:
    where, params = build_where(args)
    cur.execute(
        f"""
        SELECT
            l."код_компонента"   AS id,
            lt."ElementType"     AS category,
            lst."ElementSubType" AS subtype,
            l."Name"             AS name,
            l."Comment"          AS comment,
            l."Value"            AS value,
            l."Type"             AS type,
            l."Part Number"      AS part_number,
            l."Manufacturer"     AS manufacturer,
            l.reference_prefix   AS reference_prefix,
            m.symbol_name        AS kicad_symbol,
            m.footprint_name     AS kicad_footprint
        FROM library l
        JOIN librarysubtype lst ON l."ElementSubType" = lst."код_подтипа"
        JOIN librarytype lt ON lst."ElementType" = lt."код_типа"
        LEFT JOIN component_cad_mapping m
            ON m.component_id = l."код_компонента"
            AND m.cad_type = 'kicad'
            AND m.is_primary = true
        WHERE {where}
        ORDER BY lt."ElementType", l."Type", l."Comment", l."код_компонента"
        """,
        params,
    )
    columns = [desc[0] for desc in cur.description]
    return columns, cur.fetchall()


def value_at(row: tuple[Any, ...], columns: list[str], column: str) -> Any:
    return row[columns.index(column)]


def filter_description(args: argparse.Namespace) -> str:
    parts: list[str] = []
    if getattr(args, "ids", None):
        parts.append(f"ids={args.ids}")
    if getattr(args, "category", None):
        parts.append(f'category~"{args.category}"')
    if getattr(args, "type", None):
        parts.append(f'type="{args.type}"')
    if getattr(args, "subtype", None):
        parts.append(f'subtype~"{args.subtype}"')
    for option_name in ("filter", "exact", "starts", "empty"):
        for value in getattr(args, option_name, []) or []:
            parts.append(f"{option_name}:{value}")
    if getattr(args, "all", False):
        parts.append("all components")
    return ", ".join(parts)


def print_preview(columns: list[str], rows: list[tuple[Any, ...]], limit: int) -> None:
    total = len(rows)
    shown = min(limit, total)
    print(f"Found components: {total}")
    if not rows:
        return

    widths = {
        "id": 8,
        "category": 18,
        "type": 12,
        "comment": 18,
        "reference_prefix": 10,
        "kicad_symbol": 22,
        "kicad_footprint": 28,
    }
    visible = list(widths.keys())
    header = " ".join(name[: widths[name]].ljust(widths[name]) for name in visible)
    print(header)
    print("-" * len(header))
    for row in rows[:shown]:
        cells = []
        for name in visible:
            raw = value_at(row, columns, name)
            text = "-" if raw is None or raw == "" else str(raw)
            cells.append(text[: widths[name]].ljust(widths[name]))
        print(" ".join(cells))
    if total > shown:
        print(f"... and {total - shown} more")


def write_export(path: Path, columns: list[str], rows: list[tuple[Any, ...]], fmt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(columns)
            writer.writerows(rows)
        return

    with path.open("w", encoding="utf-8") as fh:
        fh.write("# KiCad mapping bulk list\n\n")
        fh.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        fh.write("| " + " | ".join(columns) + " |\n")
        fh.write("|" + "|".join(["---"] * len(columns)) + "|\n")
        for row in rows:
            cells = ["" if value is None else str(value).replace("|", "\\|") for value in row]
            fh.write("| " + " | ".join(cells) + " |\n")


def default_output_path(fmt: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path.cwd() / f"kicad_mapping_{stamp}.{fmt}"


def cmd_filter(args: argparse.Namespace) -> int:
    conn = connect_db(args)
    cur = conn.cursor()
    try:
        columns, rows = fetch_components(cur, args)
        print(f"Filter: {filter_description(args)}")
        print_preview(columns, rows, args.preview_limit)

        if args.output:
            output = args.output.expanduser()
            fmt = args.output_format
        elif args.no_output:
            output = None
            fmt = args.output_format
        else:
            fmt = args.output_format
            output = default_output_path(fmt)

        if output:
            write_export(output, columns, rows, fmt)
            print(f"List written to: {output}")
    finally:
        cur.close()
        conn.close()
    return 0


def normalize_set_field(field: str) -> str:
    normalized = normalize_field_name(field)
    if normalized in MAPPING_SET_ALIASES:
        return MAPPING_SET_ALIASES[normalized]
    if normalized in UPDATABLE_LIBRARY_FIELDS:
        return normalized
    raise SystemExit(f"Unknown updatable field: {field}. Run 'fields' to see allowed names.")


def collect_updates(args: argparse.Namespace) -> tuple[dict[str, str | None], str | None, str | None]:
    library_updates: dict[str, str | None] = {}
    symbol = args.symbol
    footprint = args.footprint

    if args.reference_prefix is not None:
        library_updates["reference_prefix"] = args.reference_prefix
    if args.clear_reference:
        library_updates["reference_prefix"] = None

    for raw in args.set or []:
        field, value = parse_key_value(raw)
        field = normalize_set_field(field)
        if field == "symbol":
            symbol = value
        elif field == "footprint":
            footprint = value
        else:
            column, _ = UPDATABLE_LIBRARY_FIELDS[field]
            canonical = "reference_prefix" if column == "reference_prefix" else field
            library_updates[canonical] = value

    for raw_field in args.clear_field or []:
        field = normalize_set_field(raw_field)
        if field in ("symbol", "footprint"):
            raise SystemExit("Use --clear-mapping to remove symbol/footprint mapping.")
        column, _ = UPDATABLE_LIBRARY_FIELDS[field]
        canonical = "reference_prefix" if column == "reference_prefix" else field
        library_updates[canonical] = None

    return library_updates, symbol, footprint


def apply_library_updates(cur, component_ids: list[int], updates: dict[str, str | None]) -> int:
    if not updates:
        return 0

    set_clauses: list[str] = []
    values: list[Any] = []
    for field, value in updates.items():
        if field == "reference_prefix":
            column = "reference_prefix"
        else:
            column, _ = UPDATABLE_LIBRARY_FIELDS[field]
        set_clauses.append(f"{column} = %s")
        values.append(value)

    values.append(component_ids)
    cur.execute(
        f"""
        UPDATE library
        SET {", ".join(set_clauses)}
        WHERE "код_компонента" = ANY(%s)
        """,
        values,
    )
    return cur.rowcount


def apply_mapping_updates(
    cur,
    columns: list[str],
    rows: list[tuple[Any, ...]],
    symbol: str | None,
    footprint: str | None,
    clear_mapping: bool,
) -> tuple[int, int]:
    component_ids = [value_at(row, columns, "id") for row in rows]
    if not component_ids:
        return 0, 0

    if clear_mapping:
        cur.execute(
            """
            DELETE FROM component_cad_mapping
            WHERE component_id = ANY(%s)
              AND cad_type = 'kicad'
              AND is_primary = true
            """,
            (component_ids,),
        )
        return cur.rowcount, 0

    if symbol is None and footprint is None:
        return 0, 0

    try:
        from psycopg2.extras import execute_values
    except ModuleNotFoundError as exc:
        raise SystemExit("psycopg2.extras is required for bulk insert.") from exc

    values = []
    now = datetime.now()
    for row in rows:
        component_id = value_at(row, columns, "id")
        old_symbol = value_at(row, columns, "kicad_symbol")
        old_footprint = value_at(row, columns, "kicad_footprint")
        new_symbol = symbol if symbol is not None else old_symbol
        new_footprint = footprint if footprint is not None else old_footprint
        if new_symbol or new_footprint:
            values.append((component_id, "kicad", new_symbol, new_footprint, True, "{}", now, now))

    cur.execute(
        """
        DELETE FROM component_cad_mapping
        WHERE component_id = ANY(%s)
          AND cad_type = 'kicad'
          AND is_primary = true
        """,
        (component_ids,),
    )
    deleted = cur.rowcount

    if values:
        execute_values(
            cur,
            """
            INSERT INTO component_cad_mapping
                (component_id, cad_type, symbol_name, footprint_name, is_primary, extra_data,
                 created_at, updated_at)
            VALUES %s
            """,
            values,
        )
    return deleted, len(values)


def describe_updates(
    library_updates: dict[str, str | None],
    symbol: str | None,
    footprint: str | None,
    clear_mapping: bool,
) -> list[str]:
    changes: list[str] = []
    for field, value in library_updates.items():
        changes.append(f"{field}={'NULL' if value is None else value}")
    if clear_mapping:
        changes.append("clear KiCad symbol/footprint mapping")
    else:
        if symbol is not None:
            changes.append(f"symbol={symbol}")
        if footprint is not None:
            changes.append(f"footprint={footprint}")
    return changes


def required_write_privileges(
    library_updates: dict[str, str | None],
    symbol: str | None,
    footprint: str | None,
    clear_mapping: bool,
) -> list[tuple[str, str]]:
    required: list[tuple[str, str]] = []
    if library_updates:
        required.append(("public.library", "UPDATE"))
    if clear_mapping:
        required.append(("public.component_cad_mapping", "DELETE"))
    elif symbol is not None or footprint is not None:
        required.append(("public.component_cad_mapping", "DELETE"))
        required.append(("public.component_cad_mapping", "INSERT"))
    return required


def write_privilege_hint(current_user: str, missing: list[tuple[str, str]]) -> str:
    lines = [
        f"Current DB user '{current_user}' does not have write access required for apply.",
        "",
        "Missing privileges:",
    ]
    lines.extend(f"  - {table}: {privilege}" for table, privilege in missing)
    lines.extend(
        [
            "",
            "The auto-detected .kicad_dbl commonly uses a read-only KiCad user.",
            "Run apply with a database user that can write component data, for example:",
            "",
            "  DB_USER=altium_admin DB_PASSWORD='...' ./scripts/kicad_mapping.py apply ...",
            "",
            "or avoid putting the password in shell history:",
            "",
            "  ./scripts/kicad_mapping.py apply ... --db-user altium_admin --prompt-password",
        ]
    )
    return "\n".join(lines)


def ensure_write_privileges(
    cur,
    library_updates: dict[str, str | None],
    symbol: str | None,
    footprint: str | None,
    clear_mapping: bool,
) -> None:
    required = required_write_privileges(library_updates, symbol, footprint, clear_mapping)
    if not required:
        return

    cur.execute("SELECT current_user")
    current_user = cur.fetchone()[0]

    missing: list[tuple[str, str]] = []
    for table, privilege in required:
        cur.execute("SELECT has_table_privilege(%s, %s)", (table, privilege))
        has_privilege = cur.fetchone()[0]
        if not has_privilege:
            missing.append((table, privilege))

    needs_mapping_insert = ("public.component_cad_mapping", "INSERT") in required
    if needs_mapping_insert:
        cur.execute("SELECT pg_get_serial_sequence(%s, %s)", ("public.component_cad_mapping", "id"))
        sequence = cur.fetchone()[0]
        if sequence:
            cur.execute("SELECT has_sequence_privilege(%s, %s)", (sequence, "USAGE"))
            has_sequence_privilege = cur.fetchone()[0]
            if not has_sequence_privilege:
                missing.append((sequence, "USAGE"))

    if missing:
        raise SystemExit(write_privilege_hint(current_user, missing))


def cmd_apply(args: argparse.Namespace) -> int:
    if args.clear_reference and args.reference_prefix is not None:
        raise SystemExit("--reference-prefix and --clear-reference cannot be used together.")
    if args.clear_mapping and (args.symbol is not None or args.footprint is not None):
        raise SystemExit("--clear-mapping cannot be combined with --symbol or --footprint.")

    library_updates, symbol, footprint = collect_updates(args)
    changes = describe_updates(library_updates, symbol, footprint, args.clear_mapping)
    if not changes:
        raise SystemExit(
            "Nothing to update. Use --symbol, --footprint, --reference-prefix, --set, "
            "--clear-field, --clear-reference, or --clear-mapping."
        )

    conn = connect_db(args)
    conn.autocommit = False
    cur = conn.cursor()
    try:
        columns, rows = fetch_components(cur, args)
        print(f"Filter: {filter_description(args)}")
        print_preview(columns, rows, args.preview_limit)
        if not rows:
            print("Nothing to update.")
            conn.rollback()
            return 0

        print("Planned changes:")
        for change in changes:
            print(f"  - {change}")

        if args.dry_run:
            print("Dry run: no changes written.")
            conn.rollback()
            return 0

        ensure_write_privileges(cur, library_updates, symbol, footprint, args.clear_mapping)

        if not args.yes:
            answer = input(f"Apply changes to {len(rows)} components? [y/N]: ").strip().lower()
            if answer not in ("y", "yes", "д", "да"):
                print("Cancelled.")
                conn.rollback()
                return 0

        component_ids = [value_at(row, columns, "id") for row in rows]
        updated_library = apply_library_updates(cur, component_ids, library_updates)
        deleted_mapping, inserted_mapping = apply_mapping_updates(
            cur,
            columns,
            rows,
            symbol,
            footprint,
            args.clear_mapping,
        )

        conn.commit()
        print(f"Updated library rows: {updated_library}")
        if args.clear_mapping or symbol is not None or footprint is not None:
            print(f"Deleted old KiCad mappings: {deleted_mapping}")
            print(f"Inserted KiCad mappings: {inserted_mapping}")
        print("Done.")
    except Exception as exc:
        conn.rollback()
        if getattr(exc, "pgcode", None) == "42501":
            raise SystemExit(
                "Database user does not have enough privileges for this write operation. "
                "Use --db-user/--prompt-password or DB_USER/DB_PASSWORD with a write-enabled account."
            ) from exc
        raise
    finally:
        cur.close()
        conn.close()
    return 0


def cmd_fields(_args: argparse.Namespace) -> int:
    print("Search fields:")
    for name, (_, _, description) in sorted(SEARCH_FIELDS.items()):
        print(f"  {name:<18} {description}")

    print("\nUpdatable fields for --set / --clear-field:")
    for name, (_, description) in sorted(UPDATABLE_LIBRARY_FIELDS.items()):
        print(f"  {name:<18} {description}")
    print("  symbol             KiCad Symbol")
    print("  footprint          KiCad Footprint")
    return 0


def cmd_connection(args: argparse.Namespace) -> int:
    dbl_path = args.dbl.expanduser() if args.dbl else find_default_dbl()
    config = build_db_config(args)
    print(f".kicad_dbl: {dbl_path if dbl_path else 'not found, using defaults/env'}")
    print(f"host:       {config.host}")
    print(f"port:       {config.port}")
    print(f"database:   {config.database}")
    print(f"user:       {config.user}")
    print(f"sslmode:    {config.sslmode or '-'}")
    print(f"password:   {'set' if config.password else 'not set'}")
    return 0


def add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dbl",
        type=Path,
        help=(
            "Path to KiCad .kicad_dbl. Defaults to KICAD_DBL_PATH, "
            "${KICAD_LIB_DIR_USER}, KiCad kicad_common.json, or common KiCad locations."
        ),
    )
    parser.add_argument("--db-host", help="Override DB host from .kicad_dbl/env.")
    parser.add_argument("--db-port", type=int, help="Override DB port from .kicad_dbl/env.")
    parser.add_argument("--db-name", help="Override DB name from .kicad_dbl/env.")
    parser.add_argument("--db-user", help="Override DB user from .kicad_dbl/env.")
    parser.add_argument("--db-password", help="Override DB password from .kicad_dbl/env.")
    parser.add_argument("--sslmode", help="Override PostgreSQL sslmode.")
    parser.add_argument("--prompt-password", action="store_true", help="Prompt for DB password and override file/env.")


def add_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-c", "--category", help='Category substring, for example "Резисторы".')
    parser.add_argument("-t", "--type", help="Exact Type/package value, for example 0603.")
    parser.add_argument("--subtype", help="Subtype substring.")
    parser.add_argument("--ids", help="Comma-separated IDs and ranges, for example 1,2,10-20.")
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="FIELD=TEXT",
        help="Substring search by allowed field. Repeatable.",
    )
    parser.add_argument(
        "--exact",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        help="Exact search by allowed field. Repeatable.",
    )
    parser.add_argument(
        "--starts",
        action="append",
        default=[],
        metavar="FIELD=TEXT",
        help="Prefix search by allowed field. Repeatable.",
    )
    parser.add_argument(
        "--empty",
        action="append",
        default=[],
        metavar="FIELD",
        help="Match empty field. Repeatable.",
    )
    parser.add_argument("--all", action="store_true", help="Intentionally match all components.")
    parser.add_argument("--preview-limit", type=int, default=30, help="Rows to print before export/update.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bulk update EDA-Core KiCad symbol/footprint/reference data from a client PC.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Detailed help:
  scripts/kicad_mapping.py filter --help
  scripts/kicad_mapping.py apply --help
  scripts/kicad_mapping.py fields

Connection flags:
  --dbl PATH              KiCad .kicad_dbl file. Usually found automatically.
  --db-host HOST          Override DB host from .kicad_dbl/env.
  --db-port PORT          Override DB port from .kicad_dbl/env.
  --db-name NAME          Override DB name from .kicad_dbl/env.
  --db-user USER          Override DB user from .kicad_dbl/env.
  --db-password PASSWORD  Override DB password from .kicad_dbl/env.
  --sslmode MODE          Override PostgreSQL sslmode.
  --prompt-password       Ask for password interactively and override file/env.

Search flags for filter/apply:
  -c, --category TEXT     Category substring, e.g. "Резисторы".
  -t, --type VALUE        Exact Type/package, e.g. 0603.
  --subtype TEXT          Subtype substring.
  --ids LIST              IDs and ranges, e.g. 1,2,10-20.
  --filter FIELD=TEXT     Substring search. Repeatable.
  --exact FIELD=VALUE     Exact search. Repeatable.
  --starts FIELD=TEXT     Prefix search. Repeatable.
  --empty FIELD           Match empty field. Repeatable.
  --all                   Intentionally match all components.
  --preview-limit N       Rows to print before export/update.

Apply-only flags:
  -s, --symbol VALUE      KiCad Symbol to set.
  -f, --footprint VALUE   KiCad Footprint to set.
  --reference-prefix REF  KiCad Reference override; aliases: --reference, --designator.
  --set FIELD=VALUE       Set another allowed field; accepts symbol= and footprint=.
  --clear-field FIELD     Set an allowed library field to NULL.
  --clear-reference       Set reference_prefix to NULL.
  --clear-mapping         Delete primary KiCad mapping.
  --dry-run               Preview without writing.
  -y, --yes               Do not ask for confirmation.

Filter-only flags:
  -o, --output PATH       Output list path.
  --output-format md|csv  Output format.
  --no-output             Do not write the default list file.

Examples:
  scripts/kicad_mapping.py filter --dbl ~/EDA-Core/eda-core.kicad_dbl -c "Резисторы" -t 0603

  scripts/kicad_mapping.py apply -c "Резисторы" -t 0603 \\
      --symbol "Ki-Resistors:R-0,05" --footprint "Ki-Resistors:R_0603" --reference-prefix R

  scripts/kicad_mapping.py apply --filter category=Резисторы --filter tolerance=1%% \\
      --set symbol=Device:R --set footprint=Resistor_SMD:R_0603_1608Metric --dry-run
        """,
    )
    connection_parent = argparse.ArgumentParser(add_help=False)
    add_connection_args(connection_parent)
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_filter = subparsers.add_parser(
        "filter",
        parents=[connection_parent],
        help="Find components and optionally export the list.",
    )
    add_filter_args(p_filter)
    p_filter.add_argument("-o", "--output", type=Path, help="Output list path.")
    p_filter.add_argument(
        "--output-format",
        choices=("md", "csv"),
        default="md",
        help="Output format when writing a list.",
    )
    p_filter.add_argument("--no-output", action="store_true", help="Do not write the default list file.")
    p_filter.set_defaults(func=cmd_filter)

    p_apply = subparsers.add_parser(
        "apply",
        parents=[connection_parent],
        help="Apply bulk updates to matched components.",
    )
    add_filter_args(p_apply)
    p_apply.add_argument("-s", "--symbol", help="KiCad Symbol to set.")
    p_apply.add_argument("-f", "--footprint", help="KiCad Footprint to set.")
    p_apply.add_argument(
        "--reference-prefix",
        "--reference",
        "--designator",
        dest="reference_prefix",
        help="KiCad Reference override, for example R, C, DD.",
    )
    p_apply.add_argument("--clear-reference", action="store_true", help="Set reference_prefix to NULL.")
    p_apply.add_argument("--clear-mapping", action="store_true", help="Delete primary KiCad mapping.")
    p_apply.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        help="Set an allowed field. Also accepts symbol=... and footprint=.... Repeatable.",
    )
    p_apply.add_argument(
        "--clear-field",
        action="append",
        default=[],
        metavar="FIELD",
        help="Set an allowed library field to NULL. Repeatable.",
    )
    p_apply.add_argument("--dry-run", action="store_true", help="Preview without writing.")
    p_apply.add_argument("-y", "--yes", action="store_true", help="Do not ask for confirmation.")
    p_apply.set_defaults(func=cmd_apply)

    p_fields = subparsers.add_parser(
        "fields",
        parents=[connection_parent],
        help="Show allowed search and update field names.",
    )
    p_fields.set_defaults(func=cmd_fields)

    p_connection = subparsers.add_parser(
        "connection",
        parents=[connection_parent],
        help="Show parsed DB connection without password.",
    )
    p_connection.set_defaults(func=cmd_connection)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
