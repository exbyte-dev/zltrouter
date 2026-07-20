"""Cross-platform autostart management for the zlt web dashboard.

Replaces the old install.sh/service.sh pair. Bash does not run on Windows, so
this lives in Python where one implementation can serve all three platforms.

The module is deliberately split in two. Artifact generation (render() and
artifact_path()) is pure, so the macOS and Windows artifacts can be asserted on
from a Linux machine. Everything that touches the host goes through _run(), so
tests have a single seam to monkeypatch and never mutate real system state.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path

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

    def __init__(self, exec_path: Path, host: str, port: int) -> None:
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
    exec_path: Path | None = None,
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
    def artifact_path(self) -> Path: raise NotImplementedError
    def render(self) -> str: raise NotImplementedError
    @property
    def suspend_note(self) -> str: raise NotImplementedError
    def install(self) -> None: raise NotImplementedError
    def uninstall(self) -> None: raise NotImplementedError
    def suspend(self) -> None: raise NotImplementedError
    def resume(self) -> None: raise NotImplementedError
    def status(self) -> None: raise NotImplementedError
    def logs(self) -> None: raise NotImplementedError


class LaunchdBackend(SystemdBackend):
    pass


class SchtasksBackend(SystemdBackend):
    pass
