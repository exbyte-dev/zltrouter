import responses

from tests.router_mock import install_ussd
from zlt.client import UssdResult, ZltClient
from zlt.config import Config


def _client(tmp_path):
    return ZltClient(
        Config(host="http://192.168.0.1", username="admin", password="admin"),
        session_path=tmp_path / "session.json",
    )


def test_parse_complete():
    c = ZltClient.__new__(ZltClient)
    r = c._parse_ussd({"ussd_write_flag": "1",
                       "ussd_data_info": {"ussd_data": "Balance 100", "ussd_action": "0"}})
    assert r == UssdResult("Balance 100", "complete")


def test_parse_prompt():
    c = ZltClient.__new__(ZltClient)
    r = c._parse_ussd({"ussd_write_flag": "1",
                       "ussd_data_info": {"ussd_data": "1 Data 2 Voice", "ussd_action": "1"}})
    assert r == UssdResult("1 Data 2 Voice", "prompt")


def test_parse_string_info_defaults_complete():
    c = ZltClient.__new__(ZltClient)
    r = c._parse_ussd({"ussd_write_flag": "1", "ussd_data_info": "Balance 100"})
    assert r == UssdResult("Balance 100", "complete")


def test_parse_pending_when_flag_not_ready():
    c = ZltClient.__new__(ZltClient)
    assert c._parse_ussd({"ussd_write_flag": "0", "ussd_data_info": ""}).state == "pending"


def test_parse_error_and_timeout_flags():
    c = ZltClient.__new__(ZltClient)
    assert c._parse_ussd({"ussd_write_flag": "3", "ussd_data_info": "bad"}).state == "error"
    assert c._parse_ussd({"ussd_write_flag": "2", "ussd_data_info": ""}).state == "timeout"


@responses.activate
def test_ussd_send_one_shot(tmp_path):
    install_ussd([
        {"ussd_write_flag": "0", "ussd_data_info": ""},
        {"ussd_write_flag": "1", "ussd_data_info": {"ussd_data": "Balance 100", "ussd_action": "0"}},
    ])
    r = _client(tmp_path).ussd_send("*310#", interval=0)
    assert r == UssdResult("Balance 100", "complete")


@responses.activate
def test_ussd_send_prompt_then_reply(tmp_path):
    install_ussd([
        {"ussd_write_flag": "1", "ussd_data_info": {"ussd_data": "1 Data 2 Voice", "ussd_action": "1"}},
    ])
    client = _client(tmp_path)
    first = client.ussd_send("*312#", interval=0)
    assert first.state == "prompt"
    second = client.ussd_reply("1", interval=0)
    assert second.state == "prompt"  # mock keeps returning the same menu


@responses.activate
def test_ussd_send_times_out(tmp_path):
    install_ussd([{"ussd_write_flag": "0", "ussd_data_info": ""}])
    r = _client(tmp_path).ussd_send("*310#", timeout=0.05, interval=0)
    assert r == UssdResult("", "timeout")


@responses.activate
def test_ussd_send_posts_expected_body(tmp_path):
    install_ussd([{"ussd_write_flag": "1", "ussd_data_info": "ok"}])
    _client(tmp_path).ussd_send("*310#", interval=0)
    post = [c for c in responses.calls if c.request.method == "POST"][0]
    assert "goformId=USSD_PROCESS" in post.request.body
    assert "USSD_operator=ussd_send" in post.request.body
    assert "USSD_send_number=%2A310%23" in post.request.body  # *310# url-encoded


@responses.activate
def test_ussd_cancel_posts_cancel(tmp_path):
    install_ussd([{"ussd_write_flag": "1", "ussd_data_info": "ok"}])
    _client(tmp_path).ussd_cancel()
    post = [c for c in responses.calls if c.request.method == "POST"][0]
    assert "USSD_operator=ussd_cancel" in post.request.body
