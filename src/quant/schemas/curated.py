"""Pandera contracts for the nine curated tables (mirrors of the authoritative DDL in schemas/).

Curated tables are deterministic functions of (raw, code, config) — ADR-016 — and these models
are the schema half of the doc-08 validation gate: strict column sets, exact arrow-backed dtypes
with DECIMAL(p,s) pinned (ADR-021), and enum checks only where doc 10 enumerates the value set.
"""

from typing import ClassVar

import pandas as pd

from quant.schemas._dtypes import BOOL, DATE, F64, I32, I64, STR, STR_LIST, TS, Contract, dec, field


class Security(Contract):
    """security: master record per ISIN."""

    isin: pd.ArrowDtype = field(STR, nullable=False, unique=True)
    name: pd.ArrowDtype = field(STR, nullable=True)
    status: pd.ArrowDtype = field(STR, nullable=True, isin=["active", "delisted", "suspended"])
    first_listed: pd.ArrowDtype = field(DATE, nullable=True)
    delisted_on: pd.ArrowDtype = field(DATE, nullable=True)
    delist_terminal_price: pd.ArrowDtype = field(dec(12, 2), nullable=True)


class Listing(Contract):
    """listing: effective-dated (exchange, symbol, series) map per ISIN; valid_to NULL = open."""

    isin: pd.ArrowDtype = field(STR, nullable=False)
    exchange: pd.ArrowDtype = field(STR, nullable=False)
    symbol: pd.ArrowDtype = field(STR, nullable=False)
    series: pd.ArrowDtype = field(STR, nullable=False)
    valid_from: pd.ArrowDtype = field(DATE, nullable=False)
    valid_to: pd.ArrowDtype = field(DATE, nullable=True)


class TradingCalendar(Contract):
    """trading_calendar: derived from bhavcopy presence; session enum defined by P0-08."""

    d: pd.ArrowDtype = field(DATE, nullable=False, unique=True)
    session: pd.ArrowDtype = field(STR, nullable=True, isin=["normal", "special", "muhurat"])


class PricesAdj(Contract):
    """prices_adj: adjusted EOD prices; (isin, d) unique; money at paisa precision."""

    isin: pd.ArrowDtype = field(STR, nullable=False)
    d: pd.ArrowDtype = field(DATE, nullable=False)
    exchange: pd.ArrowDtype = field(STR, nullable=True)
    series: pd.ArrowDtype = field(STR, nullable=True)
    o: pd.ArrowDtype = field(dec(12, 2), nullable=True)
    h: pd.ArrowDtype = field(dec(12, 2), nullable=True)
    l: pd.ArrowDtype = field(dec(12, 2), nullable=True)
    c: pd.ArrowDtype = field(dec(12, 2), nullable=True)
    close_unadj: pd.ArrowDtype = field(dec(12, 2), nullable=True)
    volume: pd.ArrowDtype = field(I64, nullable=True)
    traded_value: pd.ArrowDtype = field(dec(18, 2), nullable=True)
    adj_factor: pd.ArrowDtype = field(F64, nullable=True)
    band_hit: pd.ArrowDtype = field(STR, nullable=True, isin=["upper", "lower"])

    class Config(Contract.Config):
        unique: ClassVar[list[str]] = ["isin", "d"]


class CorporateActions(Contract):
    """corporate_actions: PIT-lagged facts; demergers arrive as needs_review, never auto."""

    isin: pd.ArrowDtype = field(STR, nullable=False)
    ex_date: pd.ArrowDtype = field(DATE, nullable=False)
    kind: pd.ArrowDtype = field(
        STR, nullable=False, isin=["split", "bonus", "dividend", "demerger", "rights", "buyback"]
    )
    ratio_num: pd.ArrowDtype = field(I32, nullable=True)
    ratio_den: pd.ArrowDtype = field(I32, nullable=True)
    cash_amount: pd.ArrowDtype = field(dec(12, 2), nullable=True)
    status: pd.ArrowDtype = field(STR, nullable=True, isin=["auto", "needs_review", "resolved"])
    source_ref: pd.ArrowDtype = field(STR, nullable=True)
    available_at: pd.ArrowDtype = field(TS, nullable=True)


class UniverseMembership(Contract):
    """universe_membership: the only allowed universe source (ADR-008); PIT by d."""

    isin: pd.ArrowDtype = field(STR, nullable=False)
    d: pd.ArrowDtype = field(DATE, nullable=False)
    investable: pd.ArrowDtype = field(BOOL, nullable=True)
    mdtv: pd.ArrowDtype = field(dec(18, 2), nullable=True)
    amihud: pd.ArrowDtype = field(F64, nullable=True)
    zero_days_pct: pd.ArrowDtype = field(F64, nullable=True)
    surveillance: pd.ArrowDtype = field(STR, nullable=True)  # source-shaped, not doc-enumerated
    excl_reasons: pd.ArrowDtype = field(STR_LIST, nullable=True)


class FundamentalsPit(Contract):
    """fundamentals_pit: PIT fundamentals (ADR-002); bridged rows are stress-flagged."""

    isin: pd.ArrowDtype = field(STR, nullable=False)
    period_end: pd.ArrowDtype = field(DATE, nullable=True)
    statement: pd.ArrowDtype = field(STR, nullable=True)
    item: pd.ArrowDtype = field(STR, nullable=True)
    value: pd.ArrowDtype = field(dec(18, 2), nullable=True)
    filed_at: pd.ArrowDtype = field(TS, nullable=True)
    available_at: pd.ArrowDtype = field(TS, nullable=True)
    source: pd.ArrowDtype = field(STR, nullable=True)
    confidence: pd.ArrowDtype = field(STR, nullable=True, isin=["native", "bridged"])
    revision_seq: pd.ArrowDtype = field(I32, nullable=True)


class Events(Contract):
    """events: isin NULL for market-wide events; kind values grow with P3 severity rules."""

    event_id: pd.ArrowDtype = field(STR, nullable=False, unique=True)
    isin: pd.ArrowDtype = field(STR, nullable=True)
    kind: pd.ArrowDtype = field(STR, nullable=False)
    severity: pd.ArrowDtype = field(I32, nullable=True)
    payload: pd.ArrowDtype = field(STR, nullable=True)  # JSON surfaces as arrow string
    observed_at: pd.ArrowDtype = field(TS, nullable=True)


class IndexTri(Contract):
    """index_tri: official TRI values consumed as benchmarks only (ADR-008)."""

    index_name: pd.ArrowDtype = field(STR, nullable=False)
    d: pd.ArrowDtype = field(DATE, nullable=False)
    tri_value: pd.ArrowDtype = field(dec(18, 6), nullable=True)
