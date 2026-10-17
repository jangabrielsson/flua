"""flua-mcp prompts: reusable agent guidance for QuickApp work.

Two prompts today: ``qa_debug`` (structured debugging guidance seeded with
the agent's error) and ``qa_skeleton`` (emit a self-testing QA template).
Texts reference ``flua://docs/*`` resources the host can fetch.
"""

from __future__ import annotations

from typing import Any

from .jsonrpc import INVALID_PARAMS, METHOD_NOT_FOUND, JsonRpcError

# The template handed out by qa_skeleton. Kept runnable: tests extract this
# block and run it through qa_run, so the skeleton never rots.
SKELETON = """--%%name:__NAME__

-- A QuickApp as its own test suite: assert its behavior against the
-- simulated HC3, print PASS:/FAIL:, and let finish() set the exit code --
-- the exit code is the verdict. Run offline:
--   flua --api local --instant __NAME__.lua    (or the qa_run MCP tool)

--%%file:$flua-test.lua,flua_test
-- The assertions library ships inside the .fqa, so the same file can go
-- to a real HC3: there every assertion becomes a no-op (no prints, no
-- exit) and the QA just runs.

local Test = require("flua-test")
local t = Test.new()

-- deferred-onInit: onInit only registers work; the first real step runs
-- from a timer so every QA in the ensemble can initialize first.
function QuickApp:onInit()
  self:updateProperty("value", 0)
  self:debug("initialized")
  t:expect(self.id >= 5000, "emulated QA ids start at 5000")
  setTimeout(function()
    -- the QA under test
    self:updateProperty("value", self.properties.value + 1)
    t:assert_eq(self.properties.value, 1, "timer updated the property")
    t:finish()
  end, 1000)
end
"""

SKELETON_RULES = (
    "Rules for filling this in: keep api.* calls offline (the sim answers "
    "them; a real controller is only touched when mode=remote is explicit); "
    "every run must terminate — finish() or exit() when the QA is done, "
    "never leave a timer or HTTP call pending; assertions are "
    "t:expect(cond, msg), t:assert_eq(got, want, msg), t:assert_json(text, "
    "msg), t:finish(). The exit code is the verdict — assert against it, "
    "not against log prose. See flua://docs/USAGE.md (directives and APIs) "
    "and flua://docs/tutorial/03-qa-anatomy.md."
)

DEBUG_GUIDANCE = """A flua QuickApp is misbehaving. Work the problem in this order:

1. Static layer first: run qa_check (or `flua --check <file>`) — Lua syntax,
   unknown --%% directives, deprecated HC3 APIs, missing --%%file includes.
2. Reproduce offline: qa_run with mode=local (never a controller unless
   mode=remote is deliberate). instant=true collapses virtual time.
3. Read the error by shape: a syntax error carries file/line/column; a
   runtime error is a Lua traceback into QA code; a timeout or "never
   drained" verdict means something kept the engine alive — a pending
   timer, an in-flight HTTP call, or a QA that never called exit().
4. Read the logs, not just the exit code: qa_run returns JSON logs
   ({time, level, tag, qaid, msg}) and summary with level counts and
   flua-test pass/fail tallies — filter={match: ...} narrows server-side.
5. Shrink the problem: bisect by commenting bodies, or extract the failing
   logic into a minimal one-file QA (use qa_skeleton for the harness).
6. If behavior contradicts the docs, read the pinned contracts —
   flua://docs/invariants.md — and the tracing guides
   flua://docs/walkthroughs.md, the debugging chapter
   flua://docs/tutorial/07-when-things-go-wrong.md, and the user guide
   flua://docs/USAGE.md.

Report back: the minimal reproduction, the exact error, and the fix."""


def _text(text: str) -> dict[str, Any]:
    return {"role": "user", "content": {"type": "text", "text": text}}


def _debug_message(arguments: dict[str, Any]) -> dict[str, Any]:
    error = arguments.get("error", "")
    code = arguments.get("code", "")
    parts = [DEBUG_GUIDANCE, "", "Reported error:"]
    parts.append(error.strip() or "(none provided)")
    if code:
        parts += ["", "Code under test:", "```lua", code.strip(), "```"]
    return _text("\n".join(parts))


def _skeleton_message(arguments: dict[str, Any]) -> dict[str, Any]:
    name = "".join(c for c in str(arguments.get("name") or "my-qa") if c.isalnum() or c in "_-")
    skeleton = SKELETON.replace("__NAME__", name or "my-qa")
    return _text("\n".join(["```lua", skeleton, "```", SKELETON_RULES]))


PROMPTS: dict[str, dict[str, Any]] = {
    "qa_debug": {
        "title": "Debug a flua QuickApp",
        "description": "Structured debugging guidance seeded with an error and the "
        "code under test: static checks, offline reproduction, log shape, "
        "shrinking, and which docs to read.",
        "arguments": [
            {"name": "error", "description": "the error output or symptom", "required": True},
            {"name": "code", "description": "the QA source under test (optional)"},
        ],
        "render": _debug_message,
    },
    "qa_skeleton": {
        "title": "Emit a self-testing QA skeleton",
        "description": "A runnable QuickApp template with flua-test assertions and "
        "the deferred-onInit pattern — the QA asserts its own behavior against "
        "the simulated HC3 and exits with the failure count.",
        "arguments": [
            {"name": "name", "description": "the QA/device name (default my-qa)"},
        ],
        "render": _skeleton_message,
    },
}


def list_prompts(_params: dict[str, Any]) -> dict[str, Any]:
    return {
        "resultType": "complete",
        "prompts": [
            {
                "name": name,
                "title": spec["title"],
                "description": spec["description"],
                "arguments": [
                    {**arg, "required": bool(arg.get("required"))}
                    for arg in spec.get("arguments") or []
                ],
            }
            for name, spec in PROMPTS.items()
        ],
    }


def get_prompt(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    spec = PROMPTS.get(name)
    if spec is None:
        raise JsonRpcError(METHOD_NOT_FOUND, f"unknown prompt: {name}")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise JsonRpcError(INVALID_PARAMS, "arguments must be an object")
    missing = [
        arg["name"]
        for arg in spec.get("arguments") or []
        if arg.get("required") and not arguments.get(arg["name"])
    ]
    if missing:
        raise JsonRpcError(INVALID_PARAMS, f"missing required argument(s): {', '.join(missing)}")
    return {
        "resultType": "complete",
        "description": spec["description"],
        "messages": [spec["render"](arguments)],
    }
