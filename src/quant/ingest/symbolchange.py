"""NSE symbol-change snapshot adapter (doc 06 §6.1; doc 20 P0-09).

The symbol-changes file is a SNAPSHOT source: one full-history CSV at a fixed URL, no date
placeholder — logical_date labels the fetch day, and re-fetches are idempotent by content
(identical bytes no-op; a grown file appends a supersession row, doc 08). fetch_snapshot()
does exactly: politeness sleep → download → content gate (non-empty, not an HTML block page)
→ immutable store via RawStore, and nothing else. There is no holiday semantics here: 404 is
a SourceError like any other unexpected status, and 403/429 aborts immediately without
retries (P0-06 recorded deferral). Parsing lives in curation.
"""

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date

import httpx
import structlog

from quant.config import SourceSpec
from quant.errors import SourceError
from quant.ingest.store import RawArtifact, RawStore

log = structlog.get_logger()

SOURCE = "symbolchange"


@dataclass(frozen=True, slots=True)
class SnapshotSummary:
    """Result of one snapshot ingest: the labelled day plus stored/noop disposition."""

    source: str
    logical_date: str
    stored: bool
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def fetch_snapshot(
    d: date,
    *,
    store: RawStore,
    spec: SourceSpec,
    client: httpx.Client,
    sleep: Callable[[float], None] | None = None,
) -> tuple[RawArtifact, bool]:
    """Fetch the current snapshot, labelled logical_date=d; returns (artifact, created).

    sleep is late-bound to time.sleep so tests can patch it (a def-time default would freeze
    the real function object at import).
    """
    (sleep if sleep is not None else time.sleep)(spec.delay_seconds)
    resp = client.get(spec.url_template, headers=spec.headers, timeout=spec.timeout_seconds)
    if resp.status_code in (403, 429):
        raise SourceError(
            f"{SOURCE} blocked (HTTP {resp.status_code}): NSE's edge requires the four browser"
            " headers (doc 09 P0-05); aborting without retry"
        )
    if resp.status_code != 200:
        raise SourceError(
            f"{SOURCE}: unexpected HTTP {resp.status_code} (a snapshot has no holidays)"
        )
    _reject_unless_plausible_csv(resp.content)
    artifact, created = store.put(SOURCE, d, resp.content, suffix=".csv")
    log.info(
        "ingest_stored",
        source=SOURCE,
        logical_date=str(d),
        created=created,
        sha256=artifact.sha256,
    )
    return artifact, created


def _reject_unless_plausible_csv(content: bytes) -> None:
    """Reject block pages and truncated bodies; raw fidelity checks only, never parsing."""
    if not content.strip():
        raise SourceError(f"{SOURCE}: empty response body")
    head = content.lstrip()[:256].lower()
    if head.startswith((b"<!doctype", b"<html", b"<?xml")):
        raise SourceError(f"{SOURCE}: response is a markup block page, not the CSV")
