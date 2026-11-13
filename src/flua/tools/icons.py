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
import http.server
import json
import re
import secrets
import shutil
import struct
import sys
import urllib.error
import urllib.request
from pathlib import Path

from ..devices import (
    USER_FAMILY_STATES,
    USER_ICON_FAMILY,
    icon_cache_dir,
    icon_manifest,
    icon_pattern_files,
)
from ..http import http_call

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
    ui = sub.add_parser(
        "ui",
        help="icon manager: a browser page to list, upload and delete user icon sets",
    )
    ui.add_argument(
        "--port",
        type=int,
        default=8095,
        help="local port (default 8095; 0 = pick a free one)",
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


def _with_live_custom_sets(wanted: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Extend the wanted list with the live HC3's icon sets the checked-in
    manifest does not cover — custom sets uploaded with
    uploadExternalIconSet (User<id>) and newer-firmware additions. Their
    file lists derive from the uniform <set><state>.<ext> pattern. Without
    HC3 credentials (or when the library can't be read) the manifest list
    stands."""
    from ..environment import EnvChain

    chain = EnvChain(Path(__file__).resolve().parent.parent.parent)
    url = chain.get("HC3_URL")
    if not url:
        return wanted
    base = url.rstrip("/")
    if base.endswith("/api"):
        base = base[: -len("/api")]
    auth = base64.b64encode(
        f"{chain.get('HC3_USER')}:{chain.get('HC3_PASSWORD')}".encode()
    ).decode()
    try:
        request = urllib.request.Request(
            f"{base}/api/icons", headers={"Authorization": "Basic " + auth}
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            library = json.loads(response.read())
    except (urllib.error.HTTPError, OSError, ValueError) as exc:
        print(
            f"warning: cannot read the live icon library ({exc}) — "
            "downloading the manifest sets only",
            file=sys.stderr,
        )
        return wanted
    wanted_sets = {set_name for set_name, _ in wanted}
    extra: list[tuple[str, str]] = []
    for entry in (library or {}).get("device") or [] if isinstance(library, dict) else []:
        if not isinstance(entry, dict):
            continue
        set_name = str(entry.get("iconSetName") or "")
        if not set_name or set_name in wanted_sets:
            continue
        wanted_sets.add(set_name)
        extra.extend(
            (set_name, file_name)
            for file_name in icon_pattern_files(
                set_name, str(entry.get("fileExtension") or "")
            )
        )
    return wanted + extra


def _is_placeholder(path: Path) -> bool:
    """The HC3 serves a generic gray box for states with no artwork, even
    under the requested extension (an SVG body named .png). Detect the
    mismatch: png bodies must be PNG, svg bodies must start with '<' and
    must not be HTML error documents (the userIcons tree serves ``<!doctype
    html>`` pages for missing files)."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(32)
    except OSError:
        return False
    suffix = path.suffix.lower()
    if suffix == ".png":
        return not head.startswith(b"\x89PNG")
    if suffix == ".svg":
        lowered = head.lstrip().lower()
        if lowered.startswith(b"<!doctype") or lowered.startswith(b"<html"):
            return True
        return not lowered.startswith(b"<")
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


_USER_SET_RE = re.compile(r"^User\d+$")

# the named states of the baseShutter provider (quickapp.lua's
# deviceIconTypeMapping) — user-uploaded shutter sets serve these too
_USER_NAMED_STATES = ("Opening", "Opened", "Closing", "Closed", "PartialOpen")


def _with_user_sets(wanted: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """User-uploaded icon sets (User<id>, uploadExternalIconSet) live under
    ``/assets/userIcons/devices/`` as ``<set><state>.png`` — the base for
    single-icon sets, ladder states (0..100) for binary/multilevel sets,
    named states for shutter sets. Expand each user set to that candidate
    list (the HC3 serves HTML error docs for names that do not exist, and
    the download drops those as placeholders). The fibaro tree's slots for
    these sets are placeholder art, so it is never consulted."""
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for set_name, file_name in wanted:
        if not _USER_SET_RE.fullmatch(set_name):
            result.append((set_name, file_name))
            continue
        if set_name in seen:
            continue
        seen.add(set_name)
        result.extend((set_name, name) for name in icon_pattern_files(set_name, "png"))
        result.extend(
            (set_name, f"{set_name}{state}.png") for state in _USER_NAMED_STATES
        )
    return result


def _from_dump(wanted: list[tuple[str, str]], dump: Path, cache: Path, force: bool) -> int:
    root = dump / "assets" / "icon" / "fibaro"
    if not root.is_dir():
        raise SystemExit(f"{dump} is not an HC3 webroot dump (missing assets/icon/fibaro)")
    copied = skipped = missing = 0
    placeholders = [0]
    wanted = _with_user_sets(wanted)
    user_set_files: dict[str, set[str]] = {}
    for set_name, file_name in wanted:
        if _USER_SET_RE.fullmatch(set_name):
            user_set_files.setdefault(set_name, set()).add(file_name)
    for set_name, file_name in wanted:
        target = cache / set_name / file_name
        is_user_set = bool(_USER_SET_RE.fullmatch(set_name))
        source = (
            dump / "assets" / "userIcons" / "devices" / set_name / file_name
            if is_user_set
            else root / set_name / file_name
        )
        if is_user_set:
            # drop stale cached names outside the set's candidate list
            # (placeholder art from earlier downloads must not linger)
            for stale in target.parent.glob(f"{set_name}*"):
                if stale.name not in user_set_files[set_name] and stale.is_file():
                    stale.unlink()
        if target.is_file() and not force:
            # a cached placeholder is dropped; the HC3 keeps serving the
            # same placeholder, so there is nothing to re-fetch
            if _is_placeholder(target):
                target.unlink()
                placeholders[0] += 1
            skipped += 1
            continue
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
    wanted = _with_user_sets(wanted)
    user_set_files: dict[str, set[str]] = {}
    for set_name, file_name in wanted:
        if _USER_SET_RE.fullmatch(set_name):
            user_set_files.setdefault(set_name, set()).add(file_name)
    total = len(wanted)
    for index, (set_name, file_name) in enumerate(wanted, start=1):
        target = cache / set_name / file_name
        is_user_set = bool(_USER_SET_RE.fullmatch(set_name))
        url = (
            f"{base}/assets/userIcons/devices/{set_name}/{file_name}"
            if is_user_set
            else f"{base}/assets/icon/fibaro/{set_name}/{file_name}"
        )
        if is_user_set:
            # drop stale cached names outside the set's candidate list
            # (placeholder art from earlier downloads must not linger)
            for stale in target.parent.glob(f"{set_name}*"):
                if stale.name not in user_set_files[set_name] and stale.is_file():
                    stale.unlink()
        if target.is_file() and not force:
            # a cached placeholder is dropped; the HC3 keeps serving the
            # same placeholder, so there is nothing to re-fetch
            if _is_placeholder(target):
                target.unlink()
                placeholders[0] += 1
            skipped += 1
            continue
        request = urllib.request.Request(
            url,
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
    if args.command == "ui":
        return _run_icons_ui(args)
    if args.command != "download":
        parser.error(f"unknown icons command: {args.command}")
    cache = Path(args.dir) if args.dir else icon_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    wanted = _wanted_files()
    if args.dump:
        return _from_dump(wanted, Path(args.dump), cache, args.force)
    wanted = _with_live_custom_sets(wanted)
    return _from_hc3(wanted, cache, args.force)


# -- icons ui: the icon manager ------------------------------------------------

_ICONS_UI_PAGE = (
    Path(__file__).resolve().parent.parent / "setup_templates" / "icons_manager.html"
)
_UI_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _ui_hc3() -> tuple[str, str]:
    """(base_url, auth_header) from the .env chain — the manager's server
    talks to the controller; the browser only ever talks to localhost (no
    CORS, no credentials in the page)."""
    from ..environment import EnvChain

    chain = EnvChain(Path(__file__).resolve().parent.parent.parent)
    url = chain.get("HC3_URL")
    if not url:
        raise SystemExit(
            "HC3_URL is not set (the .env chain) — configure it to run the icon manager"
        )
    base = url.rstrip("/")
    if base.endswith("/api"):
        base = base[: -len("/api")]
    auth = base64.b64encode(
        f"{chain.get('HC3_USER')}:{chain.get('HC3_PASSWORD')}".encode()
    ).decode()
    return base, f"Basic {auth}"


def _build_single_icon_multipart(category: str, data: bytes, extension: str) -> tuple[bytes, str]:
    """The single-icon upload contract for room/scene (mined from the web
    UI's generated client uploadIcon): type=<category>, one file part named
    icon, fileExtension."""
    boundary = "----fluaIconsUi" + secrets.token_hex(8)
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="type"\r\n\r\n'
        f"{category}\r\n"
    ).encode()
    icon = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="icon"; filename="icon"\r\n'
        f"Content-Type: image/png\r\n\r\n".encode() + data + b"\r\n"
    )
    ext = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="fileExtension"\r\n\r\n'
        f"{extension}\r\n".encode()
    )
    return head + icon + ext + f"--{boundary}--\r\n".encode(), boundary


def _build_icon_multipart(device_template: str, files: dict[str, bytes]) -> tuple[bytes, str]:
    """The HC3 upload format (live-verified 5.22x): type=device,
    deviceTemplate=<type>, one part per provider file, image/png."""
    boundary = "----fluaIconsUi" + secrets.token_hex(8)
    parts: list[bytes] = []

    def field(name: str, value: str) -> None:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )

    def file(name: str, data: bytes) -> None:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
            f'filename="{name}"\r\nContent-Type: image/png\r\n\r\n'.encode() + data + b"\r\n"
        )

    field("type", "device")
    field("deviceTemplate", device_template)
    for name, data in files.items():
        file(name, data)
    return b"".join(parts) + f"--{boundary}--\r\n".encode(), boundary


class _IconsUiHandler(http.server.BaseHTTPRequestHandler):
    server: IconsUiServer  # type annotation only — set on the server class

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(self.server.page)))
            self.end_headers()
            self.wfile.write(self.server.page)
            return
        if parsed.path == "/api/families":
            self._json(
                200,
                {
                    "families": {
                    device_type: family
                    for device_type, family in USER_ICON_FAMILY.items()
                },
                    "states": USER_FAMILY_STATES,
                },
            )
            return
        if parsed.path == "/api/list":
            try:
                status, body, _headers = http_call(
                    "GET",
                    f"{self.server.hc3_base}/api/icons",
                    {"Authorization": self.server.hc3_auth},
                )
            except OSError as exc:
                self._json(502, {"error": f"cannot reach the HC3: {exc}"})
                return
            if status != 200 or not isinstance(body, str):
                self._json(502, {"error": f"HC3 answered {status}"})
                return
            self._json(200, {"hc3": self.server.hc3_base, "icons": json.loads(body)})
            return
        if parsed.path == "/api/preview":
            query = urllib.parse.parse_qs(parsed.query)
            category = (query.get("cat") or ["device"])[0]
            set_name = (query.get("set") or [""])[0]
            file_name = (query.get("file") or [""])[0]
            if (
                category not in ("device", "room", "scene")
                or not _UI_NAME_RE.fullmatch(set_name)
                or not _UI_NAME_RE.fullmatch(file_name)
            ):
                self._json(400, {"error": "bad category/set/file name"})
                return
            user_set = _USER_SET_RE.fullmatch(set_name) is not None
            if category == "device":
                tree = (
                    f"assets/userIcons/devices/{set_name}/{file_name}"
                    if user_set
                    else f"assets/icon/fibaro/{set_name}/{file_name}"
                )
            elif category == "room":
                tree = (
                    f"assets/userIcons/rooms/{set_name}/{file_name}"
                    if user_set
                    else f"assets/icon/fibaro/rooms/{set_name}/{file_name}"
                )
            else:
                tree = (
                    f"assets/userIcons/scenes/{set_name}/{file_name}"
                    if user_set
                    else f"assets/icon/fibaro/scena/{set_name}/{file_name}"
                )
            url = f"{self.server.hc3_base}/{tree}"
            try:
                # the asset tree is public — no auth needed
                status, body, headers = http_call("GET", url, binary=True)
            except OSError as exc:
                self._json(502, {"error": f"cannot reach the HC3: {exc}"})
                return
            if status != 200 or not isinstance(body, bytes):
                self._json(404, {"error": "not found"})
                return
            self.send_response(200)
            self.send_header("Content-Type", headers.get("Content-Type") or "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._json(400, {"error": "bad JSON"})
            return
        if parsed.path == "/api/upload":
            category = str(request.get("category") or "device")
            if category not in ("device", "room", "scene"):
                self._json(400, {"error": "category must be device, room or scene"})
                return
            files_raw = request.get("files")
            if not isinstance(files_raw, dict) or not files_raw:
                self._json(400, {"error": "files are required"})
                return
            files: dict[str, bytes] = {}
            for name, encoded in files_raw.items():
                if not _UI_NAME_RE.fullmatch(name) or not isinstance(encoded, str):
                    self._json(400, {"error": f"bad file name {name!r}"})
                    return
                try:
                    files[name] = base64.b64decode(encoded)
                except ValueError:
                    self._json(400, {"error": f"file {name!r} is not valid base64"})
                    return
            for name, data in files.items():
                width = height = None
                if data.startswith(b"\x89PNG") and len(data) >= 24:
                    width, height = struct.unpack(">II", data[16:24])
                if width is None or width < 128 or height < 128:
                    self._json(
                        400,
                        {
                            "error": f"file {name!r} must be a PNG of at least 128x128 "
                            f"(got {width}x{height})"
                        },
                    )
                    return
            if category == "device":
                device_template = str(request.get("deviceTemplate") or "")
                if not device_template:
                    self._json(400, {"error": "deviceTemplate is required for device icons"})
                    return
                body, boundary = _build_icon_multipart(device_template, files)
            else:
                if set(files) != {"icon"}:
                    self._json(400, {"error": "room/scene uploads take exactly one file: icon"})
                    return
                extension = str(request.get("fileExtension") or "png")
                if not re.fullmatch(r"[A-Za-z0-9]+", extension):
                    self._json(400, {"error": f"bad fileExtension {extension!r}"})
                    return
                body, boundary = _build_single_icon_multipart(category, files["icon"], extension)
            try:
                status, response, _headers = http_call(
                    "POST",
                    f"{self.server.hc3_base}/api/icons",
                    {
                        "Authorization": self.server.hc3_auth,
                        "Content-Type": f"multipart/form-data; boundary={boundary}",
                    },
                    body,
                    binary=True,
                )
            except OSError as exc:
                self._json(502, {"error": f"cannot reach the HC3: {exc}"})
                return
            if status not in (200, 201):
                self._json(status, {"error": response.decode(errors="replace")})
                return
            self._json(201, {"result": response.decode(errors="replace")})
            return
        if parsed.path == "/api/delete":
            category = str(request.get("category") or "device")
            if category not in ("device", "room", "scene"):
                self._json(400, {"error": "category must be device, room or scene"})
                return
            query = urllib.parse.urlencode(
                {
                    "type": category,
                    "id": request.get("id"),
                    "name": request.get("name"),
                    "fileExtension": request.get("fileExtension"),
                }
            )
            try:
                status, response, _headers = http_call(
                    "DELETE",
                    f"{self.server.hc3_base}/api/icons?{query}",
                    {"Authorization": self.server.hc3_auth},
                    binary=True,
                )
            except OSError as exc:
                self._json(502, {"error": f"cannot reach the HC3: {exc}"})
                return
            if status != 200:
                self._json(status, {"error": response.decode(errors="replace")})
                return
            self._json(200, {"deleted": True})
            return
        self._json(404, {"error": "not found"})

    def log_message(self, *args: object) -> None:
        pass  # quiet — the tool's own output is enough


class IconsUiServer(http.server.ThreadingHTTPServer):
    def __init__(self, port: int, hc3_base: str, hc3_auth: str):
        self.hc3_base = hc3_base
        self.hc3_auth = hc3_auth
        self.page = _ICONS_UI_PAGE.read_bytes()
        super().__init__(("127.0.0.1", port), _IconsUiHandler)


def serve_icons_ui(port: int) -> IconsUiServer:
    base, auth = _ui_hc3()
    return IconsUiServer(port, base, auth)


def _run_icons_ui(args: argparse.Namespace) -> int:
    server = serve_icons_ui(args.port)
    _host, port = server.server_address[:2]
    print(f"HC3 icon manager: http://127.0.0.1:{port}/  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0
