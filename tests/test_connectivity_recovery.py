"""Native round-trip checks using generated fixtures; no MCP, root, or network."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import uuid

from tools.connectivity_recovery.board import assign_nets, extract
from tools.connectivity_recovery.cli import main, publish, install_prepared_recovery
from tools.connectivity_recovery import cli as recovery_cli
from tools.connectivity_recovery.board import sync_editor_net_assignments
from tools.kicad_sexpr import edit, parse, quote

NATIVE = bool(importlib.util.find_spec('pcbnew') and shutil.which('kicad-cli'))


def fixture(directory, placements=((0, ''), (0, '')), *, coincident=False):
    import pcbnew
    root_id = str(uuid.uuid4())
    pin2_x = -2.5 if coincident else 2.5
    lib = f'''(symbol "Test:Pair"
        (pin_names (offset 0))
        (property "Reference" "J" (at 0 4 0) (effects (font (size 1.27 1.27))))
        (property "Value" "Pair" (at 0 -4 0) (effects (font (size 1.27 1.27))))
        (symbol "Pair_0_1" (rectangle (start -1.25 1.25) (end 1.25 -1.25)
            (stroke (width 0) (type default)) (fill (type background))))
        (symbol "Pair_1_1"
            (pin passive line (at -2.5 0 0) (length 1.25)
                (name "A" (effects (font (size 1.27 1.27))))
                (number "1" (effects (font (size 1.27 1.27)))))
            (pin passive line (at {pin2_x} 0 180) (length 1.25)
                (name "B" (effects (font (size 1.27 1.27))))
                (number "2" (effects (font (size 1.27 1.27)))))))'''
    symbols = []
    board = pcbnew.BOARD()
    for index, (angle, mirror) in enumerate(placements, 1):
        ref = f'J{index}'
        symbol_id = str(uuid.uuid4())
        x, y = 25 + ((index - 1) % 4) * 40, 25 + ((index - 1) // 4) * 40
        reflection = f'(mirror {mirror})' if mirror else ''
        symbols.append(f'''(symbol (lib_id "Test:Pair") (at {x} {y} {angle})
            (unit 1) {reflection} (in_bom yes) (on_board yes) (dnp no) (uuid "{symbol_id}")
            (property "Reference" "{ref}" (at {x} {y-6} 0) (effects (font (size 1.27 1.27))))
            (property "Value" "Pair" (at {x} {y+6} 0) (effects (font (size 1.27 1.27))))
            (pin "1" (uuid "{uuid.uuid4()}")) (pin "2" (uuid "{uuid.uuid4()}"))
            (instances (project "fixture" (path "/{root_id}" (reference "{ref}") (unit 1)))))''')
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        fp.SetPath(pcbnew.KIID_PATH('/' + symbol_id))
        board.Add(fp)
        for number in (1, 2):
            pad = pcbnew.PAD(fp)
            pad.SetNumber(str(number))
            pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            pad.SetShape(pcbnew.PAD_SHAPE_RECT)
            layers = pcbnew.LSET()
            layers.AddLayer(pcbnew.F_Cu)
            pad.SetLayerSet(layers)
            pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(1), pcbnew.FromMM(1)))
            pad.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(index * 10), pcbnew.FromMM(number * 10)))
            wrong = pcbnew.NETINFO_ITEM(board, f'WRONG_{ref}_{number}')
            board.Add(wrong)
            pad.SetNetCode(wrong.GetNetCode())
            fp.Add(pad)
        if index > 1:
            track = pcbnew.PCB_TRACK(board)
            track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM((index-1)*10), pcbnew.FromMM(10)))
            track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(index*10), pcbnew.FromMM(10)))
            track.SetWidth(pcbnew.FromMM(.25))
            track.SetLayer(pcbnew.F_Cu)
            track.SetNetCode(wrong.GetNetCode())
            board.Add(track)
    board_path = directory / 'fixture.kicad_pcb'
    pcbnew.SaveBoard(str(board_path), board)
    sch = directory / 'fixture.kicad_sch'
    sch.write_text(f'''(kicad_sch (version 20250114) (generator "eeschema")
        (uuid "{root_id}") (paper "A4") (lib_symbols {lib})
        {''.join(symbols)})''')
    return board_path, sch


class SpanTests(unittest.TestCase):
    def test_quoted_parentheses_escapes_and_unicode_are_preserved(self):
        text = '(root (property "имя" "a \\" (b) \\\\ c") (number 2))'
        root = parse(text)
        node = root.one('number')
        result = edit(text, [(node.start, node.end, '(number 3)')])
        self.assertEqual(result, text.replace('(number 2)', '(number 3)'))
        value = 'quote" slash\\ newline\nкириллица'
        self.assertEqual(parse('(value ' + quote(value) + ')').atoms[1], value)

    def test_invalid_and_overlapping_input_is_rejected(self):
        for text in ('(root', '(root "broken)', '(a))', '(a)(b)'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse(text)
        with self.assertRaises(ValueError):
            edit('abc', [(0, 2, 'x'), (1, 3, 'y')])

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / 'existing'
            existing.write_bytes(b'original')
            fresh = Path(tmp) / 'fresh'
            with self.assertRaises(ValueError):
                publish({fresh: b'new', existing: b'overwrite'})
            self.assertFalse(fresh.exists())
            self.assertEqual(existing.read_bytes(), b'original')


@unittest.skipUnless(NATIVE, 'Requires native pcbnew and kicad-cli')
class RecoveryTests(unittest.TestCase):
    def run_cli(self, args, expected=0):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = main([str(arg) for arg in args])
        self.assertEqual(status, expected, out.getvalue() + err.getvalue())
        return json.loads(out.getvalue() if status == 0 else err.getvalue())

    def scan(self, board, destination):
        self.run_cli(['extract', board, '--output', destination])
        return json.loads(destination.read_text())

    def test_rotation_mirror_native_roundtrip_and_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board, sch = fixture(root, [(a, m) for a in (0, 90, 180, 270) for m in ('', 'x', 'y')])
            original_board, original_sch = board.read_bytes(), sch.read_bytes()
            table_path = root / 'nets.json'
            table = self.scan(board, table_path)
            self.assertEqual(len(table['groups']), 13)
            destination = root / 'output'
            result = self.run_cli(['apply', '--board', board, '--schematic', sch, '--nets', table_path,
                                  '--output-dir', destination, '--write-pcb'])
            self.assertEqual(result['wires_added'], 12)
            self.assertEqual(result['labels_added'], 12)
            # Repeating the same command may refresh reports, but not duplicate CAD objects.
            self.run_cli(['apply', '--board', board, '--schematic', sch, '--nets', table_path,
                          '--output-dir', destination, '--write-pcb'])
            self.assertEqual(board.read_bytes(), original_board)
            self.assertEqual(sch.read_bytes(), original_sch)
            self.run_cli(['verify', '--board', destination/board.name,
                          '--schematic', destination/sch.name, '--nets', table_path])
            again = self.run_cli(['apply', '--board', board, '--schematic', destination/sch.name,
                                 '--nets', table_path, '--output-dir', root/'again', '--write-pcb'])
            self.assertEqual(again['wires_added'], 0)
            self.assertEqual((root/'again'/sch.name).read_bytes(), (destination/sch.name).read_bytes())

    def test_coincident_pins_conflict_without_project_specific_exceptions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board, sch = fixture(root, coincident=True)
            nets = root / 'nets.json'
            self.scan(board, nets)
            original = sch.read_bytes()
            result = self.run_cli(['apply', '--board', board, '--schematic', sch, '--nets', nets,
                                  '--output-dir', root/'output', '--write-pcb'])
            self.assertTrue(result['completed'])
            self.assertFalse(result['verified'])
            self.assertEqual(result['wires_added'], 2)
            self.assertTrue(any('Совмещённые выводы' in item for item in result['warnings']))
            self.assertEqual(len(result['topology_mismatches']), 3)
            self.assertEqual(sch.read_bytes(), original)
            self.assertTrue((root/'output'/sch.name).exists())
            # Schematic shorts must not merge the physical PCB groups.
            reloaded = extract(root/'output'/board.name)
            self.assertEqual(len({tuple(g['previous_names']) for g in reloaded['groups']}), 3)
            self.run_cli(['verify', '--board', root/'output'/board.name,
                          '--schematic', root/'output'/sch.name, '--nets', nets], expected=2)
            repeat = self.run_cli(['apply', '--board', board, '--schematic', root/'output'/sch.name,
                                  '--nets', nets, '--output-dir', root/'again', '--write-pcb'])
            self.assertFalse(repeat['verified'])
            self.assertEqual(repeat['wires_added'], 0)
            self.assertEqual((root/'again'/sch.name).read_bytes(), (root/'output'/sch.name).read_bytes())

    def test_conflicting_group_does_not_block_independent_group(self):
        import pcbnew
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board_path, sch = fixture(root, [(0, '')] * 4)
            board = pcbnew.LoadBoard(str(board_path))
            for track in list(board.GetTracks()):
                if track.GetStart().x == pcbnew.FromMM(20):
                    board.Remove(track)
            pcbnew.SaveBoard(str(board_path), board)
            text = sch.read_text()
            lib = parse(text).one('lib_symbols').all('symbol')[0]
            stacked = text[lib.start:lib.end].replace('Pair', 'Stacked').replace(
                '(at 2.5 0 180)', '(at -2.5 0 180)')
            libs = parse(text).one('lib_symbols')
            text = edit(text, [(libs.end - 1, libs.end - 1, stacked)])
            sch.write_text(text.replace('(lib_id "Test:Pair")', '(lib_id "Test:Stacked")', 1))
            nets = root/'nets.json'
            table = self.scan(board_path, nets)
            result = self.run_cli(['apply', '--board', board_path, '--schematic', sch, '--nets', nets,
                                  '--output-dir', root/'output', '--write-pcb'])
            self.assertFalse(result['verified'])
            self.assertEqual(result['wires_added'], 4)
            healthy = next(g['id'] for g in table['groups']
                           if {p['key'] for p in g['pins']} == {'J3.1', 'J4.1'})
            self.assertNotIn(healthy, {item['group'] for item in result['topology_mismatches']})
            self.assertEqual(result['net_names'][healthy], result['schematic_net_names'][healthy])

    def test_no_connect_marker_is_reported_and_other_stubs_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board, sch = fixture(root)
            text = sch.read_text()
            sch.write_text(edit(text, [(len(text)-1, len(text)-1,
                f'(no_connect (at 22.5 25) (uuid "{uuid.uuid4()}"))')]))
            nets = root/'nets.json'
            self.scan(board, nets)
            result = self.run_cli(['apply', '--board', board, '--schematic', sch, '--nets', nets,
                                  '--output-dir', root/'output'])
            self.assertTrue(result['completed'])
            self.assertFalse(result['verified'])
            self.assertEqual(result['wires_added'], 1)
            self.assertTrue(any('не подключено' in item for item in result['warnings']))
            self.assertEqual(len(parse((root/'output'/sch.name).read_text()).all('no_connect')), 1)

    def test_stale_table_and_pin_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board, sch = fixture(root)
            nets = root / 'nets.json'
            table = self.scan(board, nets)
            command = ['apply', '--board', board, '--schematic', sch, '--nets', nets,
                       '--output-dir', root/'output']
            source = board.read_bytes()
            board.write_bytes(source + b'\n')
            self.assertIn('changed since extraction', self.run_cli(command, 2)['error'])
            board.write_bytes(source)
            table['groups'][0]['pins'][0]['pin'] = '999'
            nets.write_text(json.dumps(table))
            self.assertIn('Physical groups were edited', self.run_cli(command, 2)['error'])
            self.assertFalse((root/'output').exists())

    def test_install_fences_external_changes_and_rolls_back_failed_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board, sch = fixture(root)
            nets, prepared = root/'nets.json', root/'prepared'
            self.scan(board, nets)
            self.run_cli(['apply', '--board', board, '--schematic', sch, '--nets', nets,
                          '--output-dir', prepared, '--write-pcb'])
            original = {p: p.read_bytes() for p in (board, sch)}
            sch.write_bytes(original[sch] + b'\n')
            with self.assertRaisesRegex(ValueError, 'input changed'):
                install_prepared_recovery(board, sch, prepared, root/'stale-backup')
            self.assertEqual(sch.read_bytes(), original[sch] + b'\n')
            self.assertFalse((root/'stale-backup').exists())
            sch.write_bytes(original[sch])
            real_write = recovery_cli.atomic_write

            def fail_board(path, data):
                if path == board:
                    raise OSError('simulated PCB write failure')
                real_write(path, data)

            with mock.patch.object(recovery_cli, 'atomic_write', side_effect=fail_board):
                with self.assertRaisesRegex(OSError, 'PCB write failure'):
                    install_prepared_recovery(board, sch, prepared, root/'backup')
            for path, data in original.items():
                self.assertEqual(path.read_bytes(), data)
                self.assertEqual((root/'backup'/path.name).read_bytes(), data)
            self.assertFalse((root/'backup/validation.json').exists())
            # Backup failure also precedes every working-file mutation.
            (root/'foreign').mkdir()
            (root/'foreign'/sch.name).write_bytes(b'foreign backup')
            with self.assertRaises(ValueError):
                install_prepared_recovery(board, sch, prepared, root/'foreign')
            self.assertEqual(sch.read_bytes(), original[sch])

    def test_schematic_only_install_leaves_pcb_and_copies_project_for_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board, sch = fixture(root)
            project = sch.with_suffix('.kicad_pro')
            project.write_text('{}')
            original = {p: p.read_bytes() for p in (board, sch, project)}
            nets, prepared, backup = root/'nets.json', root/'prepared', root/'recovery'
            self.scan(board, nets)
            self.run_cli(['apply', '--board', board, '--schematic', sch, '--nets', nets,
                          '--output-dir', prepared])
            install_prepared_recovery(board, sch, prepared, backup)
            self.assertEqual(board.read_bytes(), original[board])
            self.assertNotEqual(sch.read_bytes(), original[sch])
            for path, data in original.items():
                self.assertEqual((backup/path.name).read_bytes(), data)

    def test_editor_net_sync_survives_save_and_rejects_other_board(self):
        import pcbnew
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board, sch = fixture(root)
            live = pcbnew.LoadBoard(str(board))
            nets, prepared = root/'nets.json', root/'prepared'
            self.scan(board, nets)
            self.run_cli(['apply', '--board', board, '--schematic', sch, '--nets', nets,
                          '--output-dir', prepared, '--write-pcb'])
            sync_editor_net_assignments(live, prepared/board.name)
            saved = root/'editor-saved.kicad_pcb'
            pcbnew.SaveBoard(str(saved), live)
            actual = {g['id']: g['previous_names'] for g in extract(saved)['groups']}
            expected = {g['id']: g['previous_names'] for g in extract(prepared/board.name)['groups']}
            self.assertEqual(actual, expected)
            old = [p.GetNetname() for f in live.GetFootprints() for p in f.Pads()]
            other_dir = root/'other'
            other_dir.mkdir()
            other, _ = fixture(other_dir)
            with self.assertRaisesRegex(ValueError, 'objects differ'):
                sync_editor_net_assignments(live, other)
            self.assertEqual([p.GetNetname() for f in live.GetFootprints() for p in f.Pads()], old)

    def test_editor_sync_reads_disk_when_loadboard_returns_stale_active_board(self):
        import pcbnew
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board, sch = fixture(root)
            live = pcbnew.LoadBoard(str(board))
            nets, prepared = root/'nets.json', root/'prepared'
            self.scan(board, nets)
            self.run_cli(['apply', '--board', board, '--schematic', sch, '--nets', nets,
                          '--output-dir', prepared, '--write-pcb'])
            expected = {g['id']: g['previous_names'] for g in extract(prepared/board.name)['groups']}
            # The worker replaces the file while PCB Editor retains its old BOARD.
            installed = (prepared/board.name).read_bytes()
            board.write_bytes(installed)
            # KiCad LoadBoard returns the active BOARD for an open project.
            with mock.patch.object(pcbnew, 'LoadBoard', return_value=live):
                sync_editor_net_assignments(live, board)
            self.assertEqual(board.read_bytes(), installed)  # Sync never writes the file.
            # A later ordinary editor save must keep recovered assignments.
            pcbnew.SaveBoard(str(board), live)
            actual = {g['id']: g['previous_names'] for g in extract(board)['groups']}
            self.assertEqual(actual, expected)

    def test_in_place_backup_and_custom_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board, sch = fixture(root)
            nets = root / 'nets.json'
            self.scan(board, nets)
            original = sch.read_bytes()
            result = self.run_cli(['apply', '--board', board, '--schematic', sch, '--nets', nets,
                                  '--in-place', '--wire-length', '5', '--label-size', '1'])
            self.assertEqual(result['wire_length_mm'], 5)
            backup, = root.glob('*.kicad_sch.before-recovery-*.bak')
            self.assertEqual(backup.read_bytes(), original)
            root_node = parse(sch.read_text())
            for wire in root_node.all('wire'):
                a, b = [list(map(float, p.atoms[1:])) for p in wire.one('pts').all('xy')]
                self.assertAlmostEqual(abs(a[0]-b[0]) + abs(a[1]-b[1]), 5)

    def test_zone_islands_do_not_join_and_assignment_refuses_ambiguity(self):
        import pcbnew
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board_path, sch = fixture(root)
            board = pcbnew.LoadBoard(str(board_path))
            for track in list(board.GetTracks()):
                board.Remove(track)
            zone = pcbnew.ZONE(board)
            zone.SetLayer(pcbnew.F_Cu)
            zone.SetNetCode(1)
            outline = zone.Outline()
            outline.NewOutline()
            for x, y in ((5, 5), (25, 5), (25, 25), (5, 25)):
                outline.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
            fill = pcbnew.SHAPE_POLY_SET()
            for x in (10, 20):
                fill.NewOutline()
                for px, py in ((x-2, 8), (x+2, 8), (x+2, 22), (x-2, 22)):
                    fill.Append(pcbnew.FromMM(px), pcbnew.FromMM(py))
            zone.SetFilledPolysList(pcbnew.F_Cu, fill)
            zone.SetIsFilled(True)
            board.Add(zone)
            pcbnew.SaveBoard(str(board_path), board)
            table = extract(board_path)
            self.assertEqual(sorted(sorted(p['key'] for p in g['pins']) for g in table['groups']),
                             [['J1.1', 'J1.2'], ['J2.1', 'J2.2']])
            with self.assertRaisesRegex(ValueError, 'disconnected islands'):
                assign_nets(board_path.read_text(), table, {g['id']: g['name'] for g in table['groups']})
            original_board = board_path.read_bytes()
            nets = root/'nets.json'
            self.scan(board_path, nets)
            result = self.run_cli(['apply', '--board', board_path, '--schematic', sch, '--nets', nets,
                                  '--output-dir', root/'output', '--write-pcb'])
            self.assertTrue(result['completed'])
            self.assertFalse(result['pcb_net_fields_updated'])
            self.assertTrue(any('островки зоны' in message for message in result['warnings']))
            self.assertEqual((root/'output'/board_path.name).read_bytes(), original_board)
            self.assertTrue((root/'output'/sch.name).exists())

    def test_different_copper_layers_do_not_connect_without_via(self):
        import pcbnew
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, _ = fixture(root)
            board = pcbnew.LoadBoard(str(path))
            for track in board.GetTracks():
                track.SetLayer(pcbnew.B_Cu)
            pcbnew.SaveBoard(str(path), board)
            self.assertEqual(sorted(len(g['pins']) for g in extract(path)['groups']), [0, 1, 1, 1, 1])
            for x in (10, 20):
                via = pcbnew.PCB_VIA(board)
                via.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(10)))
                via.SetWidth(pcbnew.FromMM(.6))
                via.SetDrill(pcbnew.FromMM(.3))
                via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                board.Add(via)
            pcbnew.SaveBoard(str(path), board)
            self.assertEqual(sorted(len(g['pins']) for g in extract(path)['groups']), [1, 1, 2])

    def test_long_stub_short_is_reported_with_published_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board, sch = fixture(root)
            nets = root / 'nets.json'
            self.scan(board, nets)
            result = self.run_cli(['apply', '--board', board, '--schematic', sch, '--nets', nets,
                                  '--output-dir', root/'output', '--wire-length', '35', '--write-pcb'])
            self.assertTrue(result['completed'])
            self.assertFalse(result['verified'])
            self.assertTrue(result['topology_mismatches'])
            self.assertTrue((root/'output'/sch.name).exists())

    def test_multisection_symbol_uses_each_units_position(self):
        import pcbnew
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board_path, sch = fixture(root)
            text = sch.read_text()
            document = parse(text)
            library = document.one('lib_symbols').all('symbol')[0]
            part = library.all('symbol')[1]
            pin1, pin2 = part.all('pin')
            multi_part = ('(symbol "Multi_1_1" ' + text[pin1.start:pin1.end] + ')'
                          '(symbol "Multi_2_1" ' + text[pin2.start:pin2.end] + ')')
            new_library = edit(text[library.start:library.end],
                               [(part.start-library.start, part.end-library.start, multi_part)])
            new_library = new_library.replace('"Test:Pair"', '"Test:Multi"').replace('"Pair_0_1"', '"Multi_0_1"')
            symbol = document.all('symbol')[0]
            first = text[symbol.start:symbol.end].replace('"Test:Pair"', '"Test:Multi"')
            second = first.replace('(unit 1)', '(unit 2)').replace('(at 25 25 0)', '(at 25 75 0)')
            # Each placed unit/pin owns its UUID; the footprint links to unit 1.
            import re
            second = re.sub(r'\(uuid "[^"]+"\)', lambda _: f'(uuid "{uuid.uuid4()}")', second)
            libs = document.one('lib_symbols')
            text = edit(text, [(libs.end-1, libs.end-1, new_library),
                               (symbol.start, symbol.end, first),
                               (document.end-1, document.end-1, second)])
            sch.write_text(text)
            board = pcbnew.LoadBoard(str(board_path))
            track = pcbnew.PCB_TRACK(board)
            track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(10), pcbnew.FromMM(20)))
            track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(20), pcbnew.FromMM(20)))
            track.SetWidth(pcbnew.FromMM(.25))
            track.SetLayer(pcbnew.F_Cu)
            board.Add(track)
            pcbnew.SaveBoard(str(board_path), board)
            nets = root/'nets.json'
            self.scan(board_path, nets)
            result = self.run_cli(['apply', '--board', board_path, '--schematic', sch, '--nets', nets,
                                  '--output-dir', root/'output', '--write-pcb'])
            self.assertEqual(result['wires_added'], 4)

    def test_invalid_drawing_settings_do_not_change_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board, sch = fixture(root)
            source = sch.read_bytes()
            for length in ('0', '-1', 'nan', 'inf'):
                with self.subTest(length=length):
                    result = self.run_cli(['apply', '--board', board, '--schematic', sch,
                                          '--nets', root/'unused.json', '--in-place',
                                          '--wire-length', length], expected=2)
                    self.assertIn('finite positive', result['error'])
            self.assertEqual(sch.read_bytes(), source)



if __name__ == '__main__':
    unittest.main()
