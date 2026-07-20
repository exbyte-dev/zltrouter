from fastapi.testclient import TestClient

from zlt.client import UssdResult
from zlt.web import create_app


class StubConfig:
    host = "http://192.168.0.1"
    username = "admin"
    password = "secret"


class UssdStub:
    def __init__(self, results):
        self.config = StubConfig()
        self._results = list(results)
        self.sent = []
        self.replies = []
        self.cancelled = False

    def ussd_send(self, code):
        self.sent.append(code)
        return self._results.pop(0)

    def ussd_reply(self, text):
        self.replies.append(text)
        return self._results.pop(0)

    def ussd_cancel(self):
        self.cancelled = True


def make(client):
    return TestClient(create_app(client), raise_server_exceptions=False)


def test_send_returns_text_and_state():
    client = UssdStub([UssdResult("Balance 100", "complete")])
    r = make(client).post("/api/ussd/send", json={"code": "*310#"})
    assert r.status_code == 200
    assert r.json() == {"text": "Balance 100", "state": "complete"}
    assert client.sent == ["*310#"]


def test_send_rejects_empty_code():
    client = UssdStub([])
    r = make(client).post("/api/ussd/send", json={"code": "  "})
    assert r.status_code == 422


def test_reply_passes_text():
    client = UssdStub([UssdResult("You chose Data", "complete")])
    r = make(client).post("/api/ussd/reply", json={"text": "1"})
    assert r.status_code == 200
    assert client.replies == ["1"]


def test_cancel_calls_client():
    client = UssdStub([])
    r = make(client).post("/api/ussd/cancel")
    assert r.status_code == 200
    assert client.cancelled is True


def test_codes_reads_store(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from zlt import ussd_store
    ussd_store.save_code("Balance", "*310#")
    r = make(UssdStub([])).get("/api/ussd/codes")
    assert r.status_code == 200
    assert r.json() == {"codes": [{"label": "Balance", "code": "*310#"}]}
