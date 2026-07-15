from click.testing import CliRunner

from zlt.cli import cli


def test_init_config_writes_file(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    result = CliRunner().invoke(cli, ["init-config"], input="s3cret\n")
    assert result.exit_code == 0
    written = (tmp_path / "zlt" / "config").read_text()
    assert "ZLT_PASSWORD=s3cret" in written
    assert "ZLT_HOST=http://192.168.0.1" in written
    # secret file perms
    import stat
    mode = (tmp_path / "zlt" / "config").stat().st_mode
    assert stat.S_IMODE(mode) == 0o600
