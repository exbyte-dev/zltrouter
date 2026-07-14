import click

from zlt import __version__


@click.group()
@click.version_option(__version__, prog_name="zlt")
def cli() -> None:
    """Control the MTN ZLT T10D MAX router from the terminal."""
