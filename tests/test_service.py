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


import configparser


def _parse_unit(text: str) -> configparser.ConfigParser:
    # interpolation=None: WorkingDirectory=%h would break BasicInterpolation.
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # preserve ExecStart, not execstart
    parser.read_string(text)
    return parser


def _systemd(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return service.SystemdBackend(Path("/opt/pipx/bin/zlt"), "0.0.0.0", 8464)


def test_systemd_unit_is_valid_and_autostarts(tmp_path, monkeypatch):
    parser = _parse_unit(_systemd(tmp_path, monkeypatch).render())
    assert parser["Service"]["ExecStart"] == (
        "/opt/pipx/bin/zlt serve --host 0.0.0.0 --port 8464")
    assert parser["Service"]["Restart"] == "on-failure"
    assert parser["Service"]["RestartSec"] == "5"
    assert parser["Service"]["WorkingDirectory"] == "%h"
    assert parser["Service"]["NoNewPrivileges"] == "yes"
    assert parser["Install"]["WantedBy"] == "default.target"


def test_systemd_artifact_path_follows_xdg(tmp_path, monkeypatch):
    backend = _systemd(tmp_path, monkeypatch)
    assert backend.artifact_path() == tmp_path / "systemd" / "user" / "zlt-web.service"


def test_systemd_install_writes_unit_and_enables(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_run", lambda cmd, **kw: calls.append(cmd))
    backend = _systemd(tmp_path, monkeypatch)
    backend.install()
    assert backend.artifact_path().exists()
    assert ["systemctl", "--user", "daemon-reload"] in calls
    assert ["systemctl", "--user", "enable", "--now", "zlt-web"] in calls


def test_systemd_uninstall_removes_unit(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_run", lambda cmd, **kw: calls.append(cmd))
    backend = _systemd(tmp_path, monkeypatch)
    backend.install()
    backend.uninstall()
    assert not backend.artifact_path().exists()
    assert ["systemctl", "--user", "disable", "--now", "zlt-web"] in calls


def test_systemd_suspend_note_mentions_next_login(tmp_path, monkeypatch):
    assert "login" in _systemd(tmp_path, monkeypatch).suspend_note
