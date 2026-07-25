import base64
import hashlib
import json
import os
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
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


class SmsError(ZltError):
    """An SMS could not be read, sent, or confirmed."""


@dataclass
class UssdResult:
    text: str
    state: str  # complete | prompt | error | timeout  (pending is internal only)


@dataclass
class SmsMessage:
    id: str
    number: str
    text: str
    date: str  # "YYYY-MM-DD HH:MM", or the device's raw string if unparseable
    unread: bool
    outgoing: bool


# --- USSD -------------------------------------------------------------------
# Captured live from an MTN ZLT T10D MAX (ZTE NV8645): the device's own
# js/service.js drives this state machine, and the values below were confirmed
# against the live router. Any other firmware that differs should only need
# changes here and in _classify_flag / _read_ussd_data / _decode_ussd.
USSD_SEND_GOFORM = "USSD_PROCESS"
USSD_OPERATOR_FIELD = "USSD_operator"
USSD_SEND_FIELD = "USSD_send_number"
USSD_REPLY_FIELD = "USSD_reply_number"
USSD_OP_SEND = "ussd_send"
USSD_OP_REPLY = "ussd_reply"
USSD_OP_CANCEL = "ussd_cancel"

USSD_FLAG_KEY = "ussd_write_flag"  # polled on its own
USSD_DATA_CMD = "ussd_data_info"  # aggregate cmd, must be requested alone
USSD_DATA_FIELD = "ussd_data"
USSD_ACTION_FIELD = "ussd_action"
USSD_DCS_FIELD = "ussd_dcs"

USSD_FLAG_PENDING = "15"  # still waiting on the network, poll again
USSD_FLAG_RECEIVED = "16"  # a reply is ready, fetch USSD_DATA_CMD
USSD_FLAG_TIMEOUT = {"3", "4", "unknown"}
USSD_FLAG_ERRORS = {
    "1": "no service",
    "2": "network terminated",
    "10": "retry",
    "41": "operation not supported",
    "99": "unsupported",
}
# ussd_action "0" is a terminal reply, "1" means the network wants a reply.
# Both confirmed live: *310# (balance) answers with "0", *323# (a balance menu)
# answers with "1" and then accepts a menu selection.
USSD_ACTION_PROMPT = "1"
USSD_DCS_UCS2_MASK = 0x0C  # (dcs & 0x0C) == 0x08 means UCS2, e.g. 0x48 ("72")
USSD_DCS_UCS2_VALUE = 0x08
USSD_TIMEOUT = 20.0
USSD_POLL_INTERVAL = 1.0


# --- SMS ---------------------------------------------------------------------
# Captured from the device's own js/service.js (sendSMS, getSMSMessages,
# getSmsStatusInfo) and js/util.js (getCurrentTimeString, encodeMessage,
# getEncodeType), then confirmed against the live router. As with USSD, a
# firmware that differs should only need changes in this block and the helpers
# just below it.
SMS_LIST_CMD = "sms_data_total"  # aggregate cmd, takes its own query params
SMS_STATUS_CMD = "sms_cmd_status_info"
# Deliberately not used: the device also exposes sms_unread_num, but it was
# observed reporting 0 while the inbox still held rows tagged unread. The unread
# count is derived from the rows instead, so the badge always agrees with the
# list underneath it.
SMS_SEND_GOFORM = "SEND_SMS"

# Read parameters. data_per_page is advisory: the device answered with ten
# messages when asked for three, so the cap is applied again on our side.
SMS_MEM_STORE = "1"
SMS_TAGS_ALL = "10"
SMS_ORDER_BY = "order by id desc"
SMS_PAGE_SIZE = "500"

# tag: "1" is an unread inbox message (confirmed live - the count of tag "1"
# rows matched sms_unread_num). The outgoing tags come from the stock UI's own
# folder mapping and are not exercised on a device with no sent messages.
SMS_TAG_UNREAD = "1"
SMS_TAGS_OUTGOING = frozenset({"2", "3", "4"})

# Send. ID "-1" is a new message rather than an edited draft; after the POST is
# accepted the device reports progress on sms_cmd slot 4.
SMS_NEW_ID = "-1"
SMS_SEND_CMD = "4"
SMS_STATUS_FIELD = "sms_cmd_status_result"
SMS_STATUS_FAILED = "2"
SMS_STATUS_SENT = "3"

# Mark read and delete, from the device's own setSmsRead and deleteMessage.
# Both address messages with msg_id: the ids joined by ";" *and* a trailing ";".
# tag 0 is read; the device offers no way back to unread.
SMS_READ_GOFORM = "SET_MSG_READ"
SMS_DELETE_GOFORM = "DELETE_SMS"
SMS_READ_TAG = "0"
# Delete confirms the same way send does - same status field, same 2/3 codes -
# and differs only in which sms_cmd slot it reports on.
SMS_DELETE_CMD = "6"
SMS_SETTLE = 1.0  # the stock UI waits this long before the first status poll
SMS_TIMEOUT = 30.0
SMS_POLL_INTERVAL = 3.0

# GSM 03.38 basic set, lifted verbatim from the device's GSM7_Table. A message
# made entirely of these goes out as GSM7 (160 characters per part); anything
# else has to be UNICODE (70 per part), so this decides the message's cost.
GSM7_CHARS = frozenset(
    "\n\x0c\r !\"#$%&'()*+,-./0123456789:;<=>?@"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_"
    "abcdefghijklmnopqrstuvwxyz{|}~"
    "\xa0¡£¤¥§¿ÄÅÆÇÉÑÖØÜßàäåæèéìñòöøùüΓΔΘΛΞΠΣΦΨΩ€"
)


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


def _hex_bytes(data: str) -> bytes | None:
    """Parse a device hex payload, or None if it is not hex.

    Both USSD replies and SMS bodies arrive hex-encoded, and both have to
    tolerate firmwares that send plain text instead.
    """
    try:
        return bytes.fromhex(data)
    except ValueError:
        return None


def _decode_ussd(data: str, dcs: str) -> str:
    """Decode a USSD ussd_data payload using its data-coding-scheme.

    The device returns ussd_data as a hex string. DCS 0x48 ("72") is UCS2 and
    decodes as UTF-16BE; other coding schemes are treated as one byte per
    character. Anything that is not valid hex (some firmwares send plain text)
    is returned unchanged.
    """
    if not data:
        return ""
    raw = _hex_bytes(data)
    if raw is None:
        return data
    try:
        dcs_value = int(dcs)
    except (TypeError, ValueError):
        dcs_value = 0
    if (dcs_value & USSD_DCS_UCS2_MASK) == USSD_DCS_UCS2_VALUE:
        try:
            return raw.decode("utf-16-be")
        except UnicodeDecodeError:
            return data
    return raw.decode("latin-1")


def _decode_sms(content: str) -> str:
    """Decode an SMS body. Unlike USSD these carry no DCS: always UCS2 hex."""
    if not content:
        return ""
    raw = _hex_bytes(content)
    if raw is None:
        return content
    try:
        text = raw.decode("utf-16-be")
    except UnicodeDecodeError:
        return content
    # The device pads short bodies with NULs; the stock UI drops them too.
    return text.replace("\x00", "")


def _encode_sms(text: str) -> str:
    """Encode an outgoing body the way MessageBody expects: UCS2 hex."""
    return text.encode("utf-16-be").hex().upper()


def _sms_encode_type(text: str) -> str:
    return "GSM7_default" if all(c in GSM7_CHARS for c in text) else "UNICODE"


def _sms_time(when: datetime | None = None) -> str:
    """Format sms_time the way the device's getCurrentTimeString() does.

    "YY;MM;DD;HH;MM;SS;<signed whole-hour UTC offset>", e.g. 26;07;24;15;28;20;+1.
    """
    when = when or datetime.now().astimezone()
    offset = when.utcoffset() or timedelta(0)
    hours = int(offset.total_seconds() / 3600)
    sign = "+" if hours >= 0 else ""
    return f"{when:%y;%m;%d;%H;%M;%S};{sign}{hours}"


def _msg_id_list(ids: Sequence[str]) -> str:
    """Build the msg_id both SET_MSG_READ and DELETE_SMS expect: "659;658;".

    The device's own setSmsRead and deleteMessage join with ";" and leave a
    trailing one, so this matches them exactly.

    Ids reach here from an HTTP request body, and ";" is the separator: an id
    carrying one would quietly widen the operation to messages the caller never
    picked. Since delete is permanent, that is refused rather than sanitised.
    """
    clean = [str(i).strip() for i in ids]
    if not clean or not all(clean):
        raise SmsError("no message ids given")
    for i in clean:
        if ";" in i or any(c.isspace() for c in i):
            raise SmsError(f"invalid message id {i!r}")
    return ";".join(clean) + ";"


def _sms_from_row(row: dict) -> SmsMessage:
    """Build an SmsMessage from one raw device row."""
    tag = str(row.get("tag", "")).strip()
    return SmsMessage(
        id=str(row.get("id", "")),
        number=str(row.get("number", "")),  # plain text, unlike the body
        text=_decode_sms(str(row.get("content", ""))),
        date=_parse_sms_date(str(row.get("date", ""))),
        unread=tag == SMS_TAG_UNREAD,
        outgoing=tag in SMS_TAGS_OUTGOING,
    )


def _parse_sms_date(raw: str) -> str:
    """Turn the device's inbox timestamp into something readable.

    Live samples come back comma-separated ("26,07,24,15,28,20,+4"); the stock
    UI's own parser accepts semicolons too, so both are handled. Anything that
    does not fit is handed back untouched rather than guessed at.
    """
    parts = re.split(r"[;,]", raw.strip())
    if len(parts) < 6:
        return raw
    try:
        yy, mm, dd, hh, mi = (int(p) for p in parts[:5])
    except ValueError:
        return raw
    return f"20{yy:02d}-{mm:02d}-{dd:02d} {hh:02d}:{mi:02d}"


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
    def get(self, *cmds: str, multi: bool | None = None,
            extra: dict | None = None) -> dict:
        params = {"isTest": "false", "cmd": ",".join(cmds)}
        if multi is None:
            multi = len(cmds) > 1
        if multi:
            params["multi_data"] = "1"
        if extra:
            # Some aggregate cmds (the SMS inbox, the SMS status slot) carry
            # their own query parameters alongside cmd.
            params.update(extra)
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
    def ussd_send(
        self, code: str, *, timeout: float = USSD_TIMEOUT, interval: float = USSD_POLL_INTERVAL
    ) -> UssdResult:
        self.post(USSD_SEND_GOFORM, **{
            USSD_OPERATOR_FIELD: USSD_OP_SEND,
            USSD_SEND_FIELD: code,
        })
        return self._ussd_poll(timeout, interval)

    def ussd_reply(
        self, text: str, *, timeout: float = USSD_TIMEOUT, interval: float = USSD_POLL_INTERVAL
    ) -> UssdResult:
        self.post(USSD_SEND_GOFORM, **{
            USSD_OPERATOR_FIELD: USSD_OP_REPLY,
            USSD_REPLY_FIELD: text,
        })
        return self._ussd_poll(timeout, interval)

    def ussd_cancel(self) -> None:
        self.post(USSD_SEND_GOFORM, **{USSD_OPERATOR_FIELD: USSD_OP_CANCEL})

    def _ussd_poll(self, timeout: float, interval: float) -> UssdResult:
        deadline = time.monotonic() + timeout
        while True:
            state = self._classify_flag(self.get(USSD_FLAG_KEY))
            if state == "received":
                return self._read_ussd_data()
            if state == "timeout":
                return UssdResult("", "timeout")
            if state.startswith("error:"):
                return UssdResult(state[len("error:"):], "error")
            # pending ("15", or any other flag the device reports while working)
            if time.monotonic() >= deadline:
                return UssdResult("", "timeout")
            time.sleep(interval)

    def _classify_flag(self, raw: dict) -> str:
        """Map a ussd_write_flag poll response to received/timeout/error:<msg>/pending.

        Raises UssdError when the flag key is absent entirely, which means the
        device speaks a different USSD API than the one captured here. Failing
        fast beats silently polling until the timeout.
        """
        if USSD_FLAG_KEY not in raw:
            raise UssdError(
                f"unexpected USSD poll response (no '{USSD_FLAG_KEY}' key); "
                f"the device may use a different USSD API: {raw}"
            )
        flag = str(raw.get(USSD_FLAG_KEY, "")).strip()
        if flag == USSD_FLAG_RECEIVED:
            return "received"
        if flag in USSD_FLAG_TIMEOUT:
            return "timeout"
        if flag in USSD_FLAG_ERRORS:
            return "error:" + USSD_FLAG_ERRORS[flag]
        return "pending"

    def _read_ussd_data(self) -> UssdResult:
        data = self.get(USSD_DATA_CMD)
        text = _decode_ussd(
            str(data.get(USSD_DATA_FIELD, "")),
            str(data.get(USSD_DCS_FIELD, "")),
        )
        action = str(data.get(USSD_ACTION_FIELD, "")).strip()
        state = "prompt" if action == USSD_ACTION_PROMPT else "complete"
        return UssdResult(text, state)

    # --- SMS ------------------------------------------------------------------
    def sms_list(self, limit: int = 50) -> list[SmsMessage]:
        """Read the inbox, newest first."""
        self.ensure_session()
        data = self.get(SMS_LIST_CMD, extra={
            "page": "0",
            "data_per_page": SMS_PAGE_SIZE,
            "mem_store": SMS_MEM_STORE,
            "tags": SMS_TAGS_ALL,
            "order_by": SMS_ORDER_BY,
        })
        rows = data.get("messages")
        if not isinstance(rows, list):
            # Same reasoning as _classify_flag: a device that speaks a different
            # SMS API should say so, not hand back a silently empty inbox.
            raise SmsError(
                f"unexpected inbox response (no 'messages' list); "
                f"the device may use a different SMS API: {data}"
            )
        # data_per_page is advisory - the device returned ten rows when asked
        # for three - so the cap is enforced here too.
        return [_sms_from_row(row) for row in rows[:limit]]

    def sms_send(self, number: str, text: str, *, timeout: float = SMS_TIMEOUT,
                 interval: float = SMS_POLL_INTERVAL,
                 settle: float = SMS_SETTLE) -> None:
        """Send one message and wait for the network to confirm it."""
        number, text = number.strip(), text.strip()
        if not number:
            raise SmsError("no recipient")
        if not text:
            raise SmsError("empty message")
        data = self.post(SMS_SEND_GOFORM, **{
            "Number": number,
            "sms_time": _sms_time(),
            "MessageBody": _encode_sms(text),
            "ID": SMS_NEW_ID,
            "encode_type": _sms_encode_type(text),
        })
        if str(data.get("result")) != "success":
            raise SmsError(
                f"router rejected the message: result={data.get('result')}")
        if settle:
            # The stock UI gives the modem a moment before its first poll.
            time.sleep(settle)
        self._sms_poll(timeout, interval)

    def sms_mark_read(self, ids: Sequence[str]) -> int:
        """Mark messages read. Returns how many were addressed.

        One shot: unlike send and delete the device answers immediately and
        reports nothing on a status slot. There is no way back to unread.
        """
        msg_id = _msg_id_list(ids)
        data = self.post(SMS_READ_GOFORM, msg_id=msg_id, tag=SMS_READ_TAG)
        if str(data.get("result")) != "success":
            raise SmsError(
                f"router refused to mark as read: result={data.get('result')}")
        return len(ids)

    def sms_delete(self, ids: Sequence[str], *, timeout: float = SMS_TIMEOUT,
                   interval: float = SMS_POLL_INTERVAL,
                   settle: float = SMS_SETTLE) -> int:
        """Delete messages and wait for the device to confirm. Permanent."""
        msg_id = _msg_id_list(ids)
        data = self.post(SMS_DELETE_GOFORM, msg_id=msg_id)
        if str(data.get("result")) != "success":
            raise SmsError(
                f"router refused to delete: result={data.get('result')}")
        if settle:
            time.sleep(settle)
        self._sms_poll(timeout, interval, cmd=SMS_DELETE_CMD,
                       actor="the device", what="the delete")
        return len(ids)

    def _sms_poll(self, timeout: float, interval: float,
                  cmd: str = SMS_SEND_CMD, actor: str = "the network",
                  what: str = "the message") -> None:
        """Wait on one of the device's sms_cmd status slots.

        Send and delete report the same way - same field, same 2/3 codes - and
        differ only in the slot, so they share this rather than growing a
        second copy. Only the wording differs: a send is refused by the network,
        a delete by the device itself.
        """
        deadline = time.monotonic() + timeout
        while True:
            data = self.get(SMS_STATUS_CMD, extra={"sms_cmd": cmd})
            status = str(data.get(SMS_STATUS_FIELD, "")).strip()
            if status == SMS_STATUS_SENT:
                return
            if status == SMS_STATUS_FAILED:
                raise SmsError(f"{actor} rejected {what}")
            # No status field at all means nothing is queued on that slot yet:
            # the live device answers {"messages": []} until the send lands.
            # Treat it as pending so a slow network is not called a failure.
            if time.monotonic() >= deadline:
                raise SmsError(
                    f"timed out waiting for {actor} to confirm {what}")
            time.sleep(interval)

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
