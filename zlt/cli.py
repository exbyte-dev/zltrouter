import json
import os as _os

import click

from zlt import __version__
from zlt.client import (
    BEARER_MAP,
    FULL_EXTRA,
    NET_KEYS,
    OPEN_KEYS,
    LockedOut,
    LoginError,
    RouterError,
    RouterUnreachable,
    ZltClient,
)
from zlt.config import DEFAULT_HOST, DEFAULT_USERNAME, config_path, load_config

@click.group()
@click.version_option(__version__, prog_name="zlt")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Control the MTN ZLT T10D MAX router from the terminal."""
    if ctx.obj is None:
        ctx.obj = ZltClient(load_config())


@cli.command()
@click.argument("cmds", nargs=-1, required=True)
@click.pass_obj
def get(client: ZltClient, cmds: tuple[str, ...]) -> None:
    """Raw proc_get passthrough: zlt get network_type rssi ..."""
    try:
        click.echo(json.dumps(client.get(*cmds), indent=2))
    except RouterUnreachable as exc:
        raise click.ClickException(str(exc))


@cli.command()
@click.pass_obj
def status(client: ZltClient) -> None:
    """Show signal/network status (full detail when logged in)."""
    authed = False
    fallback_reason = None
    try:
        try:
            client.ensure_session()
            data = client.get(*OPEN_KEYS, *FULL_EXTRA)
            authed = True
        except (LoginError, LockedOut) as exc:
            fallback_reason = str(exc) if client.config.password else None
            data = client.get(*OPEN_KEYS)
    except RouterUnreachable as exc:
        raise click.ClickException(str(exc))

    def row(label: str, key: str) -> None:
        value = data.get(key, "")
        click.echo(f"  {label:<14} {value}")

    click.echo(f"Network:")
    row("type", "network_type")
    row("signal bars", "signalbar")
    row("rssi (dBm)", "rssi")
    row("rsrq (dB)", "lte_rsrq")
    row("pci", "lte_pci")
    row("ppp", "ppp_status")
    if authed:
        row("rsrp (dBm)", "lte_rsrp")
        row("band", "lte_band")
        row("snr (dB)", "lte_snr")
    elif fallback_reason:
        click.echo(f"  (rsrp/band/snr need login — {fallback_reason})")
    else:
        click.echo("  (rsrp/band/snr need login — set ZLT_PASSWORD)")


from zlt.client import BEARER_REVERSE

@cli.group()
def net() -> None:
    """Network-mode (bearer preference) commands."""


@net.command("get")
@click.pass_obj
def net_get(client: ZltClient) -> None:
    """Show the configured network mode."""
    try:
        client.ensure_session()
        data = client.get(*NET_KEYS)
    except (LoginError, LockedOut, RouterUnreachable) as exc:
        raise click.ClickException(str(exc))
    configured = data.get("net_select") or data.get("net_select_mode") or data.get("m_netselect_save") or ""
    friendly = BEARER_REVERSE.get(configured, "?")
    click.echo(f"Configured mode : {friendly} ({configured or 'unknown'})")
    click.echo(f"Current network : {data.get('current_network_mode', '')}")


@net.command("set")
@click.argument("mode", type=click.Choice(sorted(BEARER_MAP.keys())))
@click.pass_obj
def net_set(client: ZltClient, mode: str) -> None:
    """Set network mode: auto|lte|4g|4g3g|wcdma|3g|gsm|2g."""
    value = BEARER_MAP[mode]
    try:
        client.ensure_session()
        data = client.post("SET_BEARER_PREFERENCE", BearerPreference=value)
        if str(data.get("result")) != "success":
            raise RouterError(f"router rejected mode change: result={data.get('result')}")
        confirm = client.get(*NET_KEYS)
    except (LoginError, LockedOut, RouterUnreachable, RouterError) as exc:
        raise click.ClickException(str(exc))
    now = confirm.get("net_select") or confirm.get("net_select_mode") or confirm.get("m_netselect_save") or ""
    click.echo(f"OK — set to {mode} ({value}); router now reports {now or 'unknown'}")


@cli.command()
@click.argument("goform_id")
@click.argument("pairs", nargs=-1)
@click.pass_obj
def post(client: ZltClient, goform_id: str, pairs: tuple[str, ...]) -> None:
    """Raw proc_post passthrough: zlt post GOFORMID key=val ..."""
    fields = {}
    for pair in pairs:
        if "=" not in pair:
            raise click.ClickException(f"bad field '{pair}', expected key=value")
        key, val = pair.split("=", 1)
        fields[key] = val
    try:
        click.echo(json.dumps(client.post(goform_id, **fields), indent=2))
    except (LoginError, LockedOut, RouterUnreachable) as exc:
        raise click.ClickException(str(exc))


@cli.command()
@click.pass_obj
def login(client: ZltClient) -> None:
    """Log in and cache the session."""
    try:
        remaining, lock = client.attempts_remaining()
        click.echo(f"Attempts remaining before {lock}s lockout: {remaining}")
        client.login()
    except (LoginError, LockedOut, RouterUnreachable) as exc:
        raise click.ClickException(str(exc))
    click.echo("Logged in; session cached.")


@cli.command("init-config")
@click.option("--host", default=DEFAULT_HOST, show_default=True)
@click.option("--username", default=DEFAULT_USERNAME, show_default=True)
@click.password_option(confirmation_prompt=False, help="Router admin password")
def init_config(host: str, username: str, password: str) -> None:
    """Write ~/.config/zlt/config (chmod 600)."""
    path = config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = f"ZLT_HOST={host}\nZLT_USERNAME={username}\nZLT_PASSWORD={password}\n"
        fd = _os.open(path, _os.O_CREAT | _os.O_WRONLY | _os.O_TRUNC, 0o600)
        with _os.fdopen(fd, "w") as f:
            f.write(content)
    except OSError as exc:
        raise click.ClickException(f"could not write {path}: {exc}")
    click.echo(f"Wrote {path}")


@cli.command()
@click.option("--host", "bind_host", default="127.0.0.1", show_default=True,
              help="Interface to bind. Use 0.0.0.0 to reach it from your phone on the LAN.")
@click.option("--port", default=8464, show_default=True)
@click.pass_obj
def serve(client: ZltClient, bind_host: str, port: int) -> None:
    """Serve the local web dashboard (needs: pip install 'zlt[web]')."""
    try:
        import uvicorn

        from zlt.web import create_app
    except ImportError:
        raise click.ClickException(
            "web extras not installed — run: .venv/bin/pip install -e '.[web]'"
        )
    click.echo(f"Dashboard on http://{bind_host}:{port} — router at {client.config.host}")
    if bind_host != "127.0.0.1":
        click.echo("Note: the dashboard has no auth of its own; anyone on the LAN "
                   "who can reach this port can change router settings.")
    uvicorn.run(create_app(client), host=bind_host, port=port, log_level="warning")
