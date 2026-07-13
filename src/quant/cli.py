"""Typer command-line interface: the platform's public API surface (doc 14).

Humans, cron, tests, and future agents (ADR-015) consume the platform exclusively through these
commands. Every command must be idempotent, JSON-output capable, and exit-code disciplined:
0 on success, nonzero on any unhandled error. `--until`/`--json` on ingest are additive
extensions to doc 14's signature (additive-by-default policy).
"""

import datetime
import json

import httpx
import typer

from quant import __version__
from quant.config import Settings, source_spec
from quant.errors import ConfigError, PlatformError
from quant.ingest import RawStore, bhavcopy

app = typer.Typer(name="platform")


@app.callback()
def main() -> None:
    """Quantitative research and portfolio platform for NSE equities."""


@app.command()
def status() -> None:
    """Print platform status as JSON (placeholder until the P0-17 status page lands)."""
    typer.echo(json.dumps({"ok": True, "version": __version__}))


def _make_client() -> httpx.Client:
    """Session factory (tests monkeypatch this with a MockTransport client)."""
    return httpx.Client(follow_redirects=True)


def _parse_iso(value: str, flag: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise ConfigError(f"{flag} must be an ISO date (YYYY-MM-DD), got {value!r}") from exc


@app.command()
def ingest(
    source: str = typer.Argument(help="source name from config/sources.yaml"),
    date: str | None = typer.Option(None, "--date", help="single ISO date"),
    since: str | None = typer.Option(None, "--since", help="range start, ISO date"),
    until: str | None = typer.Option(None, "--until", help="range end, ISO date (default today)"),
    json_out: bool = typer.Option(False, "--json", help="print a JSON summary"),
) -> None:
    """Ingest one source for a date or range (doc 14); idempotent; exit 1 on failure."""
    try:
        if source != bhavcopy.SOURCE:
            raise ConfigError(f"no adapter for source {source!r}; available: ['bhavcopy']")
        if (date is None) == (since is None):
            raise ConfigError("provide exactly one of --date or --since")
        spec = source_spec(source)
        if date is not None:
            first = last = _parse_iso(date, "--date")
        else:
            first = _parse_iso(since, "--since")  # type: ignore[arg-type]
            last = _parse_iso(until, "--until") if until is not None else datetime.date.today()
        store = RawStore(Settings())
        with _make_client() as client:
            summary = bhavcopy.fetch_range(first, last, store=store, spec=spec, client=client)
    except PlatformError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    if json_out:
        typer.echo(json.dumps(summary.as_dict()))
    else:
        typer.echo(
            f"{summary.source} {summary.since}..{summary.until}: "
            f"stored={summary.stored} noop={summary.noop} holiday={summary.holiday}"
        )
