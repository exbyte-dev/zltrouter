"""SMS client tests.

The contract exercised here was captured from the device's own js/service.js
plus js/util.js and confirmed against a live MTN ZLT T10D MAX (ZTE NV8645):

  read   cmd=sms_data_total with page/data_per_page/mem_store/tags/order_by,
         answering {"messages": [{id, number, content, tag, date, ...}]} where
         content is UCS2 hex and number is plain text
  send   goformId=SEND_SMS with Number/sms_time/MessageBody/ID/encode_type,
         then cmd=sms_cmd_status_info&sms_cmd=4 until sms_cmd_status_result is
         "3" (sent) or "2" (failed)
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from tests.router_mock import PROC_GET, install_sms
from zlt.client import (
    SmsError,
    SmsMessage,
    ZltClient,
    _encode_sms,
    _decode_sms,
    _parse_sms_date,
    _sms_encode_type,
    _sms_time,
)
from zlt.config import Config

# "Hi" as UCS2, the shape the device returns for every message body.
UCS2_HI = "00480069"


# --- decoding ----------------------------------------------------------------
def test_decode_ucs2_body():
    assert _decode_sms(UCS2_HI) == "Hi"


def test_decode_real_device_sample():
    # Opening word of a real inbox message captured from the live device.
    assert _decode_sms("00410063007400690076006100740069006F006E") == "Activation"


def test_decode_strips_null_padding():
    assert _decode_sms("00480069" + "0000") == "Hi"


def test_decode_non_hex_passes_through():
    assert _decode_sms("Plain text") == "Plain text"


def test_decode_empty():
    assert _decode_sms("") == ""


# --- encoding ----------------------------------------------------------------
def test_encode_is_ucs2_hex():
    assert _encode_sms("Hi") == "00480069"


def test_encode_round_trips_through_decode():
    for text in ("Hi", "Balance: N1,200.00", "naïve café", "line\nbreak"):
        assert _decode_sms(_encode_sms(text)) == text


def test_encode_empty():
    assert _encode_sms("") == ""


def test_encode_type_is_gsm7_for_plain_text():
    assert _sms_encode_type("Hello 123") == "GSM7_default"


def test_encode_type_is_unicode_for_anything_else():
    assert _sms_encode_type("café ☕") == "UNICODE"


def test_encode_type_of_empty_is_gsm7():
    assert _sms_encode_type("") == "GSM7_default"


# --- time formatting ---------------------------------------------------------
def test_sms_time_matches_device_format():
    """getCurrentTimeString(): YY;MM;DD;HH;MM;SS;<signed tz hours>."""
    when = datetime(2026, 7, 24, 15, 28, 20, tzinfo=timezone(timedelta(hours=1)))
    assert _sms_time(when) == "26;07;24;15;28;20;+1"


def test_sms_time_negative_offset():
    when = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=-5)))
    assert _sms_time(when) == "26;01;02;03;04;05;-5"


# --- inbox date parsing ------------------------------------------------------
def test_parse_device_date_comma_form():
    # Exactly what the live device returned: "YY,MM,DD,HH,MM,SS,+TZ".
    assert _parse_sms_date("26,07,24,15,28,20,+4") == "2026-07-24 15:28"


def test_parse_device_date_semicolon_form():
    assert _parse_sms_date("26;07;24;15;28;20;+4") == "2026-07-24 15:28"


def test_parse_device_date_garbage_passes_through():
    assert _parse_sms_date("whenever") == "whenever"


# --- message shape -----------------------------------------------------------
def test_sms_message_is_comparable():
    a = SmsMessage(id="1", number="121", text="Hi", date="2026-07-24 15:28",
                   unread=True, outgoing=False)
    b = SmsMessage(id="1", number="121", text="Hi", date="2026-07-24 15:28",
                   unread=True, outgoing=False)
    assert a == b


def test_sms_error_is_available():
    with pytest.raises(SmsError):
        raise SmsError("boom")


# --- inbox over the mock -----------------------------------------------------
def _client(tmp_path):
    return ZltClient(
        Config(host="http://192.168.0.1", username="admin", password="admin"),
        session_path=tmp_path / "session.json",
    )


def _raw(**over):
    """One message in the device's own shape."""
    row = {"id": "656", "number": "121", "content": UCS2_HI,
           "tag": "1", "date": "26,07,24,15,28,20,+4", "draft_group_id": ""}
    row.update(over)
    return row


def _query(cmd):
    """Query parameters of the last GET issued for `cmd`."""
    for call in reversed(responses.calls):
        if call.request.method != "GET":
            continue
        q = parse_qs(urlparse(call.request.url).query)
        if q.get("cmd", [""])[0] == cmd:
            return q
    raise AssertionError(f"no GET for cmd={cmd}")


def _post_body():
    return str([c for c in responses.calls if c.request.method == "POST"][0].request.body)


@responses.activate
def test_sms_list_decodes_a_message(tmp_path):
    install_sms([_raw()])
    assert _client(tmp_path).sms_list() == [
        SmsMessage(id="656", number="121", text="Hi",
                   date="2026-07-24 15:28", unread=True, outgoing=False)
    ]


@responses.activate
def test_sms_list_marks_read_messages(tmp_path):
    install_sms([_raw(tag="0")])
    assert _client(tmp_path).sms_list()[0].unread is False


@responses.activate
def test_sms_list_marks_outgoing_messages(tmp_path):
    install_sms([_raw(tag="2")])
    message = _client(tmp_path).sms_list()[0]
    assert message.outgoing is True
    assert message.unread is False


@responses.activate
def test_sms_list_empty_inbox(tmp_path):
    install_sms([])
    assert _client(tmp_path).sms_list() == []


@responses.activate
def test_sms_list_sends_the_captured_query(tmp_path):
    install_sms([])
    _client(tmp_path).sms_list()
    q = _query("sms_data_total")
    assert q["mem_store"] == ["1"]
    assert q["tags"] == ["10"]
    assert q["order_by"] == ["order by id desc"]
    assert q["page"] == ["0"]


@responses.activate
def test_sms_list_caps_what_the_device_returns(tmp_path):
    """data_per_page is advisory: the live device sent 10 rows when asked for 3."""
    install_sms([_raw(id=str(i)) for i in range(10)])
    assert len(_client(tmp_path).sms_list(limit=3)) == 3


@responses.activate
def test_sms_list_raises_on_contract_mismatch(tmp_path):
    # A device whose answer has no messages key at all.
    responses.add_callback(
        responses.GET, PROC_GET,
        callback=lambda r: (200, {}, '{"token": "1"}'),
    )
    with pytest.raises(SmsError):
        _client(tmp_path).sms_list()


# --- sending over the mock ---------------------------------------------------
@responses.activate
def test_sms_send_posts_the_captured_body(tmp_path):
    install_sms([])
    _client(tmp_path).sms_send("08012345678", "Hi", settle=0, interval=0)
    body = _post_body()
    assert "goformId=SEND_SMS" in body
    assert "Number=08012345678" in body
    assert "MessageBody=00480069" in body
    assert "ID=-1" in body
    assert "encode_type=GSM7_default" in body
    assert "sms_time=" in body


@responses.activate
def test_sms_send_marks_unicode_bodies(tmp_path):
    # "é" is in the GSM 03.38 set, so it takes a genuinely foreign character
    # to force UNICODE. Getting this wrong quadruples the cost of a message.
    install_sms([])
    _client(tmp_path).sms_send("121", "coffee ☕", settle=0, interval=0)
    assert "encode_type=UNICODE" in _post_body()


@responses.activate
def test_sms_send_waits_out_the_idle_status(tmp_path):
    """The device answers {"messages": []} until the send registers."""
    install_sms([], statuses=(None, None, "3"))
    _client(tmp_path).sms_send("121", "Hi", settle=0, interval=0)


@responses.activate
def test_sms_send_raises_when_the_network_rejects(tmp_path):
    install_sms([], statuses=("2",))
    with pytest.raises(SmsError, match="reject"):
        _client(tmp_path).sms_send("121", "Hi", settle=0, interval=0)


@responses.activate
def test_sms_send_raises_when_the_router_rejects_the_post(tmp_path):
    install_sms([], post_result="failure")
    with pytest.raises(SmsError):
        _client(tmp_path).sms_send("121", "Hi", settle=0, interval=0)


@responses.activate
def test_sms_send_times_out_on_deadline(tmp_path):
    install_sms([], statuses=(None,))
    with pytest.raises(SmsError, match="timed out"):
        _client(tmp_path).sms_send("121", "Hi", settle=0, timeout=0.05, interval=0)


@responses.activate
def test_sms_send_rejects_empty_recipient(tmp_path):
    install_sms([])
    with pytest.raises(SmsError):
        _client(tmp_path).sms_send("  ", "Hi", settle=0, interval=0)


@responses.activate
def test_sms_send_rejects_empty_message(tmp_path):
    install_sms([])
    with pytest.raises(SmsError):
        _client(tmp_path).sms_send("121", "  ", settle=0, interval=0)
