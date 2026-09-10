"""Unit tests for --%% annotation parsing (no lupa needed)."""

from flua.config import parse_annotations, parse_scalar


def test_scalar_values() -> None:
    assert parse_scalar("true") is True
    assert parse_scalar("FALSE") is False
    assert parse_scalar("nil") is None
    assert parse_scalar("42") == 42
    assert parse_scalar("2.5") == 2.5
    assert parse_scalar("1e3") == 1000.0
    assert parse_scalar('"hello world"') == "hello world"
    assert parse_scalar("bare") == "bare"


def test_annotations() -> None:
    source = (
        "--%%speed:10\n"
        "--%%instant:false\n"
        "--%%time:instant=true,hours=48,speed=2\n"
        'print("hi")\n'
    )
    cfg = parse_annotations(source)
    assert cfg["speed"] == 10
    assert cfg["instant"] is False
    assert cfg["time"] == {"instant": True, "hours": 48, "speed": 2}


def test_subparams_tolerate_spaces() -> None:
    cfg = parse_annotations("--%%time: instant = true , hours = 48 , speed=2")
    assert cfg["time"] == {"instant": True, "hours": 48, "speed": 2}


def test_non_header_lines_ignored() -> None:
    source = (
        "-- a plain comment\n"
        "--%%\n"          # no name
        "--%% :x\n"       # name before colon is empty
        "--%%name\n"      # no colon
        "--%%name:\n"     # empty value
    )
    assert parse_annotations(source) == {}


def test_later_lines_override() -> None:
    cfg = parse_annotations("--%%speed:1\n--%%speed:2\n")
    assert cfg["speed"] == 2


def test_headers_anywhere_in_file() -> None:
    source = (
        'print("start")\n'
        "--%%maxhours:24\n"
        'print("end")\n'
    )
    assert parse_annotations(source) == {"maxhours": 24}
