import json

import responses

from tests.router_mock import PROC_POST, install_get, install_post
from zlt.client import LockedOut, LoginError, ZltClient
from zlt.config import Config


def _client(tmp_path, password="admin"):
    return ZltClient(
        Config(host="http://192.168.0.1", username="admin", password=password),
        session_path=tmp_path / "session.json",
    )


def _post_bodies():
    return [c.request.body for c in responses.calls if c.request.method == "POST"]


@responses.activate
def test_login_success_persists_session(tmp_path):
    install_get({
        "psw_fail_num_str": "5", "login_lock_time": "300",
        "random_login": "12345678", "get_token": "",
    })
    install_post(result="0", headers={"Set-Cookie": "random=abc123; path=/"})
    client = _client(tmp_path)
    data = client.login()
    assert data["result"] == "0"

    body = _post_bodies()[0]
    assert "goformId=LOGIN" in body
    assert "username=YWRtaW4%3D" in body   # Base64("admin"), url-encoded
    assert "password=OTZlNmM5" in body     # start of Base64(sha256_hex("12345678admin"))
    saved = json.loads((tmp_path / "session.json").read_text())
    assert saved["cookies"]["random"] == "abc123"


@responses.activate
def test_login_guard_aborts_when_attempts_low(tmp_path):
    install_get({"psw_fail_num_str": "1", "login_lock_time": "300"})
    try:
        _client(tmp_path).login()
        assert False, "expected LockedOut"
    except LockedOut:
        assert not _post_bodies()  # must NOT have attempted a POST


@responses.activate
def test_login_wrong_password_raises(tmp_path):
    install_get({
        "psw_fail_num_str": "5", "login_lock_time": "300",
        "random_login": "12345678", "get_token": "",
    })
    install_post(result="3")
    try:
        _client(tmp_path).login()
        assert False, "expected LoginError"
    except LoginError:
        pass


def test_login_requires_password(tmp_path):
    try:
        _client(tmp_path, password=None).login()
        assert False, "expected LoginError"
    except LoginError:
        pass


@responses.activate
def test_ensure_session_skips_login_when_token_present(tmp_path):
    install_get({"token": "2315231"})
    _client(tmp_path).ensure_session()  # token non-empty => already authed
    assert not _post_bodies()


@responses.activate
def test_post_injects_token_and_isTest(tmp_path):
    install_get({"token": "999"})   # already authed
    install_post(result="success")
    client = _client(tmp_path)
    data = client.post("SET_BEARER_PREFERENCE", BearerPreference="NETWORK_auto")
    assert data["result"] == "success"
    body = _post_bodies()[0]
    assert "goformId=SET_BEARER_PREFERENCE" in body
    assert "BearerPreference=NETWORK_auto" in body
    assert "CSRFToken=999" in body
    assert "isTest=false" in body


@responses.activate
def test_post_reauth_retry_on_auth_failure(tmp_path):
    # First POST returns an auth-failure marker; client re-logs-in and retries once.
    install_get({
        "token": "5", "get_token": "5",
        "psw_fail_num_str": "5", "login_lock_time": "300",
        "random_login": "12345678",
    })
    responses.add(responses.POST, PROC_POST, json={"result": "no_session"})  # failed set
    responses.add(responses.POST, PROC_POST, json={"result": "0"})           # re-login
    responses.add(responses.POST, PROC_POST, json={"result": "success"})     # retried set
    client = _client(tmp_path)
    data = client.post("SET_BEARER_PREFERENCE", BearerPreference="Only_LTE")
    assert data["result"] == "success"
    assert len(_post_bodies()) == 3


@responses.activate
def test_session_cache_roundtrip_loads_cookie(tmp_path):
    (tmp_path / "session.json").write_text(
        json.dumps({"host": "http://192.168.0.1", "cookies": {"random": "zzz"}, "ts": 1})
    )
    client = _client(tmp_path)
    assert client.http.cookies.get("random") == "zzz"
