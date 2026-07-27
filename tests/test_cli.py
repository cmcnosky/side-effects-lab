"""Smoke tests for the implementation-status CLI."""

import socket
from typing import NoReturn

import pytest
from typer.testing import CliRunner

from side_effects_lab.cli import IMPLEMENTATION_STATUS, app


def _network_forbidden(*args: object, **kwargs: object) -> NoReturn:
    raise AssertionError("the status CLI attempted network access")


def test_cli_reports_implementation_status_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "socket", _network_forbidden)
    monkeypatch.setattr(socket, "create_connection", _network_forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", _network_forbidden)

    result = CliRunner().invoke(app)

    assert result.exit_code == 0
    assert result.output == f"{IMPLEMENTATION_STATUS}\n"
