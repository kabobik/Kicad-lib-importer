"""Add deterministic stubs/labels and verify their topology with native KiCad export."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from pathlib import Path
import re
import subprocess
import uuid
import xml.etree.ElementTree as ET

from tools.kicad_sexpr import edit, parse, quote

NAMESPACE = uuid.UUID('7e6c811a-5490-4c24-b118-d4d93d8dc001')


@dataclass(frozen=True)
class Pin:
    key: str
    ref: str
    symbol_uuid: str
    x: float
    y: float
    dx: float
    dy: float


def transform(x, y, angle, mirror):
    # Library Y-up -> screen Y-down -> screen-CCW rotation -> placed mirror.
    angle = math.radians(-angle)
    x, y = x, -y
    x, y = x * math.cos(angle) - y * math.sin(angle), x * math.sin(angle) + y * math.cos(angle)
    if mirror == 'x':
        y = -y
    elif mirror == 'y':
        x = -x
    elif mirror:
        raise ValueError(f'Unsupported symbol mirror: {mirror}')
    return round(x, 6), round(y, 6)


def pin_locations(text):
    root = parse(text)
    if root.tag != 'kicad_sch':
        raise ValueError('Not a KiCad schematic')
    if root.all('sheet'):
        raise ValueError('Hierarchical schematics are not supported yet; no files were changed')
    libraries = {s.atoms[1]: s for s in root.one('lib_symbols').all('symbol')}
    locations = defaultdict(list)
    references = {}
    for symbol in root.all('symbol'):
        properties = {p.atoms[1]: p.atoms[2] for p in symbol.all('property')}
        ref = properties.get('Reference', '')
        if not ref or '?' in ref:
            raise ValueError('Schematic references must be annotated')
        sx, sy, angle = map(float, symbol.one('at').atoms[1:4])
        mirror = symbol.value('mirror', '')
        unit = int(symbol.value('unit', '1'))
        body = int(symbol.value('convert', symbol.value('body_style', '1')))
        library = libraries.get(symbol.value('lib_id'))
        if library is None or library.all('extends'):
            raise ValueError(f'Missing or inherited embedded symbol definition for {ref}')
        key = (ref, unit)
        if key in references:
            raise ValueError(f'Duplicate symbol reference/unit: {key}')
        symbol_id = symbol.value('uuid')
        references[key] = symbol_id
        for part in library.all('symbol'):
            match = re.search(r'_(\d+)_(\d+)$', part.atoms[1])
            if not match:
                raise ValueError(f'Cannot determine symbol unit/style: {part.atoms[1]}')
            if int(match[1]) not in (0, unit) or int(match[2]) not in (0, body):
                continue
            for pin in part.all('pin'):
                px, py, pin_angle = map(float, pin.one('at').atoms[1:4])
                x, y = transform(px, py, angle, mirror)
                # Library angle points from the contact toward the symbol body.
                radians = math.radians(pin_angle)
                dx, dy = transform(-math.cos(radians), -math.sin(radians), angle, mirror)
                number = pin.value('number')
                locations[ref + '.' + number].append(Pin(
                    ref + '.' + number, ref, symbol_id, round(sx + x, 6), round(sy + y, 6), dx, dy))
    return root, locations


def export_nets(schematic: Path, output: Path, cli='kicad-cli'):
    result = subprocess.run([cli, 'sch', 'export', 'netlist', '--format', 'kicadxml',
                             '--output', str(output), str(schematic)],
                            capture_output=True, text=True, timeout=300)
    if result.returncode or not output.is_file():
        raise ValueError('Native schematic export failed: ' + result.stdout + result.stderr)
    root = ET.parse(output).getroot()
    networks = {}
    net_of = {}
    for net in root.findall('./nets/net'):
        name = net.attrib['name']
        keys = {n.attrib['ref'] + '.' + n.attrib['pin'] for n in net.findall('node')
                if not n.attrib['ref'].startswith('#')}
        networks[name] = keys
        for key in keys:
            if key in net_of:
                raise ValueError(f'Pin occurs in multiple exported nets: {key}')
            net_of[key] = name
    return networks, net_of


def groups_by_pin(table):
    group_of = {}
    expected = {}
    for group in table['groups']:
        keys = {p['key'] for p in group['pins']}
        expected[group['id']] = keys
        for key in keys:
            if key in group_of:
                raise ValueError(f'{key} has pads in separate copper groups. '
                                 'One schematic pin cannot represent separate nets.')
            group_of[key] = group['id']
    return expected, group_of


def preflight(table, pins):
    expected, group_of = groups_by_pin(table)
    missing = sorted(group_of.keys() - pins.keys())
    if missing:
        raise ValueError('PCB pins missing from schematic: ' + ', '.join(missing))
    reference_ids = defaultdict(set)
    for locations in pins.values():
        for pin in locations:
            reference_ids[pin.ref].add(pin.symbol_uuid)
    for group in table['groups']:
        for row in group['pins']:
            path = row['symbol_path'].rstrip('/')
            if path and path.split('/')[-1] not in reference_ids[row['ref']]:
                raise ValueError(f"Symbol UUID mismatch for {row['key']}; reference-only guessing is disabled")
    return expected


def make_stubs(text, table, networks, net_of, wire_length=2.5, label_size=1.27):
    root, pins = pin_locations(text)
    expected = preflight(table, pins)
    warnings = []
    _, group_of = groups_by_pin(table)
    positions = defaultdict(set)
    for key, locations in pins.items():
        for pin in locations:
            positions[(pin.x, pin.y)].add(key)
    for (x, y), keys in positions.items():
        if len({group_of.get(key) for key in keys}) > 1:
            warnings.append(f'Совмещённые выводы {", ".join(sorted(keys))} в точке '
                            f'({x:g}; {y:g}) мм относятся к разным группам меди. '
                            'Разнесите выводы в символе, если эта связь не нужна.')
    used_names = {name.lstrip('/') for name in networks}
    no_connects = {tuple(map(float, n.one('at').atoms[1:3])) for n in root.all('no_connect')}
    existing_ids = {n.value('uuid') for n in root.children if n.value('uuid')}
    additions = []
    generated = []
    for group in table['groups']:
        keys = expected[group['id']]
        if not keys:
            continue
        actual = {net_of.get(key) for key in keys}
        if len(actual) == 1 and None not in actual:
            # Already connected, even if an old wire or stacked pin adds an
            # unwanted connection. Native comparison reports that separately.
            continue
        if len(keys) == 1:
            continue
        name = group['name']
        if any(ch in name for ch in '\r\n\t'):
            raise ValueError('Net names cannot contain line breaks or tabs')
        # Preserve real existing labels/power names. Auto-generated net names
        # carry no naming intent. Connectivity is still taken only from copper.
        known = {net_of[key] for key in keys if key in net_of
                 and not net_of[key].lstrip('/').startswith(('Net-(', 'unconnected-('))}
        if len(known) > 1:
            warnings.append(f'Группа {group["id"]}: существующие имена {", ".join(sorted(known))}. '
                            'Выводы соединены по меди; проверьте оставшиеся метки.')
        if known:
            name = sorted(known)[0].lstrip('/')
        else:
            base, suffix = name, 2
            while name in used_names:
                name = f'{base}_{suffix}'
                suffix += 1
        used_names.add(name)
        seen = set()
        for key in sorted(keys):
            for pin in pins[key]:
                position = (pin.x, pin.y)
                if position in seen:
                    continue
                seen.add(position)
                if position in no_connects:
                    warnings.append(f'{key}: маркер «не подключено» оставлен; провод к этому выводу '
                                    'пропущен. Проверьте маркер и соедините вывод вручную.')
                    continue
                end_x = round(pin.x + wire_length * pin.dx, 6)
                end_y = round(pin.y + wire_length * pin.dy, 6)
                wire_id = str(uuid.uuid5(NAMESPACE, f'wire:{pin.symbol_uuid}:{key}:{name}:{position}:{wire_length}'))
                label_id = str(uuid.uuid5(NAMESPACE, f'label:{wire_id}'))
                if wire_id in existing_ids or label_id in existing_ids:
                    warnings.append(f'{key}: ранее созданный провод или метка изменены; '
                                    'повторное добавление пропущено. Проверьте соединение вручную.')
                    continue
                angle = 90 if abs(pin.dy) > abs(pin.dx) else 0
                justify = 'right' if pin.dx < 0 or pin.dy > 0 else 'left'
                additions.append(
                    f'\n\t(wire (pts (xy {pin.x:.6f} {pin.y:.6f}) (xy {end_x:.6f} {end_y:.6f}))'
                    f' (stroke (width 0) (type default)) (uuid {quote(wire_id)}))\n'
                    f'\t(label {quote(name)} (at {end_x:.6f} {end_y:.6f} {angle})'
                    f' (effects (font (size {label_size:g} {label_size:g})) (justify {justify} bottom))'
                    f' (uuid {quote(label_id)}))\n')
                generated.append({'pin': key, 'wire_uuid': wire_id, 'label_uuid': label_id})
    return edit(text, [(root.end - 1, root.end - 1, ''.join(additions))]), generated, warnings


def compare_topology(table, networks, net_of):
    """Describe remaining differences without preventing publication of useful work."""
    expected, group_of = groups_by_pin(table)
    failures = []
    names = {}
    for group in table['groups']:
        keys = expected[group['id']]
        if not keys:
            names[group['id']] = group['name']
            continue
        actual = {net_of.get(key) for key in keys}
        if len(keys) == 1 and actual == {None}:
            names[group['id']] = ''
            continue
        if len(actual) != 1 or None in actual:
            failures.append({'group': group['id'], 'expected': sorted(keys),
                             'actual_nets': sorted(n for n in actual if n is not None)})
            continue
        name = next(iter(actual))
        if networks[name] != keys:
            failures.append({'group': group['id'], 'expected': sorted(keys),
                             'actual': sorted(networks[name])})
        names[group['id']] = name
    return names, failures


def verify_topology(table, networks, net_of):
    """Explicit read-only verification remains strict for scripts/CI."""
    names, failures = compare_topology(table, networks, net_of)
    if failures:
        raise ValueError('Schematic/copper mismatch after native export: ' + repr(failures)
                         + '. Check overlapping pins, old wires/labels, or shorten the wire length.')
    return names
