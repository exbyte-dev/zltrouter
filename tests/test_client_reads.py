import responses

from zlt.client import (
    BEARER_MAP,
    RouterUnreachable,
    ZltClient,
    encode_password,
    encode_username,
)
from zlt.config import Config


def _client(tmp_path):
    return ZltClient(
        Config(host="http://192.168.0.1", username="admin", password="admin"),
        session_path=tmp_path / "session.json",
    )


def test_encode_username():
    assert encode_username("admin") == "YWRtaW4="


def test_encode_password_vector():
    # Base64(sha256_hex("12345678" + "admin"))
    assert encode_password("12345678", "admin") == (
        "OTZlNmM5YWY2MzY3YjBiZDc5YTc0ODQxN2MxNzI5NGFiYmJkNjY5MTM5N2RkY2VmYTUzZTI0MjcxMWNmNmJlNg=="
    )


def test_bearer_map_wcdma_is_td_w():
    assert BEARER_MAP["wcdma"] == "TD_W"
    assert BEARER_MAP["lte"] == "Only_LTE"
    assert BEARER_MAP["auto"] == "NETWORK_auto"


@responses.activate
def test_get_single_no_multi(tmp_path):
    responses.get(
        "http://192.168.0.1/reqproc/proc_get",
        json={"network_type": "LTE"},
    )
    data = _client(tmp_path).get("network_type")
    assert data == {"network_type": "LTE"}
    req = responses.calls[0].request
    assert "multi_data" not in req.url
    assert "isTest=false" in req.url


@responses.activate
def test_get_multi_sets_multi_data(tmp_path):
    responses.get(
        "http://192.168.0.1/reqproc/proc_get",
        json={"rssi": "-90", "signalbar": "5"},
    )
    _client(tmp_path).get("rssi", "signalbar")
    assert "multi_data=1" in responses.calls[0].request.url


@responses.activate
def test_token_handles_both_keys(tmp_path):
    responses.get("http://192.168.0.1/reqproc/proc_get", json={"token": "2315231"})
    assert _client(tmp_path).token() == "2315231"


@responses.activate
def test_token_empty_when_get_token_key_empty(tmp_path):
    responses.get("http://192.168.0.1/reqproc/proc_get", json={"get_token": ""})
    assert _client(tmp_path).token() == ""


def test_connection_error_becomes_router_unreachable(tmp_path):
    # No responses registered + not activated -> real connection attempt fails fast.
    c = ZltClient(
        Config(host="http://192.0.2.1", username="admin", password="admin"),
        session_path=tmp_path / "session.json",
        timeout=0.5,
    )
    try:
        c.get("network_type")
        assert False, "expected RouterUnreachable"
    except RouterUnreachable:
        pass


@responses.activate
def test_attempts_remaining_empty_defaults_to_five(tmp_path):
    responses.get(
        "http://192.168.0.1/reqproc/proc_get",
        json={"psw_fail_num_str": "", "login_lock_time": ""},
    )
    remaining, lock = _client(tmp_path).attempts_remaining()
    assert remaining == 5
    assert lock == 300
