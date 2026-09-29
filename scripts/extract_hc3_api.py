#!/usr/bin/env python3
"""Extract a factual, flua-owned API reference from the official HC3 swagger.

The official swagger files - this generator distills them into
``docs/specs/hc3-api.json`` — structural facts only: paths, methods,
parameter names/types, request-body schemas, response status codes, and
schema field names/types. No descriptions, summaries or other prose are
copied.

Usage::

    .venv/bin/python scripts/extract_hc3_api.py
"""

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "fibaro_api_docs"
OUT = ROOT / "docs" / "specs" / "hc3-api.json"

METHODS = ("get", "post", "put", "delete", "patch")


def type_name(schema: dict) -> str | None:
    if not isinstance(schema, dict):
        return None
    ref = schema.get("$ref")
    if ref:
        return ref.rsplit("/", 1)[-1]
    typ = schema.get("type")
    if typ == "array":
        items = schema.get("items") or {}
        return f"array<{type_name(items) or 'object'}>"
    return typ


def collect_parameters(operation: dict) -> list[dict]:
    out = []
    for param in operation.get("parameters") or []:
        out.append(
            {
                "name": param.get("name"),
                "in": param.get("in"),
                "required": bool(param.get("required")),
                "type": type_name(param.get("schema") or {}),
            }
        )
    return out


def collect_request_body(operation: dict) -> dict | None:
    body = operation.get("requestBody")
    if not isinstance(body, dict):
        return None
    schema = ((body.get("content") or {}).get("application/json") or {}).get("schema")
    return {"required": bool(body.get("required")), "schema": type_name(schema or {})}


def collect_responses(operation: dict) -> dict:
    out = {}
    for status, response in (operation.get("responses") or {}).items():
        schema = ((response.get("content") or {}).get("application/json") or {}).get("schema")
        out[status] = type_name(schema or {})
    return out


def collect_schema_props(schema: dict) -> dict | None:
    props = schema.get("properties")
    if not isinstance(props, dict):
        return None
    return {name: type_name(spec or {}) for name, spec in props.items()}


def main() -> int:
    if not DOCS.exists():
        print(
            f"error: {DOCS} not found — the official swagger is not distributed "
            "with the repo; the distilled reference is checked in instead",
            file=sys.stderr,
        )
        return 1
    endpoints: list[dict] = []
    schemas: dict = {}
    for path_str in sorted(glob.glob(str(DOCS / "**" / "*.json"), recursive=True)):
        try:
            doc = json.loads(Path(path_str).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for path, methods in (doc.get("paths") or {}).items():
            for method in METHODS:
                operation = methods.get(method)
                if not operation:
                    continue
                endpoints.append(
                    {
                        "method": method.upper(),
                        "path": path,
                        "parameters": collect_parameters(operation),
                        "requestBody": collect_request_body(operation),
                        "responses": collect_responses(operation),
                    }
                )
        for name, schema in (doc.get("components", {}).get("schemas") or {}).items():
            props = collect_schema_props(schema)
            if props is not None:
                schemas[name] = {"type": schema.get("type", "object"), "properties": props}
    endpoints.sort(key=lambda entry: (entry["path"], entry["method"]))
    reference = {
        "$comment": (
            "Structural reference of the HC3 REST API, distilled from the "
            "official swagger (fibaro_api_docs/, Fibaro's property — not "
            "distributed with the repo). Facts only: paths, methods, parameter "
            "names/types, request-body schemas, response status codes, and "
            "schema field names/types. Regenerate with scripts/extract_hc3_api.py."
        ),
        "generator": "scripts/extract_hc3_api.py",
        "endpoints": endpoints,
        "schemas": schemas,
    }
    OUT.write_text(json.dumps(reference, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {len(endpoints)} endpoints, {len(schemas)} schemas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
