"""Background CLI transport for the dialog; recovery logic stays in the CLI."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
import importlib
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import threading
import tempfile
import sys
from datetime import datetime


@dataclass(frozen=True)
class RecoveryRequest:
    board: Path
    schematic: Path
    output: Path
    wire_length: float = 2.5
    label_size: float = 1.27
    prefix: str = 'REC'
    write_pcb: bool = True


def repository_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / 'scripts/recover_connectivity.py').is_file():
            return parent
    raise RuntimeError('Не найден scripts/recover_connectivity.py. Проверьте установку плагина.')


def python_executable():
    executable = os.environ.get('KICAD_RECOVERY_PYTHON') or shutil.which('python3')
    if not executable:
        raise ValueError('Не найден Python 3. Установите Python с модулем pcbnew.')
    return executable


def suggested_output(board):
    base = board.parent / 'recovery' / (board.stem + '-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    candidate = base
    number = 2
    while candidate.exists():
        candidate = base.with_name(base.name + f'-{number}')
        number += 1
    return candidate


def validate_request(request):
    for path, suffix, title in ((request.board, '.kicad_pcb', 'Плата'),
                                (request.schematic, '.kicad_sch', 'Схема')):
        if not path.is_file() or path.suffix != suffix:
            raise ValueError(f'{title}: выберите существующий файл {suffix}.')
    if not request.prefix.strip():
        raise ValueError('Укажите префикс цепей.')
    if request.output.exists() and (not request.output.is_dir() or any(request.output.iterdir())):
        raise ValueError('Выберите новую или пустую папку резервной копии.')


def recovery_module(name):
    # Reuse the canonical file transaction and PCB API helpers; no second writer.
    root = str(repository_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    return importlib.import_module('tools.connectivity_recovery.' + name)


def command_steps(request, executable, script, prepared):
    """Translate dialog values into the existing public CLI, without a shell."""
    nets = request.output / 'connectivity.json'
    extract = [executable, str(script), 'extract', str(request.board), '--output', str(nets),
               '--prefix', request.prefix]
    apply = [executable, str(script), 'apply', '--board', str(request.board),
             '--schematic', str(request.schematic), '--nets', str(nets),
             '--output-dir', str(prepared), '--wire-length', str(request.wire_length),
             '--label-size', str(request.label_size)]
    if request.write_pcb:
        apply.append('--write-pcb')
    return [('Извлечение цепей из меди…', extract),
            ('Восстановление схемы и проверка соединений…', apply)]


def diagnostic(text):
    # KiCad may emit native diagnostics before the CLI's JSON error.
    for index in reversed([i for i, char in enumerate(text) if char == '{']):
        try:
            value, _ = json.JSONDecoder().raw_decode(text[index:])
        except ValueError:
            continue
        if isinstance(value, dict) and isinstance(value.get('error'), str):
            return value['error']
    return text.strip() or 'Процесс завершился без диагностического сообщения.'


class Cancelled(Exception):
    pass


class RecoveryWorker(threading.Thread):
    def __init__(self, request, *, executable=None, script=None):
        super().__init__(daemon=True, name='kicad-connectivity-recovery')
        self.request = request
        self.executable = executable or python_executable()
        self.script = script or repository_root() / 'scripts/recover_connectivity.py'
        self.events = queue.Queue(maxsize=16)
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._process = None
        self._tail = deque(maxlen=64)

    def _post(self, kind, payload):
        try:
            self.events.put_nowait((kind, payload))
        except queue.Full:
            self.events.get_nowait()
            self.events.put_nowait((kind, payload))

    @staticmethod
    def _signal(process, force=False):
        if process.poll() is not None:
            return
        try:
            if os.name == 'posix':
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
            elif force:
                process.kill()
            else:
                process.terminate()
        except ProcessLookupError:
            pass

    def cancel(self):
        self._cancel.set()
        with self._lock:
            process = self._process
        if process is not None:
            self._signal(process)
            timer = threading.Timer(2, self._signal, args=(process, True))
            timer.daemon = True
            timer.start()

    def _run_command(self, argv):
        if self._cancel.is_set():
            raise Cancelled()
        with self._lock:
            if self._cancel.is_set():
                raise Cancelled()
            self._process = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace',
                start_new_session=os.name == 'posix',
                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1'})
            process = self._process
        # The embedding application can have elevated priority. Recovery should
        # yield CPU to the editor, without imposing a fixed worker/thread limit.
        if hasattr(os, 'setpriority'):
            try:
                os.setpriority(os.PRIO_PROCESS, process.pid, 10)
            except OSError:
                pass
        tail = deque(maxlen=64)
        try:
            with process.stdout:
                for line in process.stdout:
                    tail.append(line[:4096])
                    self._tail.append(line[:4096])
            status = process.wait()
            if self._cancel.is_set():
                raise Cancelled()
            if status:
                raise RuntimeError(diagnostic(''.join(tail)))
        finally:
            if process.poll() is None:
                self._signal(process, force=True)
                process.wait()
            with self._lock:
                self._process = None

    def run(self):
        created = False
        result = {'ok': False, 'output': str(self.request.output)}
        try:
            validate_request(self.request)
            self.request.output.mkdir(parents=True, exist_ok=True)
            created = True
            with tempfile.TemporaryDirectory(prefix='kicad-recovery-prepared-') as temp:
                prepared = Path(temp) / 'prepared'
                for title, argv in command_steps(self.request, self.executable, self.script, prepared):
                    self._post('phase', title)
                    self._run_command(argv)
                if self._cancel.is_set():
                    raise Cancelled()
                # No child process remains here. Cancellation cannot interrupt
                # the short backup/install transaction or its rollback.
                self._post('phase', 'Сохранение исходников и замена рабочих файлов…')
                report = recovery_module('cli').install_prepared_recovery(
                    self.request.board, self.request.schematic, prepared, self.request.output)
                result.update(ok=True, verified=report['verified'], warnings=report['warnings'],
                              working_board=str(self.request.board), working_schematic=str(self.request.schematic),
                              summary={key: report[key] for key in
                              ('physical_groups', 'wires_added', 'labels_added', 'pcb_net_fields_updated')})
        except Cancelled:
            result.update(cancelled=True, error='Восстановление остановлено. Рабочие файлы ещё не заменены; в папке резервной копии могут остаться отчёты.')
        except Exception as error:
            result['error'] = str(error)
        finally:
            if created:
                try:
                    (self.request.output / 'recovery.log').write_text(''.join(self._tail), encoding='utf-8')
                except OSError as error:
                    result['log_warning'] = str(error)
            self._post('done', result)
