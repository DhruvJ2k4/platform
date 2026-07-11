"""Typer command-line interface: the platform's public API surface (doc 14).

Humans, cron, tests, and future agents (ADR-015) consume the platform exclusively through these
commands. Every command must be idempotent, JSON-output capable, and exit-code disciplined:
0 on success, nonzero on any unhandled error.
"""

import json

import typer

from quant import __version__

app = typer.Typer(name="platform")


@app.callback()
def main() -> None:
    """Quantitative research and portfolio platform for NSE equities."""


@app.command()
def status() -> None:
    """Print platform status as JSON (placeholder until the P0-17 status page lands)."""
    typer.echo(json.dumps({"ok": True, "version": __version__}))
