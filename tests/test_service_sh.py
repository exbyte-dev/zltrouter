import configparser
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVICE_SH = PROJECT_ROOT / "service.sh"


def _print_unit() -> str:
    # Invoke via `bash` so the test doesn't depend on the file's exec bit.
    result = subprocess.run(
        ["bash", str(SERVICE_SH), "print-unit"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _parse(unit_text: str) -> configparser.ConfigParser:
    # interpolation=None: systemd's WorkingDirectory=%h uses '%', which
    # ConfigParser's default BasicInterpolation would choke on.
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # preserve key case (ExecStart, not execstart)
    parser.read_string(unit_text)
    return parser


def test_print_unit_parses_as_systemd_unit():
    parser = _parse(_print_unit())
    assert parser.has_section("Unit")
    assert parser.has_section("Service")
    assert parser.has_section("Install")


def test_exec_start_uses_absolute_venv_zlt_with_locked_bind():
    parser = _parse(_print_unit())
    exec_start = parser["Service"]["ExecStart"]
    assert exec_start.startswith("/"), exec_start
    assert exec_start.endswith("/.venv/bin/zlt serve --host 0.0.0.0 --port 8464"), exec_start


def test_service_hardening_and_install_target():
    parser = _parse(_print_unit())
    assert parser["Service"]["WorkingDirectory"] == "%h"
    assert parser["Service"]["Restart"] == "on-failure"
    assert parser["Service"]["NoNewPrivileges"] == "yes"
    assert parser["Install"]["WantedBy"] == "default.target"
