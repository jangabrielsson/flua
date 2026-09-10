"""Wire format for flua messages.

Every message is a plain dict with a string ``"type"`` field and a payload of
JSON-compatible values only (str, int, float, bool, None, list, dict).
Functions never cross the bridge — Lua callbacks are addressed by integer IDs
that the Lua side registers in ``init.lua``.

Keeping the format JSON-compatible means the same messages could travel over
any transport (thread queue, pipe, socket, subprocess) if the engine ever
grows one — the asyncio side can stay identical.
"""

from typing import Any

# --- Lua -> Python (inbound, posted by _PY.post) -----------------------------

SET_TIMEOUT = "setTimeout"      # {"id": int, "delay": int, "qa": int?}  ms + QA attribution
CLEAR_TIMEOUT = "clearTimeout"  # {"id": int}
LOG = "log"                     # {"level": "info|warning|error", "text": str}
EXIT = "exit"                   # {"code": int}
QA_LOADED = "qaLoaded"          # {"id": int}  a QA finished loading its code

# --- Python -> Lua (outbound, delivered via _PY.dispatch) --------------------

TIMER_EXPIRED = "timerExpired"  # {"id": int}  run registered callback id


def set_timeout(timer_id: int, delay_ms: int, qa: int | None = None) -> dict[str, Any]:
    """Build a setTimeout request. ``timer_id`` doubles as the Lua callback id.

    ``qa`` attributes the timer to a QA (nil = runtime/untracked).
    """
    msg: dict[str, Any] = {"type": SET_TIMEOUT, "id": timer_id, "delay": delay_ms}
    if qa is not None:
        msg["qa"] = qa
    return msg


def clear_timeout(timer_id: int) -> dict[str, Any]:
    return {"type": CLEAR_TIMEOUT, "id": timer_id}


def log(level: str, text: str) -> dict[str, Any]:
    return {"type": LOG, "level": level, "text": text}


def exit_msg(code: int = 0) -> dict[str, Any]:
    return {"type": EXIT, "code": code}


def timer_expired(timer_id: int) -> dict[str, Any]:
    return {"type": TIMER_EXPIRED, "id": timer_id}
