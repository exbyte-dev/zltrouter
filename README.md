# zlt

A small, fast CLI for the **MTN ZLT T10D MAX** (ZTE NV8645 CPE) 4G router, so you never
have to open the slow web UI. Talks directly to the device's own JSON API
(`reqproc/proc_get` / `reqproc/proc_post`) over the LAN.

Verified live against firmware `CPE_NV8645_230A_E_QX_CAN-P42U17-20250703`.

> **Disclaimer:** This is an independent, reverse-engineered client built by reading the
> router's own served JavaScript and observing its behavior. It is **not affiliated with,
> endorsed by, or supported by ZTE, MTN, or any carrier**. The API it talks to is
> undocumented and unofficial. It can change or break on a firmware update with no
> notice. Use at your own risk, especially the write commands (`net set`, `post`,
> `login`); see [Safety notes](#safety-notes) before pointing this at a device you can't
> physically reset.

## Overview

- Read signal/network status without logging in (`zlt status`, `zlt get ...`).
- Log in exactly the way the web UI does (`zlt login`), with a safety guard against
  triggering the router's login lockout.
- Read and change the network mode / bearer preference (`zlt net get`, `zlt net set`).
- Raw passthroughs (`zlt get`, `zlt post`) for anything not first-classed above.
- Config and session cache live under your home directory (XDG paths), so the command
  works from any directory once installed.

## Compatibility with other ZLT/ZTE devices

Built and live-verified against one device: the **MTN ZLT T10D MAX**, a ZTE NV8645 CPE
(`cr_version: CPE_NV8645_230A_E_QX_CAN-P42U17-20250703`, `DEVICE: "ufi"` in its own
`config.js`). The underlying `reqproc/proc_get` + `reqproc/proc_post` API, the
`goformId=LOGIN` nonce-salted SHA-256 password scheme, and the `CSRFToken`/`get_token`
mechanism are shared across a wider family of ZTE "reqproc" firmware used in many
rebranded 4G/LTE CPE and MiFi routers (other ZLT-branded units, other carriers' rebrands
of the same ZTE hardware), so `zlt` will likely connect, log in, and read status on
similar devices with little or no change.

That said, don't assume the field-level details carry over unmodified:

- The exact `proc_get` key that holds the configured network mode is **not** consistent
  even within this device family: see "Reading back the configured mode" below, where
  this device needed a different key (`net_select`) than the one the reference
  implementation's own JS suggested.
- Session handling can differ by firmware build: this device authenticates via a
  `random` cookie; other ZTE variants (e.g. some Safaricom-branded ZTE M30S Pro units,
  per community documentation used as a reference during development) instead bind the
  session to the client's IP with no cookie at all. If porting to another device, verify
  which model applies before assuming `zlt`'s cookie-based session logic works as-is.
- `BearerPreference` values, status key names, and lockout thresholds
  (`MAX_LOGIN_COUNT`/`login_lock_time`) may vary by firmware version even on nominally
  the same hardware.

If you're trying this against a different ZLT/ZTE router, start with the read-only
commands (`zlt status`, `zlt get <cmd>`) before `zlt login`. They require no
authentication and will quickly show whether the API shape matches.

## Install

Needs [pipx](https://pipx.pypa.io). It puts `zlt` on your PATH in an isolated
environment, and works the same on Linux, macOS and Windows.

```bash
pipx install zlt
```

Then bootstrap your config. It prompts for the router admin password, writes
`~/.config/zlt/config` with `chmod 600`, and offers to run the dashboard
automatically on login:

```bash
zlt init-config                                  # host/username default to
                                                 #   http://192.168.0.1 / admin
zlt init-config --host http://192.168.8.1 --username admin
zlt init-config --no-service                     # skip the autostart offer
```

See `.env.example` for the file format if you'd rather write it by hand (or use a
project-local `.env` during development; never commit real secrets).

### Upgrading from a pre-0.4 install

Earlier versions used `./install.sh`, which built a project-local `.venv` and
symlinked `~/.local/bin/zlt` at it. pipx will not overwrite a file it does not
own, so remove the old install first. Skipping this leaves a stale symlink
shadowing the real entry point on your PATH.

```bash
systemctl --user disable --now zlt-web          # if you ran ./service.sh
rm -f ~/.config/systemd/user/zlt-web.service
systemctl --user daemon-reload
rm -f ~/.local/bin/zlt
rm -rf .venv
pipx install zlt
```

### Running the dashboard on login

`zlt init-config` offers this, and you can do it any time:

```bash
zlt service install        # start on login, bound to 0.0.0.0:8464
zlt service status
zlt service logs
zlt service suspend        # stop without uninstalling
zlt service resume
zlt service uninstall
```

The backend is picked for you: a systemd `--user` unit on Linux, a LaunchAgent
on macOS, a Task Scheduler on-logon task on Windows. Run
`zlt service print-artifact` to see exactly what would be written.

One difference worth knowing: on Linux a suspended service returns at your next
login, while on macOS and Windows it stays down until `zlt service resume`.

> The Linux path is tested on real hardware. The macOS and Windows backends have
> their generated artifacts covered by tests and are exercised in CI, but the
> `launchctl` and `schtasks` calls themselves are not yet verified on real
> machines. Reports welcome.

### Config resolution order

1. Environment variables `ZLT_HOST`, `ZLT_USERNAME`, `ZLT_PASSWORD`.
2. `$XDG_CONFIG_HOME/zlt/config` (default `~/.config/zlt/config`).
3. A project-local `./.env`, if present.

Defaults: `ZLT_HOST=http://192.168.0.1`, `ZLT_USERNAME=admin`. `ZLT_PASSWORD` is only
required for commands that need to log in.

Session cache (the authenticated cookie): `$XDG_STATE_HOME/zlt/session.json`
(default `~/.local/state/zlt/session.json`), written `chmod 600`.

## Command reference

| Command | Auth? | Description |
|---|---|---|
| `zlt status` | best-effort | Shows signal/network status. Tries to log in for full detail (adds RSRP, band, SNR); falls back to the open subset if no password is configured or login fails. |
| `zlt net get` | yes | Shows the router's configured network mode, mapped to a friendly name (`auto`, `lte`, `4g3g`, `wcdma`, `gsm`). |
| `zlt net set <mode>` | yes | Sets the network mode. `<mode>` is one of `auto \| lte \| 4g \| 4g3g \| wcdma \| 3g \| gsm \| 2g`. Verifies the POST result, then re-reads to confirm the change took. |
| `zlt get <cmd> [cmd ...]` | no | Raw `proc_get` passthrough: pretty-prints the JSON response for any key(s) the device supports. |
| `zlt post <goformId> [key=val ...]` | yes | Raw `proc_post` passthrough: ensures a session, attaches a fresh CSRF token, prints the JSON response. |
| `zlt login` | yes | Forces a fresh login, prints attempts remaining before the lockout, caches the session cookie. |
| `zlt init-config` | no | Interactively writes `~/.config/zlt/config` (`chmod 600`). Flags: `--host`, `--username`; password is prompted (hidden input). |
| `zlt --version` | no | Prints the installed version. |

Every authenticated command transparently logs in first if there's no valid cached
session (`ensure_session()`), and every write retries once with a fresh login if the
router reports an auth failure mid-request.

## Web dashboard

A local browser UI over the same client, for the things a one-shot CLI can't do:
watching signal move live while you reposition the router, and flipping network
mode with a tap from your phone.

```bash
zlt serve                      # http://127.0.0.1:8464
zlt serve --host 0.0.0.0       # reachable from other LAN devices (see note)
```

- **Walk test strip:** rolling 15-minute RSRP/RSSI history, so you can carry the
  router around and watch the line respond.
- **Live meter and tiles:** RSRP (or RSSI when not logged in), band, SNR, RSRQ,
  PCI, bars, PPP state, polled every 1/3/10s with pause.
- **Network mode switching:** the same `SET_BEARER_PREFERENCE` write as
  `zlt net set`, verified and re-read after each change.
- **USSD codes:** send a code and see the reply inline; interactive menus can be
  replied to and cancelled; saved codes appear as one-click buttons. "Manage"
  turns that row into an editor for adding and removing codes, so the default
  view stays a clean set of send buttons. The list is the same
  `~/.config/zlt/ussd.json` the CLI uses, so codes saved either way show up in
  both.
- **Light / dark:** follows your system theme by default; the toggle in the header
  overrides it and the choice sticks.
- Single self-contained HTML page, zero CDN dependencies: it works when the
  router LAN is your only network.
- All auth (nonce login, CSRF, lockout guard, session cache) is delegated to
  `ZltClient`; the web layer adds no second implementation of any of it.

The dashboard binds to `127.0.0.1` by default and has **no authentication of its
own**. If you bind `0.0.0.0`, anyone on the LAN who can reach the port can read
status and change router settings, so only do that on a network you trust.

API surface (all JSON): `GET /api/status`, `GET /api/net`,
`POST /api/net {"mode": "lte"}`, `GET /api/ussd/codes`,
`POST /api/ussd/codes {"label": "Balance", "code": "*310#"}`,
`DELETE /api/ussd/codes {"label": "Balance"}`,
`POST /api/ussd/send {"code": "*310#"}`, `POST /api/ussd/reply {"text": "1"}`,
`POST /api/ussd/cancel`. USSD is the worked example of this pattern: adding
another write feature (SMS, etc.) is one endpoint here plus one panel in
`zlt/static/index.html`; the raw `client.post()` passthrough already handles
CSRF and auth-retry for any `goformId` you capture from the stock UI.

To keep the dashboard always up (so you can hit it from your phone without leaving
a terminal open), see ["Running the dashboard on login"](#running-the-dashboard-on-login)
in the Install section above for `zlt service install` and friends.

## Discovered API reference

Derived from the device's own served JavaScript (`/js/service.js`,
`/js/config/ufi/config.js`) and confirmed against the live device.

### Endpoints

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

### Login (exact scheme, live-verified end to end)

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

### CSRF token

```
GET proc_get?isTest=false&cmd=get_token  ->  {"token": "<value>"}   (or {"get_token": "<value>"})
```

- Used **raw** as the `CSRFToken` field on every POST (no hashing).
- Empty (`""`) before login is valid and accepted for the `LOGIN` POST itself; a non-empty
  value appears once a session cookie is presented, and is fetched fresh before every
  subsequent write.

### Network mode (bearer preference)

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

#### Reading back the configured mode: important, corrected finding

The web UI's own JS reads a batch of keys to display the configured mode:
`current_network_mode, net_select_mode, m_netselect_save, m_netselect_contents,
net_select, ppp_status, modem_main_state`. On this device/firmware, most of those come
back **empty even when authenticated**. `net_select_mode` and `m_netselect_save` are
*not* reliable. The key that actually holds the configured preference on this hardware
is **`net_select`** (e.g. `net_select: "NETWORK_auto"`).

`zlt net get` / `zlt net set` query `NET_KEYS = ["current_network_mode",
"net_select_mode", "m_netselect_save", "net_select"]` and resolve the configured value
with `net_select` checked **first**, falling back to `net_select_mode` then
`m_netselect_save` only if `net_select` is empty (for forward-compatibility with other
firmware builds). If you're porting this to a different ZTE/ZLT firmware, verify which
of these keys is actually populated on your device before trusting the fallback order.

### Status / signal keys

- **Open (no login required):** `network_type` (LTE/WCDMA/GSM), `rssi` (dBm),
  `signalbar` (0-5), `lte_rsrq` (dB), `lte_pci`, `ppp_status`.
- **Auth-only (empty until logged in):** `lte_rsrp` (dBm), `lte_band`, `lte_snr` (dB).
- `zlt status` requests the open set unconditionally, and additionally requests the
  auth-only set (attempting a login first), falling back to the open-only view with a
  note if there's no password configured or login fails.

### Safety / lockout keys

- `psw_fail_num_str`: **attempts remaining** before lockout (not a failure counter).
  Empty response defaults to `5` (`MAX_LOGIN_COUNT`).
- `login_lock_time`: lockout duration in seconds once attempts are exhausted. Empty
  response defaults to `300`.
- **Guard:** before any login attempt, `zlt` reads both keys and refuses to proceed
  (`LockedOut`) if attempts remaining `< 2`, printing the state and pointing at the web
  UI to reset. No password is ever guessed or retried blindly: the encoding is exact,
  so a correct login succeeds on the first try.

### Auth-failure retry (writes)

`zlt post` / `net set` first ensure a session (`ensure_session()`: log in only if the
current `get_token` comes back empty). If a subsequent write's `result` matches a
best-effort marker set (`no_session`, `session_error`, `need_login`, `not_login`, `-1`),
the client re-logs in once and retries the write; a second failure raises. These markers
are a backstop only. The primary "am I authenticated" check is always
`token() != ""`.

## Safety notes

- The router locks out login after **5** failed attempts (`MAX_LOGIN_COUNT`), for
  **300s** (`login_lock_time`) by default.
- `zlt` refuses to attempt a login at all if `psw_fail_num_str` reports fewer than 2
  attempts remaining, to avoid ever being the thing that trips the lockout.
- If a live command ever reports few attempts remaining, **stop** and log in via the
  router's web UI first to reset the counter before retrying with `zlt`.
- Discovery (reading `service.js`/`config.js`) is inherently read-only; every write in
  this CLI happens only on an explicit command (`net set`, `post`, `login`).

## Manual live verification checklist

Run these by hand against the real router on the LAN (not part of the automated test
suite, which mocks all HTTP):

1. `zlt status`: confirm the reported network type / signal bars / RSSI match what the
   router's web UI shows.
2. `zlt net get`: confirm it reports the mode currently configured in the web UI.
3. `zlt net set lte` then `zlt net get`: confirm the mode round-trips to `lte` /
   `Only_LTE`, then `zlt net set auto` to restore the default (`NETWORK_auto`).

## Development

pipx is for using `zlt`. To work on it, use a normal virtualenv:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -v
```

All HTTP is mocked in tests (via `responses`); no test talks to a real device.
