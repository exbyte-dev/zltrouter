from click.testing import CliRunner

from zlt import __version__
from zlt.cli import cli


def test_cli_version():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_serve_log_file_redirects_and_restores(tmp_path, monkeypatch):
    import builtins
    import sys
    from pathlib import Path

    from click.testing import CliRunner
    from zlt.cli import cli

    monkeypatch.setattr("uvicorn.run", lambda *a, **k: print("served"))
    log = tmp_path / "nested" / "zlt-web.log"
    before_out, before_err = sys.stdout, sys.stderr

    # CliRunner.isolation() restores sys.stdout/sys.stderr itself in its own
    # finally block no matter what the invoked command does internally - a
    # command that redirects and never restores still passes an
    # `assert sys.stdout is before_out` check after CliRunner.invoke(). So
    # that check alone can't prove serve's own finally block ran. What can:
    # the log file handle only gets closed via serve's finally, so track the
    # handle open() returns and assert it was actually closed.
    opened = []
    real_open = builtins.open

    def tracking_open(file, *args, **kwargs):
        handle = real_open(file, *args, **kwargs)
        if Path(file) == log:
            opened.append(handle)
        return handle

    monkeypatch.setattr(builtins, "open", tracking_open)

    result = CliRunner().invoke(cli, ["serve", "--log-file", str(log)])

    assert result.exit_code == 0
    assert log.exists()
    assert "served" in log.read_text()
    assert len(opened) == 1
    assert opened[0].closed
    # a leaked redirect would poison every later test in the session
    assert sys.stdout is before_out
    assert sys.stderr is before_err


def test_serve_log_file_closes_handle_when_uvicorn_raises(tmp_path, monkeypatch):
    import builtins
    from pathlib import Path

    from click.testing import CliRunner
    from zlt.cli import cli

    def boom(*_a, **_k):
        raise RuntimeError("uvicorn blew up")

    monkeypatch.setattr("uvicorn.run", boom)
    log = tmp_path / "nested" / "zlt-web.log"

    opened = []
    real_open = builtins.open

    def tracking_open(file, *args, **kwargs):
        handle = real_open(file, *args, **kwargs)
        if Path(file) == log:
            opened.append(handle)
        return handle

    monkeypatch.setattr(builtins, "open", tracking_open)

    result = CliRunner().invoke(cli, ["serve", "--log-file", str(log)])

    assert result.exit_code != 0
    assert isinstance(result.exception, RuntimeError)
    # Proves serve's finally block ran (and closed the stream) on the crash
    # path too, not just when uvicorn.run returns normally.
    assert len(opened) == 1
    assert opened[0].closed
