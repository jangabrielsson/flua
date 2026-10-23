"""The os.getenv chain: process env > local .env > ~/.env."""

import os

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


def test_precedence_process_then_local_then_home(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("KEY=local\nONLY_LOCAL=yes\n")
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text("KEY=home\nONLY_HOME=yes\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("KEY", "process")
    monkeypatch.setenv("ONLY_PROCESS", "env")

    chain = EnvChain(directory=str(tmp_path))
    assert chain.get("KEY") == "process"  # per-invocation settings win
    assert chain.get("ONLY_PROCESS") == "env"
    assert chain.get("ONLY_LOCAL") == "yes"  # the project file beats ~/.env
    assert chain.get("ONLY_HOME") == "yes"  # ~/.env is the fallback
    assert chain.get("MISSING") is None


def test_empty_process_env_counts_as_set(tmp_path, monkeypatch) -> None:
    # an explicitly empty process value is a deliberate setting, not a miss
    (tmp_path / ".env").write_text("KEY=local\n")
    monkeypatch.setenv("KEY", "")
    chain = EnvChain(directory=str(tmp_path))
    assert chain.get("KEY") == ""


def test_mtime_reload(tmp_path) -> None:
    env = tmp_path / ".env"
    env.write_text("KEY=v1\n")
    chain = EnvChain(directory=str(tmp_path))
    assert chain.get("KEY") == "v1"
    env.write_text("KEY=v2\n")
    os.utime(env, (env.stat().st_atime, env.stat().st_mtime + 2))  # force mtime change
    assert chain.get("KEY") == "v2"
