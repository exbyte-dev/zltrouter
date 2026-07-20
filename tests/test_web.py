"""Web layer tests. All router traffic is faked via a stub client."""

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from zlt.client import LockedOut, LoginError, RouterUnreachable  # noqa: E402
from zlt.web import create_app  # noqa: E402


class StubConfig:
    host = "http://192.168.0.1"
    username = "admin"
    password = "secret"


class StubClient:
    """Minimal stand-in for ZltClient."""

    def __init__(self, *, get_data=None, login_exc=None, post_result="success"):
        self.config = StubConfig()
        self._get_data = get_data or {}
        self._login_exc = login_exc
        self._post_result = post_result
        self.posts = []

    def ensure_session(self):
        if self._login_exc:
            raise self._login_exc

    def get(self, *cmds, multi=None):
        return {k: self._get_data.get(k, "") for k in cmds}

    def post(self, goform_id, **fields):
        self.posts.append((goform_id, fields))
        return {"result": self._post_result}


def make(client):
    return TestClient(create_app(client), raise_server_exceptions=False)


def test_status_authed():
    client = StubClient(get_data={"network_type": "LTE", "rssi": "-63", "lte_rsrp": "-91"})
    r = make(client).get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["authed"] is True
    assert body["data"]["lte_rsrp"] == "-91"


def test_status_falls_back_when_login_fails():
    client = StubClient(get_data={"rssi": "-70"}, login_exc=LoginError("bad password"))
    r = make(client).get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["authed"] is False
    assert "bad password" in body["note"]
    assert "lte_rsrp" not in body["data"] or body["data"].get("rssi") == "-70"


def test_status_lockout_still_serves_open_data():
    client = StubClient(get_data={"rssi": "-70"}, login_exc=LockedOut("1 attempt left"))
    r = make(client).get("/api/status")
    assert r.status_code == 200
    assert r.json()["authed"] is False


def test_net_get_prefers_net_select():
    client = StubClient(get_data={"net_select": "NETWORK_auto", "net_select_mode": ""})
    r = make(client).get("/api/net")
    assert r.status_code == 200
    assert r.json()["friendly"] == "auto"


def test_net_set_posts_and_confirms():
    client = StubClient(get_data={"net_select": "Only_LTE"})
    r = make(client).post("/api/net", json={"mode": "lte"})
    assert r.status_code == 200
    assert client.posts == [("SET_BEARER_PREFERENCE", {"BearerPreference": "Only_LTE"})]
    assert r.json()["friendly"] == "lte"


def test_net_set_rejects_unknown_mode():
    client = StubClient()
    r = make(client).post("/api/net", json={"mode": "5g"})
    assert r.status_code == 422
    assert client.posts == []


def test_net_set_maps_lockout_to_423():
    client = StubClient(login_exc=LockedOut("refusing"))
    r = make(client).post("/api/net", json={"mode": "auto"})
    assert r.status_code == 423


def test_unreachable_maps_to_504():
    class Dead(StubClient):
        def get(self, *cmds, multi=None):
            raise RouterUnreachable("cannot reach")

        def ensure_session(self):
            raise RouterUnreachable("cannot reach")

    r = make(Dead()).get("/api/status")
    assert r.status_code == 504


def test_index_serves_dashboard():
    r = make(StubClient()).get("/")
    assert r.status_code == 200
    assert "Walk test" in r.text


def test_web_deps_are_not_optional():
    """The dashboard is the point of the service, so it must not need an extra.

    'pipx install zlt[web]' cannot be typed portably: single quotes are not
    quote characters in Windows cmd.exe. Keep these as regular dependencies.
    """
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text())
    deps = " ".join(data["project"]["dependencies"])
    assert "fastapi" in deps
    assert "uvicorn" in deps
    assert "web" not in data["project"].get("optional-dependencies", {})
