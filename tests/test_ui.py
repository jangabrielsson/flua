"""The --%%u translator: rows -> uiCallbacks + viewLayout + uiView.

Structural goldens mirror the UI compiler's output, verified
against the shapes the real HC3 stores in device properties.
"""

import asyncio

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine  # noqa: E402
from flua.ui import compile_ui, ui_to_u_rows  # noqa: E402


def test_ui_to_u_rows_roundtrip() -> None:
    # compile -> translate back: the element kinds, names and callback
    # methods survive the roundtrip
    rows = [
        {"label": "lbl", "text": "Status"},
        {"button": "btn", "text": "Go", "onReleased": "turnOn"},
        {"switch": "sw", "text": "Auto", "value": "false", "onReleased": "handleSwitch"},
        {
            "slider": "dim",
            "text": "Brightness",
            "min": "0",
            "max": "100",
            "value": "50",
            "onChanged": "handleSlider",
        },
        {
            "select": "sel",
            "text": "Mode",
            "value": "1",
            "onToggled": "handleSelect",
            "options": [
                {"type": "option", "text": "Economy", "value": "1"},
                {"type": "option", "text": "Comfort", "value": "2"},
            ],
        },
        {
            "multi": "m1",
            "text": "Tags",
            "values": ["1"],
            "onToggled": "handleMulti",
            "options": [{"type": "option", "text": "Tag A", "value": "1"}],
        },
    ]
    ui = compile_ui(rows, 5000)
    from flua.config import parse_lua_literal

    out = ui_to_u_rows(ui_view=ui["uiView"], ui_callbacks=ui["uiCallbacks"])
    assert len(out) == len(rows)
    parsed = [parse_lua_literal(row) for row in out]
    assert [list(p)[0] for p in parsed] == [
        "label",
        "button",
        "switch",
        "slider",
        "select",
        "multi",
    ]
    assert parsed[1]["button"] == "btn" and parsed[1]["onReleased"] == "turnOn"
    assert parsed[2]["switch"] == "sw" and parsed[2]["onReleased"] == "handleSwitch"
    assert parsed[3]["slider"] == "dim" and parsed[3]["onChanged"] == "handleSlider"
    assert parsed[4]["select"] == "sel" and parsed[4]["onToggled"] == "handleSelect"
    assert parsed[4]["options"] == [
        {"type": "option", "text": "Economy", "value": "1"},
        {"type": "option", "text": "Comfort", "value": "2"},
    ]
    assert parsed[5]["multi"] == "m1" and parsed[5]["values"] == ["1"]


def test_ui_to_u_rows_legacy_viewlayout() -> None:
    # QAs with only the legacy viewLayout translate through that format
    rows = [
        {"button": "on", "text": "On", "onReleased": "turnOn"},
        {"slider": "dim", "text": "Brightness", "min": "0", "max": "100", "value": "50"},
    ]
    ui = compile_ui(rows, 5000)
    from flua.config import parse_lua_literal

    out = ui_to_u_rows(view_layout=ui["viewLayout"], ui_callbacks=ui["uiCallbacks"])
    parsed = [parse_lua_literal(row) for row in out]
    assert [list(p)[0] for p in parsed] == ["button", "slider"]
    assert parsed[0]["button"] == "on" and parsed[0]["onReleased"] == "turnOn"


def test_label_row() -> None:
    ui = compile_ui([{"label": "status", "text": "Idle"}], 5000)
    assert ui["uiCallbacks"] == []
    items = ui["viewLayout"]["$jason"]["body"]["sections"]["items"]
    assert len(items) == 1
    assert items[0] == {
        "components": [
            {
                "name": "status",
                "visible": True,
                "style": {"weight": "1.2"},
                "text": "Idle",
                "type": "label",
            },
            {"style": {"weight": "0.50"}, "type": "space"},
        ],
        "style": {"weight": "1.2"},
        "type": "vertical",
    }
    assert ui["viewLayout"]["$jason"]["head"]["title"] == "quickApp_device_5000"
    assert ui["uiView"] == [
        {
            "style": {"weight": "1.0"},
            "type": "horizontal",
            "components": [
                {
                    "eventBinding": {},
                    "name": "status",
                    "style": {"weight": "1.0"},
                    "text": "Idle",
                    "type": "label",
                    "visible": True,
                }
            ],
        }
    ]


def test_button_callbacks_and_bindings() -> None:
    ui = compile_ui([{"button": "go", "text": "Go", "onReleased": "turnOn"}], 5000)
    assert ui["uiCallbacks"] == [
        {"callback": "turnOn", "eventType": "onReleased", "name": "go"},
        {"callback": "", "eventType": "onLongPressDown", "name": "go"},
        {"callback": "", "eventType": "onLongPressReleased", "name": "go"},
    ]
    component = ui["uiView"][0]["components"][0]
    assert component["type"] == "button"
    assert component["eventBinding"]["onReleased"] == [
        {"params": {"actionName": "UIAction", "args": ["onReleased", "go"]}, "type": "deviceAction"}
    ]


def test_switch_gets_value_binding_and_string_value() -> None:
    ui = compile_ui([{"switch": "s", "text": "On", "value": "true", "onReleased": "sw"}], 5000)
    component = ui["uiView"][0]["components"][0]
    assert component["value"] == "true"
    assert component["eventBinding"]["onReleased"][0]["params"]["args"] == [
        "onReleased",
        "s",
        "$event.value",
    ]
    # the legacy layout carries the same value
    legacy = ui["viewLayout"]["$jason"]["body"]["sections"]["items"][0]["components"][0]
    assert legacy["type"] == "switch" and legacy["value"] == "true"


def test_slider_defaults_and_strings() -> None:
    ui = compile_ui([{"slider": "dim", "text": "Dim", "onChanged": "setLevel"}], 5000)
    component = ui["uiView"][0]["components"][0]
    assert component["min"] == "0" and component["max"] == "100"
    assert component["step"] == "1" and component["value"] == "0"
    assert component["eventBinding"]["onChanged"][0]["params"]["args"] == [
        "onChanged",
        "dim",
        "$event.value",
    ]
    assert ui["uiCallbacks"] == [{"callback": "setLevel", "eventType": "onChanged", "name": "dim"}]


def test_slider_unit_flows_through() -> None:
    # the declared unit rides the uiView component (the viewer renders it
    # right of the value) and the legacy viewLayout (getView consumers)
    ui = compile_ui([{"slider": "temp", "text": "Temp", "unit": "\u00b0C"}], 5000)
    component = ui["uiView"][0]["components"][0]
    assert component["unit"] == "\u00b0C"
    legacy = ui["viewLayout"]["$jason"]["body"]["sections"]["items"][0]["components"][0]
    assert legacy["unit"] == "\u00b0C"
    # the inverse export keeps it (--tool ui, .fqa round trip)
    back = ui_to_u_rows(view_layout=ui["viewLayout"], ui_callbacks=ui["uiCallbacks"])
    assert "unit='\u00b0C'" in back[0]


def test_select_with_options() -> None:
    rows = [
        {
            "select": "mode",
            "text": "Mode",
            "value": "2",
            "onToggled": "setMode",
            "options": [
                {"type": "option", "text": "Off", "value": "1"},
                {"type": "option", "text": "On", "value": "2"},
            ],
        }
    ]
    ui = compile_ui(rows, 5000)
    component = ui["uiView"][0]["components"][0]
    assert component["type"] == "select" and component["selectionType"] == "single"
    assert component["values"] == ["2"]  # the 5.221 schema: values array
    assert [o["value"] for o in component["options"]] == ["1", "2"]
    assert component["eventBinding"]["onToggled"][0]["params"]["args"] == [
        "onToggled",
        "mode",
        "$event.value",
    ]
    # the legacy layout forces type='option' onto the options
    legacy = ui["viewLayout"]["$jason"]["body"]["sections"]["items"][0]["components"][0]
    assert legacy["selectionType"] == "single"
    assert legacy["options"][0]["type"] == "option"
    # ...and carries the initial selection: single select's el['value'] maps
    # to the legacy values array (the viewer/HC3 upload renders it selected)
    assert legacy["values"] == ["2"]
    assert ui["uiCallbacks"] == [{"callback": "setMode", "eventType": "onToggled", "name": "mode"}]
    # the round trip keeps the selection: legacy viewLayout -> --%%u rows
    back = ui_to_u_rows(view_layout=ui["viewLayout"], ui_callbacks=ui["uiCallbacks"])
    assert "value='2'" in back[0]


def test_multi_select_becomes_select_with_multi_selection() -> None:
    rows = [
        {
            "multi": "tags",
            "text": "Tags",
            "values": ["1", "3"],
            "options": [{"type": "option", "text": "A", "value": "1"}],
        }
    ]
    ui = compile_ui(rows, 5000)
    component = ui["uiView"][0]["components"][0]
    assert component["type"] == "select" and component["selectionType"] == "multi"
    assert component["values"] == ["1", "3"]
    legacy = ui["viewLayout"]["$jason"]["body"]["sections"]["items"][0]["components"][0]
    assert legacy["selectionType"] == "multi"


def test_multi_element_row_weights_and_legacy_horizontal() -> None:
    rows = [
        [
            {"button": "on", "text": "On", "onReleased": "turnOn"},
            {"button": "off", "text": "Off", "onReleased": "turnOff"},
        ]
    ]
    ui = compile_ui(rows, 5000)
    # uiView: each component gets the 2-element weight "0.5"
    components = ui["uiView"][0]["components"]
    assert [c["style"]["weight"] for c in components] == ["0.5", "0.5"]
    # viewLayout: one horizontal row of two + the trailing space
    items = ui["viewLayout"]["$jason"]["body"]["sections"]["items"]
    horizontal = items[0]["components"][0]
    assert horizontal["type"] == "horizontal"
    assert [c["style"]["weight"] for c in horizontal["components"]] == ["0.50", "0.50"]
    assert len(ui["uiCallbacks"]) == 6  # 3 events per button


def test_tabview_compiles_to_uiview_and_legacy() -> None:
    # a tabView is full-width (alone on its row): tabs hold rows, elements
    # inside tabs normalize like top-level ones, onTabChanged routes through
    # uiCallbacks (legacy) and an eventBinding (uiView)
    rows = [
        {
            "tabView": "mainTabs",
            "activeTab": "picker",
            "onTabChanged": "tabChanged",
            "tabs": [
                {
                    "name": "picker",
                    "text": "Picker",
                    "components": [
                        [{"button": "onBtn", "text": "On", "onReleased": "turnOn"}],
                        [
                            {
                                "slider": "dim",
                                "text": "Dim",
                                "min": "0",
                                "max": "100",
                                "value": "50",
                                "onChanged": "dim",
                            }
                        ],
                    ],
                },
                {
                    "name": "settings",
                    "text": "Settings",
                    "components": [
                        [{"switch": "auto", "text": "Auto", "value": "false", "onReleased": "auto"}]
                    ],
                },
            ],
        }
    ]
    ui = compile_ui(rows, 5000)
    # uiView: one row whose single component is the tabView; its tabs carry
    # uiView rows of components
    assert len(ui["uiView"]) == 1
    tv = ui["uiView"][0]["components"][0]
    assert tv["type"] == "tabView" and tv["name"] == "mainTabs"
    assert tv["activeTab"] == "picker"
    assert tv["eventBinding"]["onTabChanged"] == [
        {
            "params": {
                "actionName": "UIAction",
                "args": ["onTabChanged", "mainTabs", "$event.value"],
            },
            "type": "deviceAction",
        }
    ]
    assert [t["name"] for t in tv["tabs"]] == ["picker", "settings"]
    picker = tv["tabs"][0]
    assert picker["type"] == "tab" and picker["text"] == "Picker"
    assert len(picker["components"]) == 2
    assert picker["components"][0]["type"] == "horizontal"
    btn = picker["components"][0]["components"][0]
    assert btn["type"] == "button" and btn["name"] == "onBtn"
    sld = picker["components"][1]["components"][0]
    # nested elements got the same defaults (stringified slider bounds)
    assert sld["type"] == "slider" and sld["min"] == "0" and sld["max"] == "100"
    # legacy viewLayout: one tabView item, tabs hold legacy rows, no event
    # fields (the legacy convention: the binding lives in uiCallbacks only)
    items = ui["viewLayout"]["$jason"]["body"]["sections"]["items"]
    assert len(items) == 1
    assert items[0]["type"] == "tabView"
    assert items[0]["name"] == "mainTabs" and items[0]["activeTab"] == "picker"
    assert "eventBinding" not in items[0]
    assert items[0]["tabs"][0]["components"][0]["type"] == "vertical"
    # uiCallbacks carries the tab change for both formats
    assert {"callback": "tabChanged", "eventType": "onTabChanged", "name": "mainTabs"} in ui[
        "uiCallbacks"
    ]


def test_tabview_must_sit_alone_on_row() -> None:
    rows = [[{"tabView": "t", "tabs": []}, {"button": "b", "text": "x"}]]
    with pytest.raises(ValueError, match="alone"):
        compile_ui(rows, 5000)


def test_image_and_collapsible_compile() -> None:
    rows = [
        [
            {"image": "art", "url": "http://example.com/a.png", "useProxy": True},
            {"button": "b", "text": "Go", "onReleased": "go"},
        ],
        {
            "collapsible": "favs",
            "text": "Favorites",
            "collapsed": False,
            "disabled": False,
            "components": [[{"button": "play", "text": "Play", "onReleased": "play"}]],
        },
    ]
    ui = compile_ui(rows, 5000)
    # uiView: the image rides inline in the shared row; the collapsible is
    # full-width (alone on its row) and holds uiView rows
    row0 = ui["uiView"][0]["components"]
    assert [c["type"] for c in row0] == ["image", "button"]
    img = row0[0]
    assert img["name"] == "art" and img["url"] == "http://example.com/a.png"
    assert img["useProxy"] is True
    col = ui["uiView"][1]["components"][0]
    assert col["type"] == "collapsible" and col["name"] == "favs"
    assert col["text"] == "Favorites" and col["collapsed"] is False
    assert col["components"][0]["components"][0]["type"] == "button"
    # legacy: collapsible item + the image inside the shared legacy row
    # (a vertical row wrapping the horizontal image+button line)
    items = ui["viewLayout"]["$jason"]["body"]["sections"]["items"]
    assert items[0]["type"] == "vertical"
    inner = items[0]["components"][0]
    assert inner["type"] == "horizontal"
    assert [c["type"] for c in inner["components"]] == ["image", "button"]
    assert items[1]["type"] == "collapsible"
    assert items[1]["components"][0]["components"][0]["type"] == "button"
    # callbacks: the button inside the collapsible routes like a top-level one
    assert {"callback": "play", "eventType": "onReleased", "name": "play"} in ui[
        "uiCallbacks"
    ]


def test_collapsible_must_sit_alone_on_row() -> None:
    rows = [[{"collapsible": "c", "components": []}, {"button": "b", "text": "x"}]]
    with pytest.raises(ValueError, match="alone"):
        compile_ui(rows, 5000)


def test_image_and_collapsible_roundtrip() -> None:
    rows = [
        [{"image": "art", "url": "http://example.com/a.png"}],
        {
            "collapsible": "favs",
            "text": "Favorites",
            "collapsed": True,
            "components": [[{"button": "play", "text": "Play", "onReleased": "play"}]],
        },
    ]
    ui = compile_ui(rows, 5000)
    from flua.config import parse_lua_literal

    out = ui_to_u_rows(ui_view=ui["uiView"], ui_callbacks=ui["uiCallbacks"])
    parsed = [parse_lua_literal(row) for row in out]
    assert parsed[0] == {"image": "art", "url": "http://example.com/a.png"}
    col = parsed[1]
    assert col["collapsible"] == "favs" and col["text"] == "Favorites"
    assert col["collapsed"] is True
    assert col["components"] == [[{"button": "play", "text": "Play", "onReleased": "play"}]]


def test_tabview_roundtrip() -> None:
    rows = [
        {
            "tabView": "mainTabs",
            "activeTab": "picker",
            "onTabChanged": "tabChanged",
            "tabs": [
                {
                    "name": "picker",
                    "text": "Picker",
                    "components": [
                        [{"button": "onBtn", "text": "On", "onReleased": "turnOn"}],
                        [
                            {
                                "slider": "dim",
                                "text": "Dim",
                                "min": "0",
                                "max": "100",
                                "value": "50",
                                "onChanged": "dim",
                            }
                        ],
                    ],
                },
                {
                    "name": "settings",
                    "text": "Settings",
                    "components": [[{"switch": "auto", "text": "Auto", "value": "false"}]],
                },
            ],
        }
    ]
    ui = compile_ui(rows, 5000)
    from flua.config import parse_lua_literal

    out = ui_to_u_rows(ui_view=ui["uiView"], ui_callbacks=ui["uiCallbacks"])
    assert len(out) == 1
    parsed = parse_lua_literal(out[0])
    assert parsed["tabView"] == "mainTabs"
    assert parsed["onTabChanged"] == "tabChanged"
    assert [t["name"] for t in parsed["tabs"]] == ["picker", "settings"]
    assert parsed["tabs"][0]["components"] == [
        [{"button": "onBtn", "text": "On", "onReleased": "turnOn"}],
        [
            {
                "slider": "dim",
                "text": "Dim",
                "min": "0",
                "max": "100",
                "step": "1",
                "value": "50",
                "onChanged": "dim",
            }
        ],
    ]


@pytest.mark.asyncio
async def test_qa_device_gets_ui_properties(tmp_path) -> None:
    # end to end: --%%u directives in a real file -> parsed config -> device
    # properties (viewLayout, uiView, uiCallbacks, useUiView) served by api.get
    script = tmp_path / "ui.lua"
    script.write_text(
        '--%%u:{label="lbl",text="Hi"}\n'
        '--%%u:{button="b",text="Go",onReleased="go"}\n'
        '--%%u:{{button="on",text="On",onReleased="turnOn"},'
        '{button="off",text="Off",onReleased="turnOff"}}\n'
    )
    engine = LuaEngine()
    await engine.start()
    try:
        qa_id = engine.load_qa_file(str(script))[0]
        device, status = engine.api.dispatch("GET", f"/devices/{qa_id}")
        assert status == 200
        props = device["properties"]
        # undeclared: flua defaults to the legacy layout (viewLayout)
        assert props["useUiView"] is False
        assert props["uiView"][0]["components"][0]["type"] == "label"
        assert props["uiCallbacks"][0] == {
            "callback": "go",
            "eventType": "onReleased",
            "name": "b",
        }
        layout = props["viewLayout"]["$jason"]
        assert layout["head"]["title"] == f"quickApp_device_{qa_id}"
        assert len(layout["body"]["sections"]["items"]) == 3
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_use_ui_view_false_directive(tmp_path) -> None:
    script = tmp_path / "legacy.lua"
    script.write_text('--%%useUiView:false\n--%%u:{label="lbl",text="Hi"}\n')
    engine = LuaEngine()
    await engine.start()
    try:
        qa_id = engine.load_qa_file(str(script))[0]
        device, _ = engine.api.dispatch("GET", f"/devices/{qa_id}")
        assert device["properties"]["useUiView"] is False
        # both structures are still generated
        assert device["properties"]["viewLayout"]["$jason"]["head"]["title"]
        assert device["properties"]["uiView"][0]["components"][0]["type"] == "label"
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_tabview_update_view_and_tab_changed_callback(tmp_path, capsys) -> None:
    # updateView patches elements inside a tabView's tabs (the uiView search
    # recurses through tabs), the tabView's own activeTab updates the same
    # way, and UIAction("onTabChanged", ...) routes through uiCallbacks
    script = tmp_path / "tabs.lua"
    script.write_text(
        '--%%u:{tabView="mainTabs",activeTab="a",onTabChanged="tabChanged",tabs={'
        '{name="a",text="A",components={{{label="lbl",text="Hi"}}}}'
        "}}\n"
        "function QuickApp:tabChanged(event)\n"
        "  print('TAB', event.values[1])\n"
        "end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        qa_id = engine.load_qa_file(str(script))[0]
        # an element nested inside the tab: reached through the tab walk
        status = engine.api.dispatch(
            "POST",
            "/plugins/updateView",
            {
                "deviceId": qa_id,
                "componentName": "lbl",
                "propertyName": "text",
                "newValue": "Live!",
            },
        )[1]
        assert status == 204
        device, _ = engine.api.dispatch("GET", f"/devices/{qa_id}")
        tab = device["properties"]["uiView"][0]["components"][0]["tabs"][0]
        assert tab["components"][0]["components"][0]["text"] == "Live!"
        # the tabView's own activeTab changes through the same channel
        engine.api.dispatch(
            "POST",
            "/plugins/updateView",
            {
                "deviceId": qa_id,
                "componentName": "mainTabs",
                "propertyName": "activeTab",
                "newValue": "b",
            },
        )
        device, _ = engine.api.dispatch("GET", f"/devices/{qa_id}")
        assert device["properties"]["uiView"][0]["components"][0]["activeTab"] == "b"
        # onTabChanged routes to the QA method through uiCallbacks
        engine.api.dispatch(
            "GET",
            f"/plugins/callUIEvent?deviceID={qa_id}&elementName=mainTabs"
            "&eventType=onTabChanged&value=b",
        )
        await asyncio.sleep(0.4)
        assert "TAB b" in capsys.readouterr().out
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_image_and_collapsible_update_view(tmp_path) -> None:
    # updateView patches elements inside a collapsible body (the recursive
    # uiView walk) and the image's url — both through the same channel
    script = tmp_path / "img_col.lua"
    script.write_text(
        "--%%u:{image=\"art\",url=\"http://example.com/a.png\"}\n"
        "--%%u:{collapsible=\"favs\",text=\"Favorites\",components={{{label=\"lbl\",text=\"Hi\"}}}}\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        qa_id = engine.load_qa_file(str(script))[0]
        for name, prop, value in (
            ("lbl", "text", "Live!"),
            ("art", "url", "http://example.com/b.png"),
            ("favs", "collapsed", True),
        ):
            status = engine.api.dispatch(
                "POST",
                "/plugins/updateView",
                {"deviceId": qa_id, "componentName": name, "propertyName": prop, "newValue": value},
            )[1]
            assert status == 204
        device, _ = engine.api.dispatch("GET", f"/devices/{qa_id}")
        ui_view = device["properties"]["uiView"]
        img = ui_view[0]["components"][0]
        assert img["url"] == "http://example.com/b.png"
        col = ui_view[1]["components"][0]
        assert col["collapsed"] is True
        label = col["components"][0]["components"][0]
        assert label["text"] == "Live!"  # reached inside the collapsible body
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_ui_event_reaches_qa_callback(tmp_path, capsys) -> None:
    # the examples/ui.lua flow: a generated uiCallbacks entry + UIAction
    # routes a simulated UI event to the QuickApp method
    script = tmp_path / "event.lua"
    script.write_text(
        '--%%u:{button="B1",text="Press me",onReleased="fopp"}\n'
        "function QuickApp:onInit()\n"
        '  setTimeout(function() self:UIAction("onReleased", "B1") end, 20)\n'
        "end\n"
        "function QuickApp:fopp() print('RELEASED') end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.load_qa_file(str(script))
        await asyncio.sleep(0.4)
        assert "RELEASED" in capsys.readouterr().out
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_ui_event_api_endpoint_reaches_callback(tmp_path, capsys) -> None:
    # GET /plugins/callUIEvent (the real HC3 endpoint) delivers the same
    # interaction as UIAction, including the event's value
    script = tmp_path / "api_event.lua"
    script.write_text(
        '--%%u:{button="B1",text="Press me",onReleased="fopp"}\n'
        '--%%u:{slider="s1",text="Slider",min="0",max="100",onChanged="slider"}\n'
        '--%%u:{select="sel1",text="Select",value="11",onToggled="selectChanged",'
        "options={{type='option',text='One',value='11'},{type='option',text='Two',value='12'}}}\n"
        "function QuickApp:onInit()\n"
        "  local self = self\n"
        "  setTimeout(function()\n"
        "    api.get('/plugins/callUIEvent?deviceID='..self.id"
        "..'&elementName=B1&eventType=onReleased')\n"
        "    api.get('/plugins/callUIEvent?deviceID='..self.id"
        "..'&elementName=s1&eventType=onChanged&value=42')\n"
        "    api.get('/plugins/callUIEvent?deviceID='..self.id"
        "..'&elementName=sel1&eventType=onToggled&value=12')\n"
        "  end, 20)\n"
        "end\n"
        "function QuickApp:fopp() print('RELEASED') end\n"
        "function QuickApp:slider(e) print('VALUE', e.values[1]) end\n"
        "function QuickApp:selectChanged(e) print('SEL', e.values[1]) end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.load_qa_file(str(script))
        await asyncio.sleep(0.4)
        out = capsys.readouterr().out
        assert "RELEASED" in out
        assert "VALUE 42" in out
        assert "SEL 12" in out  # select's onToggled routes through uiCallbacks
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_multi_ui_event_delivers_value_list(tmp_path, capsys) -> None:
    # a multi select sends every selected value comma-joined through the
    # single value param (the callUIEvent contract); the sim restores the
    # list, and UIAction wraps it once like the HC3 — event.values[1] is
    # the whole selected-values list
    script = tmp_path / "multi_event.lua"
    script.write_text(
        '--%%u:{multi="m1",text="Pick",onToggled="multiChanged",values={\'11\'},'
        "options={{type='option',text='One',value='11'},{type='option',text='Two',value='12'}}}"
        "\n"
        "function QuickApp:onInit()\n"
        "  local self = self\n"
        "  setTimeout(function()\n"
        "    api.get('/plugins/callUIEvent?deviceID='..self.id"
        "..'&elementName=m1&eventType=onToggled&value=11%2C12')\n"
        "  end, 20)\n"
        "end\n"
        "function QuickApp:multiChanged(e)\n"
        "  print('MULTI', #e.values, type(e.values[1]), e.values[1][1], e.values[1][2])\n"
        "end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.load_qa_file(str(script))
        await asyncio.sleep(0.4)
        assert "MULTI 1 table 11 12" in capsys.readouterr().out
    finally:
        await engine.stop()


def test_switch_split_toggle_events_and_image_passthrough() -> None:
    # the 5.221 schema: switches get onToggleOn/onToggleOff callbacks +
    # event bindings, and the new element properties (image/unit/hint/
    # disabled) pass through to the compiled uiView
    ui = compile_ui(
        [
            {
                "switch": "s1",
                "text": "S",
                "onToggleOn": "on",
                "onToggleOff": "off",
                "image": "chevronDown",
                "hint": "flip me",
                "disabled": True,
            },
            {"slider": "sl", "unit": "%", "image": "slidersHorizontal"},
        ],
        5000,
    )
    callbacks = {c["eventType"]: c["callback"] for c in ui["uiCallbacks"]}
    assert callbacks["onToggleOn"] == "on"
    assert callbacks["onToggleOff"] == "off"
    components = [c for row in ui["uiView"] for c in row["components"]]
    switch = next(c for c in components if c["name"] == "s1")
    assert switch["eventBinding"]["onToggleOn"] and switch["eventBinding"]["onToggleOff"]
    assert switch["image"] == "chevronDown"
    assert switch["hint"] == "flip me"
    assert switch["disabled"] is True
    slider = next(c for c in components if c["name"] == "sl")
    assert slider["unit"] == "%"
    assert slider["image"] == "slidersHorizontal"


def test_visible_property_declared_and_defaulted() -> None:
    # the HC3's visible property: declared false passes through both
    # formats (viewLayout $jason + uiView), undeclared defaults to true
    ui = compile_ui(
        [
            {"button": "b1", "text": "hidden", "visible": False},
            {"label": "l1", "text": "shown"},
        ],
        5000,
    )
    layout = ui["viewLayout"]["$jason"]["body"]["sections"]["items"]
    components = []
    for item in layout:
        for c in item.get("components") or []:
            if c.get("components"):  # a horizontal row's inner components
                components.extend(c["components"])
            elif c.get("name"):
                components.append(c)
    by_name = {c["name"]: c for c in components}
    assert by_name["b1"]["visible"] is False
    assert by_name["l1"]["visible"] is True
    ui_components = [c for row in ui["uiView"] for c in row["components"]]
    by_name2 = {c["name"]: c for c in ui_components}
    assert by_name2["b1"]["visible"] is False
    assert by_name2["l1"]["visible"] is True


def test_select_ui_view_carries_values_array() -> None:
    # the 5.221 schema: the current selection lives in `values` (an array)
    # for BOTH select modes — single selects carry their one value in it
    ui = compile_ui(
        [
            {
                "select": "sel",
                "value": "2",
                "options": [{"type": "option", "text": "T", "value": "2"}],
            }
        ],
        5000,
    )
    component = [c for row in ui["uiView"] for c in row["components"]][0]
    assert component["selectionType"] == "single"
    assert component["values"] == ["2"]
    assert "value" not in component  # the scalar spelling is gone from the uiView


def test_legacy_layout_has_no_event_fields() -> None:
    # regression: the packed legacy viewLayout must match the HC3's own
    # export shape — elements WITHOUT event fields; the event -> method
    # binding lives in uiCallbacks only. Declaring onReleased on the element
    # (like the uiView presence) makes the HC3's import re-derive uiCallbacks
    # with generated defaults (ui<b2>OnReleased) and drop the custom names.
    rows = [
        {"button": "b2", "text": "Zone \u25bc", "onReleased": "zoneDownButton"},
        {
            "button": "b10",
            "text": "+H",
            "onLongPressReleased": "infiniteDuration",
            "onReleased": "timeUpButton",
        },
        {"switch": "auto", "value": "false", "onToggleOn": "autoOn", "onToggleOff": "autoOff"},
        {"slider": "limit", "onChanged": "setLimit"},
        {"select": "mode", "onToggled": "setMode"},
    ]
    ui = compile_ui(rows, 5000)
    components = []
    for item in ui["viewLayout"]["$jason"]["body"]["sections"]["items"]:
        for c in item.get("components") or []:
            if c.get("components"):  # a horizontal row's inner components
                components.extend(c["components"])
            elif c.get("name"):
                components.append(c)
    by_name = {c["name"]: c for c in components}
    for event in (
        "onReleased",
        "onLongPressDown",
        "onLongPressReleased",
        "onChanged",
        "onToggled",
        "onToggleOn",
        "onToggleOff",
    ):
        assert all(event not in c for c in by_name.values())
    # uiCallbacks carries the bindings — the table both flua and the HC3 dispatch
    callbacks = {(c["name"], c["eventType"]): c["callback"] for c in ui["uiCallbacks"]}
    assert callbacks[("b2", "onReleased")] == "zoneDownButton"
    assert callbacks[("b10", "onLongPressReleased")] == "infiniteDuration"
    assert callbacks[("auto", "onToggleOn")] == "autoOn"
    assert callbacks[("limit", "onChanged")] == "setLimit"
    assert callbacks[("mode", "onToggled")] == "setMode"


def test_legacy_layout_events_roundtrip_without_ui_callbacks() -> None:
    # a real HC3 legacy viewLayout carries the bindings on the elements;
    # ui_to_u_rows must read them from there — uiCallbacks may be missing
    # or mangled on the device
    layout = {
        "$jason": {
            "body": {
                "sections": {
                    "items": [
                        {
                            "components": [
                                {
                                    "name": "b2",
                                    "visible": True,
                                    "style": {"weight": "1.2"},
                                    "text": "Zone",
                                    "type": "button",
                                    "onReleased": "zoneDownButton",
                                },
                                {"style": {"weight": "0.50"}, "type": "space"},
                            ],
                            "style": {"weight": "1.2"},
                            "type": "vertical",
                        }
                    ]
                }
            }
        }
    }
    from flua.config import parse_lua_literal

    rows = ui_to_u_rows(view_layout=layout, ui_callbacks=[])
    parsed = parse_lua_literal(rows[0])
    assert parsed["button"] == "b2"
    assert parsed["onReleased"] == "zoneDownButton"


def test_device_ui_renders_from_an_hc3_device() -> None:
    # the --tool ui --device path: an HC3 device's UI properties render
    # back to --%%u rows (ui_to_u_rows, the downloadQA converter) with the
    # raw JSON alongside — the lossless form for editor-made UIs
    from flua.tools.ui import device_ui

    device = {
        "id": 57,
        "name": "sw_Proxy",
        "type": "com.fibaro.binarySwitch",
        "properties": {
            "useUiView": True,
            "uiView": [
                {
                    "type": "row",
                    "components": [
                        {"type": "button", "name": "B1", "text": "Tap me"},
                        {"type": "label", "name": "l1", "text": "Hi"},
                    ],
                }
            ],
            "uiCallbacks": [{"name": "B1", "eventType": "onReleased", "callback": "tap"}],
        },
    }
    title, rows, raw = device_ui(device)
    assert 'HC3 device "sw_Proxy"' in title
    assert len(rows) == 1
    assert "button='B1'" in rows[0] and "onReleased='tap'" in rows[0]
    assert raw == device["properties"]["uiView"]


def test_ten_element_row_gets_weights() -> None:
    # the HC3 editor stops at 5 elements per row; flua allows 10 — rows of
    # 6-10 get a sane weight instead of nil (which would emit weight=nil)
    rows = [[{"button": f"b{i}", "text": str(i)} for i in range(1, 11)]]
    ui = compile_ui(rows, 5000)
    components = ui["uiView"][0]["components"]
    assert [c["style"]["weight"] for c in components] == ["0.10"] * 10  # uniform per row
    assert all(c["style"]["weight"] for c in components)  # never nil
    # the legacy $jason row keeps its horizontal + space shape
    items = ui["viewLayout"]["$jason"]["body"]["sections"]["items"]
    assert items[0]["components"][0]["type"] == "horizontal"


def test_color_pickers_compile_and_roundtrip() -> None:
    rows = [
        {
            "colorPicker": "rgbPicker",
            "colorSpace": "RGB",
            "onChanged": "setColor",
            "channels": {
                "red": "{{device.properties.colorComponents.red}}",
                "green": "{{device.properties.colorComponents.green}}",
                "blue": "{{device.properties.colorComponents.blue}}",
            },
        },
        {
            "colorTemperaturePicker": "tempPicker",
            "minTemperature": "2200",
            "maxTemperature": "6500",
            "colorTemperature": "4000",
            "onChanged": "setTemp",
        },
    ]
    ui = compile_ui(rows, 5000)
    rgb = ui["uiView"][0]["components"][0]
    assert rgb["type"] == "colorPicker" and rgb["colorSpace"] == "RGB"
    assert rgb["channels"]["red"].startswith("{{device.properties")
    assert rgb["eventBinding"]["onChanged"][0]["params"]["args"] == [
        "onChanged", "rgbPicker", "$event.value",
    ]
    temp = ui["uiView"][1]["components"][0]
    assert temp["type"] == "colorTemperaturePicker"
    assert temp["minTemperature"] == "2200" and temp["maxTemperature"] == "6500"
    # uiCallbacks carry onChanged for both
    callbacks = {(c["eventType"], c["name"]): c["callback"] for c in ui["uiCallbacks"]}
    assert callbacks[("onChanged", "rgbPicker")] == "setColor"
    assert callbacks[("onChanged", "tempPicker")] == "setTemp"
    # roundtrip
    from flua.config import parse_lua_literal

    out = ui_to_u_rows(ui_view=ui["uiView"], ui_callbacks=ui["uiCallbacks"])
    parsed = [parse_lua_literal(row) for row in out]
    assert parsed[0]["colorPicker"] == "rgbPicker"
    assert parsed[0]["onChanged"] == "setColor"
    assert parsed[1]["colorTemperaturePicker"] == "tempPicker"
    assert parsed[1]["onChanged"] == "setTemp"
