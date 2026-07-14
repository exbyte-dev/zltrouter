import base64
import hashlib

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
        remaining = int(raw) if raw not in ("", None) else MAX_LOGIN_COUNT
        lock_raw = data.get("login_lock_time", "")
        lock = int(lock_raw) if lock_raw not in ("", None) else DEFAULT_LOCK_TIME
        return remaining, lock

    # --- session persistence (stub until Task 3b) ----------------------------
    def _load_session(self) -> None:
        pass
