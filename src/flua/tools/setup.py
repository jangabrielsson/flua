"""setup: scaffold a QA project — .vscode configs and agent files.

pip users don't get the repo's developer experience (VS Code run/debug
configs, Copilot skills/instructions, AGENTS.md). This tool writes those
files from templates that ship inside the flua package, into a QA project
directory. (The UI viewer is NOT copied — ``flua --ui`` serves it from the
package.)

Files are classified, so re-running after a flua upgrade updates what it
should and never clobbers what it shouldn't:

- ``refresh``  — vendor-owned content (the skills, instructions, LuaLS type
  stubs): always overwritten, like ``pip install --upgrade``.
- ``managed``  — vendor content the user may edit (AGENTS.md): overwritten
  while byte-identical to the shipped template, kept once locally modified
  (with a notice).
- ``if-absent`` — user-owned files (.vscode configs): never overwritten.

``--force`` overrides everything.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

NAME = "setup"
HELP = "scaffold a QA project: .vscode configs + agent files (per-file policies; -f overrides)"

# template path (inside the package) -> (target path, update policy)
_TEMPLATES = {
    "vscode/launch.json": (".vscode/launch.json", "if-absent"),
    "vscode/tasks.json": (".vscode/tasks.json", "if-absent"),
    "vscode/extensions.json": (".vscode/extensions.json", "if-absent"),
    "luals": (".luals", "refresh"),
    ".luarc.json": (".luarc.json", "refresh"),
    "AGENTS.md": ("AGENTS.md", "managed"),
    "github/copilot-instructions.md": (".github/copilot-instructions.md", "refresh"),
    "github/instructions/quickapp-dev.instructions.md": (
        ".github/instructions/quickapp-dev.instructions.md",
        "refresh",
    ),
    "github/prompts/install-qa-skills.prompt.md": (
        ".github/prompts/install-qa-skills.prompt.md",
        "if-absent",
    ),
    "github/skills": (".github/skills", "refresh"),
}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="the QA project directory to scaffold (default: the current directory)",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="overwrite existing files",
    )


def _templates_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "setup_templates"


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def _post_process(target: str, dst: Path) -> None:
    """Absolute-path substitution for the files VS Code runs (macOS GUI apps
    don't inherit the shell's PATH, so a bare `flua` is not found there)."""
    if target == ".vscode/launch.json":
        text = dst.read_text(encoding="utf-8")
        dst.write_text(
            text.replace(
                '"interpreter": "flua"',
                f'"interpreter": {json.dumps(_flua_interpreter())}',
            ),
            encoding="utf-8",
        )
    if target == ".vscode/tasks.json":
        text = dst.read_text(encoding="utf-8")
        dst.write_text(
            text.replace(
                '"command": "flua"',
                f'"command": {json.dumps(_flua_interpreter())}',
            ),
            encoding="utf-8",
        )


def _flua_interpreter() -> str:
    """The interpreter path for launch.json.

    pip user installs and venvs live outside the PATH that macOS GUI apps
    (VS Code launched from the Dock) inherit — a bare ``flua`` is not found
    there. Resolve the absolute path from the shell environment setup runs
    in; fall back to the bare name with a warning when flua is not on PATH.
    """
    resolved = shutil.which("flua")
    if resolved is None:
        print(
            "warning: flua not found on PATH — launch.json will use `flua`; "
            "launch VS Code from a terminal once, or edit the interpreter path"
        )
        return "flua"
    return resolved


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    root = Path(args.directory)
    root.mkdir(parents=True, exist_ok=True)
    # validate the package up front: a missing template (wheel packaging
    # gap) should be a clear error, not a half-scaffolded project + traceback
    missing = [
        template
        for template in _TEMPLATES
        if not (_templates_dir() / template).exists()
    ]
    if missing:
        parser.error(
            "missing packaged templates: "
            + ", ".join(missing)
            + " — reinstall fibaro-flua (or run from the source tree)"
        )
    written, updated, skipped, kept_modified = [], [], [], []
    for template, (target, policy) in _TEMPLATES.items():
        src = _templates_dir() / template
        dst = root / target
        if dst.exists():
            if policy == "if-absent" and not args.force:
                skipped.append(target)
                continue
            if policy == "managed" and not args.force:
                # vendor content until the user edits it: refresh while it
                # matches the shipped template byte for byte, keep + report
                # once modified (never clobber a local edit)
                try:
                    same = dst.is_file() and dst.read_bytes() == src.read_bytes()
                except OSError:
                    same = False
                if not same:
                    kept_modified.append(target)
                    continue
                if dst.is_dir():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
                _copy(src, dst)
                updated.append(target)
                _post_process(target, dst)
                continue
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
            if policy == "refresh":
                updated.append(target)
            else:
                written.append(target)
        else:
            written.append(target)
        dst.parent.mkdir(parents=True, exist_ok=True)
        _copy(src, dst)
        _post_process(target, dst)
    for name in sorted(written):
        print(f"  wrote {name}")
    for name in sorted(updated):
        print(f"  updated {name} (flua content)")
    for name in sorted(kept_modified):
        print(f"  kept {name} (locally modified — flua's template may have changes)")
    for name in sorted(skipped):
        print(f"  kept {name} (exists — pass --force to overwrite)")
    print(
        "done — VS Code will suggest the Python and Lua MobDebug extensions "
        "on the next open; agents pick up AGENTS.md and the .github files; "
        "`flua --ui` serves the UI viewer at http://127.0.0.1:PORT/ (no file "
        "to open)"
    )
    # clickable in the VS Code terminal and most shells (cmd/ctrl-click)
    print("Read on:")
    print("  USAGE.md   https://github.com/jangabrielsson/flua/blob/main/USAGE.md")
    print("  Tutorial   https://github.com/jangabrielsson/flua/tree/main/docs/tutorial")
    return 0
