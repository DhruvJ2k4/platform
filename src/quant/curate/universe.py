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
PIT-safety, ADR-026) · zero_days>max · delisted/suspended (from security.status — a tested hook,
inert until P0-14 populates it) · surveillance GSM*/ASM≥2 (a PIT-stamped seam; inert until P0-14)
· pending_ca_review (the ISIN has a needs_review CA with available_at <= d — PIT-scoped per row d,
never the build asof, so a future-ex-date review can't retroactively exclude a past date;
resolution status is read from build-time config, ADR-024/025 — reproducibility is per-manifest
version). `investable` is TRI-STATE: False if any real filter fired; NULL (undetermined) if clean
on every filter that RAN but surveillance is unchecked; True only if clean AND surveillance
checked — never assert clean over an unrun hard exclusion. Unchecked surveillance stores the
sentinel "UNVERIFIED" (not NULL, which reads as checked-clean).
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd
import pyarrow as pa
import structlog

from quant.config import LiquidityConfig, Settings, load_liquidity
from quant.errors import ContractViolation
from quant.schemas import BOOL, DATE, F64, STR, STR_LIST, UniverseMembership, dec

log = structlog.get_logger()

_MDTV = Decimal("0.01")  # universe_membership.mdtv is DECIMAL(18,2) (doc 10)
_UNVERIFIED = "UNVERIFIED"  # surveillance sentinel while the ASM/GSM feed is unwired (P0-14)
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
) -> UniverseResult:
    """Build the full-history universe_membership frame from the published curated tables.

    prices_adj/corporate_actions/trading_calendar/security are the validated doc-10 frames as
    of the build. `surveillance` (optional, PIT-stamped: isin, available_at, category∈{GSM,ASM},
    stage) is the P0-14 seam — when None the surveillance filter is a no-op and clean names are
    left undetermined (investable NULL). Deterministic function of its inputs (no clock, no I/O).
    """
    window = config.window_trading_days
    price_floor = float(config.price_floor_rupees)
    min_age = config.min_age_trading_days
    mdtv_floor = float(config.mdtv_floor_rupees)
    max_zero = float(config.max_zero_days_pct)
    surv_checked = surveillance is not None

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
        "surveillance_checked": int(surv_checked),
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
    surv_flag = _surveillance_flags(surveillance, c_isin, c_d) if surv_checked else None

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
    for flagged in has_reason:
        if flagged:
            investable.append(False)
            stats["investable_false"] += 1
        elif surv_checked:
            investable.append(True)
            stats["investable_true"] += 1
        else:
            investable.append(None)
            stats["investable_null"] += 1

    # surveillance column: the active flag when excluded, None when checked-clean, else UNVERIFIED.
    surv_values: list[str | None]
    if surv_checked and surv_flag is not None:
        surv_values = [f if f else None for f in surv_flag[1]]
    else:
        surv_values = [_UNVERIFIED] * len(cand)

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
    after-suspension reset is deferred (P0-14) — the zero_days_pct window is the interim guard
    against a name freshly back from suspension. Sessions before first observation are NaN.
    """
    n = present.shape[0]
    rows = np.arange(n).reshape(-1, 1)
    first = np.where(present.any(axis=0), present.argmax(axis=0), n)  # n = never present
    age = rows - first + 1
    return np.where(present, age.astype("float64"), np.nan)


def _surveillance_flags(
    surveillance: pd.DataFrame, c_isin: list[str], c_d: list[date]
) -> tuple[np.ndarray, list[str | None]]:
    """As-of surveillance exclusion (GSM* | ASM≥2) per candidate; PIT via available_at <= d.

    Returns (fired_mask, active_flag_per_candidate). The frame carries isin, available_at,
    category∈{GSM,ASM}, stage; a current snapshot applied to history would leak, so only rows
    known by d apply. Tested with a synthetic frame so P0-14 inherits verified logic.
    """
    need = {"isin", "available_at", "category", "stage"}
    if not need.issubset(surveillance.columns):
        raise ContractViolation(f"surveillance frame missing columns; need {sorted(need)}")
    by_isin: dict[str, list[tuple[date, str, int]]] = {}
    for isin, avail, cat, stage in zip(
        surveillance["isin"],
        surveillance["available_at"],
        surveillance["category"],
        surveillance["stage"],
        strict=True,
    ):
        by_isin.setdefault(str(isin), []).append((pd.Timestamp(avail).date(), str(cat), int(stage)))
    fired = np.zeros(len(c_isin), dtype=bool)
    flags: list[str | None] = [None] * len(c_isin)
    for i, (isin, d) in enumerate(zip(c_isin, c_d, strict=True)):
        active: tuple[date, str, int] | None = None
        for avail, cat, stage in by_isin.get(isin, ()):
            excludes = cat == "GSM" or (cat == "ASM" and stage >= 2)
            if avail <= d and excludes and (active is None or avail > active[0]):
                active = (avail, cat, stage)
        if active is not None:
            fired[i] = True
            flags[i] = f"{active[1]}_{active[2]}"
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
