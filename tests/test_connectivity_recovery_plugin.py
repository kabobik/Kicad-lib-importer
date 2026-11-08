"""Exercise the plugin's real CLI transport and Linux installer without a GUI."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

from test_connectivity_recovery import NATIVE, fixture

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT/'plugins/connectivity-recovery/connectivity_recovery_plugin/runner.py'
spec = importlib.util.spec_from_file_location('recovery_plugin_runner_tests', RUNNER)
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


def completed(worker):
    worker.start()
    worker.join(timeout=20)
    if worker.is_alive():
        worker.cancel()
        worker.join(timeout=5)
        raise AssertionError('Worker did not finish')
    events = []
    while not worker.events.empty():
        events.append(worker.events.get_nowait())
    assert events[-1][0] == 'done', events
    return events[-1][1]


class PluginEntryPointTests(unittest.TestCase):
    def invoke(self, app, *, modal_error=None):
        # Run the actual ActionPlugin entry point with the API shape supplied
        # by KiCad's embedded AppConsole, without registering an action in a GUI.
        package_name = 'recovery_plugin_entry_test'
        package = types.ModuleType(package_name)
        package.__path__ = [str(RUNNER.parent)]
        dialog = mock.Mock()
        dialog.ShowModal.side_effect = modal_error
        dialog_factory = mock.Mock(return_value=dialog)
        wx_module = types.SimpleNamespace(GetApp=lambda: app, MessageBox=mock.Mock(),
                                          OK=1, ICON_ERROR=2)
        board = types.SimpleNamespace(GetFileName=lambda: '/project/panel.kicad_pcb')
        pcb_module = types.SimpleNamespace(ActionPlugin=object, GetBoard=lambda: board)
        with mock.patch.dict(sys.modules, {
            package_name: package,
            package_name+'.ui': types.SimpleNamespace(RecoveryDialog=dialog_factory),
            'wx': wx_module, 'pcbnew': pcb_module,
        }):
            spec = importlib.util.spec_from_file_location(package_name+'.main', RUNNER.with_name('main.py'))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.ConnectivityRecoveryPlugin().Run()
        return dialog_factory, dialog, wx_module.MessageBox

    def test_app_console_and_missing_application_open_parentless_dialog(self):
        class AppConsole:
            pass
        for app in (AppConsole(), None):
            with self.subTest(app=type(app).__name__):
                factory, dialog, error = self.invoke(app)
                factory.assert_called_once_with(None, board_path='/project/panel.kicad_pcb')
                dialog.ShowModal.assert_called_once_with()
                dialog.Destroy.assert_called_once_with()
                error.assert_not_called()

    def test_gui_application_keeps_parent_and_cleans_up_failed_modal(self):
        parent = object()
        app = types.SimpleNamespace(GetTopWindow=lambda: parent)
        for failure in (None, RuntimeError('modal failed')):
            with self.subTest(failure=failure):
                factory, dialog, error = self.invoke(app, modal_error=failure)
                factory.assert_called_once_with(parent, board_path='/project/panel.kicad_pcb')
                dialog.Destroy.assert_called_once_with()
                if failure is None:
                    error.assert_not_called()
                else:
                    self.assertEqual(error.call_args.args[0], 'modal failed')


class PluginTransportTests(unittest.TestCase):
    @unittest.skipUnless(NATIVE, 'Requires KiCad')
    def test_real_cli_roundtrip_with_spaces_and_unicode_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'проект с пробелом & $'
            root.mkdir()
            board, sch = fixture(root)
            original = (board.read_bytes(), sch.read_bytes())
            output = root/'recovery'/'first'
            request = runner.RecoveryRequest(board, sch, output, wire_length=5, prefix='RESTORED_')
            result = completed(runner.RecoveryWorker(request, executable=sys.executable))
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['summary']['wires_added'], 2)
            self.assertNotEqual((board.read_bytes(), sch.read_bytes()), original)
            self.assertEqual(((output/board.name).read_bytes(), (output/sch.name).read_bytes()), original)
            self.assertEqual(result['working_schematic'], str(sch))
            report = json.loads((output/'validation.json').read_text())
            self.assertTrue(report['applied_in_place'])
            self.assertEqual(report['working_schematic'], str(sch))
            # Reopen/repeat uses the modified working files; backups preserve
            # the preceding version and no duplicate schematic objects appear.
            installed = sch.read_bytes()
            again = root/'recovery'/'second'
            repeated = completed(runner.RecoveryWorker(
                runner.RecoveryRequest(board, sch, again), executable=sys.executable))
            self.assertTrue(repeated['ok'], repeated)
            self.assertEqual(repeated['summary']['wires_added'], 0)
            self.assertEqual(sch.read_bytes(), installed)
            self.assertEqual((again/sch.name).read_bytes(), installed)
            self.assertEqual(report['wire_length_mm'], 5)
            self.assertTrue(report['pcb_net_fields_updated'])
            self.assertTrue((output/'connectivity.csv').exists())
            self.assertIn('RESTORED_', (output/'connectivity.json').read_text())
            self.assertTrue((output/'recovery.log').exists())

    @unittest.skipUnless(NATIVE, 'Requires KiCad')
    def test_native_conflict_installs_result_and_backs_up_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board, sch = fixture(root, coincident=True)
            source = sch.read_bytes()
            output = root/'result'
            result = completed(runner.RecoveryWorker(runner.RecoveryRequest(board, sch, output),
                                                     executable=sys.executable))
            self.assertTrue(result['ok'], result)
            self.assertFalse(result['verified'])
            self.assertTrue(any('Совмещённые выводы' in item for item in result['warnings']))
            self.assertTrue((output/'connectivity.json').exists())
            self.assertTrue((output/sch.name).exists())
            self.assertEqual((output/sch.name).read_bytes(), source)
            self.assertNotEqual(sch.read_bytes(), source)

    def test_existing_output_is_not_used_or_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board, sch = root/'a.kicad_pcb', root/'a.kicad_sch'
            board.touch()
            sch.touch()
            output = root/'result'
            output.mkdir()
            marker = output/'mine.txt'
            marker.write_text('user content')
            result = completed(runner.RecoveryWorker(runner.RecoveryRequest(board, sch, output),
                                                     executable='/not/executed'))
            self.assertFalse(result['ok'])
            self.assertEqual(marker.read_text(), 'user content')
            self.assertFalse((output/'recovery.log').exists())

    @unittest.skipUnless(os.name == 'posix' and Path('/proc').exists(), 'Linux process groups')
    def test_cancel_stops_command_and_its_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            board, sch = root/'a.kicad_pcb', root/'a.kicad_sch'
            board.touch()
            sch.touch()
            script = root/'slow.py'
            script.write_text('''import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
output = Path(sys.argv[sys.argv.index('--output')+1]).parent
(output/'child.pid').write_text(str(child.pid))
print('started', flush=True)
time.sleep(30)
''')
            output = root/'result'
            worker = runner.RecoveryWorker(runner.RecoveryRequest(board, sch, output),
                                           executable=sys.executable, script=script)
            worker.start()
            child = None
            try:
                deadline = time.monotonic()+5
                while not (output/'child.pid').exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue((output/'child.pid').exists())
                child = int((output/'child.pid').read_text())
                worker.cancel()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                events = []
                while not worker.events.empty():
                    events.append(worker.events.get_nowait())
                self.assertTrue(events[-1][1]['cancelled'])
                status = Path(f'/proc/{child}/status')
                if status.exists():
                    self.assertIn('State:\tZ', status.read_text())
            finally:
                worker.cancel()
                worker.join(timeout=5)
                if child is not None:
                    try:
                        os.kill(child, signal.SIGKILL)
                    except ProcessLookupError:
                        pass


class PluginInstallerTests(unittest.TestCase):
    def environment(self, root, version='10.0.8+local'):
        binary = root/'bin'
        binary.mkdir()
        cli = binary/'kicad-cli'
        cli.write_text('#!/bin/sh\nprintf "%s\\n" "$FAKE_KICAD_VERSION"\n')
        cli.chmod(0o755)
        python = binary/'fake-python'
        python.write_text('#!/bin/sh\nexit 0\n')
        python.chmod(0o755)
        return {**os.environ, 'PATH': str(binary)+os.pathsep+os.environ['PATH'],
                'XDG_DATA_HOME': str(root/'data with spaces'), 'KICAD_PLUGIN_DIR': '',
                'KICAD_RECOVERY_PYTHON': str(python), 'FAKE_KICAD_VERSION': version}

    def install(self, name, env):
        return subprocess.run(['bash', str(ROOT/'scripts'/f'install_{name}_plugin.sh')],
                              env=env, capture_output=True, text=True, timeout=10)

    def test_version_detection_and_idempotent_installation_for_both_plugins(self):
        for version, major_minor in [('10.0.8+local', '10.0'), ('9.0.7', '9.0')]:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                env = self.environment(root, version)
                for name, folder in [('connectivity_recovery', 'connectivity-recovery'),
                                     ('connector_generator', 'connector-generator')]:
                    for _ in range(2):
                        result = self.install(name, env)
                        self.assertEqual(result.returncode, 0, result.stderr)
                    target = Path(env['XDG_DATA_HOME'])/'kicad'/major_minor/'scripting/plugins'/f'{name}_plugin'
                    self.assertTrue(target.is_symlink())
                    self.assertEqual(target.resolve(), ROOT/'plugins'/folder/f'{name}_plugin')

    def test_foreign_installation_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self.environment(root)
            env['KICAD_PLUGIN_DIR'] = str(root/'custom')
            destination = root/'custom/connectivity_recovery_plugin'
            destination.mkdir(parents=True)
            marker = destination/'user-file'
            marker.write_text('mine')
            result = self.install('connectivity_recovery', env)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(marker.read_text(), 'mine')
            self.assertFalse(destination.is_symlink())

    def test_unknown_version_or_missing_python_does_not_install(self):
        for failure in ('version', 'python'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                env = self.environment(root, 'unknown' if failure == 'version' else '10.0.8')
                if failure == 'python':
                    env['KICAD_RECOVERY_PYTHON'] = '/bin/false'
                result = self.install('connectivity_recovery', env)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(Path(env['XDG_DATA_HOME']).exists())


if __name__ == '__main__':
    unittest.main()
