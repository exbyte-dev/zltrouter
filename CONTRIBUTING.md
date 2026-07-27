# Contributing to zlt

## Development setup

pipx is for *using* `zlt`. To work on it, use a normal virtualenv:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -v
```

All HTTP is mocked in tests (via `responses`); no test talks to a real device.
CI runs the suite across Linux/macOS/Windows on Python 3.11-3.13.

## Architecture in one paragraph

`zlt/client.py` (`ZltClient`) is the only place that knows the router protocol:
nonce+SHA-256 login, CSRF fetching, the lockout guard, session caching, and the
SMS/USSD state machines. Three thin layers sit on top: `zlt/cli.py` (Click
commands), `zlt/web.py` (`create_app(client)`, a FastAPI app whose single lock
serializes all router traffic), and `zlt/service.py` (cross-platform autostart).
The layers never re-implement protocol logic. See
[docs/protocol.md](docs/protocol.md) for the protocol itself.

## Adding a dashboard feature

The dashboard's own JSON API:

```
GET    /api/status                GET    /api/net
POST   /api/net                   {"mode": "lte"}
GET    /api/speedtest/config      GET    /api/sms
POST   /api/sms/send              {"number": "121", "text": "hi"}
POST   /api/sms/read              {"ids": ["659"]}
POST   /api/sms/delete            {"ids": ["659"]}
GET    /api/ussd/codes            POST   /api/ussd/codes    {"label": "Balance", "code": "*310#"}
DELETE /api/ussd/codes            {"label": "Balance"}
POST   /api/ussd/send             {"code": "*310#"}
POST   /api/ussd/reply            {"text": "1"}
POST   /api/ussd/cancel
```

USSD is the worked example of the pattern. Adding another write feature is one
`ZltClient` method, one endpoint in `zlt/web.py`, one panel and tab button in
`zlt/static/index.html`, one file in `zlt/static/js/`, and one
`zlt.tabs.onFirstShow(...)` registration. The raw `client.post()` passthrough
already handles CSRF and auth-retry for any `goformId` you capture from the
stock UI.

## Manual live verification

Run these by hand against the real router on the LAN. They are not part of the
automated suite, which mocks all HTTP.

1. `zlt status`: confirm the reported network type / signal bars / RSSI match what the
   router's web UI shows.
2. `zlt net get`: confirm it reports the mode currently configured in the web UI.
3. `zlt net set lte` then `zlt net get`: confirm the mode round-trips to `lte` /
   `Only_LTE`, then `zlt net set auto` to restore the default (`NETWORK_auto`).

## Conventions

- **The version lives in two places** and a test enforces they agree:
  `pyproject.toml` and `zlt/__init__.py`. Bump both.
- **CLI stdout is a contract.** The external `zlt-gnome` extension parses
  `zlt net get` output; `tests/test_cli_contract.py` guards it. A failure there
  usually means fixing the extension, not deleting the assertion.
- Prefer hyphens over em-dashes in user-visible text.

## Releasing

Releases are published to PyPI by `.github/workflows/release.yml`, triggered by
pushing a tag. Uploads use PyPI Trusted Publishing, so there is no API token
stored in the repository.

The tag decides how far the pipeline goes:

| Tag | Runs |
| --- | --- |
| `v0.11.0rc1` | tests, build, TestPyPI. Stops there. |
| `v0.11.0` | tests, build, TestPyPI, PyPI, GitHub Release. |

The tag must match the version in `pyproject.toml` exactly or the build fails,
which is what stops a mistagged release from burning a version number on PyPI.
Since the match is exact, a rehearsal needs the prerelease version committed too.

```bash
# 1. Rehearse: set version to 0.11.1rc1 in pyproject.toml AND zlt/__init__.py
#    Tag must be annotated (-a). --follow-tags ignores lightweight tags, so a
#    plain `git tag` pushes the branch and silently leaves the tag behind.
git commit -am "chore: 0.11.1rc1"
git tag -a v0.11.1rc1 -m "0.11.1rc1" && git push --follow-tags

# 2. Verify the built package really works, installed from TestPyPI.
#    Install it with --no-deps and get the dependencies from real PyPI separately.
#    Pointing --index-url at TestPyPI makes it the primary index, and it carries
#    broken stand-ins for fastapi and friends that fail to build; an
#    --extra-index-url does not save you, because pip merges both indexes.
python3 -m venv /tmp/zlt-rc && . /tmp/zlt-rc/bin/activate
pip install --index-url https://test.pypi.org/simple/ --no-deps zltrouter
pip install click requests fastapi uvicorn
zlt --version
zlt serve       # confirms the dashboard's static assets made it into the wheel
deactivate && rm -rf /tmp/zlt-rc

# 3. Release: set version to 0.11.1 in both files
git commit -am "chore: release 0.11.1"
git tag -a v0.11.1 -m "0.11.1" && git push --follow-tags
```

Skipping the rehearsal is possible but risky for anything touching packaging: a
PyPI version number is burned permanently once uploaded, even if you delete the
release.

The distribution is named `zltrouter` on PyPI, not `zlt`. Plain `zlt` collides
with the existing `zit` project under PyPI's name-similarity check, which folds
`l` and `i` to `1`. The installed command and the import package are both still
`zlt`.
