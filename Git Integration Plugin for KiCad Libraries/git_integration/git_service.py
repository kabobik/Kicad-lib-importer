# -*- coding: utf-8 -*-
"""
Git service — every git operation goes through subprocess with
GIT_SSH_COMMAND pointing at the configured SSH key.
"""

import logging
import os
import subprocess
import shutil

logger = logging.getLogger("kicad_git_plugin.git")


class GitService:
    """High-level wrapper around the ``git`` CLI."""

    def __init__(self, config):
        """
        Parameters
        ----------
        config : config_service.ConfigService
        """
        self.config = config

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _git_executable(self):
        path = shutil.which("git")
        if path is None:
            return None
        return path

    def _build_env(self):
        env = os.environ.copy()
        # Only set GIT_SSH_COMMAND for SSH remotes
        if self._is_ssh_remote():
            key_path = os.path.expanduser(self.config.get_ssh_key_path())
            if os.path.exists(key_path):
                env["GIT_SSH_COMMAND"] = (
                    'ssh -i "{key}" -o StrictHostKeyChecking=accept-new'.format(key=key_path)
                )
        return env

    def _get_remote_url(self):
        """Return the URL of the 'origin' remote, or ''."""
        repo = self.config.get_repo_path()
        if not repo:
            return ""
        git = self._git_executable()
        if not git:
            return ""
        try:
            proc = subprocess.run(
                [git, "remote", "get-url", "origin"],
                cwd=repo,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            if proc.returncode == 0:
                return proc.stdout.strip()
        except Exception:
            pass
        return ""

    def _is_ssh_remote(self):
        """Return True if origin remote uses SSH (not HTTPS)."""
        url = self._get_remote_url()
        if not url:
            return True  # assume SSH if we can't determine
        return not url.startswith("http://") and not url.startswith("https://")

    def get_remote_url(self):
        """Public: return remote URL."""
        return self._get_remote_url()

    def get_remote_type(self):
        """Return 'ssh', 'https', or 'unknown'."""
        url = self._get_remote_url()
        if url.startswith("https://") or url.startswith("http://"):
            return "https"
        if url.startswith("git@") or url.startswith("ssh://"):
            return "ssh"
        if url:
            return "ssh"  # e.g. user@host:path
        return "unknown"

    def apply_credentials(self):
        """Embed username:token into the HTTPS remote URL.

        Returns
        -------
        tuple(bool, str)
            (success, message)
        """
        url = self._get_remote_url()
        if not url:
            return (False, "Remote URL не определён.")
        if not url.startswith("https://") and not url.startswith("http://"):
            return (False, "Remote не HTTPS — токен не нужен.")

        username = self.config.get_credentials_username()
        token = self.config.get_credentials_token()
        if not username or not token:
            return (False, "Логин или токен не заданы.")

        # Parse URL: https://host/path → https://user:token@host/path
        # Also handle existing credentials: https://old:old@host/path
        import re
        match = re.match(r"(https?://)(?:[^@]+@)?(.+)", url)
        if not match:
            return (False, "Не удалось разобрать URL: {u}".format(u=url))

        scheme = match.group(1)
        rest = match.group(2)
        new_url = "{s}{u}:{t}@{r}".format(s=scheme, u=username, t=token, r=rest)

        rc, out, err = self._run_git("remote", "set-url", "origin", new_url)
        if rc == 0:
            logger.info("Credentials applied to remote URL")
            return (True, "Токен применён к remote URL.")
        return (False, "Ошибка: " + err.strip())

    def remove_credentials_from_url(self):
        """Strip username:token from the HTTPS remote URL.

        Returns
        -------
        tuple(bool, str)
        """
        url = self._get_remote_url()
        if not url:
            return (False, "Remote URL не определён.")
        import re
        match = re.match(r"(https?://)(?:[^@]+@)?(.+)", url)
        if not match:
            return (False, "Не удалось разобрать URL.")
        clean_url = match.group(1) + match.group(2)
        if clean_url == url:
            return (True, "URL уже без credentials.")
        rc, out, err = self._run_git("remote", "set-url", "origin", clean_url)
        if rc == 0:
            return (True, "Credentials удалены из URL.")
        return (False, "Ошибка: " + err.strip())

    def _run_git(self, *args):
        """Run a git command inside the repository directory.

        Returns
        -------
        tuple(int, str, str)
            (returncode, stdout, stderr)
        """
        git = self._git_executable()
        if git is None:
            return (-1, "", "Git не найден. Установите git и попробуйте снова.")

        repo = self.config.get_repo_path()
        if not repo:
            return (-1, "", "Путь к репозиторию не задан в настройках.")

        cmd = [git] + list(args)
        fetch_timeout = self.config.get_fetch_timeout()

        # Network ops get longer timeout; push/pull need more than fetch
        is_network = any(a in args for a in ("fetch", "pull", "push", "ls-remote"))
        if is_network:
            if any(a in args for a in ("push", "pull")):
                timeout = max(fetch_timeout * 3, 30)  # min 30 sec for push/pull
            else:
                timeout = fetch_timeout  # fetch/ls-remote: use config value
        else:
            timeout = 60  # local ops

        logger.debug("git %s  (cwd=%s, timeout=%s)", " ".join(args), repo, timeout)

        try:
            proc = subprocess.run(
                cmd,
                cwd=repo,
                env=self._build_env(),
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            if proc.stdout:
                logger.debug("stdout: %s", proc.stdout.strip())
            if proc.stderr:
                logger.debug("stderr: %s", proc.stderr.strip())
            return (proc.returncode, proc.stdout, proc.stderr)
        except subprocess.TimeoutExpired:
            msg = "Сервер недоступен (таймаут {t} сек)".format(t=timeout)
            logger.warning(msg)
            return (-2, "", msg)
        except FileNotFoundError:
            return (-1, "", "Git не найден. Установите git и попробуйте снова.")
        except Exception as exc:
            logger.error("git error: %s", exc)
            return (-1, "", str(exc))

    # ------------------------------------------------------------------
    # Public API — Phase 0
    # ------------------------------------------------------------------
    def has_repo(self):
        """Return True if the configured path contains a .git directory."""
        repo = self.config.get_repo_path()
        if not repo:
            return False
        return os.path.isdir(os.path.join(repo, ".git"))

    def git_available(self):
        """Return True if the git executable is found on PATH."""
        return self._git_executable() is not None

    # ------------------------------------------------------------------
    # Public API — Phase 1
    # ------------------------------------------------------------------
    def get_branch(self):
        """Return the name of the current branch or '' (detached HEAD)."""
        rc, out, err = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        if rc == 0:
            branch = out.strip()
            if branch == "HEAD":
                return ""  # detached HEAD
            return branch
        return ""

    def status(self):
        """Return a dict describing the working-tree state.

        Keys: branch, modified, untracked, staged, ahead, behind.
        """
        result = {
            "branch": "",
            "modified": [],
            "untracked": [],
            "staged": [],
            "ahead": 0,
            "behind": 0,
        }

        if not self.has_repo():
            return result

        result["branch"] = self.get_branch()

        # porcelain v1 status
        rc, out, err = self._run_git("status", "--porcelain")
        if rc == 0:
            for line in out.splitlines():
                if len(line) < 3:
                    continue
                x = line[0]  # index
                y = line[1]  # worktree
                path = line[3:]
                if x == "?" and y == "?":
                    result["untracked"].append(path)
                elif x in ("M", "A", "D", "R", "C"):
                    result["staged"].append(path)
                if y in ("M", "D"):
                    if path not in result["modified"]:
                        result["modified"].append(path)

        # ahead / behind
        rc, out, err = self._run_git(
            "rev-list", "--left-right", "--count", "HEAD...@{upstream}"
        )
        if rc == 0:
            parts = out.strip().split()
            if len(parts) == 2:
                try:
                    result["ahead"] = int(parts[0])
                    result["behind"] = int(parts[1])
                except ValueError:
                    pass

        return result

    def fetch(self):
        """Run ``git fetch``. Returns (success, message)."""
        if not self.has_repo():
            repo = self.config.get_repo_path()
            return (False, "Репозиторий не найден в {p}".format(p=repo))

        rc, out, err = self._run_git("fetch", "--all")
        if rc == 0:
            return (True, "Fetch выполнен успешно.")
        combined = (out + "\n" + err).lower()
        if "could not resolve" in combined or "name or service not known" in combined:
            return (False, "Нет подключения к серверу. Проверьте сетевое соединение.")
        return (False, self._format_error(rc, err))

    def pull(self):
        """Run ``git pull --ff-only``. Returns (success, message)."""
        if not self.has_repo():
            repo = self.config.get_repo_path()
            return (False, "Репозиторий не найден в {p}".format(p=repo))

        # Check for uncommitted changes before pull
        st = self.status()
        if st["modified"] or st["staged"]:
            return (False, "Есть незакоммиченные изменения. Сделайте Commit перед Pull.")

        rc, out, err = self._run_git("pull", "--ff-only")
        if rc == 0:
            msg = out.strip() if out.strip() else "Pull выполнен успешно."
            return (True, msg)

        combined = (out + "\n" + err).lower()
        if "conflict" in combined or "merge" in combined:
            return (False,
                    "Обнаружены конфликты слияния. "
                    "Разрешите конфликты вручную и выполните git add + git commit.")
        if "could not resolve" in combined or "name or service not known" in combined:
            return (False, "Нет подключения к серверу. Проверьте сетевое соединение.")
        return (False, self._format_error(rc, err))

    def commit(self, message):
        """Stage all changes and commit. Returns (success, message)."""
        if not self.has_repo():
            repo = self.config.get_repo_path()
            return (False, "Репозиторий не найден в {p}".format(p=repo))

        if not message or not message.strip():
            return (False, "Сообщение коммита не может быть пустым.")

        # Check if there are any changes at all
        st = self.status()
        if not st["modified"] and not st["untracked"] and not st["staged"]:
            return (True, "Нет изменений для коммита.")

        # git add .
        rc, out, err = self._run_git("add", ".")
        if rc != 0:
            return (False, "git add failed: " + err.strip())

        # git commit
        rc, out, err = self._run_git("commit", "-m", message)
        if rc == 0:
            return (True, out.strip() if out.strip() else "Коммит создан.")

        combined = (out + "\n" + err).lower()
        if "nothing to commit" in combined or "nothing added" in combined or "working tree clean" in combined:
            return (True, "Нет изменений для коммита.")
        return (False, self._format_error(rc, err))

    def push(self):
        """Run ``git push``. Returns (success, message)."""
        if not self.has_repo():
            repo = self.config.get_repo_path()
            return (False, "Репозиторий не найден в {p}".format(p=repo))

        rc, out, err = self._run_git("push")
        if rc == 0:
            msg = out.strip() or err.strip() or "Push выполнен успешно."
            return (True, msg)

        combined = (out + "\n" + err).lower()
        if "rejected" in combined or "non-fast-forward" in combined:
            return (False, "Push отклонён. Сначала выполните Pull.")
        if "could not resolve" in combined or "name or service not known" in combined:
            return (False, "Нет подключения к серверу. Проверьте сетевое соединение.")
        if "connection refused" in combined or "connection timed out" in combined:
            return (False, "Нет подключения к серверу. Проверьте сетевое соединение.")
        return (False, self._format_error(rc, err))

    def get_sync_status(self):
        """Fetch and return ahead/behind counts.

        Returns
        -------
        dict with keys: ahead, behind, success, message
        """
        ok, msg = self.fetch()
        if not ok:
            return {"ahead": 0, "behind": 0, "success": False, "message": msg}

        rc, out, err = self._run_git(
            "rev-list", "--left-right", "--count", "HEAD...@{upstream}"
        )
        ahead = 0
        behind = 0
        if rc == 0:
            parts = out.strip().split()
            if len(parts) == 2:
                try:
                    ahead = int(parts[0])
                    behind = int(parts[1])
                except ValueError:
                    pass
        return {"ahead": ahead, "behind": behind, "success": True, "message": msg}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _format_error(rc, stderr):
        text = stderr.strip() if stderr else ""
        if rc == -2:
            return text  # already a human-readable timeout message
        if text:
            return text
        return "Неизвестная ошибка (код {c})".format(c=rc)
