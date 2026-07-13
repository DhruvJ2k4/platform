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
    url = spec.url_template.format(yyyymmdd=d.strftime("%Y%m%d"))
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


def fetch_range(
    since: date,
    until: date,
    *,
    store: RawStore,
    spec: SourceSpec,
    client: httpx.Client,
    sleep: Callable[[float], None] | None = None,
) -> IngestSummary:
    """Fetch every weekday in [since, until]; aborts on the first SourceError."""
    if until < since:
        raise ConfigError(f"--until {until} is before --since {since}")
    stored = noop = holiday = 0
    d = since
    while d <= until:
        if d.weekday() < 5:  # Sat/Sun are never trading days; holidays surface as 404s
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
