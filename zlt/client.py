import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from zlt.config import Config, session_path as default_session_path


class ZltError(Exception):
    """Base error."""


class RouterUnreachable(ZltError):
    """Network/timeout talking to the router."""


class LoginError(ZltError):
    """Login rejected (wrong password, no nonce, etc.)."""


class LockedOut(ZltError):
    """Refusing to log in — too few attempts remaining / locked."""


class RouterError(ZltError):
    """The router returned an error result for a POST."""


class UssdError(ZltError):
    """The router returned an unparseable USSD reply."""


@dataclass
class UssdResult:
    text: str
    state: str  # complete | prompt | error | timeout  (pending is internal only)


# --- USSD (assumed ZTE reqproc contract; verify live, see plan) ---------------
USSD_SEND_GOFORM = "USSD_PROCESS"
USSD_OPERATOR_FIELD = "USSD_operator"
USSD_SEND_FIELD = "USSD_send_number"
USSD_REPLY_FIELD = "USSD_reply_number"
USSD_OP_SEND = "ussd_send"
USSD_OP_REPLY = "ussd_reply"
USSD_OP_CANCEL = "ussd_cancel"
USSD_FLAG_KEY = "ussd_write_flag"
USSD_DATA_KEY = "ussd_data_info"
USSD_READ_KEYS = [USSD_FLAG_KEY, USSD_DATA_KEY]
USSD_FLAG_PENDING = "0"
USSD_FLAG_RECEIVED = "1"
USSD_FLAG_TIMEOUT = "2"
USSD_FLAG_ERROR = "3"
USSD_ACTION_PROMPT = "1"  # ussd_action value meaning "network wants a reply"
USSD_TIMEOUT = 20.0
USSD_POLL_INTERVAL = 1.0


BEARER_MAP: dict[str, str] = {
    "auto": "NETWORK_auto",
    "lte": "Only_LTE",
    "4g": "Only_LTE",
    "4g3g": "TD_W_LTE",
    "wcdma": "TD_W",
    "3g": "TD_W",
    "gsm": "Only_GSM",
    "2g": "Only_GSM",
}
# First friendly alias per value, for display.
BEARER_REVERSE: dict[str, str] = {
    "NETWORK_auto": "auto",
    "Only_LTE": "lte",
    "TD_W_LTE": "4g3g",
    "TD_W": "wcdma",
    "Only_GSM": "gsm",
}

MAX_LOGIN_COUNT = 5
DEFAULT_LOCK_TIME = 300

# Status keys readable without auth, and the extras that need a session.
OPEN_KEYS = ["network_type", "rssi", "signalbar", "lte_rsrq", "lte_pci", "ppp_status"]
FULL_EXTRA = ["lte_rsrp", "lte_band", "lte_snr"]
# Keys queried to resolve the configured network mode (net_select wins; see README).
NET_KEYS = ["current_network_mode", "net_select_mode", "m_netselect_save", "net_select"]


def encode_username(username: str) -> str:
    return base64.b64encode(username.encode("utf-8")).decode("ascii")


def encode_password(random_login: str, password: str) -> str:
    digest = hashlib.sha256((random_login + password).encode("utf-8")).hexdigest()
    return base64.b64encode(digest.encode("ascii")).decode("ascii")


class ZltClient:
    def __init__(
        self,
        config: Config,
        *,
        session_path=None,
        timeout: float = 8.0,
    ) -> None:
        self.config = config
        self.timeout = timeout
        self.session_path = session_path or default_session_path()
        self.http = requests.Session()
        self.http.headers.update(
            {
                "Referer": f"{config.host}/index.html",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        self._load_session()

    # --- reads ---------------------------------------------------------------
    def get(self, *cmds: str, multi: bool | None = None) -> dict:
        params = {"isTest": "false", "cmd": ",".join(cmds)}
        if multi is None:
            multi = len(cmds) > 1
        if multi:
            params["multi_data"] = "1"
        try:
            resp = self.http.get(
                f"{self.config.host}/reqproc/proc_get",
                params=params,
                timeout=self.timeout,
            )
            return resp.json()
        except requests.RequestException as exc:
            raise RouterUnreachable(f"cannot reach {self.config.host}: {exc}") from exc
        except ValueError as exc:
            raise RouterUnreachable(f"router returned a non-JSON response: {exc}") from exc

    def token(self) -> str:
        data = self.get("get_token")
        value = data.get("token")
        if value is None:
            value = data.get("get_token", "")
        return value or ""

    def attempts_remaining(self) -> tuple[int, int]:
        data = self.get("psw_fail_num_str", "login_lock_time")
        raw = data.get("psw_fail_num_str", "")
        try:
            remaining = int(raw) if raw not in ("", None) else MAX_LOGIN_COUNT
        except ValueError:
            remaining = 0
        lock_raw = data.get("login_lock_time", "")
        try:
            lock = int(lock_raw) if lock_raw not in ("", None) else DEFAULT_LOCK_TIME
        except ValueError:
            lock = DEFAULT_LOCK_TIME
        return remaining, lock

    # --- auth / writes --------------------------------------------------------
    _AUTH_FAIL_MARKERS = {"no_session", "session_error", "need_login", "not_login", "-1"}

    def _post_raw(self, body: dict) -> dict:
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        try:
            resp = self.http.post(
                f"{self.config.host}/reqproc/proc_post",
                data=body,
                headers=headers,
                timeout=self.timeout,
            )
            return resp.json()
        except requests.RequestException as exc:
            raise RouterUnreachable(f"cannot reach {self.config.host}: {exc}") from exc
        except ValueError as exc:
            raise RouterUnreachable(f"router returned a non-JSON response: {exc}") from exc

    def login(self) -> dict:
        if not self.config.password:
            raise LoginError("ZLT_PASSWORD not set — cannot log in")
        remaining, lock = self.attempts_remaining()
        if remaining < 2:
            raise LockedOut(
                f"Only {remaining} login attempt(s) remaining before a {lock}s lockout — "
                f"refusing to try. Log in via the web UI at {self.config.host} to reset."
            )
        nonce = self.get("get_random_login").get("random_login", "")
        if not nonce:
            raise LoginError("router did not return a random_login nonce")
        body = {
            "isTest": "false",
            "goformId": "LOGIN",
            "username": encode_username(self.config.username),
            "password": encode_password(nonce, self.config.password),
            "CSRFToken": self.token(),
        }
        data = self._post_raw(body)
        if str(data.get("result")) not in ("0", "4"):
            raise LoginError(
                f"login rejected (result={data.get('result')}); "
                f"{remaining} attempt(s) were remaining"
            )
        self._save_session()
        return data

    def ensure_session(self) -> None:
        if self.token():
            return
        self.login()

    def post(self, goform_id: str, **fields: str) -> dict:
        self.ensure_session()
        return self._post_with_retry(goform_id, fields, retried=False)

    def _post_with_retry(self, goform_id: str, fields: dict, retried: bool) -> dict:
        body = {"isTest": "false", "goformId": goform_id, **fields}
        body.setdefault("CSRFToken", self.token())
        data = self._post_raw(body)
        if not retried and str(data.get("result", "")).lower() in self._AUTH_FAIL_MARKERS:
            self.login()
            return self._post_with_retry(goform_id, fields, retried=True)
        return data

    # --- USSD -----------------------------------------------------------------
    def ussd_send(self, code, *, timeout=USSD_TIMEOUT, interval=USSD_POLL_INTERVAL):
        self.post(USSD_SEND_GOFORM, **{
            USSD_OPERATOR_FIELD: USSD_OP_SEND,
            USSD_SEND_FIELD: code,
        })
        return self._ussd_poll(timeout, interval)

    def ussd_reply(self, text, *, timeout=USSD_TIMEOUT, interval=USSD_POLL_INTERVAL):
        self.post(USSD_SEND_GOFORM, **{
            USSD_OPERATOR_FIELD: USSD_OP_REPLY,
            USSD_REPLY_FIELD: text,
        })
        return self._ussd_poll(timeout, interval)

    def ussd_cancel(self):
        self.post(USSD_SEND_GOFORM, **{USSD_OPERATOR_FIELD: USSD_OP_CANCEL})

    def _ussd_poll(self, timeout, interval):
        deadline = time.monotonic() + timeout
        while True:
            result = self._parse_ussd(self.get(*USSD_READ_KEYS))
            if result.state != "pending":
                return result
            if time.monotonic() >= deadline:
                return UssdResult("", "timeout")
            time.sleep(interval)

    def _parse_ussd(self, raw):
        flag = str(raw.get(USSD_FLAG_KEY, "")).strip()
        info = raw.get(USSD_DATA_KEY, "")
        if isinstance(info, dict):
            text = str(info.get("ussd_data", ""))
            action = str(info.get("ussd_action", "")).strip()
        else:
            text = str(info)
            action = ""
        if flag == USSD_FLAG_TIMEOUT:
            return UssdResult("", "timeout")
        if flag == USSD_FLAG_ERROR:
            return UssdResult(text, "error")
        if flag == USSD_FLAG_RECEIVED and (text or action):
            state = "prompt" if action == USSD_ACTION_PROMPT else "complete"
            return UssdResult(text, state)
        return UssdResult("", "pending")

    # --- session persistence ---------------------------------------------------
    def _save_session(self) -> None:
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "host": self.config.host,
            "cookies": requests.utils.dict_from_cookiejar(self.http.cookies),
            "ts": int(time.time()),
        }
        fd = os.open(self.session_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(payload))

    def _load_session(self) -> None:
        try:
            payload = json.loads(Path(self.session_path).read_text())
        except (OSError, json.JSONDecodeError):
            return
        if payload.get("host") != self.config.host:
            return
        for name, value in payload.get("cookies", {}).items():
            self.http.cookies.set(name, value)
