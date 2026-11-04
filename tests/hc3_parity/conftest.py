"""Parity-replay pytest options (module-level pytest_addoption does not
survive pytest-xdist's controller/worker split — hooks live here)."""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--parity-fw", help="replay one fixture dir (default: the newest)")
