import sys

from click.testing import CliRunner

from zlt.cli import cli


def test_init_config_writes_file(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    result = CliRunner().invoke(cli, ["init-config"], input="s3cret\n")
    assert result.exit_code == 0
    written = (tmp_path / "zlt" / "config").read_text()
    assert "ZLT_PASSWORD=s3cret" in written
    assert "ZLT_HOST=http://192.168.0.1" in written
    if sys.platform != "win32":
        # NTFS has no POSIX permission bits; os.open's mode argument is
        # effectively ignored on Windows, so this assertion doesn't apply.
        import stat
        mode = (tmp_path / "zlt" / "config").stat().st_mode
        assert stat.S_IMODE(mode) == 0o600


import pytest

from zlt import cli as cli_mod
from zlt import service


@pytest.fixture
def installed(monkeypatch):
    """Capture whether the service would have been installed."""
    calls = []

    class FakeBackend:
        # detect_backend() in init_config is called with no args, so a real
        # backend would default to DEFAULT_BIND ("0.0.0.0") here too.
        host = "0.0.0.0"

        def install(self):
            calls.append("install")

        def artifact_path(self):
            from pathlib import Path
            return Path("/tmp/zlt-web.service")

    monkeypatch.setattr(service, "detect_backend", lambda **kw: FakeBackend())
    monkeypatch.setattr(cli_mod, "_stdin_is_tty", lambda: True)
    return calls


def test_prompt_defaults_to_yes_on_bare_enter(monkeypatch, tmp_path, installed):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    result = CliRunner().invoke(cli, ["init-config"], input="s3cret\n\n")
    assert result.exit_code == 0
    assert installed == ["install"]


def test_install_success_discloses_lan_and_no_auth(monkeypatch, tmp_path, installed):
    # detect_backend() defaults to host 0.0.0.0 here, so the success message
    # must not just say 127.0.0.1; it must disclose LAN reachability and the
    # lack of any login, since a user hitting Enter through the defaults
    # never typed a --host flag to warn them.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    result = CliRunner().invoke(cli, ["init-config"], input="s3cret\n\n")
    assert result.exit_code == 0
    assert "127.0.0.1" in result.output
    assert "LAN" in result.output
    assert "no auth" in result.output


def test_prompt_declined_leaves_service_alone(monkeypatch, tmp_path, installed):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    result = CliRunner().invoke(cli, ["init-config"], input="s3cret\nn\n")
    assert result.exit_code == 0
    assert installed == []
    assert "zlt service install" in result.output  # tell them how to do it later


def test_no_service_flag_skips_prompt(monkeypatch, tmp_path, installed):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    result = CliRunner().invoke(cli, ["init-config", "--no-service"], input="s3cret\n")
    assert result.exit_code == 0
    assert installed == []


def test_non_tty_never_prompts(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(cli_mod, "_stdin_is_tty", lambda: False)
    called = []
    monkeypatch.setattr(service, "detect_backend",
                        lambda **kw: called.append("detect"))
    result = CliRunner().invoke(cli, ["init-config"], input="s3cret\n")
    assert result.exit_code == 0
    assert called == []
    assert (tmp_path / "zlt" / "config").exists()


def test_unsupported_platform_skips_prompt_with_note(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(cli_mod, "_stdin_is_tty", lambda: True)

    def boom(**_kw):
        raise service.ServiceError("no autostart backend for platform 'sunos5'")

    monkeypatch.setattr(service, "detect_backend", boom)
    result = CliRunner().invoke(cli, ["init-config"], input="s3cret\n")
    assert result.exit_code == 0          # config still written, no crash
    assert "sunos5" in result.output
