from click.testing import CliRunner

from zlt import __version__
from zlt.cli import cli


def test_cli_version():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_serve_log_file_redirects_and_restores(tmp_path, monkeypatch):
    import sys
    from click.testing import CliRunner
    from zlt.cli import cli

    monkeypatch.setattr("uvicorn.run", lambda *a, **k: print("served"))
    log = tmp_path / "nested" / "zlt-web.log"
    before_out, before_err = sys.stdout, sys.stderr

    result = CliRunner().invoke(cli, ["serve", "--log-file", str(log)])

    assert result.exit_code == 0
    assert log.exists()
    assert "served" in log.read_text()
    # a leaked redirect would poison every later test in the session
    assert sys.stdout is before_out
    assert sys.stderr is before_err
