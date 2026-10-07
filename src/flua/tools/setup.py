"""setup: scaffold a QA project — .vscode configs and agent files.

pip users don't get the repo's developer experience (VS Code run/debug
configs, Copilot skills/instructions, AGENTS.md). This tool writes those
files from templates that ship inside the flua package, into a QA project
directory. Idempotent: existing files are kept unless --force. (The UI
viewer is NOT copied — ``flua --ui`` serves it from the package.)
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

NAME = "setup"
HELP = "scaffold a QA project: .vscode configs + agent files"

# template path (inside the package) -> target path (relative to the project)
_TEMPLATES = {
    "vscode/launch.json": ".vscode/launch.json",
    "vscode/tasks.json": ".vscode/tasks.json",
    "vscode/extensions.json": ".vscode/extensions.json",
    "luals": ".luals",
    ".luarc.json": ".luarc.json",
    "AGENTS.md": "AGENTS.md",
    "github/copilot-instructions.md": ".github/copilot-instructions.md",
    "github/instructions/quickapp-dev.instructions.md": (
        ".github/instructions/quickapp-dev.instructions.md"
    ),
    "github/prompts/install-qa-skills.prompt.md": (
        ".github/prompts/install-qa-skills.prompt.md"
    ),
    "github/skills": ".github/skills",
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
    written, skipped = [], []
    for template, target in _TEMPLATES.items():
        src = _templates_dir() / template
        dst = root / target
        if dst.exists():
            if not args.force:
                skipped.append(target)
                continue
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        if target == ".vscode/launch.json":
            # resolve `flua` to its absolute path so VS Code (which doesn't
            # inherit the shell's PATH on macOS) can launch it
            text = dst.read_text(encoding="utf-8")
            dst.write_text(
                text.replace(
                    '"interpreter": "flua"',
                    f'"interpreter": {json.dumps(_flua_interpreter())}',
                ),
                encoding="utf-8",
            )
        if target == ".vscode/tasks.json":
            # same PATH story as launch.json: the task runs flua directly
            text = dst.read_text(encoding="utf-8")
            dst.write_text(
                text.replace(
                    '"command": "flua"',
                    f'"command": {json.dumps(_flua_interpreter())}',
                ),
                encoding="utf-8",
            )
        written.append(target)
    for name in sorted(written):
        print(f"  wrote {name}")
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
