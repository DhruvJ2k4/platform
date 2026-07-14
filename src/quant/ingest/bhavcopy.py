"""NSE bhavcopy source adapter, current UDiFF format (doc 06 §6.1; doc 09 P0-05 findings).

fetch() does exactly: politeness sleep → download → zip CRC integrity check → immutable store
via RawStore, and nothing else. A 404 is an expected-absence signal (holiday) that the P0-08
calendar will consume — never an alert; 403/429 aborts immediately without retries (backoff +
alerting belong to the nightly-cron era, P0-17 — recorded deferral of doc 06's IP-block mode).
Parsing lives in curation; raw is stored regardless of content once CRC-valid.
"""

import io
import time
import zipfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, timedelta

import httpx
import structlog

from quant.config import SourceSpec
from quant.errors import ConfigError, SourceError
from quant.ingest.store import RawArtifact, RawStore

log = structlog.get_logger()

SOURCE = "bhavcopy"


@dataclass(frozen=True, slots=True)
class IngestSummary:
    """Counts for one ingest run: stored/noop days have raw files; holiday days do not."""

    source: str
    since: str
    until: str
    stored: int
    noop: int
    holiday: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def fetch(
    d: date,
    *,
    store: RawStore,
    spec: SourceSpec,
    client: httpx.Client,
    sleep: Callable[[float], None] | None = None,
) -> tuple[RawArtifact, bool] | None:
    """Fetch one date's bhavcopy; None on holiday-404, else (artifact, created).

    sleep is late-bound to time.sleep so tests can patch it (a def-time default would
    freeze the real function object at import).
    """
    (sleep if sleep is not None else time.sleep)(spec.delay_seconds)
    url = _url_for(d, spec)
    resp = client.get(url, headers=spec.headers, timeout=spec.timeout_seconds)
    if resp.status_code == 404:
        log.info("ingest_holiday_404", source=SOURCE, logical_date=str(d))
        return None
    if resp.status_code in (403, 429):
        raise SourceError(
            f"{SOURCE} blocked (HTTP {resp.status_code}) for {d}: NSE's edge requires the four"
            " browser headers (doc 09 P0-05); aborting without retry"
        )
    if resp.status_code != 200:
        raise SourceError(f"{SOURCE}: unexpected HTTP {resp.status_code} for {d}")
    _reject_unless_valid_zip(resp.content, d)
    artifact, created = store.put(SOURCE, d, resp.content, suffix=".zip")
    log.info(
        "ingest_stored",
        source=SOURCE,
        logical_date=str(d),
        created=created,
        sha256=artifact.sha256,
    )
    return artifact, created


_MONTHS_ABBR = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _url_for(d: date, spec: SourceSpec) -> str:
    """Era-aware URL: classic archive pattern before the UDiFF cutover (doc 09 epoch map)."""
    if spec.classic_until is not None and spec.classic_url_template and d <= spec.classic_until:
        mmm = _MONTHS_ABBR[d.month - 1]
        return spec.classic_url_template.format(yyyy=f"{d.year:04d}", mmm=mmm, dd=f"{d.day:02d}")
    return spec.url_template.format(yyyymmdd=d.strftime("%Y%m%d"))


def fetch_range(
    since: date,
    until: date,
    *,
    store: RawStore,
    spec: SourceSpec,
    client: httpx.Client,
    sleep: Callable[[float], None] | None = None,
    weekends: bool = False,
) -> IngestSummary:
    """Fetch every weekday (plus weekends when asked) in [since, until]; abort on SourceError.

    weekends=True exists for calendar-grade presence backfills: Muhurat sessions can fall on
    a weekend (e.g. Sunday 2023-11-12), and skipping Sat/Sun would blind the P0-08 calendar
    to them. Weekend 404s are expected absence, exactly like weekday holidays.
    """
    if until < since:
        raise ConfigError(f"--until {until} is before --since {since}")
    stored = noop = holiday = 0
    d = since
    while d <= until:
        if weekends or d.weekday() < 5:  # holidays (and quiet weekends) surface as 404s
            result = fetch(d, store=store, spec=spec, client=client, sleep=sleep)
            if result is None:
                holiday += 1
            elif result[1]:
                stored += 1
            else:
                noop += 1
        d += timedelta(days=1)
    summary = IngestSummary(SOURCE, str(since), str(until), stored, noop, holiday)
    log.info("ingest_range_done", **summary.as_dict())
    return summary


def _reject_unless_valid_zip(content: bytes, d: date) -> None:
    """doc 13 F1: a partial/corrupt download is rejected by checksum, nothing stored."""
    if content[:2] != b"PK":
        raise SourceError(f"{SOURCE} {d}: response is not a zip (block page or partial body)")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            if not zf.namelist():
                raise SourceError(f"{SOURCE} {d}: zip has no members")
            bad = zf.testzip()
            if bad is not None:
                raise SourceError(f"{SOURCE} {d}: CRC check failed for member {bad!r}")
    except zipfile.BadZipFile as exc:
        raise SourceError(f"{SOURCE} {d}: corrupt zip rejected ({exc})") from exc
