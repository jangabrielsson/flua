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


def test_file_directives_collect_in_order() -> None:
    # --%%file:path,name — later declarations do NOT override earlier ones
    source = "--%%file:b.lua,b\n--%%file:a.lua,a\n"
    assert parse_annotations(source) == {"file": ["b.lua,b", "a.lua,a"]}


def test_var_directives_merge_with_string_values() -> None:
    # --%%var:name=value — values stay literal strings, repeated directives
    # merge, and several vars may share one line
    source = "--%%var:x=1\n--%%var:y=hello\n--%%var:z=1,w=2\n"
    assert parse_annotations(source) == {"var": {"x": "1", "y": "hello", "z": "1", "w": "2"}}


def test_property_directives_merge_with_scalar_values() -> None:
    # --%%property:name=value — raw device properties, values parse as
    # scalars, repeated directives merge
    source = "--%%property:value=true\n--%%property:delay=30\n--%%property:x=1,y=2\n"
    assert parse_annotations(source) == {
        "property": {"value": True, "delay": 30, "x": 1, "y": 2}
    }


def test_eoh_stops_parsing() -> None:
    source = (
        "--%%name:outer\n"
        "-- --------------- EOH ---------------\n"
        "--%%name:inner\n"
    )
    assert parse_annotations(source) == {"name": "outer"}


def test_eoh_requires_dashed_comment() -> None:
    # a bare comment that merely mentions EOH does not end the header
    source = (
        "--%%name:outer\n"
        "-- just a comment about EOH\n"
        "--%%speed:3\n"
    )
    assert parse_annotations(source) == {"name": "outer", "speed": 3}


def test_eoh_must_be_a_comment_line() -> None:
    # the marker inside a Lua string (not a comment) does not end the header
    source = (
        "--%%name:outer\n"
        'print("--- EOH ---")\n'
        "--%%speed:3\n"
    )
    assert parse_annotations(source) == {"name": "outer", "speed": 3}