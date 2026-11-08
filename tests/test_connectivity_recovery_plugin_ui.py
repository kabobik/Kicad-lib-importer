"""Opt-in check of real wx controls, with no visible dialog or editor restart."""
import importlib
from contextlib import ExitStack
from unittest import mock
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest

from test_connectivity_recovery import NATIVE, fixture

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('KICAD_TEST_GUI') == '1' and NATIVE,
                     'Set KICAD_TEST_GUI=1 from a graphical session')
class RecoveryDialogTests(unittest.TestCase):
    def test_async_completion_controls_and_icon(self):
        import wx
        # Action registration requires an actual KiCad application. Load the UI
        # in a separate package namespace without executing __init__.py.
        package_name = 'recovery_plugin_gui_test'
        package = types.ModuleType(package_name)
        package.__path__ = [str(ROOT/'plugins/connectivity-recovery/connectivity_recovery_plugin')]
        sys.modules[package_name] = package
        app = wx.App(False)
        dialog = None
        editor_patches = ExitStack()
        try:
            ui = importlib.import_module(package_name+'.ui')
            main = importlib.import_module(package_name+'.main')
            with tempfile.TemporaryDirectory(prefix='recovery-dialog-') as temp:
                board, sch = fixture(Path(temp))
                original_schematic = sch.read_bytes()
                import pcbnew
                live = pcbnew.LoadBoard(str(board))
                editor_patches.enter_context(mock.patch.object(pcbnew, 'GetBoard', return_value=live))
                editor_patches.enter_context(mock.patch.object(pcbnew, 'LoadBoard', return_value=live))
                editor_patches.enter_context(mock.patch.object(pcbnew, 'Refresh'))
                dialog = ui.RecoveryDialog(None, board_path=str(board))
                self.assertEqual(dialog.board.GetPath(), str(board))
                self.assertEqual(dialog.schematic.GetPath(), str(sch))
                self.assertEqual(dialog.wire_length.GetValue(), 2.5)
                self.assertTrue(dialog.write_pcb.GetValue())
                self.assertFalse(dialog.cancel_button.IsEnabled())
                dialog.Layout()
                dialog._on_run(None)
                self.assertIsNotNone(dialog.worker, dialog.details.GetValue())
                self.assertFalse(dialog.run_button.IsEnabled())
                deadline = time.monotonic()+15
                while dialog.worker is not None and time.monotonic() < deadline:
                    app.Yield()
                    time.sleep(.02)
                self.assertIsNone(dialog.worker, 'Dialog did not receive completion')
                self.assertEqual(dialog.progress.GetValue(), 100, dialog.details.GetValue())
                self.assertTrue(dialog.open_button.IsEnabled())
                self.assertTrue(dialog.run_button.IsEnabled())
                self.assertIn('совпадают с медью', dialog.status.GetLabel())
                self.assertNotEqual(sch.read_bytes(), original_schematic)
                self.assertEqual((dialog.result_path/sch.name).read_bytes(), original_schematic)
                self.assertIn(str(sch), dialog.details.GetValue())
                # Check the actual GUI completion path, then simulate Ctrl+S.
                def assignments(value):
                    return {item.m_Uuid.AsString(): item.GetNetname() for item in
                            [p for f in value.GetFootprints() for p in f.Pads()]
                            + list(value.GetTracks()) + list(value.Zones())}
                native = pcbnew.PCB_IO_MGR.Load(pcbnew.PCB_IO_MGR.KICAD_SEXP, str(board))
                expected = assignments(native)
                self.assertEqual(assignments(live), expected)
                pcbnew.SaveBoard(str(board), live)
                reloaded = pcbnew.PCB_IO_MGR.Load(pcbnew.PCB_IO_MGR.KICAD_SEXP, str(board))
                self.assertEqual(assignments(reloaded), expected)
                dialog._finished({'ok': True, 'verified': False,
                                  'working_board': str(board), 'working_schematic': str(sch),
                                  'warnings': ['Совмещённые выводы J1.1, J1.2: проверьте символ.'],
                                  'summary': {'physical_groups': 3, 'wires_added': 2,
                                              'labels_added': 2, 'pcb_net_fields_updated': True}})
                self.assertIn('требуется проверка инженером', dialog.status.GetLabel())
                self.assertIn('J1.1, J1.2', dialog.details.GetValue())
                self.assertTrue(dialog.open_button.IsEnabled())
                self.assertEqual(dialog.progress.GetValue(), 100)
                plugin = main.ConnectivityRecoveryPlugin()
                self.assertTrue(plugin.show_toolbar_button)
                self.assertTrue(wx.Image(plugin.icon_file_name).IsOk())
        finally:
            if dialog is not None:
                if dialog.worker is not None:
                    dialog.worker.cancel()
                    dialog.worker.join(timeout=5)
                dialog.Destroy()
            editor_patches.close()
            app.Destroy()
            for name in list(sys.modules):
                if name == package_name or name.startswith(package_name+'.'):
                    sys.modules.pop(name)


if __name__ == '__main__':
    unittest.main()
