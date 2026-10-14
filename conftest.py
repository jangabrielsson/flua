"""Root conftest: the --serial escape hatch for the -n auto default.

xdist resolves ``-n auto`` (addopts in pyproject.toml) in its
``pytest_cmdline_main`` hook. The root conftest is loaded as an *initial*
conftest before that hook fires, so a ``tryfirst`` implementation here can
pin ``numprocesses`` to 0 first and hand the run back to plain serial
pytest. (tests/conftest.py would be too late — it loads at collection time.)

Use ``pytest --serial ...`` when parallel output interleaves badly
(debugging with -s, order-sensitive experiments): the same tests run, one
process, no workers. Plain ``-n 0`` works too.
"""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--serial",
        action="store_true",
        default=False,
        help="run tests in a single process, overriding the -n auto default",
    )


@pytest.hookimpl(tryfirst=True)
def pytest_cmdline_main(config: pytest.Config) -> int | None:
    if config.getoption("--serial", default=False):
        config.option.numprocesses = 0
    return None
