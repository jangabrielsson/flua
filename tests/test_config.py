"""Unit tests for --%% annotation parsing (no lupa needed)."""

from flua.config import (
    _apply_mode,
    expand_includes,
    parse_annotations,
    parse_lua_literal,
    parse_scalar,
    split_annotations,
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


def test_include_expands_as_defaults(tmp_path) -> None:
    # --%%include inserts the file's directives as defaults: the QA's own
    # win per key, the mode family overrides as a whole, and --%%file lists
    # append (defaults first, redeclared names win)
    (tmp_path / "defaults.lua").write_text(
        "--%%name:Default\n--%%mode:offline\n--%%file:extra.lua,extra\n--%%file:util.lua,util\n"
    )
    source = (
        "--%%include:defaults.lua\n"
        "--%%name:Mine\n"
        "--%%file:lib.lua,lib\n"
        "--%%file:util.lua,util\n"
    )
    merged = expand_includes(parse_annotations(source), tmp_path)
    assert merged["name"] == "Mine"  # the QA's own directive wins
    assert merged["mode"] == "offline"  # the included mode was kept
    # files append; the QA's redeclaration of util wins at its position
    assert merged["file"] == ["extra.lua,extra", "util.lua,util", "lib.lua,lib"]
    assert "include" not in merged  # consumed during expansion


def test_include_resolves_nested_and_guards_cycles(tmp_path) -> None:
    # nested includes resolve relative to the including file, later
    # directives override earlier ones, and cycles are skipped
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "base.lua").write_text("--%%name:Base\n--%%include:../a.lua\n")
    (tmp_path / "a.lua").write_text("--%%name:A\n--%%include:b.lua\n--%%include:sub/base.lua\n")
    (tmp_path / "b.lua").write_text("--%%name:B\n--%%include:a.lua\n")
    merged = expand_includes(parse_annotations("--%%include:a.lua\n--%%name:QA\n"), tmp_path)
    assert merged["name"] == "QA"


def test_include_missing_file_is_an_error(tmp_path) -> None:
    import pytest

    with pytest.raises(ValueError, match="cannot read"):
        expand_includes(parse_annotations("--%%include:nope.lua\n"), tmp_path)


def test_include_is_a_known_directive(caplog) -> None:
    import logging

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        parse_annotations("--%%include:defaults.lua\n")
    assert "unknown --%%" not in caplog.text


def test_include_mode_family_overrides_as_a_whole(tmp_path) -> None:
    # the QA's mode directives replace the included file's mode entirely:
    # --%%offline:false opts out of an included --%%mode:offline
    (tmp_path / "defaults.lua").write_text("--%%mode:offline\n--%%name:Default\n")
    merged = expand_includes(
        parse_annotations("--%%include:defaults.lua\n--%%offline:false\n"), tmp_path
    )
    assert merged == {
        "mode": "online",
        "offline": False,
        "proxy": False,
        "name": "Default",
    }
    merged = expand_includes(
        parse_annotations("--%%include:defaults.lua\n--%%mode:proxy\n"), tmp_path
    )
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
    assert _apply_mode({"offline": False}) == {
        "mode": "online",  # legacy --%%offline:false opts INTO online
        "offline": False,
        "proxy": False,
    }


def test_mode_proxy_no_ui_option() -> None:
    # --%%mode:proxy,noUI: proxy mode, but the connect leaves the proxy's
    # UI alone (the developer edits it in the HC3's UI editor)
    cfg = _apply_mode(parse_annotations("--%%mode:proxy,noUI\n"))
    assert cfg["mode"] == "proxy" and cfg["proxy"] is True
    assert cfg["proxyNoUI"] is True
    # plain proxy mode carries no proxyNoUI flag
    cfg = _apply_mode(parse_annotations("--%%mode:proxy\n"))
    assert cfg["proxy"] is True
    assert "proxyNoUI" not in cfg
    # noUI on a non-proxy mode is parsed but harmless (only proxy honors it)
    cfg = _apply_mode(parse_annotations("--%%mode:online,noUI\n"))
    assert cfg["proxy"] is False


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


def test_debug_directive_scalar_enables_all_channels() -> None:
    # --%%debug:true (the natural shorthand) normalizes to the dict shape so
    # every consumer reads one shape — it used to leave a plain bool that
    # crashed dict-style .get()s
    assert parse_annotations("--%%debug:true\n") == {
        "debug": {"api": True, "http": True, "refreshState": True}
    }
    assert parse_annotations("--%%debug:false\n") == {
        "debug": {"api": False, "http": False, "refreshState": False}
    }
    from flua.config import debug_flag

    assert debug_flag({"debug": True}, "api") is True  # hand-built bools still work
    assert debug_flag({"debug": {"api": True}}, "api") is True
    assert debug_flag({"debug": {"api": False}}, "api") is False
    assert debug_flag({}, "api") is False


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


def test_file_metadata_directives_are_known_and_local(caplog) -> None:
    # --%%deviceId/--%%qaFile (downloaded-file metadata for --tool uploadFile)
    # parse silently and stay local — they must never reach the shared config
    import logging

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        annotations = parse_annotations("--%%deviceId:123\n--%%qaFile:main\n")
    assert "unknown --%%" not in caplog.text
    global_params, local_params = split_annotations(annotations)
    assert global_params == {}
    assert local_params == {"deviceId": 123, "qaFile": "main"}


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
