# -*- coding: utf-8 -*-
"""
Entry point — ActionPlugin subclass that KiCad discovers and runs.
"""

import logging
import os
import sys

# ------------------------------------------------------------------
# Logging setup (once, at import time)
# ------------------------------------------------------------------
_LOG_PATH = os.path.expanduser("~/.kicad_git_plugin.log")
_root_logger = logging.getLogger("kicad_git_plugin")
if not _root_logger.handlers:
    _root_logger.setLevel(logging.DEBUG)
    try:
        _fh = logging.FileHandler(_LOG_PATH, encoding="utf-8")
        _fh.setFormatter(logging.Formatter(
            "%(asctime)s  %(name)s  %(levelname)s  %(message)s"
        ))
        _root_logger.addHandler(_fh)
    except Exception:
        pass  # logging is best-effort

logger = logging.getLogger("kicad_git_plugin.main")

# ------------------------------------------------------------------
# Conditional pcbnew import
# ------------------------------------------------------------------
try:
    import pcbnew
    _HAS_PCBNEW = True
except ImportError:
    _HAS_PCBNEW = False

# Base class — real or stub
if _HAS_PCBNEW:
    _ActionPluginBase = pcbnew.ActionPlugin
else:
    class _ActionPluginBase:
        """Stub so the module can be imported outside KiCad."""
        def register(self):
            pass

        def defaults(self):
            pass

        def Run(self):
            pass


class GitIntegrationPlugin(_ActionPluginBase):
    """KiCad Action Plugin — opens the Git Integration dialog."""

    def defaults(self):
        self.name = "Git Integration for KiCad Libraries"
        self.category = "Version Control"
        self.description = (
            "Git-интеграция для библиотек KiCad: pull, commit, push, "
            "SSH-настройка и автоматический fetch."
        )
        self.show_toolbar_button = True
        icon_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "icon.png"
        )
        if os.path.isfile(icon_path):
            self.icon_file_name = icon_path
        else:
            self.icon_file_name = ""

    def Run(self):
        logger.info("Plugin launched")
        try:
            import wx
            from .config_service import ConfigService
            from .git_service import GitService
            from .ssh_service import SSHService
            from .ui import MainDialog

            config = ConfigService()
            git = GitService(config)
            ssh = SSHService(config)

            # Determine a parent window — KiCad's main frame if available
            parent = None
            app = wx.GetApp()
            if app is not None and hasattr(app, "GetTopWindow"):
                try:
                    parent = app.GetTopWindow()
                except Exception:
                    parent = None

            dlg = MainDialog(parent, config=config, git=git, ssh=ssh)
            dlg.ShowModal()
            dlg.Destroy()
        except Exception:
            logger.exception("Unhandled error in plugin Run()")
            try:
                import wx
                wx.MessageBox(
                    "Ошибка плагина Git Integration.\n"
                    "Подробности: " + _LOG_PATH,
                    "Ошибка",
                    wx.OK | wx.ICON_ERROR,
                )
            except Exception:
                pass


# ------------------------------------------------------------------
# Standalone launch helper (for development / testing outside KiCad)
# ------------------------------------------------------------------
def _standalone():
    """Launch the plugin dialog outside KiCad for testing."""
    import wx
    # Ensure the package is importable
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)

    from git_integration.config_service import ConfigService
    from git_integration.git_service import GitService
    from git_integration.ssh_service import SSHService
    from git_integration.ui import MainDialog

    app = wx.App(False)
    config = ConfigService()
    git = GitService(config)
    ssh = SSHService(config)
    dlg = MainDialog(None, config=config, git=git, ssh=ssh)
    dlg.ShowModal()
    dlg.Destroy()
    app.MainLoop()


if __name__ == "__main__":
    _standalone()
