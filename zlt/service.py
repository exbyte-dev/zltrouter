"""Cross-platform autostart management for the zlt web dashboard.

Replaces the old shell-script installer and service manager. Bash does not run
on Windows, so this lives in Python where one implementation can serve all
three platforms.

The module is deliberately split in two. Artifact generation (render() and
artifact_path()) is pure, so the macOS and Windows artifacts can be asserted on
from a Linux machine. Everything that touches the host goes through _run(), so
tests have a single seam to monkeypatch and never mutate real system state.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path, PurePath
from xml.sax.saxutils import escape

from zlt.config import config_home

SERVICE_NAME = "zlt-web"
LAUNCHD_LABEL = "dev.zlt.web"
DESCRIPTION = "zlt router dashboard (local web UI)"
DEFAULT_BIND = "0.0.0.0"
DEFAULT_PORT = 8464


class ServiceError(Exception):
    """Autostart setup failed in a way worth showing the user verbatim."""


def resolve_zlt_binary() -> Path:
    """Absolute path to the installed 'zlt' console script.

    Prefers the sibling of sys.executable, which inside a pipx venv is exact,
    before falling back to a PATH lookup. Baking an absolute path into the
    generated artifact avoids relying on the service manager's PATH at login.
    """
    name = "zlt.exe" if sys.platform == "win32" else "zlt"
    sibling = Path(sys.executable).parent / name
    if sibling.exists():
        return sibling
    found = shutil.which("zlt")
    if found:
        return Path(found)
    raise ServiceError(
        f"could not find the 'zlt' executable (looked at {sibling} and on PATH).\n"
        "Reinstall with:  pipx install zlt"
    )


def _run(cmd: list[str], *, check: bool = True, capture: bool = False):
    """Single choke point for every OS call. Tests monkeypatch this."""
    try:
        return subprocess.run(cmd, check=check, text=True, capture_output=capture)
    except FileNotFoundError as exc:
        raise ServiceError(f"{cmd[0]} not found on this system: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip() or f"exit status {exc.returncode}"
        raise ServiceError(f"{' '.join(cmd)} failed: {detail}") from exc


def _tail(path: Path) -> None:
    """Follow a log file, for the backends with no journal of their own."""
    if not path.exists():
        raise ServiceError(f"no log file yet at {path}; is the service running?")
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(0, 2)
        while True:
            line = handle.readline()
            if line:
                print(line, end="")
            else:
                time.sleep(0.4)


class Backend(ABC):
    """One autostart mechanism. Subclasses are per-platform."""

    def __init__(self, exec_path: PurePath, host: str, port: int) -> None:
        # PurePath, not Path: exec_path is only ever stringified (render()),
        # never touched on disk, so a pure path (e.g. PurePosixPath in tests)
        # is a valid value regardless of which OS is actually running.
        self.exec_path = exec_path
        self.host = host
        self.port = port

    @abstractmethod
    def artifact_path(self) -> Path:
        """Where the generated unit/plist/task XML is written."""

    @abstractmethod
    def render(self) -> str:
        """The artifact text. Pure: no filesystem or subprocess access."""

    @property
    @abstractmethod
    def suspend_note(self) -> str:
        """What 'suspend' actually means here. Platforms differ; say so."""

    @abstractmethod
    def install(self) -> None: ...

    @abstractmethod
    def uninstall(self) -> None: ...

    @abstractmethod
    def suspend(self) -> None: ...

    @abstractmethod
    def resume(self) -> None: ...

    @abstractmethod
    def status(self) -> None: ...

    @abstractmethod
    def logs(self) -> None: ...

    def _write_artifact(self) -> Path:
        path = self.artifact_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(), encoding="utf-8")
        return path


def detect_backend(
    exec_path: PurePath | None = None,
    host: str = DEFAULT_BIND,
    port: int = DEFAULT_PORT,
) -> Backend:
    """Pick the autostart backend for the running platform."""
    resolved = exec_path if exec_path is not None else resolve_zlt_binary()
    if sys.platform.startswith("linux"):
        return SystemdBackend(resolved, host, port)
    if sys.platform == "darwin":
        return LaunchdBackend(resolved, host, port)
    if sys.platform == "win32":
        return SchtasksBackend(resolved, host, port)
    raise ServiceError(
        f"no autostart backend for platform {sys.platform!r}.\n"
        f"Run the dashboard manually instead:  zlt serve --host {host} --port {port}"
    )


class SystemdBackend(Backend):
    """Linux. systemd --user unit, started on login, no lingering."""

    def artifact_path(self) -> Path:
        return config_home() / "systemd" / "user" / f"{SERVICE_NAME}.service"

    def render(self) -> str:
        # %h is a systemd specifier and must stay literal in the output.
        return (
            "[Unit]\n"
            f"Description={DESCRIPTION}\n"
            "\n"
            "[Service]\n"
            f"ExecStart={self.exec_path} serve --host {self.host} --port {self.port}\n"
            "WorkingDirectory=%h\n"
            "Restart=on-failure\n"
            "RestartSec=5\n"
            "NoNewPrivileges=yes\n"
            "\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )

    @property
    def suspend_note(self) -> str:
        return "stopped; it comes back on 'resume' or at your next login"

    def install(self) -> None:
        self._write_artifact()
        _run(["systemctl", "--user", "daemon-reload"])
        _run(["systemctl", "--user", "enable", "--now", SERVICE_NAME])

    def uninstall(self) -> None:
        _run(["systemctl", "--user", "disable", "--now", SERVICE_NAME], check=False)
        self.artifact_path().unlink(missing_ok=True)
        _run(["systemctl", "--user", "daemon-reload"], check=False)

    def suspend(self) -> None:
        _run(["systemctl", "--user", "stop", SERVICE_NAME])

    def resume(self) -> None:
        _run(["systemctl", "--user", "start", SERVICE_NAME])

    def status(self) -> None:
        _run(["systemctl", "--user", "status", SERVICE_NAME, "--no-pager"], check=False)

    def logs(self) -> None:
        _run(["journalctl", "--user", "-u", SERVICE_NAME, "-f"], check=False)


class LaunchdBackend(Backend):
    """macOS. LaunchAgent in the user's gui domain, loaded at login."""

    def artifact_path(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"

    def log_path(self) -> Path:
        # launchd has no journal, so redirect both streams to a file.
        return Path.home() / "Library" / "Logs" / f"{SERVICE_NAME}.log"

    def _domain(self) -> str:
        return f"gui/{os.getuid()}"

    def _target(self) -> str:
        return f"{self._domain()}/{LAUNCHD_LABEL}"

    def render(self) -> str:
        plist = {
            "Label": LAUNCHD_LABEL,
            "ProgramArguments": [
                str(self.exec_path), "serve",
                "--host", self.host,
                "--port", str(self.port),
            ],
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},
            "StandardOutPath": str(self.log_path()),
            "StandardErrorPath": str(self.log_path()),
            "ProcessType": "Background",
        }
        return plistlib.dumps(plist).decode("utf-8")

    @property
    def suspend_note(self) -> str:
        return "unloaded; it stays down until you run 'zlt service resume'"

    def install(self) -> None:
        self.log_path().parent.mkdir(parents=True, exist_ok=True)
        path = self._write_artifact()
        # Tolerate a previous load so install is repeatable.
        _run(["launchctl", "bootout", self._target()], check=False)
        _run(["launchctl", "bootstrap", self._domain(), str(path)])

    def uninstall(self) -> None:
        _run(["launchctl", "bootout", self._target()], check=False)
        self.artifact_path().unlink(missing_ok=True)

    def suspend(self) -> None:
        # Tolerate an already-stopped agent so suspend is repeatable.
        _run(["launchctl", "bootout", self._target()], check=False)

    def resume(self) -> None:
        # Tolerate an already-running agent so resume is repeatable.
        _run(["launchctl", "bootstrap", self._domain(), str(self.artifact_path())],
             check=False)

    def status(self) -> None:
        _run(["launchctl", "print", self._target()], check=False)

    def logs(self) -> None:
        _tail(self.log_path())


class SchtasksBackend(Backend):
    """Windows. Task Scheduler on-logon task, registered from an XML file."""

    def _state_dir(self) -> Path:
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / "zlt"

    def artifact_path(self) -> Path:
        return self._state_dir() / f"{SERVICE_NAME}.xml"

    def log_path(self) -> Path:
        # Task Scheduler captures nothing, so serve --log-file does the work.
        return self._state_dir() / f"{SERVICE_NAME}.log"

    def render(self) -> str:
        raw_args = (f"serve --host {self.host} --port {self.port} "
                    f"--log-file {self.log_path()}")
        description = escape(DESCRIPTION)
        command = escape(str(self.exec_path))
        args = escape(raw_args)
        return (
            '<?xml version="1.0" encoding="UTF-16"?>\n'
            '<Task version="1.2" '
            'xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
            "  <RegistrationInfo>\n"
            f"    <Description>{description}</Description>\n"
            "  </RegistrationInfo>\n"
            "  <Triggers>\n"
            "    <LogonTrigger>\n"
            "      <Enabled>true</Enabled>\n"
            "    </LogonTrigger>\n"
            "  </Triggers>\n"
            "  <Principals>\n"
            '    <Principal id="Author">\n'
            "      <LogonType>InteractiveToken</LogonType>\n"
            "      <RunLevel>LeastPrivilege</RunLevel>\n"
            "    </Principal>\n"
            "  </Principals>\n"
            "  <Settings>\n"
            "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
            "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
            "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
            "    <StartWhenAvailable>true</StartWhenAvailable>\n"
            "    <Hidden>true</Hidden>\n"
            "    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n"
            "    <RestartOnFailure>\n"
            "      <Interval>PT1M</Interval>\n"
            "      <Count>3</Count>\n"
            "    </RestartOnFailure>\n"
            "  </Settings>\n"
            '  <Actions Context="Author">\n'
            "    <Exec>\n"
            f"      <Command>{command}</Command>\n"
            f"      <Arguments>{args}</Arguments>\n"
            "    </Exec>\n"
            "  </Actions>\n"
            "</Task>\n"
        )

    @property
    def suspend_note(self) -> str:
        return "disabled; it comes back on 'resume'"

    def _write_artifact(self) -> Path:
        # Override: schtasks /xml rejects a file whose bytes disagree with the
        # UTF-16 declaration in render(), so this one is not written as UTF-8.
        path = self.artifact_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(), encoding="utf-16")
        return path

    def install(self) -> None:
        path = self._write_artifact()
        _run(["schtasks", "/create", "/tn", SERVICE_NAME,
              "/xml", str(path), "/f"])
        _run(["schtasks", "/run", "/tn", SERVICE_NAME], check=False)

    def uninstall(self) -> None:
        _run(["schtasks", "/end", "/tn", SERVICE_NAME], check=False)
        _run(["schtasks", "/delete", "/tn", SERVICE_NAME, "/f"], check=False)
        self.artifact_path().unlink(missing_ok=True)

    def suspend(self) -> None:
        _run(["schtasks", "/end", "/tn", SERVICE_NAME], check=False)
        _run(["schtasks", "/change", "/tn", SERVICE_NAME, "/disable"])

    def resume(self) -> None:
        _run(["schtasks", "/change", "/tn", SERVICE_NAME, "/enable"])
        _run(["schtasks", "/run", "/tn", SERVICE_NAME], check=False)

    def status(self) -> None:
        _run(["schtasks", "/query", "/tn", SERVICE_NAME, "/v", "/fo", "list"],
             check=False)

    def logs(self) -> None:
        _tail(self.log_path())
