"""Allow `python -m zlt` (and `pythonw -m zlt`) to invoke the CLI.

The Windows autostart backend relies on this so it can launch under
pythonw.exe, which — unlike the console-mode zlt.exe wrapper — does not
make Task Scheduler pop a visible cmd window at login.
"""

from zlt.cli import cli

if __name__ == "__main__":
    cli()
