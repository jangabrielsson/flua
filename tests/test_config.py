"""Unit tests for --%% annotation parsing (no lupa needed)."""

from flua.config import (
    _apply_mode,
    load_directives_file,
    merge_directives,
    parse_annotations,
    parse_lua_literal,
    parse_scalar,
)


def test_scalar_values() -> None:
    assert parse_scalar("true") is True
    assert parse_scalar("FALSE") is False
    assert parse_scalar("nil") is None
    assert parse_scalar("42") == 42
    assert parse_scalar("2.5") == 2.5
    assert parse_scalar("1e3") == 1000.0
    assert parse_scalar('"hello world"') == "hello world"
    assert parse_scalar("bare") == "bare"


def test_keep_alive_directive() -> None:
    cfg = parse_annotations("--%%keep-alive:true\n")
    assert cfg["keep-alive"] is True
    assert parse_annotations("--%%keep-alive:false\n")["keep-alive"] is False


def test_annotations() -> None:
    source = (
        '--%%speed:10\n--%%instant:false\n--%%time:instant=true,hours=48,speed=2\nprint("hi")\n'
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
        "--%%\n"  # no name
        "--%% :x\n"  # name before colon is empty
        "--%%name\n"  # no colon
        "--%%name:\n"  # empty value
    )
    assert parse_annotations(source) == {}


def test_later_lines_override() -> None:
    cfg = parse_annotations("--%%speed:1\n--%%speed:2\n")
    assert cfg["speed"] == 2


def test_headers_anywhere_in_file() -> None:
    source = 'print("start")\n--%%maxhours:24\nprint("end")\n'
    assert parse_annotations(source) == {"maxhours": 24}


def test_file_directives_collect_in_order() -> None:
    # --%%file:path,name — later declarations do NOT override earlier ones
    source = "--%%file:b.lua,b\n--%%file:a.lua,a\n"
    assert parse_annotations(source) == {"file": ["b.lua,b", "a.lua,a"]}


def test_var_directives_merge_with_string_values() -> None:
    # --%%var:name=expr — raw expressions, repeated directives merge; the
    # whole value after the first '=' is kept (tables contain commas)
    source = "--%%var:x=1\n--%%var:y='hello'\n--%%var:t={a=1,b=2}\n"
    assert parse_annotations(source) == {"var": {"x": "1", "y": "'hello'", "t": "{a=1,b=2}"}}


def test_property_directives_merge_with_scalar_values() -> None:
    # --%%property:name=value — raw device properties, values parse as
    # scalars, repeated directives merge
    source = "--%%property:value=true\n--%%property:delay=30\n--%%property:x=1,y=2\n"
    assert parse_annotations(source) == {"property": {"value": True, "delay": 30, "x": 1, "y": 2}}


def test_directives_file_provides_defaults(tmp_path) -> None:
    (tmp_path / ".directives").write_text(
        "--%%name:Default\n--%%mode:offline\n--%%u:{label=\"d\",text=\"D\"}\n"
    )
    assert load_directives_file(tmp_path) == {
        "name": "Default",
        "mode": "offline",
        "offline": True,
        "proxy": False,
        "u": [{"label": "d", "text": "D"}],
    }
    assert load_directives_file(tmp_path / "missing") == {}


def test_merge_directives_qa_overrides_defaults() -> None:
    defaults = _apply_mode({"mode": "offline", "name": "Default"})
    # a QA directive overrides the file's value for that key
    merged = merge_directives(defaults, {"name": "Mine"})
    assert merged == {"mode": "offline", "offline": True, "proxy": False, "name": "Mine"}
    # the mode family overrides as a whole: any QA mode directive replaces
    # the file's mode default — even an explicit opt-out
    merged = merge_directives(defaults, {"offline": False})
    assert "mode" not in merged and merged["offline"] is False
    merged = merge_directives(defaults, {"mode": "proxy"})
    assert merged == {"mode": "proxy", "offline": False, "proxy": True, "name": "Default"}


def test_mode_directive_normalizes_flags() -> None:
    # --%%mode:offline -> offline flag; proxy/online likewise
    assert _apply_mode({"mode": "offline"}) == {
        "mode": "offline",
        "offline": True,
        "proxy": False,
    }
    assert _apply_mode({"mode": "proxy"}) == {
        "mode": "proxy",
        "offline": False,
        "proxy": True,
    }
    assert _apply_mode({"mode": "online"}) == {
        "mode": "online",
        "offline": False,
        "proxy": False,
    }
    assert _apply_mode({"mode": "bogus", "offline": True}) == {
        "mode": "offline",  # unknown mode falls back to the legacy flag
        "offline": True,
        "proxy": False,
    }


def test_mode_directive_parsed_with_legacy_aliases() -> None:
    assert parse_annotations("--%%mode:offline\n") == {
        "mode": "offline",
        "offline": True,
        "proxy": False,
    }
    # legacy directives map onto mode
    assert parse_annotations("--%%offline:true\n") == {
        "mode": "offline",
        "offline": True,
        "proxy": False,
    }
    assert parse_annotations("--%%proxy:true\n") == {
        "mode": "proxy",
        "offline": False,
        "proxy": True,
    }
    # an explicit --%%mode wins over legacy directives
    assert parse_annotations("--%%mode:offline\n--%%proxy:true\n") == {
        "mode": "offline",
        "offline": True,
        "proxy": False,
    }


def test_debug_directive_parses_subflags() -> None:
    config = parse_annotations(
        "--%%debug:refreshState=true,api=true,http=true\n--%%loglength:60\n"
    )
    assert config == {
        "debug": {"refreshState": True, "api": True, "http": True},
        "loglength": 60,
    }


def test_parse_annotations_warns_on_unknown_directive(caplog) -> None:
    import logging

    with caplog.at_level(logging.WARNING):
        assert parse_annotations("--%%instnat:true\n") == {"instnat": True}
    assert "unknown --%% directive: --%%instnat:true" in caplog.text
    # known directives stay quiet
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        parse_annotations(
            "--%%name:x\n--%%mode:offline\n--%%speed:2\n--%%u:{label=\"a\"}\n"
        )
    assert "unknown --%%" not in caplog.text


def test_eoh_stops_parsing() -> None:
    source = "--%%name:outer\n-- --------------- EOH ---------------\n--%%name:inner\n"
    assert parse_annotations(source) == {"name": "outer"}


def test_eoh_requires_dashed_comment() -> None:
    # a bare comment that merely mentions EOH does not end the header
    source = "--%%name:outer\n-- just a comment about EOH\n--%%speed:3\n"
    assert parse_annotations(source) == {"name": "outer", "speed": 3}


def test_eoh_must_be_a_comment_line() -> None:
    # the marker inside a Lua string (not a comment) does not end the header
    source = '--%%name:outer\nprint("--- EOH ---")\n--%%speed:3\n'
    assert parse_annotations(source) == {"name": "outer", "speed": 3}


# -- --%%u directives -----------------------------------------------------------


def test_u_directives_collect_in_order() -> None:
    source = '--%%u:{label="a",text="A"}\n--%%u:{button="b",text="B",onReleased="go"}\n'
    cfg = parse_annotations(source)
    assert cfg["u"] == [
        {"label": "a", "text": "A"},
        {"button": "b", "text": "B", "onReleased": "go"},
    ]


def test_u_row_with_multiple_elements() -> None:
    source = '--%%u:{{button="on",text="On"},{button="off",text="Off"}}\n'
    cfg = parse_annotations(source)
    assert cfg["u"] == [[{"button": "on", "text": "On"}, {"button": "off", "text": "Off"}]]


def test_u_multi_line_row_joins_continuation_lines() -> None:
    source = (
        '--%%u:{select="mode",text="Mode",onToggled="set",\n'
        "--      options={{type='option',text='Off',value='Off'},"
        "{type='option',text='On',value='On'}}}\n"
    )
    cfg = parse_annotations(source)
    assert cfg["u"] == [
        {
            "select": "mode",
            "text": "Mode",
            "onToggled": "set",
            "options": [
                {"type": "option", "text": "Off", "value": "Off"},
                {"type": "option", "text": "On", "value": "On"},
            ],
        }
    ]


def test_u_continuation_stops_at_eoh() -> None:
    source = "--%%u:{select=\"mode\",\n-- --------------- EOH ---------------\nprint('hi')\n"
    # the EOH comment is not absorbed as a continuation; the row is still
    # unbalanced so parsing reports it clearly
    import pytest

    with pytest.raises(ValueError):
        parse_annotations(source)


def test_u_trailing_comment_is_stripped() -> None:
    source = '--%%u:{label="lbl",text="Status"}  -- UI element (one per row)\n'
    assert parse_annotations(source)["u"] == [{"label": "lbl", "text": "Status"}]


def test_u_literal_values() -> None:
    # numbers stay numbers, booleans parse, single-quoted strings work
    source = '--%%u:{slider="s",min=5,max=100.5,value=50,visible=true}\n'
    cfg = parse_annotations(source)
    assert cfg["u"] == [{"slider": "s", "min": 5, "max": 100.5, "value": 50, "visible": True}]


def test_u_literal_errors_are_clear() -> None:
    import pytest

    with pytest.raises(ValueError, match="unterminated string"):
        parse_lua_literal('{label="a}')
    with pytest.raises(ValueError, match="unexpected character"):
        parse_lua_literal("{label=#a}")
    with pytest.raises(ValueError, match="must be a table"):
        parse_lua_literal('"not a table"')
