"""Corporate-actions classifier + table builder (doc 20 P0-10; doc 21 §1; ADR-023).

Turns the parsed NSE corporate-actions feed into the `corporate_actions` doc-10 table. The core
is `classify()`, a rules engine over the human-entered free-text `subject`. Its governing
principle is conservative honesty: content ambiguity routes to `needs_review` (operator resolves)
and never crashes; nothing price-affecting is ever silently dropped (the final fallthrough is
`other`/needs_review, not a drop) — only pure meetings (no ex-date effect) are dropped, counted.

Column conventions consumed by the P0-11 adjuster (doc 21 §1) — pinned here so a factor is
never inverted:
  * split: ratio_num=old face value, ratio_den=new → factor den/num (covers consolidations).
  * bonus: ratio_num=X new shares, ratio_den=Y held → factor den/(num+den).
  * rights: ratio_num:ratio_den=terms, cash_amount=premium; ALWAYS needs_review — the feed's
    faceVal is anachronistic (current, not at ex_date) so issue price S=FV+premium cannot be
    reconstructed and P_cum is unknown here; the operator enters the factor.
  * dividend: cash_amount = Σ per-share amounts (interim+special summed); not price-adjusted
    (cash-credited, doc 21 §1). No amount parseable → needs_review.
  * buyback / demerger / other: no ratio/cash; demerger+other+rights always needs_review.
`available_at` is set to ex_date (00:00, naive) — the feed carries no broadcast timestamp
(caBroadcastDate is null); this is look-ahead-safe and P0-21 refines it. The build is a pure
deterministic function of its input frame; it returns a validated frame (persistence is P0-11).
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import pandas as pd
import pyarrow as pa
import structlog

from quant.config import Settings
from quant.curate.parsers.corp_actions import parse_corp_actions
from quant.errors import ContractViolation
from quant.ingest import RawStore
from quant.schemas import DATE, I32, STR, TS, CorporateActions, dec

log = structlog.get_logger()

SOURCE = "corp_actions"

# Feed series that are NOT NSE equities (govt securities, InvIT/REIT units, RR); excluded from the
# equity CA table by an EXCLUDE-list (keep EQ and any future equity series like BE, never drop a
# real equity split tagged non-EQ — CAs are ISIN-level facts, ADR-006 EQ-filter is doc 21 §4).
_NON_EQUITY_SERIES = frozenset({"GS", "IV", "RR"})

_TWO_PLACES = Decimal("0.01")
_RATIO_RE = re.compile(r"(\d+)\s*:\s*(\d+)")
# FV groups capture decimals so a sub-rupee face value ("To Re 0.50") is SEEN (then routed to
# needs_review — a fractional FV has no integer I32 ratio) rather than silently truncated to 0.
_FV_RE = re.compile(
    r"from\s+(?:rs|re)\.?\s*(\d+(?:\.\d+)?).*?to\s+(?:rs|re)\.?\s*(\d+(?:\.\d+)?)", re.I
)
_RUPEE_RE = re.compile(r"(?:rs|re)\.?\s*(\d+(?:\.\d+)?)", re.I)
_PREM_RE = re.compile(r"(?:premium|prm)\s*(?:rs|re)?\.?\s*(\d+(?:\.\d+)?)", re.I)
_DIV_ABBR_RE = re.compile(r"\bdiv\b")  # the "Div - Rs .." abbreviation, never "sub-division"
# Non-dividend monetary clauses whose rupee figure must NOT be summed into the dividend cash
# (face value, interest, return of/on capital, redemption, premium, debenture, paid-up). Masked
# out before summing so compound dividends (interim+special) still add up but a face-value or
# interest figure never inflates the credited cash.
_NONDIV_MONEY_RE = re.compile(
    r"(?:face\s*value|paid[\s-]*up|interest|return\s+(?:on|of)\s+capital|redemption|premium|"
    r"debenture)[^/&]*?(?:rs|re)\.?\s*\d+(?:\.\d+)?",
    re.I,
)
# Equity-tradeable series are kept; GS/IV/RR are excluded (non-equity). A series outside this
# known set is KEPT (exclude-list robustness for a future tag like BE) but alarmed, never silent.
_KNOWN_SERIES = frozenset({"EQ", "BE", "GS", "IV", "RR"})

# Hard (structural, price-affecting) kind keywords — excludes dividend, which is soft. A subject
# carrying ≥2 of these categories (or a hard category + dividend) is a compound reorganization →
# other/needs_review (both 5y multi-action rows are "Scheme Of Arrangement - Bonus X:Y").
_HARD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "demerger": ("demerger", "scheme of arrangement", "scheme of amalgamation", "composite scheme"),
    "capital_reduction": ("capital reduction", "reduction of capital"),
    "split": ("face value split", "sub-division", "sub division", "consolidation"),
    "bonus": ("bonus",),
    "rights": ("rights",),
    "buyback": ("buyback", "buy back"),
}
# Non-equity-instrument markers: a bonus/split of these does NOT adjust the equity price
# (e.g. "Bonus Ncrps" = preference-share bonus) → force needs_review.
_NON_EQ_INSTRUMENT = (
    "ncrps",
    "nrps",
    "preference",
    " pref ",
    "partly paid",
    "partly-paid",
    "warrant",
    "debenture",
    " ncd ",
    "convertible",
    "cumulative",
)


@dataclass(frozen=True, slots=True)
class Classification:
    """One classified action; kind None means a droppable meeting (no ex-date effect)."""

    kind: str | None
    ratio_num: int | None
    ratio_den: int | None
    cash_amount: Decimal | None
    status: str | None


@dataclass(frozen=True)
class CorpActionsTables:
    """The validated corporate_actions frame plus the build-report counters (ADR-023)."""

    corporate_actions: pd.DataFrame
    stats: dict[str, int]


_MEETING = Classification(None, None, None, None, None)


def _to_money(text: str) -> Decimal | None:
    try:
        return Decimal(text).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def _colon_ratio(s: str) -> tuple[int, int] | None:
    m = _RATIO_RE.search(s)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _fv_split_ratio(s: str) -> tuple[int, int] | None:
    m = _FV_RE.search(s)
    if m is None:
        return None
    a, b = m.group(1), m.group(2)
    # Only integer face values map to an I32 ratio; a decimal (sub-rupee) FV has no auto ratio.
    return (int(a), int(b)) if a.isdigit() and b.isdigit() else None


def _positive(ratio: tuple[int, int] | None) -> tuple[int, int] | None:
    """Gate a ratio to strictly-positive terms; a 0 denominator/numerator can never auto-adjust
    (factor den/num or den/(num+den) would be 0 or divide-by-zero in the P0-11 adjuster)."""
    return ratio if ratio is not None and ratio[0] > 0 and ratio[1] > 0 else None


def _premium(s: str) -> Decimal | None:
    m = _PREM_RE.search(s)
    return _to_money(m.group(1)) if m else None


def _dividend_total(s: str) -> Decimal | None:
    """Sum per-share dividend cash: mask non-dividend monetary clauses (face value, interest,
    return of capital, …) first so compounds add up but a face-value/interest figure never
    inflates the credit. A zero/absent total → None (→ needs_review, never a fabricated 0)."""
    masked = _NONDIV_MONEY_RE.sub(" ", s)
    amounts = _RUPEE_RE.findall(masked)
    if not amounts:
        return None
    total = sum((Decimal(a) for a in amounts), Decimal(0)).quantize(
        _TWO_PLACES, rounding=ROUND_HALF_UP
    )
    return total if total > 0 else None


def _hard_categories(s: str) -> set[str]:
    return {cat for cat, kws in _HARD_KEYWORDS.items() if any(k in s for k in kws)}


def _is_dividend(s: str) -> bool:
    return "dividend" in s or "divdend" in s or bool(_DIV_ABBR_RE.search(s))


def _review(
    kind: str, ratio: tuple[int, int] | None = None, cash: Decimal | None = None
) -> Classification:
    num, den = (ratio[0], ratio[1]) if ratio else (None, None)
    return Classification(kind, num, den, cash, "needs_review")


def classify(subject: str) -> Classification:
    """Classify one free-text `subject` into (kind, ratio, cash, status); meetings → kind None.

    Precedence is deliberate: ≥2 actions → other/review; demerger; capital reduction (→other);
    dividend BEFORE the meeting drop (so "AGM/Dividend - Rs 2" is a dividend); then the auto
    kinds; then meetings drop; then the conservative other/review fallthrough (never a drop).
    """
    s = subject.lower()
    cats = _hard_categories(s)
    has_div = _is_dividend(s)
    if len(cats) + (1 if has_div else 0) >= 2:
        return _review("other")
    if "demerger" in cats:
        return _review("demerger")
    if "capital_reduction" in cats:
        return _review("other")
    if has_div:
        if _non_equity_instrument(
            s
        ):  # e.g. preference / cumulative dividend — not an equity credit
            return _review("dividend")
        total = _dividend_total(s)
        status = "auto" if total is not None else "needs_review"
        return Classification("dividend", None, None, total, status)
    if "split" in cats:
        ratio = _positive(_fv_split_ratio(s))
        if ratio is None or _non_equity_instrument(s):
            return _review("split", ratio)
        return Classification("split", ratio[0], ratio[1], None, "auto")
    if "bonus" in cats:
        ratio = _positive(_colon_ratio(s))
        if ratio is None or _non_equity_instrument(s):
            return _review("bonus", ratio)
        return Classification("bonus", ratio[0], ratio[1], None, "auto")
    if "rights" in cats:
        return _review("rights", _positive(_colon_ratio(s)), _premium(s))
    if "buyback" in cats:
        return Classification("buyback", None, None, None, "auto")
    if _is_meeting(s):
        return _MEETING
    return _review("other")


def _non_equity_instrument(s: str) -> bool:
    return any(token in s for token in _NON_EQ_INSTRUMENT)


def _is_meeting(s: str) -> bool:
    return "general meeting" in s


# (isin, ex_date, kind, ratio_num, ratio_den, cash_amount, status, source_ref, available_at)
_TableRow = tuple[str, date, str, int | None, int | None, Decimal | None, str, str, datetime]


def build_corp_actions_frames(parsed: pd.DataFrame) -> CorpActionsTables:
    """Pure deterministic core: parsed feed frame → validated corporate_actions table + stats."""
    stats: dict[str, int] = {
        "parsed_rows": len(parsed),
        "non_equity_dropped": 0,
        "unexpected_series": 0,
        "meetings_dropped": 0,
        "no_isin_dropped": 0,
        "no_ex_date_dropped": 0,
        "kept": 0,
        "auto": 0,
        "needs_review": 0,
    }
    for kind in ("split", "bonus", "dividend", "demerger", "rights", "buyback", "other"):
        stats[f"kind_{kind}"] = 0
    rows: list[_TableRow] = []
    for row in parsed.itertuples(index=False):
        series = None if pd.isna(row.series) else str(row.series)
        if series in _NON_EQUITY_SERIES:
            stats["non_equity_dropped"] += 1
            continue
        if series is not None and series not in _KNOWN_SERIES:
            # Kept (a new tag might be an equity series like BE) but surfaced, never silent.
            stats["unexpected_series"] += 1
            log.warning(
                "corp_actions_unexpected_series", series=series, subject=str(row.subject)[:80]
            )
        subject = str(row.subject)
        cls = classify(subject)
        # Classify BEFORE the identity/date gate so a real (non-meeting) action can never vanish
        # silently for a missing isin/ex_date (hard-exclusion integrity, risk-manager P0-10).
        if cls.kind is None:  # a pure meeting: no ex-date price/cash effect
            stats["meetings_dropped"] += 1
            continue
        if pd.isna(row.isin) or pd.isna(row.ex_date):
            reason = "no_isin_dropped" if pd.isna(row.isin) else "no_ex_date_dropped"
            stats[reason] += 1
            log.warning(
                "corp_actions_incomplete_action_dropped",
                reason=reason,
                kind=cls.kind,
                status=cls.status,
                subject=subject[:80],
            )
            continue
        ex_date: date = row.ex_date
        available_at = datetime(ex_date.year, ex_date.month, ex_date.day)
        status = cls.status if cls.status is not None else "needs_review"
        rows.append(
            (
                str(row.isin),
                ex_date,
                cls.kind,
                cls.ratio_num,
                cls.ratio_den,
                cls.cash_amount,
                status,
                subject,
                available_at,
            )
        )
        stats["kept"] += 1
        stats[status] += 1
        stats[f"kind_{cls.kind}"] += 1
    # Dedupe exact duplicates from overlapping fetch windows; distinct same-day actions survive.
    unique = sorted(set(rows), key=_sort_key)
    stats["rows"] = len(unique)
    frame = _to_frame(unique)
    log.info("corp_actions_built", **stats)
    return CorpActionsTables(corporate_actions=frame, stats=stats)


def _sort_key(r: _TableRow) -> tuple[str, date, str, int, int, str, str]:
    return (
        r[0],
        r[1],
        r[2],
        r[3] if r[3] is not None else -1,
        r[4] if r[4] is not None else -1,
        str(r[5]) if r[5] is not None else "",
        r[7],
    )


def _to_frame(rows: list[_TableRow]) -> pd.DataFrame:
    table = pa.table(
        {
            "isin": pa.array([r[0] for r in rows], STR),
            "ex_date": pa.array([r[1] for r in rows], DATE),
            "kind": pa.array([r[2] for r in rows], STR),
            "ratio_num": pa.array([r[3] for r in rows], I32),
            "ratio_den": pa.array([r[4] for r in rows], I32),
            "cash_amount": pa.array([r[5] for r in rows], dec(12, 2)),
            "status": pa.array([r[6] for r in rows], STR),
            "source_ref": pa.array([r[7] for r in rows], STR),
            "available_at": pa.array([r[8] for r in rows], TS),
        }
    )
    frame = table.to_pandas(types_mapper=pd.ArrowDtype)
    return CorporateActions.validate(frame, lazy=True)


def build_corp_actions(settings: Settings | None = None) -> CorpActionsTables:
    """Build the corporate_actions table from every registered corp_actions window in the vault."""
    store = RawStore(settings)
    frames = [parse_corp_actions(a.path.read_bytes()) for a in store.latest_per_date(SOURCE)]
    if not frames:
        raise ContractViolation("no corp_actions raw files registered; nothing to build")
    parsed: pd.DataFrame = pd.concat(frames, ignore_index=True)
    return build_corp_actions_frames(parsed)


__all__ = [
    "SOURCE",
    "Classification",
    "CorpActionsTables",
    "build_corp_actions",
    "build_corp_actions_frames",
    "classify",
]
