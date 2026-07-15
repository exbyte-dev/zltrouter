import responses
from click.testing import CliRunner

from tests.router_mock import install_get, install_post
from zlt.cli import cli
from zlt.client import ZltClient
from zlt.config import Config


def _obj(tmp_path):
    return ZltClient(
        Config(host="http://192.168.0.1", username="admin", password="admin"),
        session_path=tmp_path / "session.json",
    )


@responses.activate
def test_net_set_posts_mapped_value_and_confirms(tmp_path):
    install_get({
        "token": "1",  # authed
        "net_select_mode": "Only_GSM",     # deliberately different — must NOT win
        "m_netselect_save": "Only_GSM",    # deliberately different — must NOT win
        "net_select": "Only_LTE",          # this is the one the real device populates — must win
        "current_network_mode": "LTE",
    })
    install_post(result="success")
    result = CliRunner().invoke(cli, ["net", "set", "lte"], obj=_obj(tmp_path))
    assert result.exit_code == 0
    post_body = [c for c in responses.calls if c.request.method == "POST"][0].request.body
    assert "BearerPreference=Only_LTE" in post_body
    assert "lte" in result.output.lower()
    assert "Only_LTE" in result.output
    assert "Only_GSM" not in result.output


@responses.activate
def test_net_set_rejects_bad_result(tmp_path):
    install_get({"token": "1"})
    install_post(result="failure")
    result = CliRunner().invoke(cli, ["net", "set", "auto"], obj=_obj(tmp_path))
    assert result.exit_code != 0
    assert "failure" in result.output.lower()


def test_net_set_rejects_unknown_mode(tmp_path):
    result = CliRunner().invoke(cli, ["net", "set", "5g"], obj=_obj(tmp_path))
    assert result.exit_code != 0  # click.Choice rejects


@responses.activate
def test_post_passthrough(tmp_path):
    install_get({"token": "7"})
    install_post(result="success")
    result = CliRunner().invoke(
        cli, ["post", "SET_BEARER_PREFERENCE", "BearerPreference=NETWORK_auto"],
        obj=_obj(tmp_path),
    )
    assert result.exit_code == 0
    assert "success" in result.output
