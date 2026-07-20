from click.testing import CliRunner

from zlt import __version__
from zlt.cli import cli


def test_cli_version():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output
