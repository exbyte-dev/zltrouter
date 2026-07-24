"""SMS web layer tests. All router traffic is faked via a stub client."""

from fastapi.testclient import TestClient

from zlt.client import LockedOut, SmsError, SmsMessage
from zlt.web import create_app


class StubConfig:
    host = "http://192.168.0.1"
    username = "admin"
    password = "secret"


class SmsStub:
    def __init__(self, messages=None, *, list_exc=None, send_exc=None):
        self.config = StubConfig()
        self._messages = list(messages or [])
        self._list_exc = list_exc
        self._send_exc = send_exc
        self.sent = []

    def sms_list(self, limit=50):
        if self._list_exc:
            raise self._list_exc
        return self._messages[:limit]

    def sms_send(self, number, text):
        if self._send_exc:
            raise self._send_exc
        self.sent.append((number, text))


def make(client):
    return TestClient(create_app(client), raise_server_exceptions=False)


def msg(**over):
    row = dict(id="656", number="121", text="Hi", date="2026-07-24 15:28",
               unread=True, outgoing=False)
    row.update(over)
    return SmsMessage(**row)


def test_list_returns_messages():
    client = SmsStub([msg()])
    r = make(client).get("/api/sms")
    assert r.status_code == 200
    body = r.json()
    assert body["messages"] == [{
        "id": "656", "number": "121", "text": "Hi",
        "date": "2026-07-24 15:28", "unread": True, "outgoing": False,
    }]


def test_list_derives_unread_from_the_rows():
    """The badge has to agree with the list; the device's own counter did not."""
    client = SmsStub([msg(id="1"), msg(id="2", unread=False), msg(id="3")])
    assert make(client).get("/api/sms").json()["unread"] == 2


def test_list_empty_inbox():
    r = make(SmsStub([])).get("/api/sms")
    assert r.status_code == 200
    assert r.json() == {"unread": 0, "messages": []}


def test_list_maps_sms_error_to_502():
    client = SmsStub(list_exc=SmsError("different SMS API"))
    assert make(client).get("/api/sms").status_code == 502


def test_list_maps_lockout_to_423():
    client = SmsStub(list_exc=LockedOut("refusing"))
    assert make(client).get("/api/sms").status_code == 423


def test_send_passes_number_and_text():
    client = SmsStub()
    r = make(client).post("/api/sms/send", json={"number": "121", "text": "Hi"})
    assert r.status_code == 200
    assert client.sent == [("121", "Hi")]


def test_send_rejects_empty_number():
    client = SmsStub()
    r = make(client).post("/api/sms/send", json={"number": "  ", "text": "Hi"})
    assert r.status_code == 422
    assert client.sent == []


def test_send_rejects_empty_text():
    client = SmsStub()
    r = make(client).post("/api/sms/send", json={"number": "121", "text": "  "})
    assert r.status_code == 422
    assert client.sent == []


def test_send_maps_sms_error_to_502():
    client = SmsStub(send_exc=SmsError("the network rejected the message"))
    r = make(client).post("/api/sms/send", json={"number": "121", "text": "Hi"})
    assert r.status_code == 502
    assert "rejected" in r.json()["detail"]
