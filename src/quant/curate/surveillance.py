"""ASM/GSM surveillance builder: raw snapshot history -> the PIT frame build_universe consumes.

Reads EVERY raw ASM/GSM snapshot ever ingested (`RawStore.latest_per_date`, mirroring
`build_corp_actions`'s unconditional-scan shape — no `asof` parameter; PIT safety lives entirely
in row-level `available_at` filtering downstream, in `curate/universe.py`'s `_surveillance_flags`
and the coverage floor/ceiling gate, never in pre-truncating this scan), classifies each row's
free-text stage, and turns the SEQUENCE of full-list snapshots into a minimal event log via
`_cdc_diff` — the mechanism that makes list-*removal* correctly flip `investable` back, not just
list-*add* (a real gap in the P0-13-shipped `_surveillance_flags`, fixed alongside this module).

Stage classification: ASM's `asmSurvIndicator` is a clean structured field ("Stage I") parsed via
a strict roman-numeral map (`ParseError` on drift — this gates the doc-21 §4 ASM≥2 threshold, so
guessing here is unacceptable). GSM's real stage is NOT in the `gsmStage` field (a trap caught
2026-07-27: that field is a Roman-numeral encoding of an unrelated internal sequence number) —
it is mined via a lenient regex from `survDesc`/`survCode` free text, falling back to a distinct
`_GSM_UNKNOWN` sentinel (never a fabricated real stage) on a miss; this is safe because GSM's
exclusion (doc 21 §4's "GSM*") is presence-only, not stage-gated. A within-snapshot duplicate
isin (ASM's real `longterm`+`shortterm` tiers can both list the same security) resolves via
`max(stage)` — the worse regime governs, never an arbitrary pick.

Coverage floor/ceiling (`SurveillanceResult`): `coverage_floor = max(asm_floor, gsm_floor)`,
`coverage_ceiling = min(asm_ceiling, gsm_ceiling)` — both `None` unless BOTH categories have at
least one ingested snapshot, so a date is never wrongly treated as "fully surveillance-checked"
when only one of the two lists was ever actually verified for it (a `min()` here would be the
over-claiming bug this whole mechanism exists to prevent, just moved up one level). These bound
ONLY the affirmative "nothing fired, can we say True" question in `curate/universe.py` — they
never suppress `frame`'s real exclusion-firing rows (`frame` is always a real, possibly-empty
DataFrame, never conditionally `None`), so a security genuinely flagged in a partially-sourced
category (e.g. ASM live, GSM still blocked) always correctly excludes regardless of the other
category's coverage state. See `curate/universe.py`'s module docstring for the full split.

**Known, accepted limitation** (not solved by this module — a fundamental property of point-in-
time snapshot ingestion, since NSE's feed has no per-security event history to reconstruct from):
`coverage_ceiling` bounds staleness only at the *trailing edge* of the observed range. It does
NOT close an *intra-gap blind spot* — a name that enters AND exits surveillance entirely BETWEEN
two actually-ingested snapshots leaves no CDC-diff evidence either way, and every date in that gap
still reads as checked-clean. `stats["surveillance_gap_days_max"]` makes an anomalous gap
*observable* rather than silently trusted; P0-17's absence-of-data alarm work (doc 06 §6.10, the
same pattern already used for the filings collector per doc 13 F4) is the right place to alert on
this once live sourcing resumes (see ops/journal.md 2026-07-27).

**Known, accepted limitation, escalated not buried**: one live GSM sample's `survDesc` read "ASM
IBC Stage I and GSM Stage 0" — a possible independent ASM-flavored signal inside GSM free text,
unverified whether it also appears in `asm.json` for that security. The ASM hard-exclusion stays
scoped to `asm.json` only (never mined out of GSM text); `stats["gsm_survdesc_mentions_asm_ibc"]`
counts distinct isins in the latest GSM snapshot whose text mentions both tokens, surfaced by the
caller (`curate/build.py`) as a build-report WARN — an operator-review trigger, mirroring
`needs_review` corporate actions, until a future task can compare real `asm.json`/`gsm.json` data
side-by-side and close the gap for real.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

import pandas as pd
import pyarrow as pa
import structlog

from quant.config import Settings
from quant.curate.parsers.surveillance import parse_asm, parse_gsm
from quant.errors import ParseError
from quant.ingest import RawStore
from quant.ingest.surveillance import SOURCE_ASM, SOURCE_GSM
from quant.schemas import DATE, I32, STR, Contract, field

log = structlog.get_logger()

REMOVED = -1  # CDC-diff removal sentinel; real NSE stages are ASM 1-10, GSM 0-6 (probed), no clash
_GSM_UNKNOWN = 99  # a real GSM presence whose stage text didn't parse; != REMOVED, still excludes

_ROMAN = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
    "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
}  # fmt: skip
_ASM_STAGE_RE = re.compile(r"^Stage\s+([IVXLCDM]+)$")
# GSM stage: literal "GSM" then optional "stage"/"-" filler then a roman numeral or digit token
# (GSM Stage 0 is written as the digit "0", never a roman numeral -- Romans have no zero).
_GSM_STAGE_RE = re.compile(r"GSM\s*(?:[Ss]tage)?\s*(?:-\s*)?([IVXLCDM]+|\d+)\b")


class SurveillanceEvent(Contract):
    """The frame `build_universe`'s surveillance seam consumes (P0-13 contract, unchanged)."""

    isin: pd.ArrowDtype = field(STR, nullable=False)
    available_at: pd.ArrowDtype = field(DATE, nullable=False)
    category: pd.ArrowDtype = field(STR, nullable=False, isin=["ASM", "GSM"])
    stage: pd.ArrowDtype = field(I32, nullable=False)


@dataclass(frozen=True)
class SurveillanceResult:
    """The event frame plus the coverage bounds and accounting counters for one build."""

    frame: pd.DataFrame
    coverage_floor: date | None
    coverage_ceiling: date | None
    stats: dict[str, int]


def _asm_stage(indicator: str) -> int:
    """Strict: gates the doc-21 §4 ASM>=2 threshold, so an unrecognized shape is a ParseError."""
    m = _ASM_STAGE_RE.match(indicator.strip())
    if m and m.group(1) in _ROMAN:
        return _ROMAN[m.group(1)]
    raise ParseError(
        f"asm: unrecognized asmSurvIndicator {indicator!r} (expected 'Stage <roman I-X>')"
    )


def _gsm_stage(raw_stage_text: str) -> int:
    """Lenient — GSM's exclusion is presence-only, so a miss falls back to _GSM_UNKNOWN, never
    raises."""
    m = _GSM_STAGE_RE.search(raw_stage_text)
    if not m:
        return _GSM_UNKNOWN
    token = m.group(1)
    return int(token) if token.isdigit() else _ROMAN.get(token, _GSM_UNKNOWN)


def _mentions_asm_ibc(raw_stage_text: str) -> bool:
    upper = raw_stage_text.upper()
    return "ASM" in upper and "IBC" in upper


def _cdc_diff(snapshots: list[tuple[date, dict[str, int]]]) -> list[tuple[str, date, int]]:
    """Pure: (snapshot_date, {isin: stage}) sequence, ascending -> (isin, available_at, stage)
    events emitted ONLY on change (new isin, changed stage, or disappeared -> stage=REMOVED).

    The first-ever snapshot diffs against an implicit empty predecessor, so every isin present
    on day one correctly gets an ADD event (not silently assumed pre-existing).
    """
    events: list[tuple[str, date, int]] = []
    prev: dict[str, int] = {}
    for snap_date, state in snapshots:
        for isin in sorted(set(prev) | set(state)):
            new_stage = state.get(isin)
            old_stage = prev.get(isin)
            if new_stage is None:
                if old_stage is not None:
                    events.append((isin, snap_date, REMOVED))
            elif new_stage != old_stage:
                events.append((isin, snap_date, new_stage))
        prev = state
    return events


def _aggregate_snapshot(
    parsed: pd.DataFrame, stage_fn: Callable[[str], int], stats: dict[str, int], dup_stat_key: str
) -> dict[str, int]:
    """Group one snapshot's parsed rows by isin; a within-snapshot duplicate (e.g. ASM's real
    longterm+shortterm tiers both listing the same security) resolves via max(stage)."""
    state: dict[str, int] = {}
    for row in parsed.itertuples(index=False):
        isin = str(row.isin)
        stage = stage_fn(str(row.raw_stage_text))
        if isin in state:
            stats[dup_stat_key] = stats.get(dup_stat_key, 0) + 1
            state[isin] = max(state[isin], stage)
        else:
            state[isin] = stage
    return state


def _max_gap_days(dates: list[date]) -> int:
    if len(dates) < 2:
        return 0
    return max((b - a).days for a, b in pairwise(dates))


def build_surveillance(settings: Settings | None = None) -> SurveillanceResult:
    """Full-history rebuild of the surveillance event frame from every ASM/GSM raw snapshot."""
    store = RawStore(settings)
    stats: dict[str, int] = {
        "asm_snapshots": 0,
        "gsm_snapshots": 0,
        "asm_multi_tier_isins": 0,
        "gsm_duplicate_isins": 0,
        "surveillance_gap_days_max": 0,
        "gsm_survdesc_mentions_asm_ibc": 0,
        "asm_events": 0,
        "gsm_events": 0,
    }

    asm_artifacts = store.latest_per_date(SOURCE_ASM)
    gsm_artifacts = store.latest_per_date(SOURCE_GSM)
    stats["asm_snapshots"] = len(asm_artifacts)
    stats["gsm_snapshots"] = len(gsm_artifacts)

    # PIT ANCHOR (quant-researcher review, 2026-07-27): `available_at` MUST always be
    # `artifact.logical_date` (the day the platform actually ingested this snapshot), NEVER
    # `parsed["snapshot_date"]` (the row's self-reported asmTime/gsmTime). The parsed field is
    # informational only, deliberately unused here — using it instead would let a snapshot
    # ingested on day T back-date knowledge to whatever historical date the payload claims,
    # a textbook look-ahead. See ParsedSurveillance's snapshot_date field docs (parsers module).
    asm_snapshots: list[tuple[date, dict[str, int]]] = []
    for artifact in asm_artifacts:
        parsed = parse_asm(artifact.path.read_bytes())
        state = _aggregate_snapshot(parsed, _asm_stage, stats, "asm_multi_tier_isins")
        asm_snapshots.append((artifact.logical_date, state))

    gsm_snapshots: list[tuple[date, dict[str, int]]] = []
    for i, artifact in enumerate(gsm_artifacts):
        parsed = parse_gsm(artifact.path.read_bytes())
        state = _aggregate_snapshot(parsed, _gsm_stage, stats, "gsm_duplicate_isins")
        gsm_snapshots.append((artifact.logical_date, state))
        if i == len(gsm_artifacts) - 1:  # only the LATEST snapshot: a "right now" signal
            mentioning = {
                str(row.isin)
                for row in parsed.itertuples(index=False)
                if _mentions_asm_ibc(str(row.raw_stage_text))
            }
            stats["gsm_survdesc_mentions_asm_ibc"] = len(mentioning)

    asm_events = _cdc_diff(asm_snapshots)
    gsm_events = _cdc_diff(gsm_snapshots)
    stats["asm_events"] = len(asm_events)
    stats["gsm_events"] = len(gsm_events)

    gap = 0
    if asm_artifacts:
        gap = max(gap, _max_gap_days([a.logical_date for a in asm_artifacts]))
    if gsm_artifacts:
        gap = max(gap, _max_gap_days([a.logical_date for a in gsm_artifacts]))
    stats["surveillance_gap_days_max"] = gap

    asm_floor = asm_artifacts[0].logical_date if asm_artifacts else None
    asm_ceiling = asm_artifacts[-1].logical_date if asm_artifacts else None
    gsm_floor = gsm_artifacts[0].logical_date if gsm_artifacts else None
    gsm_ceiling = gsm_artifacts[-1].logical_date if gsm_artifacts else None
    coverage_floor = max(asm_floor, gsm_floor) if asm_floor and gsm_floor else None
    coverage_ceiling = min(asm_ceiling, gsm_ceiling) if asm_ceiling and gsm_ceiling else None
    # NOTE: coverage_floor > coverage_ceiling is a LEGITIMATE state, not a builder bug -- it
    # means the two categories' own coverage windows don't overlap at all (e.g. ASM's history
    # ends before GSM's begins). No date can then satisfy floor<=d<=ceiling, so build_universe's
    # per-row bounded check degrades safely to always-undetermined for every date -- exactly the
    # conservative behaviour wanted. (An earlier draft wrongly asserted floor<=ceiling here; a
    # unit test with asymmetric ASM/GSM coverage windows caught that the assertion itself, not
    # the underlying logic, was the bug.)

    isins = [e[0] for e in asm_events] + [e[0] for e in gsm_events]
    avails = [e[1] for e in asm_events] + [e[1] for e in gsm_events]
    cats = ["ASM"] * len(asm_events) + ["GSM"] * len(gsm_events)
    stages = [e[2] for e in asm_events] + [e[2] for e in gsm_events]
    table = pa.table(
        {
            "isin": pa.array(isins, STR),
            "available_at": pa.array(avails, DATE),
            "category": pa.array(cats, STR),
            "stage": pa.array(stages, I32),
        }
    )
    frame = SurveillanceEvent.validate(table.to_pandas(types_mapper=pd.ArrowDtype), lazy=True)
    log.info("surveillance_built", **stats)
    return SurveillanceResult(
        frame=frame, coverage_floor=coverage_floor, coverage_ceiling=coverage_ceiling, stats=stats
    )
