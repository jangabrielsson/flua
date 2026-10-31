"""The ``--capabilities-json`` compatibility surface table.

Entries are hand-curated against the runtime source; ``implemented`` means
the surface exists and its behavior contracts are pinned by the test suite
(the pinning test named where one exists). ``partial`` means the surface
exists with known gaps (the REST shape-only stubs — see
docs/rest-endpoints.md). ``unsupported`` means verified missing.

Honesty rules (the forum feedback's demand):
- an entry absent from the table is NOT claimed — unknown is unknown;
- the table is a statement about flua's emulated surface, never about
  physical-HC3/firmware parity;
- status changes ride the same commit as the change that causes them.

``report(engine, runtime)`` builds the JSON payload the CLI prints;
``runtime`` is the record ``--version --machine`` emits.
"""

from __future__ import annotations

from typing import Any

# category -> list of {name, status, note}
CAPABILITIES: dict[str, list[dict[str, str]]] = {
    "qa": [
        {
            "name": "createChildDevice",
            "status": "implemented",
            "note": "pinned by tests/test_quickapp.py",
        },
        {
            "name": "removeChildDevice",
            "status": "implemented",
            "note": "0.1.111; own children only, tests/test_quickapp.py",
        },
        {
            "name": "updateProperty",
            "status": "implemented",
            "note": "pinned by tests/test_quickapp.py",
        },
        {
            "name": "updateView",
            "status": "implemented",
            "note": "pinned by tests/test_quickapp.py",
        },
        {"name": "getView", "status": "implemented", "note": ""},
        {
            "name": "setVariable/getVariable",
            "status": "implemented",
            "note": "--%%var seeds before onInit",
        },
        {
            "name": "internalStorage*",
            "status": "implemented",
            "note": "set/get/remove/clear via /plugins/{id}/variables",
        },
        {
            "name": "interfaces (has/add/update/delete)",
            "status": "implemented",
            "note": "hasInterface/addInterfaces/updateInterfaces/deleteInterfaces",
        },
        {"name": "callAction", "status": "implemented", "note": ""},
        {
            "name": "setVisible/setEnabled/setName",
            "status": "implemented",
            "note": "",
        },
        {
            "name": "registerUICallback/setupUICallbacks",
            "status": "implemented",
            "note": "",
        },
        {
            "name": "UIAction",
            "status": "implemented",
            "note": "callUIEvent route + viewer",
        },
        {
            "name": "icon management",
            "status": "implemented",
            "note": "uploadIconFiles/externalIconsDownload/uploadExternalIconSet; --tool icons",
        },
    ],
    "qa-child": [
        {
            "name": "QuickAppChild",
            "status": "implemented",
            "note": "created via createChildDevice; parent/child ids in tests/test_quickapp.py",
        },
    ],
    "net": [
        {
            "name": "HTTPClient",
            "status": "implemented",
            "note": "incl. SSE streaming; pinned by tests/test_http.py",
        },
        {"name": "TCPSocket", "status": "implemented", "note": ""},
        {"name": "UDPSocket", "status": "implemented", "note": ""},
        {
            "name": "WebSocketClient",
            "status": "implemented",
            "note": "pinned by tests/test_websocket.py",
        },
        {
            "name": "WebSocketClientTls",
            "status": "implemented",
            "note": "no cert verification by default (HC3 behavior); checkCertificate opts in",
        },
        {
            "name": "HTTPServer/TCPServer/UDPServer/WebSocketServer",
            "status": "implemented",
            "note": "in-QA fixture servers",
        },
        {
            "name": "mqtt.Client",
            "status": "implemented",
            "note": "the mqtt global, not net.*",
        },
    ],
    "api": [
        {
            "name": "simulated HC3 REST",
            "status": "partial",
            "note": "real vs shape-only-stub routes: docs/rest-endpoints.md",
        },
        {
            "name": "api.hc3",
            "status": "implemented",
            "note": "hybrid dispatch; direct-HC3 namespace",
        },
        {
            "name": "plugin.*",
            "status": "implemented",
            "note": "getDevice/deleteDevice/getProperty/getChildDevices/createChildDevice/restart",
        },
        {
            "name": "refreshState sourceTrigger",
            "status": "implemented",
            "note": "pinned by tests/test_api.py",
        },
    ],
    "runtime": [
        {
            "name": "virtual clocks",
            "status": "implemented",
            "note": "--speed/--instant/--step; instant is deadline-ordered (0.1.111)",
        },
        {
            "name": "fibaro.sleep",
            "status": "implemented",
            "note": "per-QA suspension on the virtual clock",
        },
        {
            "name": "plugin.restart",
            "status": "implemented",
            "note": "pinned by tests/test_sleep.py",
        },
        {
            "name": "scenes (--%%scene)",
            "status": "implemented",
            "note": "COND + actions per trigger",
        },
        {
            "name": "proxy mode",
            "status": "implemented",
            "note": "shadow + HC3 mirror; tests/test_proxy.py",
        },
        {
            "name": "--%%db / --%%replay",
            "status": "implemented",
            "note": "seed + persist + recorded sessions",
        },
        {
            "name": "UI viewer / --ui HTTP API",
            "status": "implemented",
            "note": "pinned by tests/test_ui_server.py",
        },
        {
            "name": "mobdebug debugger (--debugger)",
            "status": "implemented",
            "note": "VS Code attach",
        },
        {
            "name": "--strict-tests / --result-json",
            "status": "implemented",
            "note": "0.1.112; sticky callback failures",
        },
        {
            "name": "numeric32 emulation",
            "status": "unsupported",
            "note": "Lua 5.4 8-byte integers, like the HC3's — no separate 32-bit runtime",
        },
    ],
    "tooling": [
        {
            "name": "--check",
            "status": "implemented",
            "note": "syntax + directives + deprecated APIs",
        },
        {
            "name": "export/pack/unpack",
            "status": "implemented",
            "note": "package-value/clobber baking",
        },
        {
            "name": "uploadQA/downloadQA/updateQA/uploadFile",
            "status": "implemented",
            "note": "HC3 file tools",
        },
        {
            "name": "migrate",
            "status": "implemented",
            "note": "plua-leftover scan",
        },
        {
            "name": "ws (WebSocket probe)",
            "status": "implemented",
            "note": "0.1.110",
        },
        {
            "name": "state/icons/createDB/setup/newQA",
            "status": "implemented",
            "note": "",
        },
    ],
}


def report(engine: Any, runtime: dict[str, Any]) -> dict[str, Any]:
    """The full --capabilities-json payload; ``runtime`` is the same record
    ``--version --machine`` emits (version/lua/lupa/python/integerBytes/locale)."""
    return {
        "schemaVersion": 1,
        "runtime": runtime,
        "basis": (
            "curated against the runtime source; 'implemented' entries are pinned "
            "by the test suite where a note names one. Absent from the table = not "
            "claimed. This describes flua's emulated surface, not physical-HC3 parity."
        ),
        "capabilities": CAPABILITIES,
    }
