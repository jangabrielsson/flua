"""Environment lookup for ``os.getenv`` (Lua): local .env > ~/.env > process env.

The two .env files are plain ``KEY=value`` lines (blank lines and ``#``
comments ignored, optional quotes). Values are cached per file and re-read
when the file's mtime changes, so a ``--watch`` run picks up edits without
re-parsing on every lookup.
"""

from __future__ import annotations

import os
from pathlib import Path


class EnvChain:
    """Resolution order: <directory>/.env, ~/.env, then the process environment."""

    def __init__(self, directory: str | None = None) -> None:
        self._directory = Path(directory) if directory else Path.cwd()
        self._cache: dict[Path, tuple[float, dict[str, str]]] = {}

    @staticmethod
    def parse(path: Path) -> dict[str, str]:
        values: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if not sep:
                continue
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if key:
                values[key] = value
        return values

    def _values(self, path: Path) -> dict[str, str]:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return {}
        cached = self._cache.get(path)
        if cached is None or cached[0] != mtime:
            values = self.parse(path)
            self._cache[path] = (mtime, values)
            return values
        return cached[1]

    def get(self, name: str) -> str | None:
        """Look up one variable through the chain. None if not set anywhere."""
        for path in (self._directory / ".env", Path.home() / ".env"):
            values = self._values(path)
            if name in values:
                return values[name]
        return os.environ.get(name)
