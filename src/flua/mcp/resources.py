"""flua-mcp resources: the docs shipped in the wheel, served over MCP.

``flua://docs/<relpath>`` resolves inside the packaged docs tree
(``src/flua/setup_templates/docs``, synced by ``scripts/sync-skills.sh``) so
an MCP host without a repo checkout can still read the flua docs — the same
knowledge a local agent would read from the checkout. Text files only;
paths are canonicalized and traversal is rejected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .jsonrpc import INVALID_PARAMS, JsonRpcError

URI_PREFIX = "flua://docs/"

DOCS_DIR = Path(__file__).resolve().parent.parent / "setup_templates" / "docs"

MIME_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".json": "application/json",
    ".txt": "text/plain",
    ".lua": "text/x-lua",
    ".py": "text/x-python",
    ".sh": "text/x-sh",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
}

# curated descriptions for the entries agents reach for most; the rest get
# a path-derived fallback
DESCRIPTIONS = {
    "README.md": "the flua documentation index: what lives where",
    "USAGE.md": "the flua user guide: CLI, modes, directives, tools",
    "ARCHITECTURE.md": "how flua is built: engine, API, Lua runtime",
    "CONTRIBUTING.md": "how to contribute to flua",
    "concurrency.md": "threading and execution model, blocking rules",
    "invariants.md": "behavioral contracts and their pinning tests",
    "walkthroughs.md": "guided traces of key flows",
    "mcp.md": "the flua-mcp server: protocol, tools, host setup",
    "rest-endpoints.md": "REST routes: real vs shape-only stubs",
    "specs/hc3-api.json": "the HC3 REST API structural reference",
    "specs/refreshEvents.json": "HC3 refreshState event shapes",
    "decisions/README.md": "index of the ADR-lite decision log",
}


def _mime(path: Path) -> str:
    return MIME_TYPES.get(path.suffix.lower(), "text/plain")


def _is_text(path: Path) -> bool:
    # text only; the tutorial PDF and any binary stay out of the list
    return path.suffix.lower() in MIME_TYPES


def _resolve(uri: Any) -> Path:
    """Map a flua://docs/ URI to a file inside the docs tree, rejecting
    traversal and non-text targets."""
    if not isinstance(uri, str) or not uri.startswith(URI_PREFIX):
        raise JsonRpcError(INVALID_PARAMS, f"uri must start with {URI_PREFIX}")
    rel = unquote(uri[len(URI_PREFIX) :]).replace("\\", "/")
    if not rel or "\x00" in rel:
        raise JsonRpcError(INVALID_PARAMS, "empty or invalid uri path")
    path = Path(rel)
    if path.is_absolute() or ".." in path.parts:
        raise JsonRpcError(INVALID_PARAMS, f"path escapes the docs tree: {rel}")
    candidate = (DOCS_DIR / path).resolve()
    if not candidate.is_relative_to(DOCS_DIR.resolve()) or not candidate.is_file():
        raise JsonRpcError(INVALID_PARAMS, f"no such resource: {uri}")
    if not _is_text(candidate):
        raise JsonRpcError(INVALID_PARAMS, f"not a text resource: {uri}")
    return candidate


def _title(rel: str, path: Path) -> str:
    """The first markdown heading where available, else the file name."""
    if path.suffix.lower() in (".md", ".markdown"):
        try:
            for line in path.read_text(encoding="utf-8").splitlines()[:5]:
                stripped = line.strip()
                if stripped.startswith("# "):
                    return stripped[2:].strip()
        except (OSError, UnicodeDecodeError):
            pass
    return path.name


def list_resources(_params: dict[str, Any]) -> dict[str, Any]:
    resources = []
    for path in sorted(DOCS_DIR.rglob("*")):
        if not path.is_file() or not _is_text(path):
            continue
        rel = path.relative_to(DOCS_DIR).as_posix()
        resources.append(
            {
                "uri": URI_PREFIX + rel,
                "name": path.name,
                "title": _title(rel, path),
                "description": DESCRIPTIONS.get(rel, f"flua documentation: {rel}"),
                "mimeType": _mime(path),
            }
        )
    return {"resultType": "complete", "resources": resources}


def read_resource(params: dict[str, Any]) -> dict[str, Any]:
    uri = params.get("uri")
    path = _resolve(uri)
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "resultType": "complete",
        "contents": [{"uri": uri, "mimeType": _mime(path), "text": text}],
    }
