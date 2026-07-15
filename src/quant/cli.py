"""Typer command-line interface: the platform's public API surface (doc 14).

Humans, cron, tests, and future agents (ADR-015) consume the platform exclusively through these
commands. Every command must be idempotent, JSON-output capable, and exit-code disciplined:
0 on success, nonzero on any unhandled error. `--until`/`--json` on ingest are additive
extensions to doc 14's signature (additive-by-default policy), as is the snapshot-source
rule (P0-09): snapshot sources like symbolchange take an optional --date (default today,
labelling the fetch) and reject range/weekend flags with ConfigError.
"""

import datetime
import json

import httpx
import typer

from quant import __version__
from quant.config import Settings, source_spec
from quant.errors import ConfigError, PlatformError
from quant.ingest import RawStore, bhavcopy, symbolchange

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
    weekends: bool = typer.Option(
        False, "--include-weekends", help="also request Sat/Sun (calendar-grade presence)"
    ),
    json_out: bool = typer.Option(False, "--json", help="print a JSON summary"),
) -> None:
    """Ingest one source for a date or range (doc 14); idempotent; exit 1 on failure."""
    try:
        if source == bhavcopy.SOURCE:
            summary = _ingest_bhavcopy(date, since, until, weekends)
        elif source == symbolchange.SOURCE:
            summary = _ingest_symbolchange(date, since, until, weekends)
        else:
            raise ConfigError(
                f"no adapter for source {source!r}; available: "
                f"{[bhavcopy.SOURCE, symbolchange.SOURCE]}"
            )
    except PlatformError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    if json_out:
        typer.echo(json.dumps(summary.as_dict()))
    elif isinstance(summary, bhavcopy.IngestSummary):
        typer.echo(
            f"{summary.source} {summary.since}..{summary.until}: "
            f"stored={summary.stored} noop={summary.noop} holiday={summary.holiday}"
        )
    else:
        typer.echo(
            f"{summary.source} {summary.logical_date}: "
            f"{'stored' if summary.stored else 'noop'} sha256={summary.sha256[:12]}"
        )


def _ingest_bhavcopy(
    date: str | None, since: str | None, until: str | None, weekends: bool
) -> bhavcopy.IngestSummary:
    """Per-date source: exactly one of --date/--since selects a day or a range."""
    if (date is None) == (since is None):
        raise ConfigError("provide exactly one of --date or --since")
    spec = source_spec(bhavcopy.SOURCE)
    if date is not None:
        first = last = _parse_iso(date, "--date")
        weekends = True  # an explicitly requested date is always fetched
    else:
        first = _parse_iso(since, "--since")  # type: ignore[arg-type]
        last = _parse_iso(until, "--until") if until is not None else datetime.date.today()
    store = RawStore(Settings())
    with _make_client() as client:
        return bhavcopy.fetch_range(
            first, last, store=store, spec=spec, client=client, weekends=weekends
        )


def _ingest_symbolchange(
    date: str | None, since: str | None, until: str | None, weekends: bool
) -> symbolchange.SnapshotSummary:
    """Snapshot source: --date optionally labels the fetch day; range flags are meaningless."""
    if since is not None or until is not None or weekends:
        raise ConfigError(
            f"{symbolchange.SOURCE} is a snapshot source: use only --date "
            "(optional; defaults to today)"
        )
    d = _parse_iso(date, "--date") if date is not None else datetime.date.today()
    spec = source_spec(symbolchange.SOURCE)
    store = RawStore(Settings())
    with _make_client() as client:
        artifact, created = symbolchange.fetch_snapshot(d, store=store, spec=spec, client=client)
    return symbolchange.SnapshotSummary(
        symbolchange.SOURCE, str(artifact.logical_date), created, artifact.sha256
    )
