# -*- coding: utf-8 -*-
"""
SSH service — key generation, ssh config management, connection test.
"""

import logging
import os
import re
import subprocess

logger = logging.getLogger("kicad_git_plugin.ssh")

_SSH_CONFIG_MARKER = "# KiCad Git Integration Plugin"


class SSHService:
    """Manages SSH keys and ``~/.ssh/config`` for the plugin."""

    def __init__(self, config):
        """
        Parameters
        ----------
        config : config_service.ConfigService
        """
        self.config = config

    # ------------------------------------------------------------------
    # Key management
    # ------------------------------------------------------------------
    def _key_path(self):
        return os.path.expanduser(self.config.get_ssh_key_path())

    def _pub_path(self):
        return self._key_path() + ".pub"

    def key_exists(self):
        return os.path.isfile(self._key_path())

    def get_public_key(self):
        """Return the contents of the .pub file, or None."""
        pub = self._pub_path()
        if not os.path.isfile(pub):
            return None
        try:
            with open(pub, "r", encoding="utf-8") as fh:
                return fh.read().strip()
        except Exception as exc:
            logger.error("Cannot read public key: %s", exc)
            return None

    def generate_key(self, passphrase=""):
        """Generate a new ed25519 key pair.

        Returns
        -------
        tuple(bool, str, str or None)
            (success, message, public_key_content_or_None)
        """
        key_path = self._key_path()
        ssh_dir = os.path.dirname(key_path)

        # Ensure ~/.ssh exists with correct permissions
        if not os.path.isdir(ssh_dir):
            try:
                os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
            except Exception as exc:
                return (False, "Не удалось создать {d}: {e}".format(d=ssh_dir, e=exc), None)

        cmd = [
            "ssh-keygen",
            "-t", "ed25519",
            "-f", key_path,
            "-N", passphrase,
            "-C", "kicad-git-plugin",
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except FileNotFoundError:
            return (False, "ssh-keygen не найден. Установите OpenSSH.", None)
        except subprocess.TimeoutExpired:
            return (False, "ssh-keygen: таймаут.", None)
        except Exception as exc:
            return (False, str(exc), None)

        if proc.returncode != 0:
            err = proc.stderr.strip() if proc.stderr else "Неизвестная ошибка"
            return (False, "ssh-keygen ошибка: " + err, None)

        pub = self.get_public_key()
        if pub:
            logger.info("SSH key generated: %s", key_path)
            return (True, "Ключ создан: {p}".format(p=key_path), pub)
        return (False, "Ключ создан, но не удалось прочитать .pub файл.", None)

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------
    def test_connection(self):
        """Try ``ssh -T`` to the configured server.

        Returns
        -------
        tuple(bool, str)
            (success, message)
        """
        host = self.config.get_server_host()
        if not host:
            return (False, "Сервер не задан в настройках.")

        port = self.config.get_server_port()
        user = self.config.get_server_user()
        key_path = self._key_path()
        timeout = self.config.get_fetch_timeout()

        cmd = [
            "ssh", "-T",
            "-i", key_path,
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout={t}".format(t=timeout),
            "-p", str(port),
            "{u}@{h}".format(u=user, h=host),
        ]

        logger.debug("Testing SSH: %s", " ".join(cmd))

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout + 5,
            )
        except FileNotFoundError:
            return (False, "ssh не найден. Установите OpenSSH.")
        except subprocess.TimeoutExpired:
            return (False, "Сервер недоступен (таймаут {t} сек).".format(t=timeout))
        except Exception as exc:
            return (False, str(exc))

        combined = (proc.stdout + "\n" + proc.stderr).strip()

        # Forgejo/Gitea/GitHub return rc=1 with a greeting on -T
        if proc.returncode == 0 or "welcome" in combined.lower() or "successfully" in combined.lower():
            msg = combined if combined else "Соединение установлено."
            return (True, msg)

        if "permission denied" in combined.lower():
            return (False, "Доступ запрещён. Проверьте, что публичный ключ добавлен на сервер.")
        if "could not resolve" in combined.lower() or "name or service not known" in combined.lower():
            return (False, "Не удалось разрешить имя хоста: {h}".format(h=host))
        if "connection refused" in combined.lower():
            return (False, "Соединение отклонено ({h}:{p}).".format(h=host, p=port))

        return (False, combined if combined else "SSH соединение не удалось (код {c}).".format(c=proc.returncode))

    # ------------------------------------------------------------------
    # ~/.ssh/config management
    # ------------------------------------------------------------------
    def update_ssh_config(self):
        """Add a Host block to ``~/.ssh/config`` for the plugin.

        Returns
        -------
        tuple(bool, str)
        """
        host = self.config.get_server_host()
        if not host:
            return (False, "Сервер не задан в настройках.")

        ssh_config_path = os.path.expanduser("~/.ssh/config")
        ssh_dir = os.path.dirname(ssh_config_path)

        if not os.path.isdir(ssh_dir):
            try:
                os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
            except Exception as exc:
                return (False, "Не удалось создать {d}: {e}".format(d=ssh_dir, e=exc))

        port = self.config.get_server_port()
        user = self.config.get_server_user()
        key_path = self.config.get_ssh_key_path()  # keep unexpanded for portability

        block = (
            "\n{marker}\n"
            "Host kicad-forgejo\n"
            "    HostName {host}\n"
            "    Port {port}\n"
            "    User {user}\n"
            "    IdentityFile {key}\n"
            "    IdentitiesOnly yes\n"
        ).format(
            marker=_SSH_CONFIG_MARKER,
            host=host,
            port=port,
            user=user,
            key=key_path,
        )

        # Read existing config
        existing = ""
        if os.path.isfile(ssh_config_path):
            try:
                with open(ssh_config_path, "r", encoding="utf-8") as fh:
                    existing = fh.read()
            except Exception as exc:
                return (False, "Не удалось прочитать {p}: {e}".format(p=ssh_config_path, e=exc))

        # Check for existing plugin block — remove it first
        if _SSH_CONFIG_MARKER in existing:
            # Remove old block (marker line through next empty line or EOF)
            pattern = re.compile(
                r"\n?" + re.escape(_SSH_CONFIG_MARKER) + r".*?(?=\n\n|\nHost |\Z)",
                re.DOTALL,
            )
            existing = pattern.sub("", existing)

        new_content = existing.rstrip("\n") + "\n" + block

        try:
            with open(ssh_config_path, "w", encoding="utf-8") as fh:
                fh.write(new_content)
            # Ensure correct permissions
            os.chmod(ssh_config_path, 0o600)
            logger.info("Updated %s", ssh_config_path)
            return (True, "SSH config обновлён.")
        except Exception as exc:
            return (False, "Не удалось записать {p}: {e}".format(p=ssh_config_path, e=exc))
