"""setup: scaffold a QA project — .vscode configs and the agent files.

pip users don't get the repo's developer experience (VS Code run/debug
configs, Copilot skills/instructions, AGENTS.md). This tool writes those
files from templates that ship inside the flua package, into a QA project
directory. Idempotent: existing files are kept unless --force.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

NAME = "setup"
HELP = "scaffold a QA project: .vscode configs + agent skills and instructions"

# template path (inside the package) -> target path (relative to the project)
_TEMPLATES = {
    "vscode/launch.json": ".vscode/launch.json",
    "vscode/extensions.json": ".vscode/extensions.json",
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


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    root = Path(args.directory)
    root.mkdir(parents=True, exist_ok=True)
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
        written.append(target)
    for name in sorted(written):
        print(f"  wrote {name}")
    for name in sorted(skipped):
        print(f"  kept {name} (exists — pass --force to overwrite)")
    print(
        "done — VS Code will suggest the Python and Lua MobDebug extensions "
        "on the next open; agents pick up AGENTS.md and the .github files"
    )
    return 0
