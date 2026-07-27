"""Web layer tests. All router traffic is faked via a stub client."""

from fastapi.testclient import TestClient

from zlt.client import LockedOut, LoginError, RouterUnreachable
from zlt.web import create_app


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


def test_index_has_tab_bar():
    """The four panels and the tabs that reach them.

    Each tab points at its panel through aria-controls, which is also how
    tabs.js finds panels, so asserting the pair keeps the wiring honest.
    """
    r = make(StubClient()).get("/")
    assert r.status_code == 200
    for tab, panel in [
        ("tab-signal", "signal-panel"),
        ("tab-messages", "sms-panel"),
        ("tab-ussd", "ussd-panel"),
        ("tab-speed", "speed-panel"),
    ]:
        assert f'id="{tab}"' in r.text
        assert f'aria-controls="{panel}"' in r.text
        assert f'id="{panel}"' in r.text


def test_index_has_ussd_panel():
    r = make(StubClient()).get("/")
    assert r.status_code == 200
    assert 'id="ussd-panel"' in r.text


def test_index_has_speed_panel():
    r = make(StubClient()).get("/")
    assert r.status_code == 200
    assert 'id="speed-panel"' in r.text


def test_index_has_sms_panel():
    r = make(StubClient()).get("/")
    assert r.status_code == 200
    assert 'id="sms-panel"' in r.text


def test_index_has_the_select_mode_controls():
    r = make(StubClient()).get("/")
    assert r.status_code == 200
    for el in ["sms-select", "sms-all", "sms-bar", "sms-mark",
               "sms-delete", "sms-delete-yes", "sms-delete-no"]:
        assert f'id="{el}"' in r.text


# The panel scripts live under /static/js/ now, so the assertions that used to
# look for endpoint URLs in the served HTML follow them there.
def test_static_scripts_call_their_endpoints():
    client = make(StubClient())
    for name, endpoint in [
        ("ussd.js", "/api/ussd/send"),
        ("speed.js", "/api/speedtest/config"),
        ("sms.js", "/api/sms/send"),
        ("sms.js", "/api/sms/read"),
        ("sms.js", "/api/sms/delete"),
        ("net.js", "/api/net"),
        ("signal.js", "/api/status"),
    ]:
        r = client.get(f"/static/js/{name}")
        assert r.status_code == 200, name
        assert endpoint in r.text, name


def test_static_css_is_served():
    r = make(StubClient()).get("/static/app.css")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")
    assert "--bg:" in r.text


def test_static_assets_are_packaged():
    """A missing package-data glob ships a dashboard with no styles.

    The dev checkout keeps working either way, because the files are right
    there on disk, so nothing but this test catches it before a pipx install
    serves an unstyled page.
    """
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text())
    globs = data["tool"]["setuptools"]["package-data"]["zlt"]

    # Deliberately no assertion on the literal glob strings. What matters is
    # which files end up shipped, not how the patterns are spelled, and pinning
    # the spelling failed a change that widened them to a recursive match.

    # Every asset index.html asks for has to be matched by one of those globs.
    static = root / "zlt" / "static"
    shipped = {p.relative_to(static).as_posix() for g in globs for p in static.glob(g[len("static/"):])}
    for asset in ["index.html", "app.css"]:
        assert asset in shipped
    for script in (static / "js").glob("*.js"):
        assert f"js/{script.name}" in shipped


def test_web_deps_are_not_optional():
    """The dashboard is the point of the service, so it must not need an extra.

    A quoted extras install cannot be typed portably: single quotes are not
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
