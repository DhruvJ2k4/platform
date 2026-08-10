"""niftyindices Total Return Index benchmark adapter (doc 06 §6.1; doc 20 P0-15; ADR-008).

Two sibling snapshot-free WINDOWED sources -- `nifty50_tri` and `midcap150_tri` -- feed the
`index_tri` benchmark table (ADR-008: official indices are consumed ONLY as TRI return series,
never constituents). Both hit niftyindices' `getTotalReturnIndexString` POST page-method, which
is DISTINCT from the price `getHistoricaldatatabletoString` endpoint (sourcing probe 2026-08-09,
ops/journal.md): it takes a JSON `cinfo` body {name,startDate,endDate,indexName} (dates
DD-Mon-YYYY) and returns the historical index table computed on the TR index. The plain index
label ('NIFTY 50') selects the TR series -- there is no separate '... TR' index name (every such
spelling returns []). The endpoint rejects windows wider than ~1y, so `fetch_window` slices
[since,until] into <= spec.chunk_days chunks, each stored under logical_date = its chunk end.

`fetch_window` does exactly: cookie-prime GET -> per chunk (politeness sleep -> POST -> content
gate -> immutable store), and nothing else. The FORMAT parser lives in curation (doc 06 §6.1);
`_reject_unless_json_array` is a fetch-VALIDITY pre-filter only (same category as corp_actions'
gate), rejecting the HTML shell / block page / tarpit body before storage.

SOURCING BLOCKER (2026-08-09): every scripted client -- plain, cookie-primed, or replaying a live
browser's Akamai cookies -- is walled: the price endpoint returns an HTML shell to non-browser
callers and the TR endpoint tarpits (no response inside 120s). niftyindices' historical-data UI
exposes no plain-TRI report either, so there is no browser call to capture. This adapter is
therefore forward-compatible exactly like the P0-14 ASM/GSM adapters: today a live run hits the
gate and exits 1 with a loud SourceError (nothing stored); the day a valid session mechanism
exists, this same code stores real TRI with zero changes. See ops/journal.md 2026-08-10 and the
P0-15 mini-ADR (doc 07) for the full investigation and the deferred-sourcing decision.
"""

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, timedelta

import httpx
import structlog

from quant.config import SourceSpec
from quant.errors import ConfigError, SourceError
from quant.ingest.store import RawArtifact, RawStore

log = structlog.get_logger()

SOURCE_NIFTY50 = "nifty50_tri"
SOURCE_MIDCAP150 = "midcap150_tri"
SOURCES = (SOURCE_NIFTY50, SOURCE_MIDCAP150)

# Raw source -> the curated index_tri.index_name it lands under (the TR series, explicit).
INDEX_NAME = {SOURCE_NIFTY50: "NIFTY 50 TR", SOURCE_MIDCAP150: "NIFTY MIDCAP 150 TR"}

_MONTHS_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass(frozen=True, slots=True)
class IngestSummary:
    """Result of one windowed TRI ingest: the [since,until] span plus per-chunk disposition."""

    source: str
    since: str
    until: str
    stored: int
    noop: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _fmt_date(d: date) -> str:
    """niftyindices request date: DD-Mon-YYYY with an English abbreviation (never locale %b)."""
    return f"{d.day:02d}-{_MONTHS_ABBR[d.month - 1]}-{d.year:04d}"


def _cinfo_body(label: str, since: date, until: date) -> str:
    """The `getTotalReturnIndexString` JSON body: a `cinfo` string of a single-quoted dict."""
    cinfo = (
        "{"
        f"'name':'{label}','startDate':'{_fmt_date(since)}',"
        f"'endDate':'{_fmt_date(until)}','indexName':'{label}'"
        "}"
    )
    return json.dumps({"cinfo": cinfo})


def fetch_window(
    source: str,
    since: date,
    until: date,
    *,
    store: RawStore,
    spec: SourceSpec,
    client: httpx.Client,
    sleep: Callable[[float], None] | None = None,
) -> IngestSummary:
    """Fetch a TRI index's [since,until] in <= chunk_days slices; store each chunk immutably.

    sleep is late-bound to time.sleep so tests can patch it (a def-time default would freeze the
    real function object at import).
    """
    if until < since:
        raise ConfigError(f"--until {until} is before --since {since}")
    if spec.method != "POST" or spec.index_label is None or spec.chunk_days is None:
        raise ConfigError(
            f"{source} spec needs method=POST, index_label and chunk_days (doc 09 P0-15)"
        )
    if spec.prime_url is None:
        raise ConfigError(f"{source} spec needs prime_url for the cookie-prime step (doc 09)")
    _sleep = sleep if sleep is not None else time.sleep

    # Cookie-prime: seed the niftyindices session/Akamai cookies from the historical-data page
    # (its status is not gated -- a non-200 here is not a block of our real POST).
    _sleep(spec.delay_seconds)
    try:
        client.get(spec.prime_url, headers=spec.headers, timeout=spec.timeout_seconds)
    except httpx.HTTPError as exc:
        raise SourceError(f"{source}: cookie-prime GET to {spec.prime_url} failed: {exc}") from exc

    stored = noop = 0
    chunk_start = since
    while chunk_start <= until:
        chunk_end = min(chunk_start + timedelta(days=spec.chunk_days - 1), until)
        _, created = _fetch_chunk(
            source, chunk_start, chunk_end, store=store, spec=spec, client=client, sleep=_sleep
        )
        if created:
            stored += 1
        else:
            noop += 1
        chunk_start = chunk_end + timedelta(days=1)

    summary = IngestSummary(source, str(since), str(until), stored, noop)
    log.info("ingest_range_done", **summary.as_dict())
    return summary


def _fetch_chunk(
    source: str,
    since: date,
    until: date,
    *,
    store: RawStore,
    spec: SourceSpec,
    client: httpx.Client,
    sleep: Callable[[float], None],
) -> tuple[RawArtifact, bool]:
    """One <= chunk_days window: POST, gate, store under logical_date = the chunk's end date."""
    sleep(spec.delay_seconds)
    body = _cinfo_body(spec.index_label, since, until)  # type: ignore[arg-type]  # checked by caller
    try:
        resp = client.post(
            spec.url_template, headers=spec.headers, content=body, timeout=spec.timeout_seconds
        )
    except httpx.HTTPError as exc:
        raise SourceError(
            f"{source} [{since}..{until}]: request failed ({exc}). niftyindices' TR endpoint"
            " tarpits scripted clients (Akamai bot wall, no session) -- see ops/journal.md"
            " 2026-08-10; aborting without retry"
        ) from exc
    if resp.status_code in (403, 429):
        raise SourceError(
            f"{source} blocked (HTTP {resp.status_code}) for [{since}..{until}]: niftyindices'"
            " Akamai edge (doc 09 P0-15); aborting without retry"
        )
    if resp.status_code != 200:
        raise SourceError(f"{source}: unexpected HTTP {resp.status_code} for [{since}..{until}]")
    _reject_unless_json_data(resp.content, source)
    artifact, created = store.put(source, until, resp.content, suffix=".json")
    log.info(
        "ingest_stored",
        source=source,
        logical_date=str(until),
        created=created,
        sha256=artifact.sha256,
    )
    return artifact, created


def _reject_unless_json_data(content: bytes, source: str) -> None:
    """Reject the HTML shell / block page / tarpit body; a raw-fidelity check, never parsing.

    Today's real response to a scripted client is the niftyindices SPA shell (`<!DOCTYPE html>`),
    conclusively NOT DATA -- refused before storage so the raw vault never accumulates worthless
    shell files while the sourcing blocker persists (doc 06 §6.1 carve-out). BOTH JSON data
    envelopes are admitted: a bare array `[...]` AND the ASP.NET page-method wrapper `{"d": "..."}`
    (the curate-layer parser handles both), so a wrapped real TR response is stored, never
    misclassified as a block page (ADR-028 forward-compat: same code stores real TRI unchanged). A
    well-formed empty `[]` still passes through (an empty window is a curate concern, not a fetch
    failure).
    """
    stripped = content.strip()
    if not stripped:
        raise SourceError(f"{source}: empty response body")
    if stripped[:1] not in (b"[", b"{"):
        raise SourceError(
            f"{source}: response is not JSON (niftyindices HTML shell / block page -- scripted"
            " access is walled, see ops/journal.md 2026-08-10); refusing to store"
        )
