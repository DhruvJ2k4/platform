"""Corporate-action price adjuster: reverse cumulative factors, exact to the paisa (doc 21 §1).

Pure deterministic core of P0-11. Factors are exact `fractions.Fraction`s built from the CA
ratio columns (kind semantics uniform across status, ADR-023/024): auto or resolved split →
den/num; bonus → den/(num+den); resolved rights/demerger/other → den/num. Dividends and
buybacks never price-adjust. adj_factor(isin, d) = ∏ factor(a) for a.ex_date > d, so the
latest dates carry factor 1 and o/h/l/c are quantized Decimal(12,2) ROUND_HALF_UP — golden
scenarios reproduce to the paisa. Three withholding rules keep wrong prices unpublishable:
(1) pre-ex block — a pending needs_review action at E makes every d < E unknowable for that
ISIN (operator-approved window semantics, ADR-024); (2) coverage floor/ceiling — price dates
outside the CA fetch window would silently miss forward actions (the P0-10 missing-past
bias), so they are excluded and counted, never partially adjusted; (3) PIT — only CA rows
with available_at <= asof exist for the build. Every input row is accounted for: published +
each exclusion reason sums back to the panel.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

import pandas as pd
import pyarrow as pa
import structlog

from quant.errors import ContractViolation
from quant.schemas import DATE, F64, I64, STR, PricesAdj, dec

log = structlog.get_logger()

_PAISA = Decimal("0.01")
# Kinds whose ratio means factor = den/num (split convention; resolved reorganizations too).
_DEN_OVER_NUM = {"split", "rights", "demerger", "other"}


@dataclass(frozen=True)
class AdjustedPrices:
    """The validated prices_adj frame plus per-reason accounting counters."""

    prices_adj: pd.DataFrame
    stats: dict[str, int]


def action_factor(
    kind: str, status: str, ratio_num: int | None, ratio_den: int | None
) -> Fraction | None:
    """The exact price factor of one CA row, or None when it does not price-adjust.

    needs_review rows never factor (they BLOCK instead — the caller handles the window);
    dividend/buyback never factor; a factoring row missing its ratio is a ContractViolation
    (the P0-10 classifier guarantees auto split/bonus carry positive ratios — drift alarm).
    """
    if status == "needs_review":
        return None
    if kind == "bonus":
        if ratio_num is None or ratio_den is None:
            raise ContractViolation(f"bonus row with status={status} lacks ratio terms")
        return Fraction(ratio_den, ratio_num + ratio_den)
    if kind in _DEN_OVER_NUM:
        if status == "auto" and kind != "split":
            # rights/demerger/other are never auto (ADR-023); an auto one is upstream drift.
            raise ContractViolation(f"{kind} row with status=auto violates ADR-023")
        if ratio_num is None or ratio_den is None:
            raise ContractViolation(f"{kind} row with status={status} lacks ratio terms")
        return Fraction(ratio_den, ratio_num)
    return None  # dividend, buyback: cash/valuation events, never price factors


def adjust_prices(
    panel: pd.DataFrame,
    corporate_actions: pd.DataFrame,
    *,
    coverage_floor: date,
    coverage_ceiling: date,
    asof: date,
) -> AdjustedPrices:
    """Apply doc 21 §1 to the raw panel; returns the validated prices_adj frame + accounting.

    panel is ParsedBhavcopy-shaped (one primary row per (isin, day), isin non-null);
    corporate_actions is the validated doc-10 frame. asof gates both prices (d <= asof) and
    actions (available_at <= asof, doc 21 §2).
    """
    stats: dict[str, int] = {
        "panel_rows": len(panel),
        "after_asof_excluded": 0,
        "coverage_excluded": 0,
        "pre_ex_blocked": 0,
        "published": 0,
        "blocked_isins": 0,
        "factored_actions": 0,
    }
    rows = panel[panel["trade_date"] <= asof]
    stats["after_asof_excluded"] = len(panel) - len(rows)

    in_cover = (rows["trade_date"] >= coverage_floor) & (rows["trade_date"] <= coverage_ceiling)
    stats["coverage_excluded"] = int((~in_cover).sum())
    rows = rows[in_cover]

    ca = corporate_actions[corporate_actions["available_at"] <= pd.Timestamp(asof)]

    # Per ISIN: pending block boundary (latest needs_review ex_date) + factor steps.
    pending: dict[str, date] = {}
    steps: dict[str, list[tuple[date, Fraction]]] = {}
    for a in ca.itertuples(index=False):
        isin = str(a.isin)
        status = str(a.status)
        if status == "needs_review":
            e: date = a.ex_date
            if isin not in pending or e > pending[isin]:
                pending[isin] = e
            continue
        f = action_factor(
            str(a.kind),
            status,
            None if pd.isna(a.ratio_num) else int(a.ratio_num),
            None if pd.isna(a.ratio_den) else int(a.ratio_den),
        )
        if f is not None:
            steps.setdefault(isin, []).append((a.ex_date, f))
            stats["factored_actions"] += 1

    # Pre-ex block: drop d < E(pending). Any pending action severs adjustability of ALL
    # earlier dates — the unknown factor sits between them and the anchor at the latest date.
    if pending:
        blocked = [
            isin in pending and d < pending[str(isin)]
            for isin, d in zip(rows["isin"], rows["trade_date"], strict=True)
        ]
        blocked_mask = pd.Series(blocked, index=rows.index)
        stats["pre_ex_blocked"] = int(blocked_mask.sum())
        stats["blocked_isins"] = int(rows[blocked_mask]["isin"].nunique())
        rows = rows[~blocked_mask]

    out = _apply_factors(rows, steps)
    stats["published"] = len(out)
    log.info("prices_adjusted", **stats)
    return AdjustedPrices(prices_adj=out, stats=stats)


def _apply_factors(
    rows: pd.DataFrame, steps: dict[str, list[tuple[date, Fraction]]]
) -> pd.DataFrame:
    """Compute cumulative factors per row and emit the validated prices_adj frame.

    For one ISIN with factor steps at ex-dates E1<E2<…, adj_factor(d) = ∏ f(Ei) for Ei > d —
    computed by walking dates ascending against reverse-cumulative suffix products (exact
    Fractions; same-day multiple actions multiply, order-independent).
    """
    suffix: dict[str, list[tuple[date, Fraction]]] = {}
    for isin, sts in steps.items():
        sts_sorted = sorted(sts, key=lambda t: t[0])  # ties multiply into one boundary below
        # Build boundaries: distinct ex_dates ascending with the product of that day's factors.
        merged: list[tuple[date, Fraction]] = []
        for e, f in sts_sorted:
            if merged and merged[-1][0] == e:
                merged[-1] = (e, merged[-1][1] * f)
            else:
                merged.append((e, f))
        # Suffix products: factor for d is the product of all boundary factors with e > d.
        acc = Fraction(1)
        suf: list[tuple[date, Fraction]] = []  # (e, product of factors at >= this boundary)
        for e, f in reversed(merged):
            acc *= f
            suf.append((e, acc))
        suf.reverse()
        suffix[isin] = suf

    def factor_for(isin: str, d: date) -> Fraction:
        suf = suffix.get(isin)
        if not suf:
            return Fraction(1)
        # first boundary with e > d gives the full remaining suffix product
        for e, prod in suf:
            if e > d:
                return prod
        return Fraction(1)

    isins: list[str] = []
    ds: list[date] = []
    exchanges: list[str] = []
    series: list[str | None] = []
    o: list[Decimal | None] = []
    h: list[Decimal | None] = []
    lo: list[Decimal | None] = []
    c: list[Decimal | None] = []
    close_unadj: list[Decimal | None] = []
    volume: list[int | None] = []
    traded_value: list[Decimal | None] = []
    adj_factor: list[float] = []
    band_hit: list[str | None] = []

    def scale(v: object, f: Fraction) -> Decimal | None:
        # Tie-safety of dividing at the default 28-digit context before quantizing: HALF_UP
        # ties (x.xx5 exactly) occur only for TERMINATING quotients, and any in-range price
        # (≤12 digits) times a ratio with denominator ≤ ~1e6 terminates well within 28
        # significant digits — so the intermediate division is exact wherever a tie exists,
        # and non-terminating quotients never sit on one (probed, review 2026-07-19).
        if v is None or pd.isna(v):
            return None
        if f == 1:
            return Decimal(str(v))
        return (Decimal(str(v)) * Decimal(f.numerator) / Decimal(f.denominator)).quantize(
            _PAISA, rounding=ROUND_HALF_UP
        )

    for r in rows.itertuples(index=False):
        isin = str(r.isin)
        d: date = r.trade_date
        f = factor_for(isin, d)
        isins.append(isin)
        ds.append(d)
        exchanges.append("NSE")
        series.append(None if pd.isna(r.series) else str(r.series))
        o.append(scale(r.open, f))
        h.append(scale(r.high, f))
        lo.append(scale(r.low, f))
        c.append(scale(r.close, f))
        close_unadj.append(None if pd.isna(r.close) else Decimal(str(r.close)))
        volume.append(None if pd.isna(r.volume) else int(r.volume))
        traded_value.append(None if pd.isna(r.traded_value) else Decimal(str(r.traded_value)))
        adj_factor.append(float(f))
        band_hit.append(None)  # bhavcopy carries no band columns; source lands later (doc 10)

    table = pa.table(
        {
            "isin": pa.array(isins, STR),
            "d": pa.array(ds, DATE),
            "exchange": pa.array(exchanges, STR),
            "series": pa.array(series, STR),
            "o": pa.array(o, dec(12, 2)),
            "h": pa.array(h, dec(12, 2)),
            "l": pa.array(lo, dec(12, 2)),
            "c": pa.array(c, dec(12, 2)),
            "close_unadj": pa.array(close_unadj, dec(12, 2)),
            "volume": pa.array(volume, I64),
            "traded_value": pa.array(traded_value, dec(18, 2)),
            "adj_factor": pa.array(adj_factor, F64),
            "band_hit": pa.array(band_hit, STR),
        }
    )
    frame = table.to_pandas(types_mapper=pd.ArrowDtype)
    return PricesAdj.validate(frame, lazy=True)
