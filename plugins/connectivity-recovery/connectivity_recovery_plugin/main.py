"""Register the recovery toolbar action in the KiCad PCB editor."""
from pathlib import Path

import pcbnew


class ConnectivityRecoveryPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = 'Восстановить схему по меди'
        self.category = 'Schematic Tools'
        self.description = 'Восстановление соединений схемы по сохранённой меди платы'
        self.show_toolbar_button = True
        self.icon_file_name = str(Path(__file__).resolve().with_name('icon.png'))
        self.dark_icon_file_name = self.icon_file_name

    def Run(self):
        import wx
        try:
            from .ui import RecoveryDialog
            board = pcbnew.GetBoard()
            path = board.GetFileName() if board else ''
            # KiCad's embedded wx application can be AppConsole, which has
            # no GetTopWindow. wx.Dialog also accepts an absent parent.
            get_top_window = getattr(wx.GetApp(), 'GetTopWindow', None)
            parent = get_top_window() if callable(get_top_window) else None
            dialog = RecoveryDialog(parent, board_path=path)
            try:
                dialog.ShowModal()
            finally:
                dialog.Destroy()
        except Exception as error:
            wx.MessageBox(str(error), 'Восстановление схемы', wx.OK | wx.ICON_ERROR)
