"""Local web dashboard for zlt.

A thin FastAPI layer over ZltClient. This exists because a browser cannot talk
to the router directly: the reqproc API sends no CORS headers and the session
cookie belongs to the router's origin. Everything auth-related (nonce login,
CSRF, lockout guard, session cache) is delegated to the existing client.

Launched via 'zlt serve', or automatically on login via 'zlt service install'.
"""

from __future__ import annotations

import threading
from importlib import resources

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from zlt import ussd_store
from zlt.client import (
    BEARER_MAP,
    BEARER_REVERSE,
    FULL_EXTRA,
    NET_KEYS,
    OPEN_KEYS,
    LockedOut,
    LoginError,
    RouterError,
    RouterUnreachable,
    UssdError,
    ZltClient,
)


class ModeBody(BaseModel):
    mode: str


class UssdSendBody(BaseModel):
    code: str


class UssdReplyBody(BaseModel):
    text: str


def _resolve_configured(data: dict) -> str:
    return (
        data.get("net_select")
        or data.get("net_select_mode")
        or data.get("m_netselect_save")
        or ""
    )


def create_app(client: ZltClient) -> FastAPI:
    app = FastAPI(title="zlt dashboard", docs_url=None, redoc_url=None)
    # requests.Session is not thread-safe and FastAPI runs sync endpoints in a
    # thread pool, so serialize all router traffic through one lock. The router
    # is a single slow embedded device anyway; concurrency buys nothing.
    lock = threading.Lock()

    def _guard(fn):
        try:
            return fn()
        except LockedOut as exc:
            raise HTTPException(status_code=423, detail=str(exc))
        except LoginError as exc:
            raise HTTPException(status_code=401, detail=str(exc))
        except UssdError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        except RouterError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        except RouterUnreachable as exc:
            raise HTTPException(status_code=504, detail=str(exc))

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return resources.files("zlt").joinpath("static/index.html").read_text()

    @app.get("/api/status")
    def status() -> dict:
        def work() -> dict:
            with lock:
                authed = False
                note = None
                try:
                    client.ensure_session()
                    data = client.get(*OPEN_KEYS, *FULL_EXTRA)
                    authed = True
                except (LoginError, LockedOut) as exc:
                    note = (
                        str(exc)
                        if client.config.password
                        else "no password configured — rsrp/band/snr hidden"
                    )
                    data = client.get(*OPEN_KEYS)
                return {
                    "authed": authed,
                    "note": note,
                    "host": client.config.host,
                    "data": data,
                }

        return _guard(work)

    @app.get("/api/net")
    def net_get() -> dict:
        def work() -> dict:
            with lock:
                client.ensure_session()
                data = client.get(*NET_KEYS)
            configured = _resolve_configured(data)
            return {
                "configured": configured,
                "friendly": BEARER_REVERSE.get(configured, ""),
                "current": data.get("current_network_mode", ""),
            }

        return _guard(work)

    @app.post("/api/net")
    def net_set(body: ModeBody) -> dict:
        mode = body.mode.strip().lower()
        if mode not in BEARER_MAP:
            raise HTTPException(
                status_code=422,
                detail=f"unknown mode '{mode}' — expected one of {sorted(BEARER_MAP)}",
            )
        value = BEARER_MAP[mode]

        def work() -> dict:
            with lock:
                client.ensure_session()
                data = client.post("SET_BEARER_PREFERENCE", BearerPreference=value)
                if str(data.get("result")) != "success":
                    raise RouterError(
                        f"router rejected mode change: result={data.get('result')}"
                    )
                confirm = client.get(*NET_KEYS)
            configured = _resolve_configured(confirm)
            return {
                "requested": mode,
                "value": value,
                "configured": configured,
                "friendly": BEARER_REVERSE.get(configured, ""),
            }

        return _guard(work)

    @app.get("/api/ussd/codes")
    def ussd_codes() -> dict:
        return {"codes": ussd_store.load_codes()}

    @app.post("/api/ussd/send")
    def ussd_send(body: UssdSendBody) -> dict:
        code = body.code.strip()
        if not code:
            raise HTTPException(status_code=422, detail="empty USSD code")

        def work():
            with lock:
                return client.ussd_send(code)

        result = _guard(work)
        return {"text": result.text, "state": result.state}

    @app.post("/api/ussd/reply")
    def ussd_reply(body: UssdReplyBody) -> dict:
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="empty USSD reply")

        def work():
            with lock:
                return client.ussd_reply(text)

        result = _guard(work)
        return {"text": result.text, "state": result.state}

    @app.post("/api/ussd/cancel")
    def ussd_cancel() -> dict:
        def work():
            with lock:
                client.ussd_cancel()
                return {"ok": True}

        return _guard(work)

    return app
