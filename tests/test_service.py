import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

from zlt import service


def test_resolve_prefers_sibling_of_sys_executable(monkeypatch, tmp_path):
    binroot = tmp_path / "venv" / "bin"
    binroot.mkdir(parents=True)
    name = "zlt.exe" if sys.platform == "win32" else "zlt"
    (binroot / name).write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "executable", str(binroot / "python"))
    monkeypatch.setattr(service.shutil, "which", lambda _n: "/usr/bin/zlt")
    assert service.resolve_zlt_binary() == binroot / name


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
    # PurePosixPath, not Path: this backend only ever sees POSIX exec paths in
    # production, and str(Path("/opt/...")) turns into backslashes on a
    # Windows test runner, breaking the exact-string assertions below.
    return service.SystemdBackend(PurePosixPath("/opt/pipx/bin/zlt"), "0.0.0.0", 8464)


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


import plistlib


def _launchd(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    # PurePosixPath, not Path: same reasoning as _systemd() above.
    return service.LaunchdBackend(PurePosixPath("/opt/pipx/bin/zlt"), "0.0.0.0", 8464)


def test_launchd_plist_is_valid_and_autostarts(tmp_path, monkeypatch):
    backend = _launchd(tmp_path, monkeypatch)
    plist = plistlib.loads(backend.render().encode("utf-8"))
    assert plist["Label"] == "dev.zlt.web"
    assert plist["ProgramArguments"] == [
        "/opt/pipx/bin/zlt", "serve", "--host", "0.0.0.0", "--port", "8464"]
    assert plist["RunAtLoad"] is True
    # launchd's nearest equivalent of systemd's Restart=on-failure
    assert plist["KeepAlive"] == {"SuccessfulExit": False}
    assert plist["StandardOutPath"] == str(backend.log_path())
    assert plist["StandardErrorPath"] == str(backend.log_path())


def test_launchd_artifact_path(tmp_path, monkeypatch):
    backend = _launchd(tmp_path, monkeypatch)
    assert backend.artifact_path() == (
        tmp_path / "Library" / "LaunchAgents" / "dev.zlt.web.plist")


def test_launchd_install_bootstraps_into_gui_domain(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_run", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(service.os, "getuid", lambda: 501, raising=False)
    backend = _launchd(tmp_path, monkeypatch)
    backend.install()
    assert backend.artifact_path().exists()
    assert ["launchctl", "bootstrap", "gui/501",
            str(backend.artifact_path())] in calls


def test_launchd_suspend_note_says_it_stays_down(tmp_path, monkeypatch):
    # bootout unloads the agent, so unlike systemd it does NOT return at login
    note = _launchd(tmp_path, monkeypatch).suspend_note
    assert "resume" in note
    assert "login" not in note


def test_launchd_suspend_is_tolerant_of_already_stopped(tmp_path, monkeypatch):
    # bootout errors if the target isn't loaded; calling suspend() twice in a
    # row (or when already stopped) must not raise.
    calls = []
    monkeypatch.setattr(service, "_run", lambda cmd, **kw: calls.append((cmd, kw)))
    monkeypatch.setattr(service.os, "getuid", lambda: 501, raising=False)
    backend = _launchd(tmp_path, monkeypatch)
    backend.suspend()
    assert calls == [
        (["launchctl", "bootout", "gui/501/dev.zlt.web"], {"check": False})]


def test_launchd_resume_is_tolerant_of_already_running(tmp_path, monkeypatch):
    # bootstrap errors if the label is already loaded; calling resume() right
    # after install(), or twice in a row, must not raise.
    calls = []
    monkeypatch.setattr(service, "_run", lambda cmd, **kw: calls.append((cmd, kw)))
    monkeypatch.setattr(service.os, "getuid", lambda: 501, raising=False)
    backend = _launchd(tmp_path, monkeypatch)
    backend.resume()
    assert calls == [
        (["launchctl", "bootstrap", "gui/501", str(backend.artifact_path())],
         {"check": False})]


import xml.etree.ElementTree as ET

TASK_NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def _schtasks(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return service.SchtasksBackend(Path(r"C:\pipx\bin\zlt.exe"), "0.0.0.0", 8464)


def test_schtasks_xml_is_valid_and_triggers_on_logon(tmp_path, monkeypatch):
    backend = _schtasks(tmp_path, monkeypatch)
    # The declaration says UTF-16, so encode to match before parsing.
    root = ET.fromstring(backend.render().encode("utf-16"))
    assert root.find(".//t:LogonTrigger/t:Enabled", TASK_NS).text == "true"
    assert root.find(".//t:Exec/t:Command", TASK_NS).text == r"C:\pipx\bin\zlt.exe"
    args = root.find(".//t:Exec/t:Arguments", TASK_NS).text
    assert args.startswith("serve --host 0.0.0.0 --port 8464 --log-file ")
    assert root.find(".//t:RestartOnFailure/t:Count", TASK_NS).text == "3"
    assert root.find(".//t:Settings/t:Hidden", TASK_NS).text == "true"


def test_schtasks_render_escapes_xml_entities(tmp_path, monkeypatch):
    # A path or description containing '&' or '<' (e.g. a Windows username
    # with an ampersand) must not break the generated XML.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(service, "DESCRIPTION", "zlt dashboard <local> & friends")
    backend = service.SchtasksBackend(
        Path(r"C:\Users\Bob & Alice\bin\zlt.exe"), "0.0.0.0", 8464)
    xml_text = backend.render()
    # This is the concrete failure mode being fixed: unescaped '&'/'<' would
    # make this raise instead of parsing cleanly.
    root = ET.fromstring(xml_text.encode("utf-16"))
    assert root.find(".//t:Exec/t:Command", TASK_NS).text == r"C:\Users\Bob & Alice\bin\zlt.exe"
    assert root.find(".//t:RegistrationInfo/t:Description", TASK_NS).text == (
        "zlt dashboard <local> & friends")


def test_schtasks_install_registers_task(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_run", lambda cmd, **kw: calls.append(cmd))
    backend = _schtasks(tmp_path, monkeypatch)
    backend.install()
    assert backend.artifact_path().exists()
    assert ["schtasks", "/create", "/tn", "zlt-web",
            "/xml", str(backend.artifact_path()), "/f"] in calls


def test_schtasks_xml_written_as_utf16(tmp_path, monkeypatch):
    # schtasks /xml rejects a file whose encoding disagrees with its declaration
    monkeypatch.setattr(service, "_run", lambda cmd, **kw: None)
    backend = _schtasks(tmp_path, monkeypatch)
    backend.install()
    raw = backend.artifact_path().read_bytes()
    assert raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff")


def test_schtasks_suspend_disables_task(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_run", lambda cmd, **kw: calls.append(cmd))
    _schtasks(tmp_path, monkeypatch).suspend()
    assert ["schtasks", "/change", "/tn", "zlt-web", "/disable"] in calls
