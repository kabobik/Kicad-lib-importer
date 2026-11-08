"""wx dialog; native preparation runs in the CLI, editor net refresh runs on the GUI thread."""
from pathlib import Path
import queue
import time

import wx

from .runner import RecoveryRequest, RecoveryWorker, suggested_output, validate_request, recovery_module


class RecoveryDialog(wx.Dialog):
    def __init__(self, parent=None, *, board_path=''):
        super().__init__(parent, title='Восстановление схемы по меди',
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER, size=(860, 650))
        self.worker = None
        self.result_path = None
        self._closing = False
        self._started = 0
        self._phase = ''
        self._auto_output = ''
        self._previous_board = ''
        self._build_ui()
        self.SetMinSize((700, 560))
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_tick, self.timer)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        if board_path:
            self.board.SetPath(board_path)
            self._on_board_changed(None)
        self.CentreOnParent()

    def _build_ui(self):
        main = wx.BoxSizer(wx.VERTICAL)
        heading = wx.StaticText(self, label='Соединения схемы из медных проводников платы')
        main.Add(heading, 0, wx.ALL, 12)
        note = wx.StaticText(self, label='Сохраните плату и закройте сохранённую схему. Рабочие файлы будут обновлены, исходники сохранены в recovery.')
        note.Wrap(790)
        main.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        form = wx.FlexGridSizer(cols=2, hgap=10, vgap=10)
        form.AddGrowableCol(1)
        self.board = wx.FilePickerCtrl(self, wildcard='Плата KiCad (*.kicad_pcb)|*.kicad_pcb',
                                       style=wx.FLP_OPEN | wx.FLP_FILE_MUST_EXIST | wx.FLP_USE_TEXTCTRL)
        self.schematic = wx.FilePickerCtrl(self, wildcard='Схема KiCad (*.kicad_sch)|*.kicad_sch',
                                           style=wx.FLP_OPEN | wx.FLP_FILE_MUST_EXIST | wx.FLP_USE_TEXTCTRL)
        self.output = wx.DirPickerCtrl(self, message='Новая или пустая папка резервной копии', style=wx.DIRP_USE_TEXTCTRL)
        for title, control in (('Плата', self.board), ('Схема', self.schematic), ('Резервная копия', self.output)):
            form.Add(wx.StaticText(self, label=title), 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(control, 1, wx.EXPAND)
        self.board.Bind(wx.EVT_FILEPICKER_CHANGED, self._on_board_changed)
        main.Add(form, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        drawing = wx.BoxSizer(wx.HORIZONTAL)
        self.wire_length = wx.SpinCtrlDouble(self, min=.01, max=100, initial=2.5, inc=.25, size=(100, -1))
        self.wire_length.SetDigits(3)
        self.label_size = wx.SpinCtrlDouble(self, min=.1, max=10, initial=1.27, inc=.1, size=(100, -1))
        self.label_size.SetDigits(2)
        self.prefix = wx.TextCtrl(self, value='REC', size=(100, -1))
        for title, control in (('Провод, мм', self.wire_length), ('Текст, мм', self.label_size), ('Префикс цепей', self.prefix)):
            drawing.Add(wx.StaticText(self, label=title), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
            drawing.Add(control, 0, wx.RIGHT, 16)
        main.Add(drawing, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.write_pcb = wx.CheckBox(self, label='Назначить восстановленные цепи в рабочей плате')
        self.write_pcb.SetValue(True)
        main.Add(self.write_pcb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self._inputs = [self.board, self.schematic, self.output, self.wire_length,
                        self.label_size, self.prefix, self.write_pcb]

        self.status = wx.StaticText(self, label='Готово к запуску')
        main.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.progress = wx.Gauge(self, range=100)
        main.Add(self.progress, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.details = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
        main.Add(self.details, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.run_button = wx.Button(self, label='Восстановить')
        self.run_button.SetDefault()
        self.cancel_button = wx.Button(self, label='Остановить')
        self.cancel_button.Disable()
        self.open_button = wx.Button(self, label='Открыть резервную копию')
        self.open_button.Disable()
        self.close_button = wx.Button(self, label='Закрыть')
        self.run_button.Bind(wx.EVT_BUTTON, self._on_run)
        self.cancel_button.Bind(wx.EVT_BUTTON, self._on_cancel)
        self.open_button.Bind(wx.EVT_BUTTON, self._on_open)
        self.close_button.Bind(wx.EVT_BUTTON, lambda _event: self.Close())
        for control in (self.run_button, self.cancel_button, self.open_button):
            actions.Add(control, 0, wx.RIGHT, 8)
        actions.AddStretchSpacer()
        actions.Add(self.close_button)
        main.Add(actions, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizer(main)

    def _on_board_changed(self, _event):
        value = self.board.GetPath()
        if not value:
            return
        board = Path(value)
        old_schematic = str(Path(self._previous_board).with_suffix('.kicad_sch')) if self._previous_board else ''
        if not self.schematic.GetPath() or self.schematic.GetPath() == old_schematic:
            candidate = board.with_suffix('.kicad_sch')
            self.schematic.SetPath(str(candidate) if candidate.is_file() else '')
        if not self.output.GetPath() or self.output.GetPath() == self._auto_output:
            self._auto_output = str(suggested_output(board))
            self.output.SetPath(self._auto_output)
        self._previous_board = value

    def _request(self):
        if not all(control.GetPath().strip() for control in (self.board, self.schematic, self.output)):
            raise ValueError('Выберите плату, схему и папку резервной копии.')
        request = RecoveryRequest(
            board=Path(self.board.GetPath()).expanduser().resolve(),
            schematic=Path(self.schematic.GetPath()).expanduser().resolve(),
            output=Path(self.output.GetPath()).expanduser().resolve(),
            wire_length=self.wire_length.GetValue(), label_size=self.label_size.GetValue(),
            prefix=self.prefix.GetValue().strip(), write_pcb=self.write_pcb.GetValue())
        validate_request(request)
        # Query editor state only on the GUI thread; subprocesses read saved files.
        import pcbnew
        board = pcbnew.GetBoard()
        if board and board.GetFileName() and Path(board.GetFileName()).resolve() == request.board and board.IsModified():
            raise ValueError('Сохраните изменения открытой платы перед восстановлением.')
        return request

    def _on_run(self, _event):
        if self.worker is not None:
            return
        try:
            request = self._request()
            self.worker = RecoveryWorker(request)
        except Exception as error:
            self.status.SetLabel('Проверьте параметры')
            self.details.SetValue(str(error))
            return
        self.result_path = request.output
        self.details.SetValue('')
        self._phase = 'Запуск восстановления…'
        self.status.SetLabel(self._phase)
        self._started = time.monotonic()
        for control in self._inputs:
            control.Disable()
        self.run_button.Disable()
        self.open_button.Disable()
        self.cancel_button.Enable()
        self.timer.Start(150)
        self.worker.start()

    def _on_tick(self, _event):
        if self.worker is None:
            return
        while True:
            try:
                kind, payload = self.worker.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'phase':
                self._phase = payload
                self.details.AppendText(payload + '\n')
            elif kind == 'done':
                self._finished(payload)
                return
        self.progress.Pulse()
        elapsed = int(time.monotonic() - self._started)
        self.status.SetLabel(f'{self._phase}  {elapsed // 60}:{elapsed % 60:02d}')

    def _finished(self, result):
        self.timer.Stop()
        self.worker = None
        for control in self._inputs:
            control.Enable()
        self.run_button.Enable()
        self.cancel_button.Disable()
        self.open_button.Enable(self.result_path is not None and self.result_path.is_dir())
        if result['ok']:
            self.progress.SetValue(100)
            self.status.SetLabel('Готово — требуется проверка инженером' if result['warnings']
                                 else 'Готово — соединения совпадают с медью')
            summary = result['summary']
            if summary['pcb_net_fields_updated']:
                try:
                    import pcbnew
                    board = pcbnew.GetBoard()
                    if board and board.GetFileName() and Path(board.GetFileName()).resolve() == Path(result['working_board']):
                        recovery_module('board').sync_editor_net_assignments(board, Path(result['working_board']))
                        pcbnew.Refresh()
                except Exception as error:
                    result['warnings'].append('Файлы сохранены, но открытая плата не обновилась: '
                                              + str(error) + '. Переоткройте плату без сохранения старой версии.')
                    self.status.SetLabel('Файлы обновлены — переоткройте плату')
            self.details.AppendText(
                f'\nФизических групп: {summary["physical_groups"]}\n'
                f'Добавлено проводов: {summary["wires_added"]}\n'
                f'Добавлено меток: {summary["labels_added"]}\n'
                f'\nРабочая схема обновлена: {result["working_schematic"]}\n'
                f'Исходники и отчёты: {self.result_path}\n'
                'Список цепей: connectivity.csv\nОтчёт проверки: validation.json\n'
                'Откройте рабочую схему заново, чтобы увидеть изменения.\n')
            if not summary['pcb_net_fields_updated']:
                self.details.AppendText('Назначения цепей в PCB оставлены без изменений.\n')
            if result['warnings']:
                self.details.AppendText('\nТребует внимания:\n' + '\n\n'.join(result['warnings']) + '\n')
        else:
            self.progress.SetValue(0)
            self.status.SetLabel('Остановлено' if result.get('cancelled') else 'Восстановление не завершено')
            self.details.AppendText('\n' + result['error'] + '\n')
        if result.get('log_warning'):
            self.details.AppendText('Не удалось сохранить журнал: ' + result['log_warning'] + '\n')
        if self.output.GetPath() == self._auto_output and self.result_path and self.result_path.exists():
            self._auto_output = str(suggested_output(Path(self.board.GetPath())))
            self.output.SetPath(self._auto_output)
        if self._closing:
            self.Close()

    def _on_cancel(self, _event):
        if self.worker is not None:
            self.worker.cancel()
            self.cancel_button.Disable()
            self._phase = 'Остановка…'

    def _on_open(self, _event):
        if self.result_path and self.result_path.is_dir():
            wx.LaunchDefaultApplication(str(self.result_path))

    def _on_close(self, event):
        if self.worker is not None:
            self._closing = True
            self._on_cancel(None)
            if event.CanVeto():
                event.Veto()
                return
        self.timer.Stop()
        event.Skip()
