import json

import click

from zlt import __version__
from zlt.client import LockedOut, LoginError, RouterUnreachable, ZltClient
from zlt.config import load_config

OPEN_KEYS = ["network_type", "rssi", "signalbar", "lte_rsrq", "lte_pci", "ppp_status"]
FULL_EXTRA = ["lte_rsrp", "lte_band", "lte_snr"]


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
    try:
        client.ensure_session()
        data = client.get(*OPEN_KEYS, *FULL_EXTRA)
        authed = True
    except (LoginError, LockedOut):
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
    else:
        click.echo("  (rsrp/band/snr need login — set ZLT_PASSWORD)")
