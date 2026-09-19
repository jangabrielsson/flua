"""The --%%u translator: rows -> uiCallbacks + viewLayout + uiView.

Structural goldens mirror plua's src/lua/fibaro/ui.lua output, verified
against the shapes the real HC3 stores in device properties.
"""

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine  # noqa: E402
from flua.ui import compile_ui  # noqa: E402


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
    assert component["value"] == "2"
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
    assert ui["uiCallbacks"] == [{"callback": "setMode", "eventType": "onToggled", "name": "mode"}]


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
        assert props["useUiView"] is True
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
