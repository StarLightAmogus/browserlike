from __future__ import annotations

from typing import Any

import pytest

from .helpers import load_fixture


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--run-network", action="store_true", help="run tests that talk to tls.peet.ws")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-network"):
        return
    skip = pytest.mark.skip(reason="needs --run-network")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def chrome156_reference() -> dict[str, Any]:
    """Real Chrome 156 on Windows, ru-RU, opening https://tls.peet.ws/api/all."""
    return load_fixture("chrome-156-windows.json")
