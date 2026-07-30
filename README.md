# zlt

A small, fast CLI and local web dashboard for the **MTN ZLT T10D MAX** (ZTE NV8645 CPE)
4G router, so you never have to open the slow web UI. Talks directly to the device's own
JSON API over the LAN.

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
- Read and change the network mode / bearer preference (`zlt net get`, `zlt net set`).
- Read, send, mark read and delete SMS (`zlt sms ...`).
- A local dashboard with a live signal meter, walk test, USSD and messages (`zlt serve`).
- Config and session cache live under your home directory (XDG paths), so the command
  works from any directory once installed.

There is also an **Android app**, [Router Signal](https://github.com/exbyte-dev/zlt-android),
which ports the login and `reqproc` handling from this project. It covers signal,
connection state and the network mode switcher, with a Quick Settings tile. This
project remains the reference for the protocol — see [`docs/protocol.md`](docs/protocol.md).

## Install

Needs [pipx](https://pipx.pypa.io). It puts `zlt` on your PATH in an isolated
environment, and works the same on Linux, macOS and Windows.

```bash
pipx install zltrouter
```

The package is `zltrouter` but the command it installs is **`zlt`**, which is
what every example below uses. (Plain `zlt` is not available on PyPI.)

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

### Upgrading from a pre-0.4 install

Earlier versions used `./install.sh`, which built a project-local `.venv` and
symlinked `~/.local/bin/zlt` at it. pipx will not overwrite a file it does not
own, so remove the old install first, or a stale symlink shadows the real entry
point on your PATH.

```bash
systemctl --user disable --now zlt-web          # if you ran ./service.sh
rm -f ~/.config/systemd/user/zlt-web.service
systemctl --user daemon-reload
rm -f ~/.local/bin/zlt
pipx install zltrouter
```

## Command reference

| Command | Auth? | Description |
|---|---|---|
| `zlt status` | best-effort | Shows signal/network status. Tries to log in for full detail (adds RSRP, band, SNR); falls back to the open subset if no password is configured or login fails. |
| `zlt net get` | yes | Shows the router's configured network mode, mapped to a friendly name (`auto`, `lte`, `4g3g`, `wcdma`, `gsm`). |
| `zlt net set <mode>` | yes | Sets the network mode. `<mode>` is one of `auto \| lte \| 4g \| 4g3g \| wcdma \| 3g \| gsm \| 2g`. Verifies the POST result, then re-reads to confirm the change took. |
| `zlt sms list` | yes | Shows the inbox, newest first, id in the first column, unread marked with `*`. `--limit` caps how many (default 20). |
| `zlt sms send <number> <text>` | yes | Sends a message and waits for the network to confirm it. Costs money. |
| `zlt sms read <id>...` | yes | Marks one or more messages read. The device has no way back to unread. |
| `zlt sms rm <id>...` | yes | Deletes one or more messages and waits for the device to confirm. Permanent, and it does not prompt. |
| `zlt get <cmd> [cmd ...]` | no | Raw `proc_get` passthrough: pretty-prints the JSON response for any key(s) the device supports. |
| `zlt post <goformId> [key=val ...]` | yes | Raw `proc_post` passthrough: ensures a session, attaches a fresh CSRF token, prints the JSON response. |
| `zlt login` | yes | Forces a fresh login, prints attempts remaining before the lockout, caches the session cookie. |
| `zlt init-config` | no | Interactively writes `~/.config/zlt/config` (`chmod 600`). Flags: `--host`, `--username`; password is prompted (hidden input). |
| `zlt --version` | no | Prints the installed version. |

Every authenticated command transparently logs in first if there's no valid cached
session, and every write retries once with a fresh login if the router reports an
auth failure mid-request.

## Web dashboard

A local browser UI over the same client, for the things a one-shot CLI can't do:
watching signal move live while you reposition the router, and flipping network
mode with a tap from your phone.

```bash
zlt serve                      # http://127.0.0.1:8464
zlt serve --host 0.0.0.0       # reachable from other LAN devices (see note)
```

- **Pinned meter, tabbed tools:** the reading, quality word and range bar stay on
  screen whichever tab you are on, and fold to a single line once you scroll.
  Tabs are `#signal`, `#messages`, `#ussd` and `#speed`, so a tab is linkable and
  the back button moves between them.
- **Walk test strip:** rolling 15-minute RSRP/RSSI history, so you can carry the
  router around and watch the line respond. It keeps recording on every tab.
- **Live meter and tiles:** RSRP (or RSSI when not logged in), band, SNR, RSRQ,
  PCI, bars, PPP state, polled every 1/3/10s with pause.
- **Network mode switching:** the same write as `zlt net set`, verified and
  re-read after each change.
- **USSD codes:** send a code and see the reply inline; interactive menus can be
  replied to and cancelled; saved codes appear as one-click buttons. The list is
  the same `~/.config/zlt/ussd.json` the CLI uses, so codes saved either way show
  up in both.
- **Messages:** the SMS inbox with unread marked and counted, plus a compose box.
  "Select" turns the list into checkboxes with Select all, and marks the
  selection read or deletes it in one go. Deleting asks once, inline.
- **Speed test:** an on-demand download/upload/ping test that runs in the browser,
  so it measures the link of whatever device you opened the panel on (phone
  included), through the router, out over 4G. Both directions are time-boxed
  rather than fixed-size, so a weak cell finishes in seconds instead of minutes.
- **Light / dark:** follows your system theme by default; the toggle in the header
  overrides it and the choice sticks.
- Served entirely from the local server, zero CDN dependencies and no build step:
  it works when the router LAN is your only network.

The dashboard binds to `127.0.0.1` by default and has **no authentication of its
own**. If you bind `0.0.0.0`, anyone on the LAN who can reach the port can read
status and change router settings, so only do that on a network you trust.

### Speed test target

The measurement is browser-to-target with no backend in the middle, so the target
has to be a public host that sends CORS headers. The default is Cloudflare's
speed backend, which does:

| Setting | Default | Meaning |
|---|---|---|
| `ZLT_SPEEDTEST_DOWN_URL` | `https://speed.cloudflare.com/__down` | Download endpoint. A `bytes=` query parameter is appended. |
| `ZLT_SPEEDTEST_UP_URL` | `https://speed.cloudflare.com/__up` | Upload endpoint, sent a POST body. |
| `ZLT_SPEEDTEST_DOWN_BYTES` | `25000000` | Upper bound on the download. The stream stops early at 8s, so this is a ceiling, not a fixed cost. |
| `ZLT_SPEEDTEST_UP_BYTES` | `8000000` | Upper bound on the upload. A 512 KB probe sizes the real run to about 5s, capped here. |

These follow the same resolution order as everything else. A non-numeric or
non-positive byte count falls back to the default rather than breaking the panel.

## Compatibility with other ZLT/ZTE devices

Built and live-verified against one device, but the underlying `reqproc` API and
login scheme are shared across a wider family of ZTE firmware used in many
rebranded 4G/LTE CPE and MiFi routers, so `zlt` will likely connect, log in, and
read status on similar devices with little or no change.

Field-level details do vary by firmware, though: the network-mode key, session
handling, and lockout thresholds all differ across builds. Start with the
read-only commands (`zlt status`, `zlt get <cmd>`) before `zlt login` - they need
no authentication and will quickly show whether the API shape matches.

If you're porting, the caveats and the full protocol are documented in
[docs/protocol.md](https://github.com/exbyte-dev/zltrouter/blob/master/docs/protocol.md).

## Safety notes

- The router locks out login after **5** failed attempts (`MAX_LOGIN_COUNT`), for
  **300s** (`login_lock_time`) by default.
- `zlt` refuses to attempt a login at all if the router reports fewer than 2
  attempts remaining, to avoid ever being the thing that trips the lockout.
- If a live command ever reports few attempts remaining, **stop** and log in via the
  router's web UI first to reset the counter before retrying with `zlt`.
- Every write in this CLI happens only on an explicit command (`net set`, `post`,
  `login`).

## Documentation

- **[docs/protocol.md](https://github.com/exbyte-dev/zltrouter/blob/master/docs/protocol.md)**
  - the reverse-engineered router API: endpoints, login scheme, CSRF, bearer
  values, SMS encoding, status and lockout keys. Read this to port `zlt` to
  different hardware.
- **[CONTRIBUTING.md](https://github.com/exbyte-dev/zltrouter/blob/master/CONTRIBUTING.md)**
  - development setup, architecture, the dashboard's own JSON API, manual
  verification steps, and the release process.

## License

MIT. See [LICENSE](https://github.com/exbyte-dev/zltrouter/blob/master/LICENSE).
