"""NSE corporate-actions source adapter (doc 06 §6.1; doc 20 P0-10; doc 09 P0-10 finding).

The corporate-actions feed is the `www` JSON API, which is COOKIE-gated (P0-10 probe 2026-07-15):
a GET to prime_url returns 403 but sets the Akamai bootstrap cookie, after which the API returns
200 to a plain client — so `fetch_window` does a two-step polite flow: cookie-prime GET (its
status is IGNORED — the 403 still seeds the httpx cookie jar) → politeness sleep → windowed API
GET. It stores the raw JSON immutably via RawStore under logical_date=until and nothing else;
403/429 on the API aborts without retry (P0-06 recorded deferral of backoff to P0-17). The
window is uncapped (5y in one call, probed), so one invocation populates the DoD's 5y. Parsing
and classification live in curation; raw is stored regardless of parseability once it is a JSON
array (an HTML block page or error envelope is rejected as a fetch failure, not stored as data).
"""

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date

import httpx
import structlog

from quant.config import SourceSpec
from quant.errors import ConfigError, SourceError
from quant.ingest.store import RawArtifact, RawStore

log = structlog.get_logger()

SOURCE = "corp_actions"


@dataclass(frozen=True, slots=True)
class IngestSummary:
    """Result of one windowed ingest: the [since, until] span plus stored/noop disposition."""

    source: str
    since: str
    until: str
    stored: bool
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def fetch_window(
    since: date,
    until: date,
    *,
    store: RawStore,
    spec: SourceSpec,
    client: httpx.Client,
    sleep: Callable[[float], None] | None = None,
) -> tuple[RawArtifact, bool]:
    """Cookie-prime, then fetch the CA window [since, until]; store under logical_date=until.

    sleep is late-bound to time.sleep so tests can patch it (a def-time default would freeze the
    real function object at import).
    """
    if until < since:
        raise ConfigError(f"--until {until} is before --since {since}")
    if spec.prime_url is None:
        raise ConfigError(f"{SOURCE} spec needs prime_url for the cookie-prime step (doc 09)")
    _sleep = sleep if sleep is not None else time.sleep

    # Cookie-prime: the homepage 403s but sets the Akamai cookie into the httpx jar; its status is
    # deliberately not gated (a 403 here is the EXPECTED shape, not a block of our real request).
    _sleep(spec.delay_seconds)
    try:
        client.get(spec.prime_url, headers=spec.headers, timeout=spec.timeout_seconds)
    except httpx.HTTPError as exc:
        raise SourceError(f"{SOURCE}: cookie-prime GET to {spec.prime_url} failed: {exc}") from exc

    _sleep(spec.delay_seconds)
    url = spec.url_template.format(
        from_date=since.strftime("%d-%m-%Y"), to_date=until.strftime("%d-%m-%Y")
    )
    resp = client.get(url, headers=spec.headers, timeout=spec.timeout_seconds)
    if resp.status_code in (403, 429):
        raise SourceError(
            f"{SOURCE} blocked (HTTP {resp.status_code}) for [{since}..{until}]: the cookie-prime"
            " did not unlock the API (doc 09 P0-10); aborting without retry"
        )
    if resp.status_code != 200:
        raise SourceError(f"{SOURCE}: unexpected HTTP {resp.status_code} for [{since}..{until}]")
    _reject_unless_json_array(resp.content)
    artifact, created = store.put(SOURCE, until, resp.content, suffix=".json")
    log.info(
        "ingest_stored",
        source=SOURCE,
        since=str(since),
        until=str(until),
        created=created,
        sha256=artifact.sha256,
    )
    return artifact, created


def _reject_unless_json_array(content: bytes) -> None:
    """Reject block pages / error envelopes; a raw-fidelity check only, never parsing."""
    stripped = content.strip()
    if not stripped:
        raise SourceError(f"{SOURCE}: empty response body")
    if stripped[:1] != b"[":
        raise SourceError(
            f"{SOURCE}: response is not a JSON array (HTML block page or error envelope)"
        )
