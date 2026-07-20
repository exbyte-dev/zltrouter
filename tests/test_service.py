import subprocess
import sys
from pathlib import Path

import pytest

from zlt import service


def test_resolve_prefers_sibling_of_sys_executable(monkeypatch, tmp_path):
    binroot = tmp_path / "venv" / "bin"
    binroot.mkdir(parents=True)
    (binroot / "zlt").write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "executable", str(binroot / "python"))
    monkeypatch.setattr(service.shutil, "which", lambda _n: "/usr/bin/zlt")
    assert service.resolve_zlt_binary() == binroot / "zlt"


def test_resolve_falls_back_to_path(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "executable", str(tmp_path / "nowhere" / "python"))
    monkeypatch.setattr(service.shutil, "which", lambda _n: "/usr/bin/zlt")
    assert service.resolve_zlt_binary() == Path("/usr/bin/zlt")


def test_resolve_raises_clear_error_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "executable", str(tmp_path / "nowhere" / "python"))
    monkeypatch.setattr(service.shutil, "which", lambda _n: None)
    with pytest.raises(service.ServiceError) as exc:
        service.resolve_zlt_binary()
    assert "pipx install zlt" in str(exc.value)


@pytest.mark.parametrize("platform,expected", [
    ("linux", "SystemdBackend"),
    ("darwin", "LaunchdBackend"),
    ("win32", "SchtasksBackend"),
])
def test_detect_backend_dispatches_on_platform(monkeypatch, platform, expected):
    monkeypatch.setattr(sys, "platform", platform)
    backend = service.detect_backend(exec_path=Path("/opt/zlt"))
    assert type(backend).__name__ == expected


def test_detect_backend_rejects_unknown_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "sunos5")
    with pytest.raises(service.ServiceError) as exc:
        service.detect_backend(exec_path=Path("/opt/zlt"))
    assert "sunos5" in str(exc.value)


def test_run_raises_service_error_on_missing_command(monkeypatch):
    def boom(*_a, **_k):
        raise FileNotFoundError("no such tool")
    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(service.ServiceError):
        service._run(["definitely-not-a-real-command"])
