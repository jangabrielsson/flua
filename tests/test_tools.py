"""The --tool registry: one module per tool, discovered automatically.

Adding a tool means adding a module to flua/tools/ exporting NAME, HELP,
add_arguments() and run() — no other file changes.
"""

import pytest

pytest.importorskip("lupa")

from flua import tools


def test_registry_discovers_all_tools() -> None:
    assert tools.tool_names() == ["downloadQA", "updateQA", "uploadQA"]
    for name in tools.tool_names():
        module = tools._TOOLS[name]
        assert module.NAME == name
        assert module.HELP
        assert callable(module.add_arguments)
        assert callable(module.run)


def test_unknown_tool_reports_and_exits_2(capsys) -> None:
    assert tools.run_tool("bogus", []) == 2
    err = capsys.readouterr().err
    assert "unknown tool 'bogus'" in err
    assert "downloadQA" in err  # the usage hint lists the known tools


def test_tool_listing(capsys) -> None:
    # "help", a bare name, and the flag spellings all list the installed tools
    for name in ("", "help", "list", "-h", "--help"):
        assert tools.run_tool(name, []) == 0
        out = capsys.readouterr().out
        for tool in tools.tool_names():
            assert tool in out
        assert "flua --tool <name> --help" in out


def test_sanitize_filename() -> None:
    from flua.engine import sanitize_filename

    assert sanitize_filename("My QA!") == "My_QA"
    assert sanitize_filename("compiler-qa.v2") == "compiler_qa_v2"
    assert sanitize_filename("  ") == "qa"  # nothing usable left -> "qa"
