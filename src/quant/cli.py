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
from quant.ingest import RawStore, bhavcopy, corp_actions, symbolchange

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
        elif source == corp_actions.SOURCE:
            summary = _ingest_corp_actions(date, since, until, weekends)
        else:
            raise ConfigError(
                f"no adapter for source {source!r}; available: "
                f"{[bhavcopy.SOURCE, symbolchange.SOURCE, corp_actions.SOURCE]}"
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
    elif isinstance(summary, corp_actions.IngestSummary):
        typer.echo(
            f"{summary.source} {summary.since}..{summary.until}: "
            f"{'stored' if summary.stored else 'noop'} sha256={summary.sha256[:12]}"
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


@app.command()
def curate(
    rebuild: bool = typer.Option(False, "--rebuild", help="full deterministic rebuild + publish"),
    incremental: bool = typer.Option(
        False, "--incremental", help="incremental update (not yet implemented; use --rebuild)"
    ),
    asof: str | None = typer.Option(None, "--asof", help="build as-of ISO date (default today)"),
    json_out: bool = typer.Option(False, "--json", help="print the full JSON report"),
) -> None:
    """Rebuild the curated store from the raw vault and publish atomically (doc 06 §6.2)."""
    from quant.curate.build import curate_rebuild  # heavy import deferred off CLI startup

    try:
        if rebuild == incremental:
            raise ConfigError("provide exactly one of --rebuild or --incremental")
        if incremental:
            raise ConfigError(
                "curate --incremental is not implemented yet (P0-11 recorded deferral): "
                "--rebuild is the correctness path; incremental lands with the nightly era"
            )
        d = _parse_iso(asof, "--asof") if asof is not None else datetime.date.today()
        report = curate_rebuild(d)
    except PlatformError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    if json_out:
        typer.echo(json.dumps(report.as_dict()))
    else:
        typer.echo(
            f"{report.run_id}: {'published' if report.created else 'no-op (identical)'} "
            f"asof={report.asof} rows={report.stats['tables']}"
        )


@app.command()
def universe(
    date: str = typer.Option(..., "--date", help="decision date, ISO (YYYY-MM-DD)"),
    book: str | None = typer.Option(
        None, "--book", help="book name (capacity overlay deferred to P1/P2 — see banner)"
    ),
    json_out: bool = typer.Option(False, "--json", help="print the full per-name JSON"),
) -> None:
    """Print the PIT investable universe for a date with per-name exclusion reasons (doc 21 §4).

    Reads the published universe_membership as-of the date (<1s). `investable` is tri-state:
    true, false, or null (=undetermined: clean but surveillance unchecked until P0-14). `--book`
    is accepted but the investable(book) overlay is deferred; a per-name capacity = p_max·MDTV is
    shown as the honest raw material.
    """
    import pandas as pd

    from quant.config import load_liquidity
    from quant.curate.universe import load_universe

    try:
        d = _parse_iso(date, "--date")
        frame = load_universe(d)
        p_max = load_liquidity().p_max
    except PlatformError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc

    out_of_coverage = len(frame) == 0
    inv = frame["investable"]
    n_true = int((inv == True).sum())  # noqa: E712 — Arrow bool; `is True` would miss it
    n_false = int((inv == False).sum())  # noqa: E712
    n_null = len(frame) - n_true - n_false
    names = [
        {
            "isin": str(r.isin),
            "investable": None if pd.isna(r.investable) else bool(r.investable),
            "mdtv": None if pd.isna(r.mdtv) else str(r.mdtv),
            "capacity_pmax_mdtv": None if pd.isna(r.mdtv) else str(p_max * r.mdtv),
            "excl_reasons": list(r.excl_reasons),
        }
        for r in frame.itertuples(index=False)
    ]
    payload = {
        "date": str(d),
        "out_of_coverage": out_of_coverage,
        "candidates": len(frame),
        "investable": n_true,
        "undetermined": n_null,
        "excluded": n_false,
        "names": names,
    }
    if book is not None:
        typer.echo(
            f"NOTE --book {book!r}: base universe only — investable(book) needs a corpus (P2) "
            "and engine sizing (P1); capacity_pmax_mdtv is the query-time raw material, NOT a "
            "book-investability verdict.",
            err=True,
        )
    if json_out:
        typer.echo(json.dumps(payload))
        return
    if out_of_coverage:
        typer.echo(f"{d}: no candidates — out of coverage or a non-trading day (no universe rows)")
        return
    reason_hist: dict[str, int] = {}
    for r in frame.itertuples(index=False):
        for reason in r.excl_reasons:
            reason_hist[reason] = reason_hist.get(reason, 0) + 1
    typer.echo(
        f"{d}: candidates={payload['candidates']} investable={n_true} "
        f"undetermined={n_null} excluded={n_false}"
    )
    if n_null:
        typer.echo("  (undetermined = clean but surveillance unchecked until P0-14 wires ASM/GSM)")
    for reason, count in sorted(reason_hist.items(), key=lambda kv: (-kv[1], kv[0])):
        typer.echo(f"  {reason}: {count}")


def _ingest_corp_actions(
    date: str | None, since: str | None, until: str | None, weekends: bool
) -> corp_actions.IngestSummary:
    """Windowed source: --since is required (window start); --until defaults to today."""
    if date is not None or weekends:
        raise ConfigError(
            f"{corp_actions.SOURCE} is a windowed source: use --since (required) and optional"
            " --until; --date and --include-weekends do not apply"
        )
    if since is None:
        raise ConfigError(f"{corp_actions.SOURCE} requires --since (window start)")
    first = _parse_iso(since, "--since")
    last = _parse_iso(until, "--until") if until is not None else datetime.date.today()
    spec = source_spec(corp_actions.SOURCE)
    store = RawStore(Settings())
    with _make_client() as client:
        artifact, created = corp_actions.fetch_window(
            first, last, store=store, spec=spec, client=client
        )
    return corp_actions.IngestSummary(
        corp_actions.SOURCE, str(first), str(last), created, artifact.sha256
    )
