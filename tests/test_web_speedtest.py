"""Speed-test config endpoint tests.

The measurement itself runs in the browser (it has to: the point is to time the
path from the device viewing the dashboard, through the router, to the
internet). The backend only publishes where to aim, so the target can be moved
without editing the page.
"""

from fastapi.testclient import TestClient

from zlt.web import create_app


class StubConfig:
    host = "http://192.168.0.1"
    username = "admin"
    password = "secret"


class StubClient:
    def __init__(self):
        self.config = StubConfig()


def make():
    return TestClient(create_app(StubClient()), raise_server_exceptions=False)


def test_config_defaults_to_cloudflare():
    r = make().get("/api/speedtest/config")
    assert r.status_code == 200
    body = r.json()
    assert body["down_url"] == "https://speed.cloudflare.com/__down"
    assert body["up_url"] == "https://speed.cloudflare.com/__up"
    assert body["down_bytes"] > 0
    assert body["up_bytes"] > 0


def test_config_honours_env_overrides(monkeypatch):
    monkeypatch.setenv("ZLT_SPEEDTEST_DOWN_URL", "http://example.test/down")
    monkeypatch.setenv("ZLT_SPEEDTEST_UP_URL", "http://example.test/up")
    monkeypatch.setenv("ZLT_SPEEDTEST_DOWN_BYTES", "1000")
    monkeypatch.setenv("ZLT_SPEEDTEST_UP_BYTES", "500")
    body = make().get("/api/speedtest/config").json()
    assert body["down_url"] == "http://example.test/down"
    assert body["up_url"] == "http://example.test/up"
    assert body["down_bytes"] == 1000
    assert body["up_bytes"] == 500


def test_config_falls_back_when_byte_counts_are_not_numbers(monkeypatch):
    """A typo in the config must not break the panel with a 500."""
    monkeypatch.setenv("ZLT_SPEEDTEST_DOWN_BYTES", "twenty-five megs")
    body = make().get("/api/speedtest/config").json()
    assert body["down_bytes"] == 25_000_000


def test_config_needs_no_router():
    """The endpoint must never touch the device - it is pure configuration.

    A client stub with no get/post/ensure_session at all would raise
    AttributeError if the handler reached for the router.
    """
    assert make().get("/api/speedtest/config").status_code == 200
