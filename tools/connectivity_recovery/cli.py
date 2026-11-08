"""File-based copper -> connectivity table -> schematic workflow, without MCP."""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib

from .board import NetAssignmentConflict, assign_nets, digest, extract, physical_signature, validate_table
from .schematic import compare_topology, export_nets, make_stubs, pin_locations, verify_topology


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            os.chmod(temp, path.stat().st_mode & 0o777)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def publish(files, *, replace=False, reports=frozenset(), backup_dir=None):
    old = {path: path.read_bytes() if path.exists() else None for path in files}
    if not replace:
        for path, previous in old.items():
            if path not in reports and previous is not None and previous != files[path]:
                raise ValueError(f'Output already exists: {path}; choose an empty output directory')
    if replace:
        for path, previous in old.items():
            if path not in reports and previous is not None and previous != files[path]:
                backup = (backup_dir / path.name if backup_dir is not None else
                          path.with_name(path.name + '.before-recovery-' + digest(previous)[:12] + '.bak'))
                if backup.exists() and backup.read_bytes() != previous:
                    raise ValueError(f'Backup name collision: {backup}')
                if not backup.exists():
                    atomic_write(backup, previous)
    written = []
    try:
        for path, data in files.items():
            if old[path] == data:
                continue
            atomic_write(path, data)
            written.append(path)
    except Exception:
        for path in reversed(written):
            if old[path] is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, old[path])
        raise


def install_prepared_recovery(board, schematic, prepared, backup_dir):
    """Install verified staged bytes, preserving the exact previous project first.

    Called by the GUI transport only after cancellable native processing ends.
    Source hashes fence external edits; publish owns rollback on write errors.
    """
    report = json.loads((prepared / 'validation.json').read_text())
    if report.get('completed') is not True:
        raise ValueError('Recovery preparation did not complete')
    paths = {'pcb': board, 'schematic': schematic}
    original, recovered = {}, {}
    for key, path in paths.items():
        original[path] = path.read_bytes()
        recovered[path] = (prepared / path.name).read_bytes()
        if digest(original[path]) != report['input_sha256'][key]:
            raise ValueError('An input changed during recovery: ' + str(path))
        if digest(recovered[path]) != report['output_sha256'][key]:
            raise ValueError('Prepared recovery file changed: ' + str(path))
    if backup_dir.resolve() in {p.parent.resolve() for p in paths.values()}:
        raise ValueError('Backup directory must not contain the working CAD files')
    for suffix in ('~' + schematic.name + '.lck', schematic.name + '.lck'):
        if schematic.with_name(suffix).exists():
            raise ValueError('Save and close the schematic editor before recovery')
    backups = {backup_dir / p.name: data for p, data in original.items()}
    project = schematic.with_suffix('.kicad_pro')
    if project.exists():
        backups[backup_dir / project.name] = project.read_bytes()
    publish(backups)
    # Check again after backups: an editor may have saved while they were written.
    if any(p.read_bytes() != data for p, data in original.items()):
        raise ValueError('An input changed while backing up; working files were not replaced')
    report.update(applied_in_place=True, backup_directory=str(backup_dir),
                  working_schematic=str(schematic), working_board=str(board))
    outputs = {schematic: recovered[schematic]}
    if report['pcb_net_fields_updated']:
        outputs[board] = recovered[board]
    reports = {backup_dir / 'validation.json': json_bytes(report),
               backup_dir / 'netlist.xml': (prepared / 'netlist.xml').read_bytes()}
    outputs.update(reports)
    publish(outputs, replace=True, reports=set(reports), backup_dir=backup_dir)
    return report


def settings(args):
    config = {}
    if args.config:
        with args.config.open('rb') as stream:
            config = tomllib.load(stream)
    allowed = {'drawing': {'wire_length_mm', 'label_size_mm'}, 'naming': {'prefix'}}
    if config.keys() - allowed.keys():
        raise ValueError('Unknown configuration section')
    for section, values in config.items():
        if not isinstance(values, dict) or values.keys() - allowed[section]:
            raise ValueError(f'Unknown settings in [{section}]')
    drawing = config.get('drawing', {})
    length = args.wire_length if getattr(args, 'wire_length', None) is not None else drawing.get('wire_length_mm', 2.5)
    size = args.label_size if getattr(args, 'label_size', None) is not None else drawing.get('label_size_mm', 1.27)
    prefix = getattr(args, 'prefix', None) or config.get('naming', {}).get('prefix', 'REC')
    for name, value in [('wire length', length), ('label size', size)]:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{name} must be a finite positive number in millimetres')
    if not isinstance(prefix, str) or not prefix or any(ch in prefix for ch in '\n\r\t'):
        raise ValueError('Invalid net prefix')
    return length, size, prefix


def read_table(path):
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or not isinstance(value.get('groups'), list):
        raise ValueError('Invalid connectivity table')
    return value


def extract_command(args):
    _, _, prefix = settings(args)
    if args.output.suffix != '.json':
        raise ValueError('Extraction output must have a .json extension')
    csv_path = args.output.with_suffix('.csv')
    if args.board.resolve() in (args.output.resolve(), csv_path.resolve()):
        raise ValueError('Report output cannot overwrite the input PCB')
    table = extract(args.board, prefix)
    csv_stream = io.StringIO(newline='')
    writer = csv.writer(csv_stream)
    writer.writerow(['net', 'reference', 'pin', 'pad_uuid', 'physical_group'])
    for group in table['groups']:
        for pin in group['pins']:
            writer.writerow([group['name'], pin['ref'], pin['pin'], pin['pad_uuid'], group['id']])
    publish({args.output: json_bytes(table), csv_path: csv_stream.getvalue().encode()})
    return {'physical_groups': len(table['groups']),
            'connected_pin_groups': sum(len({p['key'] for p in g['pins']}) > 1 for g in table['groups']),
            'table': str(args.output), 'csv': str(csv_path), 'warnings': table['warnings']}


def stage_schematic(source, work):
    staged = work / source.name
    shutil.copyfile(source, staged)
    project = source.with_suffix('.kicad_pro')
    if project.exists():
        shutil.copyfile(project, staged.with_suffix('.kicad_pro'))
    return staged


def apply_command(args):
    length, size, _ = settings(args)
    board_source = args.board.read_bytes()
    schematic_source = args.schematic.read_bytes()
    table = read_table(args.nets)
    validate_table(table, args.board)
    if args.in_place:
        for path in (args.schematic, args.board):
            if any(p.exists() for p in (path.with_name('~' + path.name + '.lck'), path.with_suffix(path.suffix + '.lck'))):
                raise ValueError('Close the KiCad editors before an in-place update')
    elif args.output_dir.resolve() in (args.schematic.parent.resolve(), args.board.parent.resolve()):
        raise ValueError('Output directory contains source files; use a new directory or --in-place')
    with tempfile.TemporaryDirectory(prefix='kicad-copper-recovery-') as temp:
        work = Path(temp)
        schematic = stage_schematic(args.schematic, work)
        networks, net_of = export_nets(schematic, work / 'before.xml', args.kicad_cli)
        recovered, generated, warnings = make_stubs(schematic_source.decode('utf-8'), table, networks, net_of,
                                                     wire_length=length, label_size=size)
        schematic.write_text(recovered, encoding='utf-8')
        networks, net_of = export_nets(schematic, work / 'after.xml', args.kicad_cli)
        schematic_names, mismatches = compare_topology(table, networks, net_of)
        for mismatch in mismatches:
            actual = mismatch.get('actual', mismatch.get('actual_nets', []))
            warnings.append(f'Группа {mismatch["group"]}: по меди — {", ".join(mismatch["expected"])}; '
                            f'в схеме — {", ".join(actual) or "нет общей цепи"}. '
                            'Проверьте выводы, старые провода/метки и длину добавленных проводов.')
        # A schematic short must never propagate into PCB net assignment. Keep
        # matched names; name each unmatched copper group independently.
        unmatched = {item['group'] for item in mismatches}
        names = {key: value for key, value in schematic_names.items() if key not in unmatched}
        used_names = set(names.values()) | set(networks)
        for group in table['groups']:
            if group['id'] in names:
                continue
            name, suffix = group['name'], 2
            while name in used_names:
                name = f'{group["name"]}_{suffix}'
                suffix += 1
            names[group['id']] = name
            used_names.add(name)
        pcb_data = board_source
        pcb_updated = False
        if args.write_pcb:
            try:
                pcb_data = assign_nets(board_source.decode('utf-8'), table, names).encode()
                pcb_updated = True
            except NetAssignmentConflict as error:
                warnings.append('Назначение цепей PCB пропущено: разделите островки зоны на отдельные зоны. '
                                'Плата скопирована без изменений. ' + str(error))
        if pcb_updated:
            pcb = work / args.board.name
            pcb.write_bytes(pcb_data)
            reloaded = extract(pcb)
            if physical_signature(reloaded) != physical_signature(table):
                raise ValueError('Physical copper connectivity changed after PCB net assignment')
            for group in reloaded['groups']:
                expected_names = {names[group['id']]} - {''}
                if set(group['previous_names']) != expected_names:
                    raise ValueError('PCB net names did not survive native reload: ' + group['id'])
        if args.board.read_bytes() != board_source or args.schematic.read_bytes() != schematic_source:
            raise ValueError('An input changed during recovery; retry with editors closed')
        mapped_keys = {p['key'] for g in table['groups'] for p in g['pins']}
        report = {
            'completed': True, 'verified': not mismatches, 'physical_groups': len(table['groups']),
            'wires_added': len(generated), 'labels_added': len(generated),
            'wire_length_mm': length, 'label_size_mm': size,
            'pcb_net_fields_updated': pcb_updated,
            'pcb_net_fields_requested': args.write_pcb,
            'net_names': names, 'schematic_net_names': schematic_names,
            'topology_mismatches': mismatches, 'generated_objects': generated,
            'input_sha256': {'pcb': digest(board_source), 'schematic': digest(schematic_source)},
            'output_sha256': {'pcb': digest(pcb_data), 'schematic': digest(recovered.encode())},
            'warnings': table.get('warnings', []) + warnings,
            'schematic_pins_without_pads': sorted(
                key for key in pin_locations(recovered)[1]
                if not key.startswith('#') and key not in mapped_keys),
        }
        if args.in_place:
            outputs = {args.schematic: recovered.encode()}
            if args.write_pcb:
                outputs[args.board] = pcb_data
            publish(outputs, replace=True)
        else:
            outputs = {args.output_dir / args.schematic.name: recovered.encode(),
                       args.output_dir / args.board.name: pcb_data,
                       args.output_dir / 'validation.json': json_bytes(report),
                       args.output_dir / 'netlist.xml': (work / 'after.xml').read_bytes()}
            project = args.schematic.with_suffix('.kicad_pro')
            if project.exists():
                outputs[args.output_dir / project.name] = project.read_bytes()
            publish(outputs, reports={args.output_dir / "validation.json", args.output_dir / "netlist.xml"})
        return report


def verify_command(args):
    table = read_table(args.nets)
    validate_table(table, args.board, require_source_hash=False)
    with tempfile.TemporaryDirectory(prefix='kicad-copper-verify-') as temp:
        work = Path(temp)
        schematic = stage_schematic(args.schematic, work)
        networks, net_of = export_nets(schematic, work / 'netlist.xml', args.kicad_cli)
        names = verify_topology(table, networks, net_of)
    return {'verified': True, 'physical_groups': len(table['groups']), 'net_names': names}


def parser():
    result = argparse.ArgumentParser(description='Recover schematic connections from physical PCB copper, without MCP.')
    sub = result.add_subparsers(dest='command', required=True)
    scan = sub.add_parser('extract', help='Extract physical groups to JSON and CSV; never change PCB')
    scan.add_argument('board', type=Path)
    scan.add_argument('--output', type=Path, required=True)
    scan.add_argument('--prefix')
    scan.add_argument('--config', type=Path)
    scan.set_defaults(handler=extract_command)
    apply = sub.add_parser('apply', help='Add stubs/labels and publish output files with a report of remaining differences')
    apply.add_argument('--board', type=Path, required=True)
    apply.add_argument('--schematic', type=Path, required=True)
    apply.add_argument('--nets', type=Path, required=True)
    destination = apply.add_mutually_exclusive_group(required=True)
    destination.add_argument('--output-dir', type=Path)
    destination.add_argument('--in-place', action='store_true')
    apply.add_argument('--write-pcb', action='store_true', help='Also assign PCB net names; copper geometry/fill stays unchanged')
    apply.add_argument('--wire-length', type=float, help='Stub length in mm (default 2.5)')
    apply.add_argument('--label-size', type=float, help='Label font size in mm (default 1.27)')
    apply.add_argument('--config', type=Path)
    apply.add_argument('--kicad-cli', default='kicad-cli')
    apply.set_defaults(handler=apply_command)
    verify = sub.add_parser('verify', help='Read-only comparison of schematic netlist and extracted physical groups')
    verify.add_argument('--board', type=Path, required=True)
    verify.add_argument('--schematic', type=Path, required=True)
    verify.add_argument('--nets', type=Path, required=True)
    verify.add_argument('--kicad-cli', default='kicad-cli')
    verify.set_defaults(handler=verify_command)
    for command in (scan, apply, verify):
        command.add_argument('--report', type=Path, help='Write command results and remaining differences as JSON')
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.report and args.report.suffix != ".json":
            raise ValueError("Report path must end in .json")
        # A diagnostic path must never alias source files or the connectivity table.
        if args.report and args.report.resolve() in {
            path.resolve() for path in (getattr(args, 'board', None), getattr(args, 'schematic', None),
                                        getattr(args, 'nets', None), getattr(args, 'output', None)) if path}:
            raise ValueError('Report path cannot overwrite an input or table output')
        report = args.handler(args)
    except (ValueError, OSError, KeyError, TypeError, ImportError, RuntimeError, subprocess.SubprocessError) as error:
        report = {'verified': False, 'error': str(error)}
        print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
        # Do not write on failure: a caller-supplied path may be the cause.
        return 2
    if args.report:
        atomic_write(args.report, json_bytes(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0
