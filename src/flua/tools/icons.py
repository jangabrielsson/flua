"""``flua --tool icons download`` — populate the machine-level icon cache.

The HC3's standard icon library (~5,300 state files, ~30 MB) is Fibaro
copyrighted artwork, so flua ships only the manifest (``devices/
icon_manifest.json``: icon set -> file names). The images are fetched once
into a shared cache (``~/.flua/icons``, FLUA_ICON_DIR overrides) — one per
machine, never per repo. The sim serves the cache to the viewer at
``GET /flua/icons/<set>/<file>``; user-uploaded QA icons land in the same
store later.

Two sources:

- ``--dump www`` — a local HC3 webroot dump (var/www): copies the icons
  from ``<dump>/assets/icon/fibaro`` — zero network;
- the live HC3 (the .env chain) — downloads every manifest file via
  ``GET /assets/icon/fibaro/<set>/<file>`` (assets live OUTSIDE ``/api``,
  basic auth, like scripts/extract_icon_files.py).
"""

from __future__ import annotations

import argparse
import base64
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

from ..devices import icon_cache_dir, icon_manifest

NAME = "icons"
HELP = "populate the icon cache (icons download)"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="command", required=True)
    download = sub.add_parser(
        "download", help="fetch the standard icon library into the shared cache"
    )
    download.add_argument(
        "--dump",
        metavar="WWW",
        help="a local HC3 webroot dump (var/www) — copy icons from "
        "<WWW>/assets/icon/fibaro instead of downloading from the HC3",
    )
    download.add_argument(
        "--dir",
        metavar="PATH",
        help=f"cache directory (default: {icon_cache_dir()})",
    )
    download.add_argument(
        "--force",
        action="store_true",
        help="re-fetch files that are already cached",
    )


def _wanted_files() -> list[tuple[str, str]]:
    manifest = icon_manifest()
    if manifest is None:
        raise SystemExit(
            "no icon manifest (src/flua/devices/icon_manifest.json) — "
            "build it with scripts/extract_icon_files.py first"
        )
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise SystemExit("icon manifest has no files table")
    return [(set_name, file_name) for set_name, names in files.items() for file_name in names]


def _is_placeholder(path: Path) -> bool:
    """The HC3 serves a generic gray box for states with no artwork, even
    under the requested extension (an SVG body named .png). Detect the
    mismatch: png bodies must be PNG, svg bodies must start with '<'."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(8)
    except OSError:
        return False
    suffix = path.suffix.lower()
    if suffix == ".png":
        return not head.startswith(b"\x89PNG")
    if suffix == ".svg":
        return not head.lstrip().startswith(b"<")
    return False


def _store(source: Path, target: Path, placeholder_count: list[int]) -> bool:
    """Copy one icon file into the cache; placeholder bodies are dropped
    (not cached) — the viewer falls back to the set's default. Returns True
    when the file was stored."""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if _is_placeholder(target):
        target.unlink()
        placeholder_count[0] += 1
        return False
    return True


def _from_dump(wanted: list[tuple[str, str]], dump: Path, cache: Path, force: bool) -> int:
    root = dump / "assets" / "icon" / "fibaro"
    if not root.is_dir():
        raise SystemExit(f"{dump} is not an HC3 webroot dump (missing assets/icon/fibaro)")
    copied = skipped = missing = 0
    placeholders = [0]
    for set_name, file_name in wanted:
        target = cache / set_name / file_name
        if target.is_file() and not force:
            # a cached placeholder is dropped; the HC3 keeps serving the
            # same placeholder, so there is nothing to re-fetch
            if _is_placeholder(target):
                target.unlink()
                placeholders[0] += 1
            skipped += 1
            continue
        source = root / set_name / file_name
        if not source.is_file():
            missing += 1
            continue
        if _store(source, target, placeholders):
            copied += 1
    print(
        f"copied {copied} icon file(s), skipped {skipped} cached, "
        f"{placeholders[0]} placeholder(s) dropped, {missing} not in the dump"
    )
    if missing:
        print(
            f"hint: {missing} file(s) are missing from this dump — use a newer "
            "dump or run without --dump to fetch them from the HC3"
        )
    return 0


def _from_hc3(wanted: list[tuple[str, str]], cache: Path, force: bool) -> int:
    from ..environment import EnvChain

    chain = EnvChain(Path(__file__).resolve().parent.parent.parent)
    url = chain.get("HC3_URL")
    if not url:
        raise SystemExit("HC3_URL is not set (the .env chain) — pass --dump or configure it")
    base = url.rstrip("/")
    if base.endswith("/api"):
        base = base[: -len("/api")]
    auth = base64.b64encode(
        f"{chain.get('HC3_USER')}:{chain.get('HC3_PASSWORD')}".encode()
    ).decode()
    fetched = skipped = failed = 0
    placeholders = [0]
    total = len(wanted)
    for index, (set_name, file_name) in enumerate(wanted, start=1):
        target = cache / set_name / file_name
        if target.is_file() and not force:
            # a cached placeholder is dropped; the HC3 keeps serving the
            # same placeholder, so there is nothing to re-fetch
            if _is_placeholder(target):
                target.unlink()
                placeholders[0] += 1
            skipped += 1
            continue
        request = urllib.request.Request(
            f"{base}/assets/icon/fibaro/{set_name}/{file_name}",
            headers={"Authorization": "Basic " + auth},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(response.read())
            if _is_placeholder(target):
                target.unlink()
                placeholders[0] += 1
            else:
                fetched += 1
        except (urllib.error.HTTPError, OSError) as exc:
            failed += 1
            print(f"  failed {set_name}/{file_name}: {exc}", file=sys.stderr)
        if index % 500 == 0 or index == total:
            print(
                f"  {index}/{total} files (fetched {fetched}, skipped {skipped}, "
                f"failed {failed}, placeholders {placeholders[0]})"
            )
    print(
        f"icon cache at {cache}: fetched {fetched}, skipped {skipped}, "
        f"failed {failed}, placeholders dropped {placeholders[0]} of {total}"
    )
    return 1 if failed and not fetched else 0


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.command != "download":
        parser.error(f"unknown icons command: {args.command}")
    cache = Path(args.dir) if args.dir else icon_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    wanted = _wanted_files()
    if args.dump:
        return _from_dump(wanted, Path(args.dump), cache, args.force)
    return _from_hc3(wanted, cache, args.force)
