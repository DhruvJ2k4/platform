"""NSE ASM/GSM surveillance-list snapshot adapters (doc 06 §6.1; doc 20 P0-14; doc 09 finding).

Both `asm.json` and `gsm.json` are SNAPSHOT sources exactly like `symbolchange.csv`: one full
list at a fixed URL, no date placeholder, `logical_date` labels the fetch day. Verified live
2026-07-27 (two probes, cold and with corp_actions-tier simple priming, byte-identical both
times): a plain client with just the four browser headers gets HTTP 200 — no cookie-priming
needed at the transport level. But the response CONTENT depends on session validity that plain
`httpx` cannot obtain (a full Akamai bot-challenge session — JS-solved cookies): without it, the
body is a byte-identical STUB `{"columns": [...]}`, zero data rows, no error. `fetch_asm_snapshot`
/`fetch_gsm_snapshot` do exactly: politeness sleep → download → content gate → immutable store,
and nothing else (the FORMAT parser is not here — doc 06 §6.1 — genuinely uncertain content
still always reaches curation unfiltered).

`_reject_columns_only_stub` is a fetch-VALIDITY pre-filter, not a parser — the same category of
check `symbolchange.py`'s `_reject_unless_plausible_csv` and `corp_actions.py`'s
`_reject_unless_json_array` already make (reject a response that is conclusively NOT DATA before
ever storing it; doc 06 §6.1 carve-out), just for a more sophisticated failure mode: an HTML
block page is byte-sniffable by prefix, but the stub and a real payload are BOTH well-formed
JSON objects starting with `{`, so distinguishing them genuinely requires `json.loads` + a
top-level-key check — this is honestly a real (if minimal) parse, not a byte-sniff, and is
scoped to detect ONLY the one known degraded shape; an unrecognized-but-real shape always passes
through to the curate-layer parser rather than being second-guessed here. Deliberately duplicates
part of what `curate/parsers/surveillance.py`'s `parse_asm`/`parse_gsm` would also reject (a
snapshot with no data groups) — kept at the ingest layer too so the operator gets an IMMEDIATE,
actionable signal (`ingest asm` exits 1 with the specific reason) instead of a stub silently
"succeeding" into the raw store and only surfacing as a downstream `ParseError` at the next
`curate --rebuild`, and so the raw vault doesn't accumulate an unbounded run of byte-identical
worthless stub files for as long as the sourcing blocker persists. See ops/journal.md 2026-07-27
for the full sourcing investigation (why this can't be resolved with headers alone) and the
deferred-sourcing decision this adapter is forward-compatible with: the day a valid session
becomes available by whatever means, this same code starts storing real data with zero changes.
"""

import json
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

SOURCE_ASM = "asm"
SOURCE_GSM = "gsm"
_STUB_ONLY_KEYS = frozenset({"columns"})


@dataclass(frozen=True, slots=True)
class SnapshotSummary:
    """Result of one snapshot ingest: the labelled day plus stored/noop disposition."""

    source: str
    logical_date: str
    stored: bool
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def fetch_asm_snapshot(
    d: date,
    *,
    store: RawStore,
    spec: SourceSpec,
    client: httpx.Client,
    sleep: Callable[[float], None] | None = None,
) -> tuple[RawArtifact, bool]:
    """Fetch the current ASM list snapshot, labelled logical_date=d; returns (artifact, created)."""
    return _fetch_snapshot(SOURCE_ASM, d, store=store, spec=spec, client=client, sleep=sleep)


def fetch_gsm_snapshot(
    d: date,
    *,
    store: RawStore,
    spec: SourceSpec,
    client: httpx.Client,
    sleep: Callable[[float], None] | None = None,
) -> tuple[RawArtifact, bool]:
    """Fetch the current GSM list snapshot, labelled logical_date=d; returns (artifact, created)."""
    return _fetch_snapshot(SOURCE_GSM, d, store=store, spec=spec, client=client, sleep=sleep)


def _fetch_snapshot(
    source: str,
    d: date,
    *,
    store: RawStore,
    spec: SourceSpec,
    client: httpx.Client,
    sleep: Callable[[float], None] | None,
) -> tuple[RawArtifact, bool]:
    """Shared snapshot flow for both sources (sleep is late-bound so tests can patch it)."""
    (sleep if sleep is not None else time.sleep)(spec.delay_seconds)
    resp = client.get(spec.url_template, headers=spec.headers, timeout=spec.timeout_seconds)
    if resp.status_code in (403, 429):
        raise SourceError(
            f"{source} blocked (HTTP {resp.status_code}): NSE's edge requires the four browser"
            " headers (doc 09 P0-14); aborting without retry"
        )
    if resp.status_code != 200:
        raise SourceError(
            f"{source}: unexpected HTTP {resp.status_code} (a snapshot has no holidays)"
        )
    _reject_columns_only_stub(resp.content, source)
    artifact, created = store.put(source, d, resp.content, suffix=".json")
    log.info(
        "ingest_stored", source=source, logical_date=str(d), created=created, sha256=artifact.sha256
    )
    return artifact, created


def _reject_columns_only_stub(content: bytes, source: str) -> None:
    """Reject the known degraded shape; a narrow, documented exception to byte-sniff-only gates.

    The stub `{"columns": [...]}` and a real payload (`{"columns": [...], "longterm": {...}}` or
    similar) are both well-formed JSON objects starting with `{` — indistinguishable by prefix —
    so this must actually parse the envelope. It checks ONLY that the top-level key set is not a
    subset of `{"columns"}`; it never inspects what the other key(s) look like (that is the
    curate-layer parser's job, per doc 06 §6.1's "parser is NOT here" — an unrecognized-but-real
    shape must still pass through to curation, never be second-guessed at the ingest gate).
    """
    if not content.strip():
        raise SourceError(f"{source}: empty response body")
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceError(f"{source}: response is not valid JSON: {exc}") from exc
    if isinstance(payload, dict) and set(payload.keys()) <= _STUB_ONLY_KEYS:
        raise SourceError(
            f"{source}: response is the columns-only stub (no Akamai bot-challenge session — a"
            " plain client cannot obtain one; see ops/journal.md 2026-07-27) — refusing to store"
            " degraded data as real"
        )
