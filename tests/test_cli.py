"""Smoke tests for the planning-status CLI."""

import socket
from typing import NoReturn

import pytest
from typer.testing import CliRunner

from side_effects_lab.cli import BOOTSTRAP_STATUS, app


def _network_forbidden(*args: object, **kwargs: object) -> NoReturn:
    raise AssertionError("the bootstrap CLI attempted network access")


def test_cli_reports_bootstrap_status_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "socket", _network_forbidden)
    monkeypatch.setattr(socket, "create_connection", _network_forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", _network_forbidden)

    result = CliRunner().invoke(app)

    assert result.exit_code == 0
    assert result.output == f"{BOOTSTRAP_STATUS}\n"
