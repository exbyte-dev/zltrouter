import json

import responses
from click.testing import CliRunner

from tests.router_mock import install_get, install_post
from zlt.cli import cli
from zlt.client import ZltClient
from zlt.config import Config


def _obj(tmp_path, password=None):
    return ZltClient(
        Config(host="http://192.168.0.1", username="admin", password=password),
        session_path=tmp_path / "session.json",
    )


@responses.activate
def test_get_raw_prints_json(tmp_path):
    responses.get("http://192.168.0.1/reqproc/proc_get", json={"network_type": "LTE"})
    result = CliRunner().invoke(cli, ["get", "network_type"], obj=_obj(tmp_path))
    assert result.exit_code == 0
    assert json.loads(result.output) == {"network_type": "LTE"}


@responses.activate
def test_status_falls_back_to_open_reads_without_password(tmp_path):
    # get_token empty -> not authed; status must still print open fields.
    responses.get(
        "http://192.168.0.1/reqproc/proc_get",
        json={
            "get_token": "",
            "network_type": "LTE",
            "rssi": "-90",
            "signalbar": "5",
            "lte_rsrq": "-10",
            "lte_pci": "312",
            "ppp_status": "ppp_connected",
        },
    )
    result = CliRunner().invoke(cli, ["status"], obj=_obj(tmp_path))
    assert result.exit_code == 0
    assert "LTE" in result.output
    assert "-90" in result.output


@responses.activate
def test_status_shows_real_reason_when_password_is_wrong(tmp_path):
    # A password IS configured but the router rejects it — status must show the
    # real login-failure reason, not the generic "set ZLT_PASSWORD" hint.
    install_get({
        "psw_fail_num_str": "5", "login_lock_time": "300",
        "random_login": "12345678", "get_token": "",
        "network_type": "LTE",
        "rssi": "-90",
        "signalbar": "5",
        "lte_rsrq": "-10",
        "lte_pci": "312",
        "ppp_status": "ppp_connected",
    })
    install_post(result="3")  # login rejected
    result = CliRunner().invoke(cli, ["status"], obj=_obj(tmp_path, password="wrongpass"))
    assert result.exit_code == 0
    assert "login rejected" in result.output.lower()
    assert "set zlt_password" not in result.output.lower()
