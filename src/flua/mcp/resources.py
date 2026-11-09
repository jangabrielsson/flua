"""flua-mcp resources: the docs and skills shipped in the wheel, served
over MCP.

``flua://docs/<relpath>`` resolves inside the packaged docs tree
(``src/flua/setup_templates/docs``, synced by ``scripts/sync-skills.sh``)
and ``flua://skills/<relpath>`` inside the packaged skills tree
(``src/flua/setup_templates/github/skills`` — the same skills ``--tool
setup`` installs for Copilot), so an MCP host without a repo checkout can
still read the flua docs and skill guidance. Text files only; paths are
canonicalized and traversal is rejected.
"""

from __future__ import annotations

from difflib import get_close_matches
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .jsonrpc import INVALID_PARAMS, JsonRpcError

URI_PREFIX = "flua://docs/"
SKILLS_URI_PREFIX = "flua://skills/"

DOCS_DIR = Path(__file__).resolve().parent.parent / "setup_templates" / "docs"
SKILLS_DIR = Path(__file__).resolve().parent.parent / "setup_templates" / "github" / "skills"

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
    "dirigera_plua_flua_migration.md": (
        "a real plua→flua migration report (Dirigera project): "
        "checklist, gotchas, upstream findings"
    ),
    "DIRIGERA_FLUA_BUG_REPORT.md": "the Dirigera migration's upstream bug reports with repros",
    "flua-feedback_from_eventrunner7.md": "the EventRunner7 migration's feedback report",
    "specs/hc3-api.json": "the HC3 REST API structural reference",
    "specs/refreshEvents.json": "HC3 refreshState event shapes",
    "decisions/README.md": "index of the ADR-lite decision log",
}


def _mime(path: Path) -> str:
    return MIME_TYPES.get(path.suffix.lower(), "text/plain")


@lru_cache(maxsize=1)
def _text_paths(tree: Path) -> tuple[str, ...]:
    """Every text file as a relative posix path — the suggestion pool for
    unknown-URI errors (agents guess paths and read the error)."""
    return tuple(
        path.relative_to(tree).as_posix()
        for path in tree.rglob("*")
        if path.is_file() and _is_text(path)
    )


def _skill_meta(path: Path) -> dict[str, str]:
    """A skill file's frontmatter (--- ... ---) as name/description, plus
    the first heading after the block as the title."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    meta: dict[str, str] = {}
    body = 1
    for line in lines[1:60]:
        body += 1
        stripped = line.strip()
        if stripped == "---":
            break
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            if key.strip() and key.strip() not in meta:
                meta[key.strip()] = value.strip()
    for line in lines[body : body + 5]:
        if line.startswith("# "):
            meta["title"] = line[2:].strip()
            break
    return meta


def _is_text(path: Path) -> bool:
    # text only; the tutorial PDF and any binary stay out of the list
    return path.suffix.lower() in MIME_TYPES


def _resolve(uri: Any) -> Path:
    """Map a flua://docs/ or flua://skills/ URI to a file inside the
    matching packaged tree, rejecting traversal and non-text targets."""
    if not isinstance(uri, str):
        raise JsonRpcError(
            INVALID_PARAMS, f"uri must start with {URI_PREFIX} or {SKILLS_URI_PREFIX}"
        )
    if uri.startswith(URI_PREFIX):
        tree, prefix, rel = DOCS_DIR, URI_PREFIX, uri[len(URI_PREFIX) :]
    elif uri.startswith(SKILLS_URI_PREFIX):
        tree, prefix, rel = SKILLS_DIR, SKILLS_URI_PREFIX, uri[len(SKILLS_URI_PREFIX) :]
    else:
        raise JsonRpcError(
            INVALID_PARAMS, f"uri must start with {URI_PREFIX} or {SKILLS_URI_PREFIX}"
        )
    rel = unquote(rel).replace("\\", "/")
    if not rel or "\x00" in rel:
        raise JsonRpcError(INVALID_PARAMS, "empty or invalid uri path")
    path = Path(rel)
    if path.is_absolute() or ".." in path.parts:
        raise JsonRpcError(INVALID_PARAMS, f"path escapes the {prefix.rstrip('/')} tree: {rel}")
    candidate = (tree / path).resolve()
    if not candidate.is_relative_to(tree.resolve()) or not candidate.is_file():
        close = get_close_matches(rel, _text_paths(tree), n=3, cutoff=0.5)
        hint = f" — did you mean {', '.join(repr(p) for p in close)}?" if close else ""
        raise JsonRpcError(INVALID_PARAMS, f"no such resource: {uri}{hint}")
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
    for path in sorted(SKILLS_DIR.rglob("*")):
        if not path.is_file() or not _is_text(path):
            continue
        rel = path.relative_to(SKILLS_DIR).as_posix()
        meta = _skill_meta(path)
        resources.append(
            {
                "uri": SKILLS_URI_PREFIX + rel,
                "name": meta.get("name") or path.name,
                "title": meta.get("title") or path.name,
                "description": meta.get("description") or f"flua skill: {rel}",
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
