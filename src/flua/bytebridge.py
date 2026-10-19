"""Byte-safe payload transport across the UTF-8 Lua bridge.

The engine<->Lua message bridge is UTF-8 text: a raw byte >= 0x80 crossing
it would be mangled. Socket payloads use ``_FLUA.escapeBytes`` on the Lua
side and these mirrors here — bytes that cannot cross are written as ``\\xHH``
and the backslash itself is escaped, so the transforms are exact inverses.
"""

from __future__ import annotations

from typing import Any

_HEX = "0123456789abcdefABCDEF"


def _unescape_data(text: Any) -> bytes | str:
    """Inverse of the Lua side's byte escaper (_FLUA.escapeBytes) for socket
    and HTTP payloads: ``\\xHH`` becomes the raw byte. A literal backslash
    arrived escaped as ``\\x5C``, so the transform is exact. Payloads without
    escapes return unchanged (kept as str — plain text behaves as before)."""
    if isinstance(text, bytes):
        return text
    s = str(text)
    if "\\x" not in s:
        return s
    out = bytearray()
    i, n = 0, len(s)
    while i < n:
        if (
            s[i] == "\\"
            and i + 3 < n
            and s[i + 1] == "x"
            and s[i + 2] in _HEX
            and s[i + 3] in _HEX
        ):
            out.append(int(s[i + 2 : i + 4], 16))
            i += 4
            continue
        out += s[i].encode("utf-8")
        i += 1
    return bytes(out)


def _escape_data(data: Any) -> str:
    """Mirror of _FLUA.escapeBytes for engine -> Lua payloads: returns the
    ASCII-safe escaped form (bytes that cannot cross the UTF-8 bridge become
    ``\\xHH``; NUL, DEL and the backslash itself are escaped too)."""
    if isinstance(data, str):
        data = data.encode("latin-1", errors="replace")
    out: list[str] = []
    for b in data:
        if b >= 0x80 or b in (0x00, 0x7F, 0x5C):
            out.append(f"\\x{b:02X}")
        else:
            out.append(chr(b))
    return "".join(out)
