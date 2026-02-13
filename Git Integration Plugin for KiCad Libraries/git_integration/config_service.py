# -*- coding: utf-8 -*-
"""
Configuration service — reads/writes config.ini next to the plugin package.
"""

import configparser
import os
import logging

logger = logging.getLogger("kicad_git_plugin.config")

_DEFAULTS = {
    "server": {
        "host": "",
        "port": "22",
        "user": "git",
    },
    "repository": {
        "path": "",
    },
    "ssh": {
        "key_path": "~/.ssh/kicad_forgejo_ed25519",
    },
    "credentials": {
        "username": "",
        "token": "",
    },
    "fetch": {
        "interval_sec": "300",
        "timeout_sec": "10",
    },
}


class ConfigService:
    """Thin wrapper around configparser with typed accessors."""

    def __init__(self, ini_path=None):
        if ini_path is None:
            ini_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")
        self._path = ini_path
        self._cp = configparser.ConfigParser()
        self._apply_defaults()
        self._load()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _apply_defaults(self):
        for section, values in _DEFAULTS.items():
            if not self._cp.has_section(section):
                self._cp.add_section(section)
            for key, val in values.items():
                self._cp.set(section, key, val)

    def _load(self):
        if os.path.isfile(self._path):
            try:
                self._cp.read(self._path, encoding="utf-8")
                logger.info("Loaded config from %s", self._path)
            except Exception as exc:
                logger.warning("Failed to read config %s: %s", self._path, exc)
        else:
            logger.info("Config file not found, using defaults: %s", self._path)

    # ------------------------------------------------------------------
    # Generic accessors
    # ------------------------------------------------------------------
    def get(self, section, key, fallback=""):
        return self._cp.get(section, key, fallback=fallback)

    def getint(self, section, key, fallback=0):
        try:
            return self._cp.getint(section, key, fallback=fallback)
        except (ValueError, TypeError):
            return fallback

    def set(self, section, key, value):
        if not self._cp.has_section(section):
            self._cp.add_section(section)
        self._cp.set(section, key, str(value))

    def save(self):
        try:
            with open(self._path, "w", encoding="utf-8") as fh:
                self._cp.write(fh)
            logger.info("Config saved to %s", self._path)
            return True
        except Exception as exc:
            logger.error("Failed to save config: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Typed convenience methods
    # ------------------------------------------------------------------
    def get_server_host(self):
        return self.get("server", "host")

    def get_server_port(self):
        return self.getint("server", "port", fallback=22)

    def get_server_user(self):
        return self.get("server", "user", fallback="git")

    def get_repo_path(self):
        raw = self.get("repository", "path")
        if raw:
            return os.path.expanduser(os.path.abspath(raw))
        return ""

    def get_ssh_key_path(self):
        return self.get("ssh", "key_path", fallback="~/.ssh/kicad_forgejo_ed25519")

    def get_fetch_interval(self):
        return self.getint("fetch", "interval_sec", fallback=300)

    def get_fetch_timeout(self):
        return self.getint("fetch", "timeout_sec", fallback=10)

    def get_credentials_username(self):
        return self.get("credentials", "username")

    def get_credentials_token(self):
        return self.get("credentials", "token")

    def is_configured(self):
        """Return True when the minimum required settings are filled in."""
        return bool(self.get_repo_path())
