"""Output contracts relied on by downstream consumers.

The GNOME extension at https://github.com/exbyte-dev/zlt-gnome shells out to
this CLI and parses its stdout. These tests exist so a cosmetic change to that
output fails here rather than silently breaking the extension on a desktop.

If a test in this file fails, the fix is usually to open a PR against zlt-gnome
first, not to delete the assertion.
"""

import re

import responses
from click.testing import CliRunner

from tests.router_mock import install_get
from zlt.cli import cli
from zlt.client import ZltClient
from zlt.config import Config


def _obj(tmp_path):
    return ZltClient(
        Config(host="http://192.168.0.1", username="admin", password="admin"),
        session_path=tmp_path / "session.json",
    )


@responses.activate
def test_net_get_exposes_raw_mode_in_first_parentheses(tmp_path):
    # zlt-gnome extension.js:_refreshModeFromCli matches /\(([^)]+)\)/ and
    # expects the first parenthesized group to be the raw router value.
    install_get({
        "token": "1",
        "current_network_mode": "LTE",
        "net_select": "Only_LTE",
    })
    result = CliRunner().invoke(cli, ["net", "get"], obj=_obj(tmp_path))
    assert result.exit_code == 0
    match = re.search(r"\(([^)]+)\)", result.output)
    assert match is not None, result.output
    assert match.group(1) == "Only_LTE"


def test_net_set_accepts_every_alias_the_extension_offers():
    # The alias list in zlt-gnome extension.js MODES must stay valid input.
    aliases = ["auto", "lte", "4g3g", "wcdma", "gsm"]
    help_text = CliRunner().invoke(cli, ["net", "set", "--help"]).output
    for alias in aliases:
        assert alias in help_text, f"{alias} missing from 'zlt net set' choices"
