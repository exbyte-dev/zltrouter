import json
import os as _os
import sys
from pathlib import Path

import click

from zlt import __version__
from zlt import service as service_mod
from zlt import ussd_store
from zlt.client import (
    BEARER_MAP,
    FULL_EXTRA,
    NET_KEYS,
    OPEN_KEYS,
    LockedOut,
    LoginError,
    RouterError,
    RouterUnreachable,
    UssdError,
    UssdResult,
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


def _print_ussd(result: UssdResult) -> None:
    if result.state == "timeout":
        click.echo("(no response from network)")
        return
    if result.state == "error":
        click.echo(f"USSD error: {result.text}".rstrip())
        return
    click.echo(result.text)


def _ussd_flow(client: ZltClient, code: str) -> None:
    try:
        result = client.ussd_send(code)
        while True:
            _print_ussd(result)
            if result.state != "prompt":
                return
            if not _stdin_is_tty():
                return
            try:
                reply = click.prompt("reply", prompt_suffix="> ",
                                     default="", show_default=False)
            except (click.Abort, EOFError):
                client.ussd_cancel()
                click.echo("cancelled")
                return
            if reply.strip() == "":
                client.ussd_cancel()
                click.echo("cancelled")
                return
            result = client.ussd_reply(reply.strip())
    except (LoginError, LockedOut, RouterUnreachable, UssdError) as exc:
        raise click.ClickException(str(exc))


@cli.group()
def ussd() -> None:
    """Send USSD codes and manage saved ones."""


@ussd.command("send")
@click.argument("code")
@click.pass_obj
def ussd_send_cmd(client: ZltClient, code: str) -> None:
    """Send a USSD code (e.g. zlt ussd send '*310#')."""
    _ussd_flow(client, code)


@ussd.command("cancel")
@click.pass_obj
def ussd_cancel_cmd(client: ZltClient) -> None:
    """Cancel the active USSD session."""
    try:
        client.ussd_cancel()
    except (LoginError, LockedOut, RouterUnreachable, UssdError) as exc:
        raise click.ClickException(str(exc))
    click.echo("cancelled")


@ussd.command("run")
@click.argument("label")
@click.pass_obj
def ussd_run_cmd(client: ZltClient, label: str) -> None:
    """Run a saved code by label."""
    match = next((c for c in ussd_store.load_codes()
                  if c["label"].lower() == label.strip().lower()), None)
    if match is None:
        raise click.ClickException(f"no saved code labelled '{label}'")
    _ussd_flow(client, match["code"])


@ussd.command("list")
def ussd_list_cmd() -> None:
    """List saved USSD codes."""
    codes = ussd_store.load_codes()
    if not codes:
        click.echo("(no saved codes)")
        return
    width = max(len(c["label"]) for c in codes)
    for c in codes:
        click.echo(f"  {c['label']:<{width}}  {c['code']}")


@ussd.command("save")
@click.argument("label")
@click.argument("code")
def ussd_save_cmd(label: str, code: str) -> None:
    """Save a code under a label."""
    ussd_store.save_code(label, code)
    click.echo(f"Saved {label!r} -> {code}")


@ussd.command("rm")
@click.argument("label")
def ussd_rm_cmd(label: str) -> None:
    """Remove a saved code by label."""
    if ussd_store.remove_code(label):
        click.echo(f"Removed {label!r}")
    else:
        raise click.ClickException(f"no saved code labelled '{label}'")


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


def _stdin_is_tty() -> bool:
    # Its own function so tests can force it; CliRunner always reports False.
    return sys.stdin.isatty()


@cli.command("init-config")
@click.option("--host", default=DEFAULT_HOST, show_default=True)
@click.option("--username", default=DEFAULT_USERNAME, show_default=True)
@click.option("--no-service", is_flag=True,
              help="Skip the offer to run the dashboard on login.")
@click.password_option(confirmation_prompt=False, help="Router admin password")
def init_config(host: str, username: str, no_service: bool, password: str) -> None:
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

    if no_service or not _stdin_is_tty():
        return

    try:
        backend = service_mod.detect_backend()
    except service_mod.ServiceError as exc:
        # Not fatal: the config is written, they just get no autostart offer.
        click.echo(f"\nSkipping the dashboard service: {exc}")
        return

    click.echo()
    if not click.confirm("Start the dashboard on login?", default=True):
        click.echo("Skipped. Run 'zlt service install' whenever you want it.")
        return

    try:
        backend.install()
    except service_mod.ServiceError as exc:
        click.echo(f"Could not install the service: {exc}", err=True)
        click.echo("Your config is saved; only the autostart step failed. "
                   "It is safe to retry\nwith 'zlt service install' at any time.",
                   err=True)
        return
    click.echo(f"Installed {service_mod.SERVICE_NAME}:")
    click.echo(f"  local: http://127.0.0.1:{service_mod.DEFAULT_PORT}")
    if backend.host == "0.0.0.0":
        click.echo(f"  LAN:   http://<this machine's IP>:{service_mod.DEFAULT_PORT}   "
                   "(phone, tablet)")
        click.echo("  Note: the dashboard has no auth of its own; anyone on the LAN "
                   "who can reach this port can change router settings.")


@cli.command()
@click.option("--host", "bind_host", default="127.0.0.1", show_default=True,
              help="Interface to bind. Use 0.0.0.0 to reach it from your phone on the LAN.")
@click.option("--port", default=8464, show_default=True)
@click.option("--log-file", type=click.Path(dir_okay=False, path_type=Path),
              default=None,
              help="Append output to this file. Used by the Windows service "
                   "backend, which has no journal of its own.")
@click.pass_obj
def serve(client: ZltClient, bind_host: str, port: int, log_file: Path | None) -> None:
    """Serve the local web dashboard."""
    try:
        import uvicorn

        from zlt.web import create_app
    except ImportError as exc:
        raise click.ClickException(f"could not import the web dashboard: {exc}")

    stream = None
    saved = (sys.stdout, sys.stderr)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        stream = open(log_file, "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stderr = stream
    try:
        click.echo(f"Dashboard on http://{bind_host}:{port} - router at {client.config.host}")
        if bind_host != "127.0.0.1":
            click.echo("Note: the dashboard has no auth of its own; anyone on the LAN "
                       "who can reach this port can change router settings.")
        uvicorn.run(create_app(client), host=bind_host, port=port, log_level="warning")
    finally:
        sys.stdout, sys.stderr = saved
        if stream is not None:
            stream.close()


@cli.group("service")
def service_group() -> None:
    """Run the dashboard automatically on login."""


def _backend(host: str = service_mod.DEFAULT_BIND, port: int = service_mod.DEFAULT_PORT):
    try:
        return service_mod.detect_backend(host=host, port=port)
    except service_mod.ServiceError as exc:
        raise click.ClickException(str(exc))


def _do(verb: str, host: str = service_mod.DEFAULT_BIND,
        port: int = service_mod.DEFAULT_PORT):
    backend = _backend(host, port)
    try:
        getattr(backend, verb)()
    except service_mod.ServiceError as exc:
        raise click.ClickException(str(exc))
    return backend


@service_group.command("install")
@click.option("--host", "bind_host", default=service_mod.DEFAULT_BIND, show_default=True,
              help="Interface the dashboard binds to. 0.0.0.0 reaches your phone.")
@click.option("--port", default=service_mod.DEFAULT_PORT, show_default=True)
def service_install(bind_host: str, port: int) -> None:
    """Install and start the dashboard service."""
    backend = _do("install", bind_host, port)
    click.echo(f"Installed {service_mod.SERVICE_NAME}, starting on login.")
    if bind_host == "0.0.0.0":
        click.echo(f"  local: http://127.0.0.1:{port}")
        click.echo(f"  LAN:   http://<this machine's IP>:{port}   (phone, tablet)")
    else:
        click.echo(f"  local: http://{bind_host}:{port}")
    click.echo(f"  unit:  {backend.artifact_path()}")


@service_group.command("uninstall")
def service_uninstall() -> None:
    """Stop the service and remove it for good."""
    _do("uninstall")
    click.echo(f"Uninstalled {service_mod.SERVICE_NAME}.")


@service_group.command("suspend")
def service_suspend() -> None:
    """Stop the service without uninstalling it."""
    backend = _do("suspend")
    click.echo(f"Suspended {service_mod.SERVICE_NAME}: {backend.suspend_note}.")


@service_group.command("resume")
def service_resume() -> None:
    """Start a suspended service."""
    _do("resume")
    click.echo(f"Resumed {service_mod.SERVICE_NAME}.")


@service_group.command("status")
def service_status() -> None:
    """Show what the service manager reports."""
    _do("status")


@service_group.command("logs")
def service_logs() -> None:
    """Follow the dashboard's logs."""
    _do("logs")


@service_group.command("print-artifact")
def service_print_artifact() -> None:
    """Print the generated unit/plist/task XML without installing it."""
    click.echo(_backend().render())
