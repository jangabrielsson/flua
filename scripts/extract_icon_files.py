#!/usr/bin/env python3
"""Build the checked-in icon FILE manifest (iconSetName -> state files).

Ground truth is the LIVE HC3: it serves every icon set's full uniform
pattern — 14 state suffixes (base, 0, 10..100, Unknown, 255) in BOTH png
and svg — 28 files per set. The webroot dump only ships a partial,
pre-computed subset (the shipped base artwork), so it is used only as a
complement: named state files the standard pattern does not cover
(``COSensorV2-alarm``, ``DoorLock_unkown``, ...) and a fallback when a
set cannot be probed.

The icon assets are served OUTSIDE ``/api`` (plain webroot paths), so this
script hits the base URL directly — Hc3Remote's ``/api`` prefix would 501.

Writes ``src/flua/devices/icon_manifest.json``: the file lists (facts) only —
the image bytes stay out of the repo (Fibaro assets).

Usage::

    .venv/bin/python scripts/extract_icon_files.py [--dump www/assets/icon/fibaro]
"""

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "flua" / "devices" / "icon_manifest.json"
CATALOG = ROOT / "src" / "flua" / "devices" / "icons.json"

sys.path.insert(0, str(ROOT / "src"))
from flua.environment import EnvChain  # noqa: E402

IMAGE_EXTS = {".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp"}
# the HC3's uniform per-set state pattern (both image formats are served)
STATE_SUFFIXES = (
    "",
    "0",
    "10",
    "20",
    "30",
    "40",
    "50",
    "60",
    "70",
    "80",
    "90",
    "100",
    "Unknown",
    "255",
)
FORMATS = ("png", "svg")


def _catalog_set_names() -> set[str]:
    with open(CATALOG, encoding="utf-8") as handle:
        catalog = json.load(handle)
    data = catalog.get("data")
    device = data.get("device") if isinstance(data, dict) else None
    return {
        entry["iconSetName"]
        for entry in (device or [])
        if isinstance(entry, dict) and entry.get("iconSetName")
    }


def _from_dump(dump: Path) -> tuple[dict[str, list[str]], dict[str, str]]:
    files: dict[str, list[str]] = {}
    source: dict[str, str] = {}
    if not dump.is_dir():
        print(f"dump not found: {dump} — live probes only", file=sys.stderr)
        return files, source
    for folder in sorted(entry for entry in dump.iterdir() if entry.is_dir()):
        names = sorted(
            child.name
            for child in folder.iterdir()
            if child.is_file() and child.suffix.lower() in IMAGE_EXTS
        )
        if names:
            files[folder.name] = names
            source[folder.name] = "dump"
    return files, source


def _probe_hc3(base: str, auth: str, setname: str) -> list[str]:
    """Probe the set's state files on the live HC3 (assets live outside
    /api); a small, sequential, read-only probe."""
    hits: list[str] = []
    for fmt in FORMATS:
        for suffix in STATE_SUFFIXES:
            name = f"{setname}{suffix}.{fmt}"
            request = urllib.request.Request(
                f"{base}/assets/icon/fibaro/{setname}/{name}",
                headers={"Authorization": "Basic " + auth},
            )
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    response.read()
                hits.append(name)
            except urllib.error.HTTPError:
                pass  # 404: that state file does not exist for this set
    return hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dump",
        default=str(ROOT / "www" / "assets" / "icon" / "fibaro"),
        help="path to the HC3 webroot dump's icon library (named-state extras)",
    )
    args = parser.parse_args()

    dump_files, _dump_source = _from_dump(Path(args.dump))
    set_names = sorted(set(_catalog_set_names()) | set(dump_files))
    files: dict[str, list[str]] = {}
    source: dict[str, str] = {}
    probed = 0
    firmware = None

    chain = EnvChain(ROOT)
    url = chain.get("HC3_URL")
    if not url:
        print(
            "HC3_URL is not set (the .env chain) — recording the dump's files only",
            file=sys.stderr,
        )
    if url:
        base = url.rstrip("/")
        if base.endswith("/api"):
            base = base[: -len("/api")]
        auth = base64.b64encode(
            f"{chain.get('HC3_USER')}:{chain.get('HC3_PASSWORD')}".encode()
        ).decode()
        for index, setname in enumerate(set_names, start=1):
            hits = _probe_hc3(base, auth, setname)
            if hits:
                files[setname] = hits
                source[setname] = "hc3"
                probed += 1
            if index % 20 == 0 or index == len(set_names):
                print(f"probed {index}/{len(set_names)} sets", file=sys.stderr)

        from flua.hc3 import Hc3Remote

        remote = Hc3Remote(url, chain.get("HC3_USER"), chain.get("HC3_PASSWORD"), timeout=15)
        info, info_status = remote.request("GET", "/settings/info")
        firmware = (info or {}).get("softVersion") if info_status == 200 else None

    # the dump's named-state files (outside the standard pattern) ride along
    # — the live probe covers the uniform 28, the dump completes the extras
    for setname, names in dump_files.items():
        extras = [n for n in names if n not in files.get(setname, [])]
        if extras:
            files[setname] = sorted(files.get(setname, []) + extras)
            source[setname] = source.get(setname, "dump") + "+dump"
        elif setname not in files:
            files[setname] = names
            source[setname] = "dump"

    document = {
        "meta": {
            "fetched": datetime.now(UTC).isoformat(),
            "firmware": firmware,
            "note": "icon set -> state file names, live-probed from the HC3 "
            "(the uniform 14-suffix x 2-format pattern) plus the webroot dump's "
            "named-state extras (scripts/extract_icon_files.py). Image bytes are "
            "NOT stored here — the controller / the dump carry them.",
        },
        "files": dict(sorted(files.items())),
        "source": dict(sorted(source.items())),
    }
    OUT.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    total_files = sum(len(names) for names in files.values())
    print(
        f"wrote {OUT} | {len(files)} sets, {total_files} files | "
        f"{probed} sets live-probed | firmware {firmware}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
