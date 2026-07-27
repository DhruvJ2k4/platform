"""PIT universe builder + rolling liquidity statistics (doc 21 §3-4, P0-13).

Pure deterministic core: `build_universe(...)` turns the published equity price panel into one
`universe_membership` row per candidate (isin, d) — a day the ISIN has a `prices_adj` row with
`series=='EQ'`, `exchange=='NSE'` — carrying its trailing-60-session liquidity stats and the
FULL list of exclusion reasons (never the first). It is materialised for the whole coverage
history inside `curate_rebuild` and published atomically as a doc-10 table (the only allowed
universe source, ADR-008); `load_universe(d)` is the fast as-of read behind `universe --date`.

Liquidity (§3) is computed on a per-ISIN grid reindexed onto the dense session axis (every
trading day with published prices), absent day = NaN, NO forward-fill:
  MDTV = median(traded_value)  [traded_value stays raw — level is adjustment-invariant]
  zero_days_pct = mean(volume==0 OR no-row)  [absent day = illiquid]
  amihud = mean(|ret| / traded_value) over volume>0 days, where ret uses the ADJUSTED/factor
    path close_unadj·adj_factor (ADR-024: only that path is return-invariant; a raw close jumps
    ~50% at a split ex-date). A calendar gap yields a NaN return (skipped), never a multi-session
    return mislabelled daily.

Exclusions (§4): price<floor · age<180td (age = sessions since first observed row, ADR-022) ·
ff_mcap proxy (MDTV<floor, absolute — supersedes §4's cross-sectional "rank by MDTV" for
PIT-safety, ADR-026) · zero_days>max · delisted/suspended (from security.status — a tested hook;
P0-09's master leaves lifecycle fields NULL by design and NO NSE source has been identified for
delisting/suspension facts — a separate, still-unsourced item, distinct from surveillance) ·
surveillance GSM*/ASM≥2 (wired by P0-14: `curate/surveillance.py` supplies the PIT event frame
from real ASM/GSM ingestion) · pending_ca_review (the ISIN has a needs_review CA with
available_at <= d — PIT-scoped per row d, never the build asof, so a future-ex-date review can't
retroactively exclude a past date; resolution status is read from build-time config,
ADR-024/025 — reproducibility is per-manifest version).

`investable` is TRI-STATE, and — P0-14 — the floor/ceiling gate ONLY the affirmative "nothing
fired, can we say True" branch; they NEVER suppress a real exclusion. `_surveillance_flags` runs
whenever a `surveillance` frame is supplied, full stop, reading whatever rows exist independent
of coverage completeness (so a genuinely-flagged name in a partially-sourced category — e.g. ASM
live, GSM still blocked — always correctly excludes). `investable=False` if any filter fired
(including a real surveillance row, regardless of floor/ceiling); `investable=True` only if
nothing fired AND `surveillance_coverage_floor <= d <= surveillance_coverage_ceiling` (both
supplied — both categories must have been checked for that date, ADR-026 §P0-14 addendum);
otherwise `investable` stays NULL (undetermined) — the same honest state whether surveillance is
entirely unconfigured or merely not fully covered for that date. The `surveillance` STRING
column shows the active flag when excluded, `None` when affirmatively checked-clean, else the
sentinel `"UNVERIFIED"` (never plain NULL, which would read as checked-clean).
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd
import pyarrow as pa
import structlog

from quant.config import LiquidityConfig, Settings, load_liquidity
from quant.curate.surveillance import REMOVED as _REMOVED_STAGE
from quant.errors import ContractViolation
from quant.schemas import BOOL, DATE, F64, STR, STR_LIST, UniverseMembership, dec

log = structlog.get_logger()

_MDTV = Decimal("0.01")  # universe_membership.mdtv is DECIMAL(18,2) (doc 10)
_UNVERIFIED = "UNVERIFIED"  # sentinel when a date isn't fully surveillance-bounded (see docstring)
# Reasons in a fixed, deterministic emission order (doc 21 §4: emit ALL, never the first).
_REASONS = (
    "price_below_floor",
    "age_below_min",
    "ff_mcap_proxy",
    "zero_days_gt_max",
    "delisted",
    "suspended",
    "surveillance",
    "pending_ca_review",
)


@dataclass(frozen=True)
class UniverseResult:
    """The validated universe_membership frame plus per-stage accounting counters."""

    frame: pd.DataFrame
    stats: dict[str, int]


def build_universe(
    prices_adj: pd.DataFrame,
    corporate_actions: pd.DataFrame,
    trading_calendar: pd.DataFrame,
    security: pd.DataFrame,
    config: LiquidityConfig,
    *,
    surveillance: pd.DataFrame | None = None,
    surveillance_coverage_floor: date | None = None,
    surveillance_coverage_ceiling: date | None = None,
) -> UniverseResult:
    """Build the full-history universe_membership frame from the published curated tables.

    prices_adj/corporate_actions/trading_calendar/security are the validated doc-10 frames as of
    the build. `surveillance` (PIT event frame: isin, available_at, category∈{GSM,ASM}, stage —
    `curate/surveillance.py`'s P0-14 output) is optional; when supplied, exclusion-firing reads
    its rows unconditionally (never gated by coverage completeness — see module docstring), while
    `surveillance_coverage_floor`/`_ceiling` gate ONLY whether a clean name can affirmatively
    reach `investable=True` for a given date. Every (frame, floor, ceiling) combination has a
    well-defined, conservative meaning — no ambiguous state requiring a defensive raise.
    Deterministic function of its inputs (no clock, no I/O).
    """
    # NOTE: floor > ceiling is a legitimate state (the two surveillance categories' own coverage
    # windows don't overlap) — never asserted against. The per-row `bounded` check below is
    # `floor <= d <= ceiling`, which is simply never true when floor>ceiling, degrading safely
    # to always-undetermined for every date (curate/surveillance.py has the full reasoning).
    window = config.window_trading_days
    price_floor = float(config.price_floor_rupees)
    min_age = config.min_age_trading_days
    mdtv_floor = float(config.mdtv_floor_rupees)
    max_zero = float(config.max_zero_days_pct)
    surv_present = surveillance is not None

    # Dense session axis = every trading day with a published price (⊆ trading_calendar). Using
    # observed-price dates (not the raw calendar) keeps "60 trading sessions" a genuine window of
    # consecutive market days and excludes sparse pre-coverage calendar entries.
    cal_dates = set(trading_calendar["d"])
    price_dates = sorted(set(prices_adj["d"].tolist()))
    stray = [d for d in price_dates if d not in cal_dates]
    if stray:
        raise ContractViolation(f"prices_adj has {len(stray)} date(s) absent from trading_calendar")
    axis = price_dates  # sorted, ascending
    n = len(axis)
    stats: dict[str, int] = {
        "sessions": n,
        "price_rows": len(prices_adj),
        "candidates": 0,
        "non_candidate_rows": 0,
        "surveillance_present": int(surv_present),
        "surveillance_checked_rows": 0,  # per-row count: floor <= d <= ceiling (see below)
    }
    for r in _REASONS:
        stats[f"excluded_{r}"] = 0
    stats["investable_true"] = 0
    stats["investable_false"] = 0
    stats["investable_null"] = 0

    empty = _empty_frame()
    if n == 0:
        log.info("universe_built", **stats)
        return UniverseResult(frame=empty, stats=stats)

    idx_of = {d: i for i, d in enumerate(axis)}
    px = prices_adj.copy()
    px["cidx"] = px["d"].map(idx_of).astype("int64")
    isins = sorted(px["isin"].unique().tolist())
    col_of = {isin: j for j, isin in enumerate(isins)}
    px["col"] = px["isin"].map(col_of).astype("int64")

    # Dense (session x isin) matrices; absent cell = NaN. adj_close uses the factor path.
    shape = (n, len(isins))
    tv = np.full(shape, np.nan)
    vol = np.full(shape, np.nan)
    adjc = np.full(shape, np.nan)
    ri = px["cidx"].to_numpy()
    ci = px["col"].to_numpy()
    tv[ri, ci] = px["traded_value"].to_numpy(dtype="float64", na_value=np.nan)
    vol[ri, ci] = px["volume"].to_numpy(dtype="float64", na_value=np.nan)
    close_unadj = px["close_unadj"].to_numpy(dtype="float64", na_value=np.nan)
    adjf = px["adj_factor"].to_numpy(dtype="float64", na_value=np.nan)
    adjc[ri, ci] = close_unadj * adjf

    mdtv_m, amihud_m, zero_m, age_m = _rolling_stats(tv, vol, adjc, window)

    # Per-candidate signals via fancy indexing at (session, isin).
    cand = px[(px["series"] == "EQ") & (px["exchange"] == "NSE")].sort_values(
        ["isin", "cidx"], kind="stable"
    )
    stats["candidates"] = len(cand)
    stats["non_candidate_rows"] = len(px) - len(cand)
    if cand.empty:
        log.info("universe_built", **stats)
        return UniverseResult(frame=empty, stats=stats)

    c_row = cand["cidx"].to_numpy()
    c_col = cand["col"].to_numpy()
    c_isin = [str(i) for i in cand["isin"].tolist()]
    c_d = cand["d"].tolist()
    c_close = cand["close_unadj"].to_numpy(dtype="float64", na_value=np.nan)
    c_mdtv = mdtv_m[c_row, c_col]
    c_amihud = amihud_m[c_row, c_col]
    c_zero = zero_m[c_row, c_col]
    c_age = age_m[c_row, c_col]

    # PIT-scoped needs_review threshold per ISIN: earliest available_at among its needs_review
    # CAs — the ISIN is "under review" from that date onward (until an operator resolution
    # removes the row, ADR-024/025). Fires for a candidate iff that date <= its membership d.
    nr = corporate_actions[corporate_actions["status"] == "needs_review"]
    review_since: dict[str, date] = {}
    if not nr.empty:
        for isin, avail in zip(nr["isin"], nr["available_at"], strict=True):
            d0 = pd.Timestamp(avail).date()
            k = str(isin)
            if k not in review_since or d0 < review_since[k]:
                review_since[k] = d0

    status_of = {
        str(k): (v if isinstance(v, str) else None)
        for k, v in zip(security["isin"], security["status"], strict=True)
    }
    # Exclusion-firing runs off frame presence alone — coverage completeness never suppresses it.
    surv_flag = _surveillance_flags(surveillance, c_isin, c_d) if surv_present else None
    # Bounded: BOTH categories must have been checked for this date before "nothing fired" can
    # affirmatively become True (max()-derived floor/min()-derived ceiling, curate/surveillance.py).
    if surveillance_coverage_floor is not None and surveillance_coverage_ceiling is not None:
        bounded = np.array(
            [surveillance_coverage_floor <= d <= surveillance_coverage_ceiling for d in c_d],
            dtype=bool,
        )
    else:
        bounded = np.zeros(len(cand), dtype=bool)
    stats["surveillance_checked_rows"] = int(bounded.sum())

    masks: dict[str, np.ndarray] = {
        "price_below_floor": c_close < price_floor,
        "age_below_min": c_age < min_age,
        # NaN MDTV means a candidate's traded_value was null across the whole window (a data
        # hole; traded_value is nullable). NaN<floor is False, so exclude conservatively —
        # liquidity cannot be confirmed (miss beats guess); the mdtv column stores NULL below.
        "ff_mcap_proxy": (c_mdtv < mdtv_floor) | np.isnan(c_mdtv),
        "zero_days_gt_max": c_zero > max_zero,
        "delisted": np.array([status_of.get(k) == "delisted" for k in c_isin], dtype=bool),
        "suspended": np.array([status_of.get(k) == "suspended" for k in c_isin], dtype=bool),
        "surveillance": surv_flag[0] if surv_flag else np.zeros(len(cand), dtype=bool),
        "pending_ca_review": np.array(
            [k in review_since and review_since[k] <= d for k, d in zip(c_isin, c_d, strict=True)],
            dtype=bool,
        ),
    }

    excl_reasons: list[list[str]] = [[] for _ in range(len(cand))]
    for reason in _REASONS:
        fired = np.nonzero(masks[reason])[0]
        stats[f"excluded_{reason}"] = len(fired)
        for i in fired:
            excl_reasons[i].append(reason)

    has_reason = np.zeros(len(cand), dtype=bool)
    for reason in _REASONS:
        has_reason |= masks[reason]
    investable: list[bool | None] = []
    for i, flagged in enumerate(has_reason):
        if flagged:
            investable.append(False)
            stats["investable_false"] += 1
        elif bounded[i]:
            investable.append(True)
            stats["investable_true"] += 1
        else:
            investable.append(None)
            stats["investable_null"] += 1

    # surveillance column: the active flag when excluded; None when affirmatively checked-clean
    # (bounded); else the sentinel (unconfigured OR present-but-not-fully-bounded for this date).
    active_flags = surv_flag[1] if surv_flag is not None else [None] * len(cand)
    surv_values: list[str | None] = [
        active_flags[i] if active_flags[i] else (None if bounded[i] else _UNVERIFIED)
        for i in range(len(cand))
    ]

    # NaN MDTV stores as NULL (the column is nullable) rather than crashing the DECIMAL write
    # (pa.array rejects Decimal('NaN')); the row is already ff_mcap-excluded above.
    mdtv_dec = [
        None if np.isnan(v) else Decimal(str(v)).quantize(_MDTV, rounding=ROUND_HALF_UP)
        for v in c_mdtv
    ]
    table = pa.table(
        {
            "isin": pa.array([str(i) for i in c_isin], STR),
            "d": pa.array(c_d, DATE),
            "investable": pa.array(investable, BOOL),
            "mdtv": pa.array(mdtv_dec, dec(18, 2)),
            "amihud": pa.array([float(v) for v in c_amihud], F64),
            "zero_days_pct": pa.array([float(v) for v in c_zero], F64),
            "surveillance": pa.array(surv_values, STR),
            "excl_reasons": pa.array(excl_reasons, STR_LIST),
        }
    )
    frame = UniverseMembership.validate(table.to_pandas(types_mapper=pd.ArrowDtype), lazy=True)
    log.info("universe_built", **stats)
    return UniverseResult(frame=frame, stats=stats)


def _rolling_stats(
    tv: np.ndarray, vol: np.ndarray, adjc: np.ndarray, window: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Trailing-`window`-session MDTV / amihud / zero_days_pct / age matrices (session x isin).

    pandas rolling median/mean skip NaN with min_periods=1 (probed 2026-07-23), so absent
    sessions drop out of MDTV/amihud rather than poisoning the window; the zero_days flag grid
    has no NaN so its rolling mean is a true fraction. Returns use adj_close ratios with NO
    forward-fill: a gap yields a NaN return, excluded from amihud.
    """
    tv_df = pd.DataFrame(tv)
    mdtv = tv_df.rolling(window, min_periods=1).median().to_numpy()

    ret = adjc / _shift_rows(adjc, 1) - 1.0  # session-over-prior-session; gap → NaN (no ffill)
    with np.errstate(invalid="ignore", divide="ignore"):
        illiq = np.abs(ret) / tv
    illiq[~(vol > 0)] = np.nan  # amihud skips zero-volume (and absent) days
    amihud = pd.DataFrame(illiq).rolling(window, min_periods=1).mean().to_numpy()

    zeroabs = np.where(np.isnan(vol) | (vol == 0), 1.0, 0.0)
    zero_days = pd.DataFrame(zeroabs).rolling(window, min_periods=1).mean().to_numpy()

    age = _age_matrix(~np.isnan(tv))
    return mdtv, amihud, zero_days, age


def _shift_rows(a: np.ndarray, k: int) -> np.ndarray:
    """Shift a 2-D array down by k rows, filling the top with NaN (prior-session lookup)."""
    out = np.full_like(a, np.nan)
    if k < a.shape[0]:
        out[k:, :] = a[:-k, :]
    return out


def _age_matrix(present: np.ndarray) -> np.ndarray:
    """age[i, j] = trading sessions from the ISIN's first observed row to session i, inclusive.

    Span since first observation (ADR-022: age from price rows, never listing bounds); relist-
    after-suspension reset is deferred (no NSE delisting/suspension source has been identified —
    a separate, still-unsourced item, distinct from P0-14's ASM/GSM surveillance work) — the
    zero_days_pct window is the interim guard against a name freshly back from suspension.
    Sessions before first observation are NaN.
    """
    n = present.shape[0]
    rows = np.arange(n).reshape(-1, 1)
    first = np.where(present.any(axis=0), present.argmax(axis=0), n)  # n = never present
    age = rows - first + 1
    return np.where(present, age.astype("float64"), np.nan)


def _excludes(category: str, stage: int) -> bool:
    """doc 21 §4: GSM at ANY stage (except the CDC-diff removal sentinel) excludes; ASM only >=2."""
    return (category == "GSM" and stage != _REMOVED_STAGE) or (category == "ASM" and stage >= 2)


def _surveillance_flags(
    surveillance: pd.DataFrame, c_isin: list[str], c_d: list[date]
) -> tuple[np.ndarray, list[str | None]]:
    """As-of surveillance exclusion (GSM* | ASM≥2) per candidate; PIT via available_at <= d.

    Returns (fired_mask, active_flag_per_candidate). The frame carries isin, available_at,
    category∈{GSM,ASM}, stage — a current snapshot applied to history would leak, so only rows
    known by d apply.

    Each (isin, category) is tracked INDEPENDENTLY: for a given d, that category's own LATEST
    row <= d (regardless of whether IT excludes) determines that category's current state, and
    the two categories are then OR'd. This is deliberately NOT "the latest row across both
    categories wins" — a GSM removal event landing after an ASM stage-3 row must never clear the
    still-active ASM exclusion, and a name concurrently on both must have each tracked on its own
    timeline. Deterministic tie-break when both categories fire at the identical available_at:
    fixed iteration order (ASM then GSM) plus a stable max() over (avail, category) — GSM's flag
    string wins an exact tie (GSM sorts after ASM lexicographically). Tested with a synthetic
    frame so P0-14 inherits verified logic.
    """
    need = {"isin", "available_at", "category", "stage"}
    if not need.issubset(surveillance.columns):
        raise ContractViolation(f"surveillance frame missing columns; need {sorted(need)}")
    by_key: dict[tuple[str, str], list[tuple[date, int]]] = {}
    for isin, avail, cat, stage in zip(
        surveillance["isin"],
        surveillance["available_at"],
        surveillance["category"],
        surveillance["stage"],
        strict=True,
    ):
        key = (str(isin), str(cat))
        by_key.setdefault(key, []).append((pd.Timestamp(avail).date(), int(stage)))
    for entries in by_key.values():
        entries.sort()  # ascending available_at, so "latest <= d" is a simple tail scan below

    fired = np.zeros(len(c_isin), dtype=bool)
    flags: list[str | None] = [None] * len(c_isin)
    for i, (isin, d) in enumerate(zip(c_isin, c_d, strict=True)):
        firing: list[tuple[date, str, int]] = []
        for cat in ("ASM", "GSM"):  # fixed order: deterministic tie-break
            cat_entries = by_key.get((isin, cat))
            if not cat_entries:
                continue
            eligible = [(avail, stage) for avail, stage in cat_entries if avail <= d]
            if not eligible:
                continue
            avail, stage = eligible[-1]  # latest row <= d, PERIOD -- matched or not
            if _excludes(cat, stage):
                firing.append((avail, cat, stage))
        if firing:
            avail, cat, stage = max(firing, key=lambda t: (t[0], t[1]))
            fired[i] = True
            flags[i] = f"{cat}_{stage}"
    return fired, flags


def _empty_frame() -> pd.DataFrame:
    """A validated zero-row universe_membership frame (empty coverage / no candidates)."""
    table = pa.table(
        {
            "isin": pa.array([], STR),
            "d": pa.array([], DATE),
            "investable": pa.array([], BOOL),
            "mdtv": pa.array([], dec(18, 2)),
            "amihud": pa.array([], F64),
            "zero_days_pct": pa.array([], F64),
            "surveillance": pa.array([], STR),
            "excl_reasons": pa.array([], STR_LIST),
        }
    )
    return UniverseMembership.validate(table.to_pandas(types_mapper=pd.ArrowDtype), lazy=True)


def load_universe(d: date, settings: Settings | None = None) -> pd.DataFrame:
    """Fast as-of read of one session's universe from the CURRENT published store (Arrow path).

    Reads only the target year-partition with a `d` predicate so `universe --date` stays <1s;
    validates against the doc-10 contract. Returns a zero-row frame for an out-of-coverage or
    non-trading date (the caller distinguishes that from a present-but-all-excluded session).
    """
    import pyarrow.parquet as pq

    from quant.curate.publish import version_dir

    table_dir = version_dir(settings) / "universe_membership"
    dataset = pq.ParquetDataset(table_dir, filters=[("year", "==", d.year), ("d", "==", d)])
    arrow = dataset.read()
    if "year" in arrow.column_names:  # hive partition column, not part of the doc-10 contract
        arrow = arrow.drop_columns(["year"])
    frame = arrow.to_pandas(types_mapper=pd.ArrowDtype)
    frame = frame.sort_values(["isin"], kind="stable").reset_index(drop=True)
    validated: pd.DataFrame = UniverseMembership.validate(frame, lazy=True)
    return validated


def load_liquidity_config(settings: Settings | None = None) -> LiquidityConfig:
    """Thin re-export so callers of this module get the universe's config in one import."""
    return load_liquidity(settings)
