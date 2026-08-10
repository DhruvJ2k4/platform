"""Index TRI builder: raw niftyindices TR chunks -> validated index_tri frame + gap stats (P0-15).

Reads EVERY raw TR chunk ever ingested for both benchmark sources (`RawStore.latest_per_date`,
mirroring build_surveillance's unconditional full-history scan), parses each into (index_name, d,
tri_value), concatenates, enforces (index_name, d) uniqueness (index_tri has no PK -- the check
lives here, ContractViolation on drift), sorts deterministically, and validates against the
doc-10 IndexTri contract. It then GAP-CHECKS each series against the trading_calendar (the DoD's
"gap-checked" half): every calendar session in the overlapping covered span should carry a
tri_value, with no forward-fill (doc 21 §3 idiom) and no extraneous non-session dates.

Gap-check is a reported DIAGNOSTIC (stats -> build report + WARN), never a publish gate: a benchmark
hole must not block the whole money-path curated store (doc 08's "calendar completeness" gates the
trading_calendar itself; "stale-but-consistent beats fresh-but-wrong" is the money-path rule).
Metric interpretation under the ADR-026 SAMPLED backfill vault (calendar sparse, real TRI dense):
`missing_sessions`/`gap_days_max` (calendar sessions in the OVERLAP with no TR value) are the
TRUSTWORTHY-but-coverage-limited signals -- ~0 today, and a real hole in TRI on a known trading day
shows here; `extraneous_dates` (TR dates in the overlap that are NOT calendar sessions) is DOMINATED
by calendar incompleteness until P0-19 densifies it, so it is recorded, NOT alarmed (a dense daily
TRI has many dates a sparse calendar lacks -- that is sampling, not drift). A genuinely broken date
axis is caught earlier, at parse time (strict DD-Mon-YYYY -> ParseError), never via extraneous. One
accepted tolerance: a weekend "special" session (DR-drill/Budget) is a bhavcopy-present calendar day
niftyindices may not publish a TR level for, so it can read as <=1 missing session / +1 gap -- a
bound accepted until the endpoint is reachable to verify special-day index publication. A
(index_name, d) value CONFLICT across overlapping re-ingested chunks QUARANTINES that one series
(published empty + a loud error stat), never aborts the rebuild -- a benchmark glitch must not take
down the money path. On the real vault today both sources are EMPTY (sourcing blocker,
ops/journal.md 2026-08-10): index_tri publishes zero rows -- honest, inert on real data like P0-14.
"""

from dataclasses import dataclass
from datetime import date

import pandas as pd
import structlog

from quant.config import Settings
from quant.curate.parsers.index_tri import parse_index_tri
from quant.ingest import RawStore
from quant.ingest.index_tri import INDEX_NAME, SOURCES
from quant.schemas import IndexTri

log = structlog.get_logger()


@dataclass(frozen=True)
class IndexTriResult:
    """The validated index_tri frame plus per-source gap-check + accounting counters."""

    frame: pd.DataFrame
    stats: dict[str, int]


def _gap_stats(tri_dates: list[date], cal_dates: list[date]) -> dict[str, int]:
    """Per-index gap diagnostics vs the trading calendar; see module docstring for semantics."""
    tri = sorted(set(tri_dates))
    cal = sorted(set(cal_dates))
    if not tri or not cal:
        return {"missing_sessions": 0, "gap_days_max": 0, "extraneous_dates": 0}
    tri_set, cal_set = set(tri), set(cal)
    lo, hi = max(tri[0], cal[0]), min(tri[-1], cal[-1])
    overlap = [c for c in cal if lo <= c <= hi]
    missing = [c for c in overlap if c not in tri_set]
    # extraneous: TR dates WITHIN the overlap that are not sessions (ADR-028: over the overlapping
    # span only -- leading/trailing out-of-coverage TR dates are not drift, so never counted).
    extraneous = sum(1 for d in tri if lo <= d <= hi and d not in cal_set)
    run = best = 0
    for c in overlap:
        if c in tri_set:
            run = 0
        else:
            run += 1
            best = max(best, run)
    return {"missing_sessions": len(missing), "gap_days_max": best, "extraneous_dates": extraneous}


def build_index_tri(
    calendar: pd.DataFrame, asof: date, settings: Settings | None = None
) -> IndexTriResult:
    """Full-history rebuild of index_tri from every raw TR chunk <= asof, gap-checked vs cal."""
    store = RawStore(settings)
    cal_dates = [d for d in calendar["d"].tolist() if d <= asof]

    frames: list[pd.DataFrame] = []
    stats: dict[str, int] = {"rows": 0, "gap_days_max": 0, "extraneous_dates": 0, "conflicts": 0}
    for source in SOURCES:
        index_name = INDEX_NAME[source]
        rows = [
            parse_index_tri(a.path.read_bytes(), index_name)
            for a in store.latest_per_date(source)
            if a.logical_date <= asof
        ]
        frame = pd.concat(rows, ignore_index=True) if rows else parse_index_tri(b"[]", index_name)
        # Overlapping re-ingested windows (different chunk-end logical_dates) legitimately repeat a
        # (index, day) with the SAME value -> collapse; a CONFLICTING value is feed drift, which
        # QUARANTINES that series (publish empty + loud error stat), never aborting the rebuild -- a
        # benchmark glitch must not take down the money-path store (ADR-028).
        frame = frame.drop_duplicates(ignore_index=True)
        conflict = frame.duplicated(subset=["index_name", "d"], keep=False)
        stats[f"{source}_conflict"] = int(bool(conflict.any()))
        if bool(conflict.any()):
            sample = frame[conflict].iloc[0]
            log.error(
                "index_tri_value_conflict",
                index_name=index_name,
                d=str(sample["d"]),
                note="conflicting TR levels across chunks -- series quarantined (empty)",
            )
            stats["conflicts"] += 1
            frame = frame.iloc[0:0]  # empty slice keeps dtypes -- quarantine this one series
        gaps = _gap_stats(frame["d"].tolist(), cal_dates)
        stats[f"{source}_rows"] = len(frame)
        stats[f"{source}_missing_sessions"] = gaps["missing_sessions"]
        stats[f"{source}_gap_days_max"] = gaps["gap_days_max"]
        stats[f"{source}_extraneous_dates"] = gaps["extraneous_dates"]
        stats["gap_days_max"] = max(stats["gap_days_max"], gaps["gap_days_max"])
        stats["extraneous_dates"] += gaps["extraneous_dates"]
        frames.append(frame)

    combined = (
        pd.concat(frames, ignore_index=True)
        .sort_values(["index_name", "d"], kind="stable")
        .reset_index(drop=True)
    )
    stats["rows"] = len(combined)
    validated: pd.DataFrame = IndexTri.validate(combined, lazy=True)
    log.info("index_tri_built", **stats)
    return IndexTriResult(frame=validated, stats=stats)
