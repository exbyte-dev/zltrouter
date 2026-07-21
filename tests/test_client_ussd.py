"""USSD client tests.

The contract exercised here was captured live from an MTN ZLT T10D MAX
(ZTE NV8645): poll ussd_write_flag on its own, and once it reports "16",
fetch ussd_data_info on its own for the hex-encoded reply text.
"""

import pytest
import responses

from tests.router_mock import install_ussd
from zlt.client import UssdError, UssdResult, ZltClient, _decode_ussd
from zlt.config import Config

PROC_GET = "http://192.168.0.1/reqproc/proc_get"
PROC_POST = "http://192.168.0.1/reqproc/proc_post"

# "Hi" as UCS2 (UTF-16BE), the shape the device returns with ussd_dcs "72".
UCS2_HI = "00480069"


def _client(tmp_path):
    return ZltClient(
        Config(host="http://192.168.0.1", username="admin", password="admin"),
        session_path=tmp_path / "session.json",
    )


def _bare():
    # _classify_flag needs no instance state, so skip __init__ and its session load.
    return ZltClient.__new__(ZltClient)


# --- decoding ----------------------------------------------------------------
def test_decode_ucs2():
    assert _decode_ussd(UCS2_HI, "72") == "Hi"


def test_decode_ucs2_real_device_sample():
    # First three characters of a real balance reply captured from the device.
    assert _decode_ussd("004d0054004e", "72") == "MTN"


def test_decode_single_byte_scheme():
    assert _decode_ussd("48656c6c6f", "68") == "Hello"


def test_decode_non_hex_passes_through():
    assert _decode_ussd("Balance: 5", "0") == "Balance: 5"


def test_decode_empty():
    assert _decode_ussd("", "72") == ""


# --- flag classification -----------------------------------------------------
def test_classify_received():
    assert _bare()._classify_flag({"ussd_write_flag": "16"}) == "received"


def test_classify_pending():
    assert _bare()._classify_flag({"ussd_write_flag": "15"}) == "pending"


def test_classify_timeout_values():
    for flag in ("3", "4", "unknown"):
        assert _bare()._classify_flag({"ussd_write_flag": flag}) == "timeout"


def test_classify_error_values():
    state = _bare()._classify_flag({"ussd_write_flag": "2"})
    assert state.startswith("error:")
    assert "network terminated" in state
    assert "no service" in _bare()._classify_flag({"ussd_write_flag": "1"})


def test_classify_missing_flag_key_raises():
    with pytest.raises(UssdError):
        _bare()._classify_flag({"ussd_data": "x"})


# --- end to end over the mock ------------------------------------------------
@responses.activate
def test_ussd_send_one_shot_complete(tmp_path):
    install_ussd(
        ["15", "16"],
        {"ussd_data": UCS2_HI, "ussd_action": "0", "ussd_dcs": "72"},
    )
    result = _client(tmp_path).ussd_send("*310#", interval=0)
    assert result == UssdResult("Hi", "complete")


@responses.activate
def test_ussd_send_prompt_when_action_wants_reply(tmp_path):
    install_ussd(
        ["16"],
        {"ussd_data": UCS2_HI, "ussd_action": "1", "ussd_dcs": "72"},
    )
    assert _client(tmp_path).ussd_send("*312#", interval=0).state == "prompt"


@responses.activate
def test_ussd_send_timeout_flag(tmp_path):
    install_ussd(["3"])
    assert _client(tmp_path).ussd_send("*310#", interval=0).state == "timeout"


@responses.activate
def test_ussd_send_times_out_on_deadline(tmp_path):
    install_ussd(["15"])
    result = _client(tmp_path).ussd_send("*310#", timeout=0.05, interval=0)
    assert result == UssdResult("", "timeout")


@responses.activate
def test_ussd_send_error_flag(tmp_path):
    install_ussd(["2"])
    result = _client(tmp_path).ussd_send("*310#", interval=0)
    assert result.state == "error"
    assert "network terminated" in result.text


@responses.activate
def test_ussd_send_raises_on_contract_mismatch(tmp_path):
    # A device whose poll answer has no ussd_write_flag key at all.
    responses.add_callback(
        responses.GET, PROC_GET,
        callback=lambda r: (200, {}, '{"token": "1"}'),
    )
    responses.add(responses.POST, PROC_POST, json={"result": "success"})
    with pytest.raises(UssdError):
        _client(tmp_path).ussd_send("*310#", interval=0)


@responses.activate
def test_ussd_send_posts_expected_body(tmp_path):
    install_ussd(["16"], {"ussd_data": UCS2_HI, "ussd_action": "0", "ussd_dcs": "72"})
    _client(tmp_path).ussd_send("*310#", interval=0)
    body = str([c for c in responses.calls if c.request.method == "POST"][0].request.body)
    assert "goformId=USSD_PROCESS" in body
    assert "USSD_operator=ussd_send" in body
    assert "USSD_send_number=%2A310%23" in body  # *310# url-encoded


@responses.activate
def test_ussd_reply_posts_expected_body(tmp_path):
    install_ussd(["16"], {"ussd_data": UCS2_HI, "ussd_action": "1", "ussd_dcs": "72"})
    client = _client(tmp_path)
    client.ussd_send("*312#", interval=0)
    client.ussd_reply("1", interval=0)
    posts = [c for c in responses.calls if c.request.method == "POST"]
    reply_body = str(posts[1].request.body)
    assert "USSD_operator=ussd_reply" in reply_body
    assert "USSD_reply_number=1" in reply_body


@responses.activate
def test_ussd_cancel_posts_cancel(tmp_path):
    install_ussd(["16"], {"ussd_data": UCS2_HI, "ussd_action": "0", "ussd_dcs": "72"})
    _client(tmp_path).ussd_cancel()
    body = str([c for c in responses.calls if c.request.method == "POST"][0].request.body)
    assert "USSD_operator=ussd_cancel" in body
