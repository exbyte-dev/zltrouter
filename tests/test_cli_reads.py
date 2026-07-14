import json

import responses
from click.testing import CliRunner

from zlt.cli import cli
from zlt.client import ZltClient
from zlt.config import Config


def _obj(tmp_path):
    return ZltClient(
        Config(host="http://192.168.0.1", username="admin", password=None),
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
