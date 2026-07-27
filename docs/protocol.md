# The ZLT / ZTE `reqproc` protocol

Everything `zlt` knows about the router's undocumented JSON API. Derived from
the device's own served JavaScript (`/js/service.js`, `/js/util.js`,
`/js/config/ufi/config.js`) and confirmed against a live device.

This is the reference to read if you are porting `zlt` to different firmware or
debugging why a call behaves differently on your hardware. For installing and
using `zlt`, see the [README](../README.md).

All of it lives behind one class, `ZltClient` in `zlt/client.py`. The CLI and
web layers never re-implement any of it.

## Porting to other devices

Built and live-verified against one device: the **MTN ZLT T10D MAX**, a ZTE
NV8645 CPE (`cr_version: CPE_NV8645_230A_E_QX_CAN-P42U17-20250703`,
`DEVICE: "ufi"` in its own `config.js`).

The `reqproc` API, the `goformId=LOGIN` nonce-salted SHA-256 password scheme,
and the `CSRFToken`/`get_token` mechanism are shared across a wider family of
ZTE firmware used in many rebranded 4G/LTE CPE and MiFi routers, so `zlt` will
likely connect, log in, and read status on similar devices with little or no
change.

Do not assume the field-level details carry over:

- **The network-mode key is not consistent even within this device family.** See
  [Reading back the configured mode](#reading-back-the-configured-mode) below,
  where this device needed `net_select` rather than the key its own JS
  suggested.
- **Session handling differs by build.** This device authenticates via a
  `random` cookie. Other ZTE variants (some Safaricom-branded ZTE M30S Pro
  units, per community documentation) bind the session to the client's IP with
  no cookie at all. Verify which model applies before assuming the cookie logic
  works as-is.
- **`BearerPreference` values, status key names, and lockout thresholds** may
  vary by firmware version even on nominally the same hardware.

Start with the read-only commands (`zlt status`, `zlt get <cmd>`) before
`zlt login`. They need no authentication and will quickly show whether the API
shape matches.

When porting, the device-specific constants and the `_classify_flag` /
`_read_ussd_data` / `_decode_*` / `_sms_*` helpers at the top of `client.py` are
the single point of change.

## Endpoints

- **Reads:** `GET /reqproc/proc_get?isTest=false[&multi_data=1]&cmd=<comma,separated,keys>`
  → JSON. Response keys echo the requested `cmd` names. `multi_data=1` is sent whenever
  more than one `cmd` is requested.
- **Writes:** `POST /reqproc/proc_post`, body
  `isTest=false&goformId=<ACTION>&...&CSRFToken=<token>`,
  `Content-Type: application/x-www-form-urlencoded; charset=UTF-8`.
- **Headers replicated from the web UI:** `Referer: <host>/index.html`,
  `X-Requested-With: XMLHttpRequest`.
- **Session:** carried by a cookie named `random`, set by a successful `LOGIN` POST.
  Stored server-side per-cookie, not IP-bound: an unauthenticated request from the same
  machine gets empty/unauthenticated results even while the web UI is independently
  logged in; only presenting the actual session cookie authenticates.

## Login (exact scheme, live-verified end to end)

```
1. GET  proc_get?isTest=false&cmd=get_random_login  ->  {"random_login": "<nonce>"}
2. username = Base64( plaintext_username )
   password = Base64( sha256_hex( random_login + plaintext_password ) )
   token    = GET proc_get?isTest=false&cmd=get_token  (raw value; empty is valid pre-login)
3. POST proc_post:
     isTest=false
     goformId=LOGIN
     username=<base64>
     password=<base64>
     CSRFToken=<token or empty>
```

- `sha256_hex` is a lowercase hex digest; the whole hex *string* is then Base64-encoded
  (not the raw digest bytes).
- Success: `result == "0"` (fresh login) or `result == "4"` (already logged in). Either
  counts as authenticated and the session cookie is cached.
- Any other `result` is a rejected login (wrong password, etc.) and raises `LoginError`.

## CSRF token

```
GET proc_get?isTest=false&cmd=get_token  ->  {"token": "<value>"}   (or {"get_token": "<value>"})
```

- Used **raw** as the `CSRFToken` field on every POST (no hashing).
- Empty (`""`) before login is valid and accepted for the `LOGIN` POST itself; a non-empty
  value appears once a session cookie is presented, and is fetched fresh before every
  subsequent write.

## Network mode (bearer preference)

Write: `POST goformId=SET_BEARER_PREFERENCE&BearerPreference=<value>`, success is
`result == "success"`.

| CLI mode | `BearerPreference` value | Web UI label |
|---|---|---|
| `auto` | `NETWORK_auto` | Automatic |
| `lte`, `4g` | `Only_LTE` | 4G Only |
| `4g3g` | `TD_W_LTE` | 4G/3G Only |
| `wcdma`, `3g` | `TD_W` | 3G Only |
| `gsm`, `2g` | `Only_GSM` | 2G Only |

All five values are live-verified against the real device (not just read from config JS).
Note `wcdma`/`3g` maps to `TD_W`, **not** `Only_WCDMA`.

### Reading back the configured mode

An important corrected finding. The web UI's own JS reads a batch of keys to
display the configured mode: `current_network_mode, net_select_mode,
m_netselect_save, m_netselect_contents, net_select, ppp_status,
modem_main_state`. On this device/firmware, most of those come back **empty even
when authenticated**. `net_select_mode` and `m_netselect_save` are *not*
reliable. The key that actually holds the configured preference on this hardware
is **`net_select`** (e.g. `net_select: "NETWORK_auto"`).

`zlt net get` / `zlt net set` query `NET_KEYS = ["current_network_mode",
"net_select_mode", "m_netselect_save", "net_select"]` and resolve the configured value
with `net_select` checked **first**, falling back to `net_select_mode` then
`m_netselect_save` only if `net_select` is empty (for forward-compatibility with other
firmware builds). If you're porting this to a different ZTE/ZLT firmware, verify which
of these keys is actually populated on your device before trusting the fallback order.

## Status / signal keys

- **Open (no login required):** `network_type` (LTE/WCDMA/GSM), `rssi` (dBm),
  `signalbar` (0-5), `lte_rsrq` (dB), `lte_pci`, `ppp_status`.
- **Auth-only (empty until logged in):** `lte_rsrp` (dBm), `lte_band`, `lte_snr` (dB).
- `zlt status` requests the open set unconditionally, and additionally requests the
  auth-only set (attempting a login first), falling back to the open-only view with a
  note if there's no password configured or login fails.

## SMS (live-verified)

Derived from the device's `sendSMS` / `getSMSMessages` / `getSmsStatusInfo` in
`js/service.js` and `getCurrentTimeString` / `encodeMessage` / `getEncodeType` in
`js/util.js`, then confirmed against the live device. All of it needs a session.

**Read the inbox** (`cmd=sms_data_total`, with its own query parameters
alongside `cmd`):

```http
GET /reqproc/proc_get?isTest=false&cmd=sms_data_total&page=0
    &data_per_page=500&mem_store=1&tags=10&order_by=order by id desc
→ {"messages": [{"id","number","content","tag","date","draft_group_id"}, ...]}
```

- `content` is **UCS2 hex** (UTF-16BE, 4 hex digits per unit). NUL padding is stripped.
- `number` is **plain text**, not hex (`"121"`, `"MTNN"`).
- `tag` `"1"` is an unread inbox message; `"2"`/`"3"`/`"4"` are the outgoing folders.
- `date` came back comma-separated on this device (`26,07,24,15,28,20,+4`). The
  stock UI's own parser also accepts semicolons, so both are handled.
- `data_per_page` is **advisory**: asked for 3, the device returned 10. The limit
  is applied again client-side.

**Send** (costs money; confirmed by sending a real message):

```http
POST /reqproc/proc_post
  goformId=SEND_SMS & Number=<plain> & sms_time=<YY;MM;DD;HH;MM;SS;+TZ>
  & MessageBody=<UCS2 hex> & ID=-1 & encode_type=<GSM7_default|UNICODE>
```

then poll until the network answers:

```http
GET /reqproc/proc_get?isTest=false&cmd=sms_cmd_status_info&sms_cmd=4
→ sms_cmd_status_result: "3" sent, "2" failed, anything else keep waiting
```

- `encode_type` is `GSM7_default` when every character is in the GSM 03.38 basic
  set (lifted verbatim from the device's `GSM7_Table`), else `UNICODE`. This
  decides the message's cost: 160 characters per part versus 70. Note that `é` is
  in the GSM7 set; it takes a genuinely foreign character to force `UNICODE`.
- `MessageBody` is always UCS2 hex regardless of `encode_type`.
- **Idle slot quirk:** `sms_cmd_status_info` answers `{"messages": []}`, with no
  status key at all, when nothing is queued on that slot. A missing status is
  treated as pending, so a slow send is not misreported as a failure.

**Mark read and delete** (from the device's own `setSmsRead` and `deleteMessage`):

```http
POST /reqproc/proc_post
  goformId=SET_MSG_READ & msg_id=<659;658;> & tag=0
→ result: "success", answered immediately

POST /reqproc/proc_post
  goformId=DELETE_SMS & msg_id=<659;658;>
→ result: "success", then poll sms_cmd_status_info with sms_cmd=6
```

- `msg_id` is the ids joined with `;` **and a trailing `;`**. Both device
  functions build it that way.
- `tag=0` is read. The device offers no way back to unread.
- Delete confirms on the same status field and the same `"3"`/`"2"` codes as
  send, differing only in the `sms_cmd` slot: `6` for delete, `4` for send. The
  two share one poll here rather than growing a second copy.
- `ALL_DELETE_SMS` also exists on the device and is deliberately unused: Select
  all plus Delete clears the inbox without a second, blunter code path.
- An id carrying a `;` would widen the operation to messages the caller never
  picked, so ids are rejected rather than sanitised.

**`sms_unread_num` is deliberately unused.** It was observed reporting `0` while
the inbox still held 29 rows tagged unread. The unread count is derived from the
rows instead, so the dashboard badge cannot disagree with the list beneath it.

## Safety / lockout keys

- `psw_fail_num_str`: **attempts remaining** before lockout (not a failure counter).
  Empty response defaults to `5` (`MAX_LOGIN_COUNT`).
- `login_lock_time`: lockout duration in seconds once attempts are exhausted. Empty
  response defaults to `300`.
- **Guard:** before any login attempt, `zlt` reads both keys and refuses to proceed
  (`LockedOut`) if attempts remaining `< 2`, printing the state and pointing at the web
  UI to reset. No password is ever guessed or retried blindly: the encoding is exact,
  so a correct login succeeds on the first try.

## Auth-failure retry (writes)

`zlt post` / `net set` first ensure a session (`ensure_session()`: log in only if the
current `get_token` comes back empty). If a subsequent write's `result` matches a
best-effort marker set (`no_session`, `session_error`, `need_login`, `not_login`, `-1`),
the client re-logs in once and retries the write; a second failure raises. These markers
are a backstop only. The primary "am I authenticated" check is always
`token() != ""`.
