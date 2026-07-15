import responses
from click.testing import CliRunner

from tests.router_mock import install_get
from zlt.cli import cli
from zlt.client import ZltClient
from zlt.config import Config


def _obj(tmp_path, password="admin"):
    return ZltClient(
        Config(host="http://192.168.0.1", username="admin", password=password),
        session_path=tmp_path / "session.json",
    )


@responses.activate
def test_net_get_maps_value_to_friendly(tmp_path):
    install_get({
        "token": "1",  # authed
        "current_network_mode": "LTE",
        "net_select_mode": "Only_LTE",
        "m_netselect_save": "Only_LTE",
        "net_select": "Only_LTE",
    })
    result = CliRunner().invoke(cli, ["net", "get"], obj=_obj(tmp_path))
    assert result.exit_code == 0
    assert "lte" in result.output.lower()
    assert "Only_LTE" in result.output


@responses.activate
def test_status_authed_shows_band(tmp_path):
    install_get({
        "token": "1",  # authed
        "network_type": "LTE",
        "rssi": "-90",
        "signalbar": "5",
        "lte_rsrq": "-10",
        "lte_pci": "312",
        "ppp_status": "ppp_connected",
        "lte_rsrp": "-105",
        "lte_band": "3",
        "lte_snr": "12",
    })
    result = CliRunner().invoke(cli, ["status"], obj=_obj(tmp_path))
    assert result.exit_code == 0
    assert "band" in result.output
    assert "-105" in result.output
