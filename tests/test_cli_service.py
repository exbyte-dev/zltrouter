from pathlib import Path

import pytest
from click.testing import CliRunner

from zlt import service
from zlt.cli import cli


class FakeBackend:
    """Stands in for a real backend so no OS call is ever made."""

    def __init__(self):
        self.calls = []

    def artifact_path(self):
        return Path("/tmp/zlt-web.service")

    def render(self):
        return "[Unit]\nDescription=fake\n"

    suspend_note = "stopped; it comes back at your next login"

    def __getattr__(self, name):
        if name in {"install", "uninstall", "suspend", "resume", "status", "logs"}:
            return lambda: self.calls.append(name)
        raise AttributeError(name)


@pytest.fixture
def fake(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(service, "detect_backend", lambda **kw: backend)
    return backend


@pytest.mark.parametrize("verb", ["install", "uninstall", "suspend", "resume", "status", "logs"])
def test_service_verbs_delegate_to_backend(fake, verb):
    result = CliRunner().invoke(cli, ["service", verb])
    assert result.exit_code == 0, result.output
    assert fake.calls == [verb]


def test_print_artifact_writes_nothing_and_prints_unit(fake):
    result = CliRunner().invoke(cli, ["service", "print-artifact"])
    assert result.exit_code == 0
    assert "Description=fake" in result.output
    assert fake.calls == []


def test_suspend_prints_platform_specific_note(fake):
    result = CliRunner().invoke(cli, ["service", "suspend"])
    assert "next login" in result.output


def test_service_error_becomes_clean_click_error(monkeypatch):
    def boom(**_kw):
        raise service.ServiceError("no autostart backend for platform 'sunos5'")
    monkeypatch.setattr(service, "detect_backend", boom)
    result = CliRunner().invoke(cli, ["service", "install"])
    assert result.exit_code != 0
    assert "sunos5" in result.output
    assert "Traceback" not in result.output
