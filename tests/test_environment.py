"""The os.getenv chain: local .env > ~/.env > process environment."""

import os

import pytest

from flua.environment import EnvChain


def test_parse_formats(tmp_path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# comment\n"
        "PLAIN=value\n"
        'QUOTED="hello world"\n'
        "SINGLE='x y'\n"
        "  SPACED = padded  \n"
        "NO_VALUE=\n"
        "BROKENLINE\n"
    )
    values = EnvChain.parse(env)
    assert values["PLAIN"] == "value"
    assert values["QUOTED"] == "hello world"
    assert values["SINGLE"] == "x y"
    assert values["SPACED"] == "padded"
    assert values["NO_VALUE"] == ""
    assert "BROKENLINE" not in values


def test_precedence_local_then_home_then_process(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("KEY=local\nONLY_LOCAL=yes\n")
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text("KEY=home\nONLY_HOME=yes\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("KEY", "process")
    monkeypatch.setenv("ONLY_PROCESS", "env")

    chain = EnvChain(directory=str(tmp_path))
    assert chain.get("KEY") == "local"  # local wins over home and process
    assert chain.get("ONLY_LOCAL") == "yes"
    assert chain.get("ONLY_HOME") == "yes"  # home beats process
    assert chain.get("ONLY_PROCESS") == "env"  # process is the fallback
    assert chain.get("MISSING") is None


def test_mtime_reload(tmp_path) -> None:
    env = tmp_path / ".env"
    env.write_text("KEY=v1\n")
    chain = EnvChain(directory=str(tmp_path))
    assert chain.get("KEY") == "v1"
    env.write_text("KEY=v2\n")
    os.utime(env, (env.stat().st_atime, env.stat().st_mtime + 2))  # force mtime change
    assert chain.get("KEY") == "v2"
