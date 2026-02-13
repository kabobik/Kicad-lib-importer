# -*- coding: utf-8 -*-
"""
wxPython UI — all dialogs for the Git Integration plugin.

Every dialog receives service objects via the constructor so that the
UI layer never touches subprocess or file I/O directly.
"""

import logging
import os
import threading
import time

import wx

logger = logging.getLogger("kicad_git_plugin.ui")


# ======================================================================
#  MainDialog
# ======================================================================
class MainDialog(wx.Dialog):
    """Primary window with status bar, action buttons, and output log."""

    def __init__(self, parent, config, git, ssh):
        super(MainDialog, self).__init__(
            parent,
            title="Git Integration for KiCad Libraries",
            size=(620, 520),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.config = config
        self.git = git
        self.ssh = ssh
        self._last_fetch_time = None

        self.SetMinSize((500, 400))
        self._build_ui()
        self.Centre()

        # Check git availability
        self._git_available = self.git.git_available()

        # Initial refresh (local, fast)
        wx.CallAfter(self._on_refresh_status)
        # Background fetch
        wx.CallAfter(self._start_bg_fetch)

        # Periodic fetch timer
        self._fetch_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_fetch_timer, self._fetch_timer)
        interval_ms = self.config.get_fetch_interval() * 1000
        if interval_ms >= 10000:  # min 10 sec
            self._fetch_timer.Start(interval_ms)

        # Close handler
        self.Bind(wx.EVT_CLOSE, self._on_close)

        # First-run wizard (deferred)
        wx.CallAfter(self._first_run_check)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_ui(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # --- Status bar ---
        self.lbl_branch = wx.StaticText(panel, label="...")
        font_branch = self.lbl_branch.GetFont()
        font_branch.SetWeight(wx.FONTWEIGHT_BOLD)
        font_branch.SetPointSize(font_branch.GetPointSize() + 1)
        self.lbl_branch.SetFont(font_branch)

        self.lbl_sync = wx.StaticText(panel, label="")
        self.lbl_dirty = wx.StaticText(panel, label="")
        self.lbl_fetch_time = wx.StaticText(panel, label="")

        status_row1 = wx.BoxSizer(wx.HORIZONTAL)
        status_row1.Add(self.lbl_branch, 0, wx.RIGHT, 10)
        status_row1.Add(self.lbl_sync, 0, wx.RIGHT, 15)
        status_row1.Add(self.lbl_dirty, 0, wx.RIGHT, 15)
        status_row1.Add(self.lbl_fetch_time, 0)

        vbox.Add(status_row1, 0, wx.ALL | wx.EXPAND, 8)
        vbox.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        # --- Action buttons ---
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_pull = wx.Button(panel, label="Pull")
        self.btn_commit = wx.Button(panel, label="Commit")
        self.btn_push = wx.Button(panel, label="Push")
        self.btn_status = wx.Button(panel, label="Status")
        for btn in (self.btn_pull, self.btn_commit, self.btn_push, self.btn_status):
            btn_row.Add(btn, 0, wx.ALL, 4)
        vbox.Add(btn_row, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
        vbox.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)

        # --- Output log ---
        vbox.Add(
            wx.StaticText(panel, label="Output:"),
            0, wx.LEFT | wx.TOP, 8,
        )
        self.txt_output = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP | wx.HSCROLL,
        )
        self.txt_output.SetFont(wx.Font(
            9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL,
        ))
        vbox.Add(self.txt_output, 1, wx.ALL | wx.EXPAND, 8)

        # --- Bottom bar ---
        vbox.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        bottom_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_settings = wx.Button(panel, label=u"\u2699 Settings")
        self.btn_ssh = wx.Button(panel, label=u"\U0001F511 SSH Setup")
        self.btn_help = wx.Button(panel, label="? Help")
        bottom_row.Add(self.btn_settings, 0, wx.ALL, 4)
        bottom_row.Add(self.btn_ssh, 0, wx.ALL, 4)
        bottom_row.AddStretchSpacer()
        bottom_row.Add(self.btn_help, 0, wx.ALL, 4)
        vbox.Add(bottom_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        panel.SetSizer(vbox)

        # --- Bindings ---
        self.btn_pull.Bind(wx.EVT_BUTTON, self._on_pull)
        self.btn_commit.Bind(wx.EVT_BUTTON, self._on_commit)
        self.btn_push.Bind(wx.EVT_BUTTON, self._on_push)
        self.btn_status.Bind(wx.EVT_BUTTON, self._on_status)
        self.btn_settings.Bind(wx.EVT_BUTTON, self._on_settings)
        self.btn_ssh.Bind(wx.EVT_BUTTON, self._on_ssh_setup)
        self.btn_help.Bind(wx.EVT_BUTTON, self._on_help)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _log(self, text):
        ts = time.strftime("%H:%M:%S")
        self.txt_output.AppendText("[{t}] {m}\n".format(t=ts, m=text))

    def _set_buttons_enabled(self, enabled):
        for btn in (self.btn_pull, self.btn_commit, self.btn_push, self.btn_status):
            btn.Enable(enabled)

    def _update_status_labels(self, st):
        branch = st.get("branch", "")
        if branch:
            self.lbl_branch.SetLabel("[{b}]".format(b=branch))
        else:
            self.lbl_branch.SetLabel("[нет репозитория]")

        ahead = st.get("ahead", 0)
        behind = st.get("behind", 0)
        self.lbl_sync.SetLabel(u"\u2B07{b} \u2B06{a}".format(a=ahead, b=behind))

        n_mod = len(st.get("modified", []))
        n_new = len(st.get("untracked", []))
        self.lbl_dirty.SetLabel("{m} изменено, {n} новых".format(m=n_mod, n=n_new))

        if self._last_fetch_time:
            self.lbl_fetch_time.SetLabel(
                u"\u21BB " + time.strftime("%H:%M:%S", time.localtime(self._last_fetch_time))
            )

        # Update button labels with counts
        if behind > 0:
            self.btn_pull.SetLabel(u"Pull \u2B07{n}".format(n=behind))
        else:
            self.btn_pull.SetLabel("Pull")

        if ahead > 0:
            self.btn_push.SetLabel(u"Push \u2B06{n}".format(n=ahead))
        else:
            self.btn_push.SetLabel("Push")

        n_changes = n_mod + n_new + len(st.get("staged", []))
        if n_changes > 0:
            self.btn_commit.SetLabel("Commit ({n})".format(n=n_changes))
        else:
            self.btn_commit.SetLabel("Commit")

    # ------------------------------------------------------------------
    # Status / Fetch
    # ------------------------------------------------------------------
    def _on_refresh_status(self):
        if not self._git_available:
            self.lbl_branch.SetLabel(u"[Git не найден]")
            self._log(u"Git не найден в системе. Установите Git для работы плагина.")
            self._set_buttons_enabled(False)
            return
        if not self.config.is_configured():
            self.lbl_branch.SetLabel(u"[не настроено]")
            self._log(u"Плагин не настроен. Откройте Settings.")
            return
        st = self.git.status()
        self._update_status_labels(st)

        # Show remote type
        rtype = self.git.get_remote_type()
        rurl = self.git.get_remote_url()
        if rtype == "https":
            self._log(u"Remote: HTTPS ({u})".format(u=rurl))
        elif rtype == "ssh":
            self._log(u"Remote: SSH ({u})".format(u=rurl))
        else:
            self._log(u"Remote: не определён")

    def _on_status(self, event=None):
        if not self.config.is_configured():
            self._log("Плагин не настроен.")
            return
        self._log("--- git status ---")
        st = self.git.status()
        self._update_status_labels(st)
        if st["staged"]:
            self._log("Staged: " + ", ".join(st["staged"]))
        if st["modified"]:
            self._log("Modified: " + ", ".join(st["modified"]))
        if st["untracked"]:
            self._log("Untracked: " + ", ".join(st["untracked"]))
        if not st["staged"] and not st["modified"] and not st["untracked"]:
            self._log("Working tree clean.")

    def _start_bg_fetch(self):
        if not self.config.is_configured():
            return

        def _worker():
            sync = self.git.get_sync_status()
            wx.CallAfter(self._bg_fetch_done, sync)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _bg_fetch_done(self, sync):
        self._last_fetch_time = time.time()
        if sync.get("success"):
            self._log("Fetch OK.")
        else:
            self._log("Fetch: " + sync.get("message", "ошибка"))
        # refresh labels
        st = self.git.status()
        self._update_status_labels(st)

    # ------------------------------------------------------------------
    # Timer / Close / First-run
    # ------------------------------------------------------------------
    def _on_fetch_timer(self, event):
        self._start_bg_fetch()

    def _on_close(self, event):
        if hasattr(self, '_fetch_timer') and self._fetch_timer.IsRunning():
            self._fetch_timer.Stop()
        self.EndModal(wx.ID_CANCEL)

    def _first_run_check(self):
        """Show first-run wizard if plugin is not configured."""
        if not self._git_available:
            return
        if self.config.is_configured():
            return

        wx.MessageBox(
            u"\u0414\u043e\u0431\u0440\u043e \u043f\u043e\u0436\u0430\u043b\u043e\u0432\u0430\u0442\u044c \u0432 Git Integration for KiCad Libraries!\n\n"
            u"\u0414\u0430\u0432\u0430\u0439\u0442\u0435 \u043d\u0430\u0441\u0442\u0440\u043e\u0438\u043c \u043f\u043b\u0430\u0433\u0438\u043d \u0434\u043b\u044f \u0440\u0430\u0431\u043e\u0442\u044b.",
            u"\u041f\u0435\u0440\u0432\u044b\u0439 \u0437\u0430\u043f\u0443\u0441\u043a",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

        # Open Settings dialog
        dlg = SettingsDialog(self, config=self.config)
        if dlg.ShowModal() == wx.ID_OK:
            self._log(u"\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u044b.")
        dlg.Destroy()

        # Check SSH key
        if not self.ssh.key_exists():
            ret = wx.MessageBox(
                u"SSH-\u043a\u043b\u044e\u0447 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d. \u0421\u043e\u0437\u0434\u0430\u0442\u044c \u0435\u0433\u043e \u0441\u0435\u0439\u0447\u0430\u0441?",
                u"SSH Setup",
                wx.YES_NO | wx.ICON_QUESTION,
                self,
            )
            if ret == wx.YES:
                dlg = SSHSetupDialog(self, config=self.config, ssh=self.ssh)
                dlg.ShowModal()
                dlg.Destroy()
        else:
            ret = wx.MessageBox(
                u"SSH-\u043a\u043b\u044e\u0447 \u043d\u0430\u0439\u0434\u0435\u043d. \u041f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u0441\u043e\u0435\u0434\u0438\u043d\u0435\u043d\u0438\u0435 \u0441 \u0441\u0435\u0440\u0432\u0435\u0440\u043e\u043c?",
                u"\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0441\u043e\u0435\u0434\u0438\u043d\u0435\u043d\u0438\u044f",
                wx.YES_NO | wx.ICON_QUESTION,
                self,
            )
            if ret == wx.YES:
                dlg = SSHSetupDialog(self, config=self.config, ssh=self.ssh)
                dlg.ShowModal()
                dlg.Destroy()

        # Refresh status after setup
        self._on_refresh_status()

    # ------------------------------------------------------------------
    # Pull / Commit / Push
    # ------------------------------------------------------------------
    def _on_pull(self, event):
        if not self.config.is_configured():
            self._log("Плагин не настроен.")
            return
        self._set_buttons_enabled(False)
        self._log("Pull ...")

        def _worker():
            ok, msg = self.git.pull()
            wx.CallAfter(self._action_done, "Pull", ok, msg)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_commit(self, event):
        if not self.config.is_configured():
            self._log("Плагин не настроен.")
            return
        dlg = CommitDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            message = dlg.get_message()
            dlg.Destroy()
            if not message.strip():
                self._log("Commit: пустое сообщение, отменено.")
                return
            self._set_buttons_enabled(False)
            self._log("Commit ...")

            def _worker():
                ok, msg = self.git.commit(message)
                wx.CallAfter(self._action_done, "Commit", ok, msg)

            threading.Thread(target=_worker, daemon=True).start()
        else:
            dlg.Destroy()

    def _on_push(self, event):
        if not self.config.is_configured():
            self._log(u"Плагин не настроен.")
            return
        # Block push if behind remote
        st = self.git.status()
        behind = st.get("behind", 0)
        if behind > 0:
            wx.MessageBox(
                u"Репозиторий отстаёт от сервера на {n} коммитов.\n"
                u"Сначала выполните Pull.".format(n=behind),
                u"Push заблокирован",
                wx.OK | wx.ICON_WARNING,
                self,
            )
            return
        ret = wx.MessageBox(
            u"Отправить коммиты на сервер?",
            "Push",
            wx.YES_NO | wx.ICON_QUESTION,
            self,
        )
        if ret != wx.YES:
            return
        self._set_buttons_enabled(False)
        self._log("Push ...")

        def _worker():
            ok, msg = self.git.push()
            wx.CallAfter(self._action_done, "Push", ok, msg)

        threading.Thread(target=_worker, daemon=True).start()

    def _action_done(self, action, ok, msg):
        self._set_buttons_enabled(True)
        prefix = u"\u2713 " if ok else u"\u2717 "
        self._log("{p}{a}: {m}".format(p=prefix, a=action, m=msg))
        # Refresh status labels
        st = self.git.status()
        self._update_status_labels(st)

    # ------------------------------------------------------------------
    # Settings / SSH / Help dialogs
    # ------------------------------------------------------------------
    def _on_settings(self, event):
        dlg = SettingsDialog(self, config=self.config, git=self.git)
        if dlg.ShowModal() == wx.ID_OK:
            self._log("Настройки сохранены.")
            wx.CallAfter(self._on_refresh_status)
        dlg.Destroy()

    def _on_ssh_setup(self, event):
        dlg = SSHSetupDialog(self, config=self.config, ssh=self.ssh)
        dlg.ShowModal()
        dlg.Destroy()

    def _on_help(self, event):
        dlg = HelpDialog(self)
        dlg.ShowModal()
        dlg.Destroy()


# ======================================================================
#  SettingsDialog
# ======================================================================
class SettingsDialog(wx.Dialog):
    """Edit plugin settings (server, repo, ssh, fetch)."""

    def __init__(self, parent, config, git=None):
        super(SettingsDialog, self).__init__(
            parent,
            title=u"Настройки",
            size=(520, 520),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.config = config
        self.git = git
        self._build_ui()
        self.Centre()

    def _build_ui(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # --- Repository section ---
        repo_box = wx.StaticBoxSizer(wx.VERTICAL, panel, u"Репозиторий")
        repo_grid = wx.FlexGridSizer(cols=3, vgap=6, hgap=6)
        repo_grid.AddGrowableCol(1, 1)

        self.txt_repo = wx.TextCtrl(panel)
        btn_browse_repo = wx.Button(panel, label="...", size=(32, -1))
        repo_grid.Add(wx.StaticText(panel, label=u"Путь:"), 0, wx.ALIGN_CENTER_VERTICAL)
        repo_grid.Add(self.txt_repo, 1, wx.EXPAND)
        repo_grid.Add(btn_browse_repo, 0)

        self.txt_interval = wx.TextCtrl(panel, size=(60, -1))
        repo_grid.Add(wx.StaticText(panel, label=u"Fetch интервал (сек):"), 0, wx.ALIGN_CENTER_VERTICAL)
        repo_grid.Add(self.txt_interval, 0)
        repo_grid.Add((0, 0))

        repo_box.Add(repo_grid, 1, wx.ALL | wx.EXPAND, 6)
        vbox.Add(repo_box, 0, wx.ALL | wx.EXPAND, 8)

        # --- Remote info (read-only) ---
        self.lbl_remote_info = wx.StaticText(panel, label=u"Remote: определяется...")
        vbox.Add(self.lbl_remote_info, 0, wx.LEFT | wx.RIGHT, 14)

        # --- HTTPS Credentials section ---
        cred_box = wx.StaticBoxSizer(wx.VERTICAL, panel, u"HTTPS авторизация (токен)")
        cred_grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=6)
        cred_grid.AddGrowableCol(1, 1)

        self.txt_username = wx.TextCtrl(panel)
        self.txt_token = wx.TextCtrl(panel, style=wx.TE_PASSWORD)

        cred_grid.Add(wx.StaticText(panel, label=u"Логин:"), 0, wx.ALIGN_CENTER_VERTICAL)
        cred_grid.Add(self.txt_username, 1, wx.EXPAND)
        cred_grid.Add(wx.StaticText(panel, label=u"Токен:"), 0, wx.ALIGN_CENTER_VERTICAL)
        cred_grid.Add(self.txt_token, 1, wx.EXPAND)

        cred_box.Add(cred_grid, 1, wx.ALL | wx.EXPAND, 6)
        self.lbl_cred_hint = wx.StaticText(
            panel,
            label=u"Forgejo: Settings \u2192 Applications \u2192 Generate Token",
        )
        self.lbl_cred_hint.SetForegroundColour(wx.Colour(100, 100, 100))
        cred_box.Add(self.lbl_cred_hint, 0, wx.LEFT | wx.BOTTOM, 6)
        vbox.Add(cred_box, 0, wx.ALL | wx.EXPAND, 8)

        # --- SSH / Server section ---
        ssh_box = wx.StaticBoxSizer(wx.VERTICAL, panel, u"SSH (для SSH-remote)")
        ssh_grid = wx.FlexGridSizer(cols=3, vgap=6, hgap=6)
        ssh_grid.AddGrowableCol(1, 1)

        self.txt_host = wx.TextCtrl(panel)
        self.txt_port = wx.TextCtrl(panel, size=(60, -1))
        self.txt_user = wx.TextCtrl(panel)
        self.txt_key = wx.TextCtrl(panel)
        btn_browse_key = wx.Button(panel, label="...", size=(32, -1))

        ssh_rows = [
            (u"Server host:", self.txt_host, None),
            (u"SSH port:", self.txt_port, None),
            (u"User:", self.txt_user, None),
            (u"SSH key:", self.txt_key, btn_browse_key),
        ]
        for label, ctrl, btn in ssh_rows:
            ssh_grid.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            ssh_grid.Add(ctrl, 1, wx.EXPAND)
            if btn:
                ssh_grid.Add(btn, 0)
            else:
                ssh_grid.Add((0, 0))

        ssh_box.Add(ssh_grid, 1, wx.ALL | wx.EXPAND, 6)
        vbox.Add(ssh_box, 0, wx.ALL | wx.EXPAND, 8)

        # --- Buttons ---
        btn_sizer = wx.StdDialogButtonSizer()
        btn_ok = wx.Button(panel, wx.ID_OK, u"Сохранить")
        btn_cancel = wx.Button(panel, wx.ID_CANCEL, u"Отмена")
        btn_sizer.AddButton(btn_ok)
        btn_sizer.AddButton(btn_cancel)
        btn_sizer.Realize()

        vbox.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        vbox.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        panel.SetSizer(vbox)

        # --- Populate ---
        self.txt_repo.SetValue(self.config.get("repository", "path"))
        self.txt_interval.SetValue(str(self.config.get_fetch_interval()))
        self.txt_username.SetValue(self.config.get_credentials_username())
        self.txt_token.SetValue(self.config.get_credentials_token())
        self.txt_host.SetValue(self.config.get_server_host())
        self.txt_port.SetValue(str(self.config.get_server_port()))
        self.txt_user.SetValue(self.config.get_server_user())
        self.txt_key.SetValue(self.config.get_ssh_key_path())

        # Show remote type if git service available
        self._update_remote_info()

        # --- Bindings ---
        btn_ok.Bind(wx.EVT_BUTTON, self._on_save)
        btn_browse_repo.Bind(wx.EVT_BUTTON, self._on_browse_repo)
        btn_browse_key.Bind(wx.EVT_BUTTON, self._on_browse_key)

    def _update_remote_info(self):
        if self.git is not None:
            rtype = self.git.get_remote_type()
            rurl = self.git.get_remote_url()
            if rtype == "https":
                self.lbl_remote_info.SetLabel(u"Remote: HTTPS \u2014 \u0442\u0440\u0435\u0431\u0443\u0435\u0442\u0441\u044f \u043b\u043e\u0433\u0438\u043d/\u0442\u043e\u043a\u0435\u043d")
                self.lbl_remote_info.SetForegroundColour(wx.Colour(0, 100, 180))
            elif rtype == "ssh":
                self.lbl_remote_info.SetLabel(u"Remote: SSH \u2014 \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0435\u0442\u0441\u044f \u043a\u043b\u044e\u0447")
                self.lbl_remote_info.SetForegroundColour(wx.Colour(0, 128, 0))
            elif rurl:
                self.lbl_remote_info.SetLabel(u"Remote: {u}".format(u=rurl))
            else:
                self.lbl_remote_info.SetLabel(u"Remote: \u043d\u0435 \u043e\u043f\u0440\u0435\u0434\u0435\u043b\u0451\u043d")
        else:
            self.lbl_remote_info.SetLabel(u"")

    def _on_browse_repo(self, event):
        dlg = wx.DirDialog(self, u"Выберите директорию репозитория")
        if dlg.ShowModal() == wx.ID_OK:
            self.txt_repo.SetValue(dlg.GetPath())
        dlg.Destroy()

    def _on_browse_key(self, event):
        dlg = wx.FileDialog(
            self, u"Выберите SSH ключ",
            wildcard="All files (*)|*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self.txt_key.SetValue(dlg.GetPath())
        dlg.Destroy()

    def _on_save(self, event):
        # Validate
        repo = self.txt_repo.GetValue().strip()
        interval_str = self.txt_interval.GetValue().strip()
        port_str = self.txt_port.GetValue().strip()

        try:
            port = int(port_str)
            if port < 1 or port > 65535:
                raise ValueError
        except ValueError:
            wx.MessageBox(u"Порт должен быть числом от 1 до 65535.", u"Ошибка", wx.OK | wx.ICON_ERROR)
            return

        try:
            interval = int(interval_str)
            if interval < 10:
                raise ValueError
        except ValueError:
            wx.MessageBox(
                u"Интервал Fetch должен быть числом >= 10 (секунд).",
                u"Ошибка", wx.OK | wx.ICON_ERROR,
            )
            return

        # Warn if repo path doesn't contain .git (not a blocker)
        if repo and os.path.isdir(repo):
            git_dir = os.path.join(repo, ".git")
            if not os.path.isdir(git_dir):
                ret = wx.MessageBox(
                    u"Директория не содержит .git репозиторий:\n{p}\n\n"
                    u"Продолжить сохранение?".format(p=repo),
                    u"Предупреждение",
                    wx.YES_NO | wx.ICON_WARNING,
                )
                if ret != wx.YES:
                    return

        # Save all settings
        self.config.set("repository", "path", repo)
        self.config.set("fetch", "interval_sec", str(interval))
        self.config.set("server", "host", self.txt_host.GetValue().strip())
        self.config.set("server", "port", str(port))
        self.config.set("server", "user", self.txt_user.GetValue().strip() or "git")
        self.config.set("ssh", "key_path", self.txt_key.GetValue().strip())

        username = self.txt_username.GetValue().strip()
        token = self.txt_token.GetValue().strip()
        self.config.set("credentials", "username", username)
        self.config.set("credentials", "token", token)
        self.config.save()

        # Auto-apply token to HTTPS remote
        if self.git is not None and username and token:
            rtype = self.git.get_remote_type()
            if rtype == "https":
                ok, msg = self.git.apply_credentials()
                if ok:
                    wx.MessageBox(
                        u"Токен успешно применён к remote URL.\n"
                        u"Push/Pull будут работать без ввода пароля.",
                        u"Готово",
                        wx.OK | wx.ICON_INFORMATION,
                    )
                else:
                    wx.MessageBox(
                        u"Не удалось применить токен:\n{m}".format(m=msg),
                        u"Ошибка",
                        wx.OK | wx.ICON_WARNING,
                    )

        self.EndModal(wx.ID_OK)


# ======================================================================
#  SSHSetupDialog
# ======================================================================
class SSHSetupDialog(wx.Dialog):
    """Generate key, display public key, test connection."""

    def __init__(self, parent, config, ssh):
        super(SSHSetupDialog, self).__init__(
            parent,
            title=u"Настройка SSH",
            size=(560, 520),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.config = config
        self.ssh = ssh
        self._build_ui()
        self._refresh_key_status()
        self.Centre()

    def _build_ui(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # --- Key status ---
        self.lbl_key_status = wx.StaticText(panel, label="")
        font = self.lbl_key_status.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        self.lbl_key_status.SetFont(font)
        vbox.Add(self.lbl_key_status, 0, wx.ALL, 10)

        # --- Passphrase + Generate ---
        row_pass = wx.BoxSizer(wx.HORIZONTAL)
        row_pass.Add(
            wx.StaticText(panel, label=u"Passphrase (необязательно):"),
            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6,
        )
        self.txt_passphrase = wx.TextCtrl(panel, style=wx.TE_PASSWORD, size=(200, -1))
        row_pass.Add(self.txt_passphrase, 1, wx.RIGHT, 8)
        self.btn_generate = wx.Button(panel, label=u"Генерировать ключ")
        row_pass.Add(self.btn_generate, 0)
        vbox.Add(row_pass, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        vbox.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.ALL, 8)

        # --- Public key display ---
        vbox.Add(wx.StaticText(panel, label=u"Публичный ключ:"), 0, wx.LEFT | wx.TOP, 10)
        self.txt_pubkey = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
            size=(-1, 60),
        )
        self.txt_pubkey.SetFont(wx.Font(
            8, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL,
        ))
        vbox.Add(self.txt_pubkey, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self.btn_copy = wx.Button(panel, label=u"\U0001F4CB Скопировать")
        vbox.Add(self.btn_copy, 0, wx.LEFT | wx.TOP, 10)

        vbox.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.ALL, 8)

        # --- Instructions ---
        instructions = (
            u"Инструкция:\n"
            u"1. Откройте Forgejo \u2192 Settings \u2192 SSH / GPG Keys\n"
            u"2. Нажмите \u00abAdd Key\u00bb\n"
            u"3. Вставьте скопированный ключ\n"
            u"4. Нажмите Save"
        )
        lbl_instr = wx.StaticText(panel, label=instructions)
        vbox.Add(lbl_instr, 0, wx.ALL, 10)

        vbox.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # --- Test connection + Update SSH config + Close ---
        bottom_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_test = wx.Button(panel, label=u"Проверить соединение")
        self.btn_update_config = wx.Button(panel, label=u"Обновить SSH config")
        btn_close = wx.Button(panel, wx.ID_CANCEL, u"Закрыть")
        bottom_row.Add(self.btn_test, 0, wx.RIGHT, 6)
        bottom_row.Add(self.btn_update_config, 0, wx.RIGHT, 6)
        bottom_row.AddStretchSpacer()
        bottom_row.Add(btn_close, 0)
        vbox.Add(bottom_row, 0, wx.EXPAND | wx.ALL, 10)

        # --- Result label ---
        self.lbl_result = wx.StaticText(panel, label="")
        vbox.Add(self.lbl_result, 0, wx.LEFT | wx.BOTTOM, 10)

        panel.SetSizer(vbox)

        # Bindings
        self.btn_generate.Bind(wx.EVT_BUTTON, self._on_generate)
        self.btn_copy.Bind(wx.EVT_BUTTON, self._on_copy)
        self.btn_test.Bind(wx.EVT_BUTTON, self._on_test)
        self.btn_update_config.Bind(wx.EVT_BUTTON, self._on_update_ssh_config)

    def _refresh_key_status(self):
        if self.ssh.key_exists():
            self.lbl_key_status.SetLabel(u"\u2713 Ключ найден")
            self.lbl_key_status.SetForegroundColour(wx.Colour(0, 128, 0))
            pub = self.ssh.get_public_key()
            if pub:
                self.txt_pubkey.SetValue(pub)
        else:
            self.lbl_key_status.SetLabel(u"\u26A0 Ключ не найден")
            self.lbl_key_status.SetForegroundColour(wx.Colour(200, 120, 0))
            self.txt_pubkey.SetValue("")

    def _on_generate(self, event):
        if self.ssh.key_exists():
            ret = wx.MessageBox(
                u"Ключ уже существует. Перезаписать?",
                u"Подтверждение",
                wx.YES_NO | wx.ICON_WARNING,
                self,
            )
            if ret != wx.YES:
                return
            # Remove existing key files so ssh-keygen won't prompt
            import os
            key = os.path.expanduser(self.config.get_ssh_key_path())
            for f in (key, key + ".pub"):
                if os.path.isfile(f):
                    os.remove(f)

        passphrase = self.txt_passphrase.GetValue()
        ok, msg, pub = self.ssh.generate_key(passphrase=passphrase)
        if ok:
            self.lbl_result.SetLabel(msg)
            self.lbl_result.SetForegroundColour(wx.Colour(0, 128, 0))
        else:
            self.lbl_result.SetLabel(msg)
            self.lbl_result.SetForegroundColour(wx.Colour(200, 0, 0))
        self._refresh_key_status()

    def _on_copy(self, event):
        pub = self.txt_pubkey.GetValue()
        if not pub:
            return
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(pub))
            wx.TheClipboard.Close()
            orig_label = self.btn_copy.GetLabel()
            self.btn_copy.SetLabel(u"\u2713 Скопировано")
            self.btn_copy.Enable(False)

            def _restore():
                if self.btn_copy:
                    self.btn_copy.SetLabel(orig_label)
                    self.btn_copy.Enable(True)

            wx.CallLater(2000, _restore)

    def _on_test(self, event):
        self.lbl_result.SetLabel(u"Подключение...")
        self.lbl_result.SetForegroundColour(wx.Colour(0, 0, 0))
        self.btn_test.Enable(False)

        def _worker():
            ok, msg = self.ssh.test_connection()
            wx.CallAfter(self._test_done, ok, msg)

        threading.Thread(target=_worker, daemon=True).start()

    def _test_done(self, ok, msg):
        self.btn_test.Enable(True)
        if ok:
            self.lbl_result.SetLabel(u"\u2713 " + msg)
            self.lbl_result.SetForegroundColour(wx.Colour(0, 128, 0))
        else:
            self.lbl_result.SetLabel(u"\u2717 " + msg)
            self.lbl_result.SetForegroundColour(wx.Colour(200, 0, 0))

    def _on_update_ssh_config(self, event):
        ok, msg = self.ssh.update_ssh_config()
        if ok:
            self.lbl_result.SetLabel(u"\u2713 " + msg)
            self.lbl_result.SetForegroundColour(wx.Colour(0, 128, 0))
        else:
            self.lbl_result.SetLabel(u"\u2717 " + msg)
            self.lbl_result.SetForegroundColour(wx.Colour(200, 0, 0))


# ======================================================================
#  CommitDialog
# ======================================================================
class CommitDialog(wx.Dialog):
    """Simple modal to enter a commit message."""

    def __init__(self, parent):
        super(CommitDialog, self).__init__(
            parent,
            title=u"Сообщение коммита",
            size=(420, 200),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._build_ui()
        self.Centre()

    def _build_ui(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        vbox.Add(
            wx.StaticText(panel, label=u"Введите сообщение коммита:"),
            0, wx.ALL, 8,
        )
        self.txt_message = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE,
        )
        vbox.Add(self.txt_message, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        btn_sizer = wx.StdDialogButtonSizer()
        btn_ok = wx.Button(panel, wx.ID_OK, "OK")
        btn_cancel = wx.Button(panel, wx.ID_CANCEL, u"Отмена")
        btn_sizer.AddButton(btn_ok)
        btn_sizer.AddButton(btn_cancel)
        btn_sizer.Realize()
        vbox.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        panel.SetSizer(vbox)
        self.txt_message.SetFocus()

    def get_message(self):
        return self.txt_message.GetValue().strip()


# ======================================================================
#  HelpDialog
# ======================================================================
class HelpDialog(wx.Dialog):
    """Built-in help / quick reference."""

    _HELP_TEXT = (
        u"Git Integration for KiCad Libraries\n"
        u"=====================================\n\n"
        u"Этот плагин позволяет управлять библиотеками KiCad\n"
        u"через Git прямо из редактора.\n\n"
        u"Быстрый старт:\n"
        u"1. Откройте Settings и укажите:\n"
        u"   - Адрес сервера Forgejo/Gitea\n"
        u"   - Путь к локальному репозиторию\n"
        u"2. Откройте SSH Setup:\n"
        u"   - Сгенерируйте SSH-ключ\n"
        u"   - Скопируйте публичный ключ и добавьте его на сервер\n"
        u"   - Проверьте соединение\n"
        u"3. Используйте кнопки Pull / Commit / Push для работы.\n\n"
        u"Кнопки:\n"
        u"  Pull    — получить изменения с сервера (git pull --ff-only)\n"
        u"  Commit  — зафиксировать все изменения (git add . && git commit)\n"
        u"  Push    — отправить коммиты на сервер\n"
        u"  Status  — показать состояние рабочей директории\n\n"
        u"Фоновый Fetch:\n"
        u"  Плагин автоматически проверяет обновления на сервере\n"
        u"  при каждом открытии диалога.\n\n"
        u"Лог-файл: ~/.kicad_git_plugin.log\n"
    )

    def __init__(self, parent):
        super(HelpDialog, self).__init__(
            parent,
            title=u"Справка",
            size=(500, 420),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._build_ui()
        self.Centre()

    def _build_ui(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        txt = wx.TextCtrl(
            panel,
            value=self._HELP_TEXT,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        txt.SetFont(wx.Font(
            10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL,
        ))
        vbox.Add(txt, 1, wx.ALL | wx.EXPAND, 10)

        btn_close = wx.Button(panel, wx.ID_OK, u"Закрыть")
        vbox.Add(btn_close, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        panel.SetSizer(vbox)
