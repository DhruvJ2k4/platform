"""Shared pytest configuration: deterministic hypothesis profiles + typed frame factories.

Hypothesis does not read HYPOTHESIS_PROFILE itself, so this conftest both registers
the "ci" profile and loads whichever profile the environment selects. CI sets
HYPOTHESIS_PROFILE=ci for derandomized, reproducible property runs (doc 23).

The frame factories build arrow-typed ParsedBhavcopy-shaped panels and doc-10
corporate_actions frames for the adjuster suites (golden/unit/property share them via
`from conftest import …`, which works in pytest's prepend import mode because this
directory joins sys.path).
"""

import json
import os
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import pyarrow as pa
from hypothesis import settings

from quant.schemas import DATE, F64, I32, I64, STR, TS, dec

settings.register_profile("ci", derandomize=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))


def panel_frame(
    rows: list[tuple[date, str, str, str, Decimal | None, int | None]],
) -> pd.DataFrame:
    """ParsedBhavcopy-shaped panel from (trade_date, symbol, series, isin, close, volume).

    open/high/low mirror close (adjustment scales them identically); the golden and property
    suites assert on close, the paisa-critical column.
    """
    td, sym, ser, isin, close, vol = (list(c) for c in zip(*rows, strict=True))
    table = pa.table(
        {
            "trade_date": pa.array(td, DATE),
            "symbol": pa.array(sym, STR),
            "series": pa.array(ser, STR),
            "isin": pa.array(isin, STR),
            "open": pa.array(close, dec(12, 2)),
            "high": pa.array(close, dec(12, 2)),
            "low": pa.array(close, dec(12, 2)),
            "close": pa.array(close, dec(12, 2)),
            "last": pa.array([None] * len(td), dec(12, 2)),
            "prev_close": pa.array([None] * len(td), dec(12, 2)),
            "volume": pa.array(vol, I64),
            "traded_value": pa.array([None] * len(td), dec(18, 2)),
            "total_trades": pa.array([None] * len(td), I64),
            "security_name": pa.array([None] * len(td), STR),
        }
    )
    return table.to_pandas(types_mapper=pd.ArrowDtype)


def ca_frame(
    entries: list[
        tuple[str, date, str, int | None, int | None, Decimal | None, str, str, datetime]
    ],
) -> pd.DataFrame:
    """doc-10 corporate_actions frame from
    (isin, ex_date, kind, ratio_num, ratio_den, cash_amount, status, source_ref, available_at)."""
    if not entries:
        isin, ex, kind, num, den, cash, status, ref, avail = ([], [], [], [], [], [], [], [], [])
    else:
        isin, ex, kind, num, den, cash, status, ref, avail = (
            list(c) for c in zip(*entries, strict=True)
        )
    table = pa.table(
        {
            "isin": pa.array(isin, STR),
            "ex_date": pa.array(ex, DATE),
            "kind": pa.array(kind, STR),
            "ratio_num": pa.array(num, I32),
            "ratio_den": pa.array(den, I32),
            "cash_amount": pa.array(cash, dec(12, 2)),
            "status": pa.array(status, STR),
            "source_ref": pa.array(ref, STR),
            "available_at": pa.array(avail, TS),
        }
    )
    return table.to_pandas(types_mapper=pd.ArrowDtype)


def prices_adj_frame(
    rows: list[tuple[str, date, str, Decimal | None, int | None, Decimal | None, float]],
) -> pd.DataFrame:
    """doc-10 prices_adj frame from
    (isin, d, series, close_unadj, volume, traded_value, adj_factor); o/h/l/c mirror the
    adjusted close (close_unadj·adj_factor, paisa) so the universe suites drive liquidity math."""
    isin, d, series, cu, vol, tv, af = (
        (list(c) for c in zip(*rows, strict=True)) if rows else ([], [], [], [], [], [], [])
    )
    adj_c = [
        None if c is None else (c * Decimal(str(f))).quantize(Decimal("0.01"))
        for c, f in zip(cu, af, strict=True)
    ]
    table = pa.table(
        {
            "isin": pa.array(isin, STR),
            "d": pa.array(d, DATE),
            "exchange": pa.array(["NSE"] * len(isin), STR),
            "series": pa.array(series, STR),
            "o": pa.array(adj_c, dec(12, 2)),
            "h": pa.array(adj_c, dec(12, 2)),
            "l": pa.array(adj_c, dec(12, 2)),
            "c": pa.array(adj_c, dec(12, 2)),
            "close_unadj": pa.array(cu, dec(12, 2)),
            "volume": pa.array(vol, I64),
            "traded_value": pa.array(tv, dec(18, 2)),
            "adj_factor": pa.array(af, F64),
            "band_hit": pa.array([None] * len(isin), STR),
        }
    )
    return table.to_pandas(types_mapper=pd.ArrowDtype)


def calendar_frame(dates: list[date]) -> pd.DataFrame:
    """doc-10 trading_calendar frame (all sessions 'normal') from a list of dates."""
    table = pa.table(
        {"d": pa.array(dates, DATE), "session": pa.array(["normal"] * len(dates), STR)}
    )
    return table.to_pandas(types_mapper=pd.ArrowDtype)


def security_frame(
    rows: list[tuple[str, str | None, str | None, date | None, date | None, Decimal | None]],
) -> pd.DataFrame:
    """doc-10 security frame from
    (isin, name, status, first_listed, delisted_on, delist_terminal_price)."""
    isin, name, status, fl, don, dtp = (
        (list(c) for c in zip(*rows, strict=True)) if rows else ([], [], [], [], [], [])
    )
    table = pa.table(
        {
            "isin": pa.array(isin, STR),
            "name": pa.array(name, STR),
            "status": pa.array(status, STR),
            "first_listed": pa.array(fl, DATE),
            "delisted_on": pa.array(don, DATE),
            "delist_terminal_price": pa.array(dtp, dec(12, 2)),
        }
    )
    return table.to_pandas(types_mapper=pd.ArrowDtype)


def surveillance_frame(rows: list[tuple[str, date, str, int]]) -> pd.DataFrame:
    """P0-14 seam frame from (isin, available_at, category∈{GSM,ASM}, stage) — PIT-stamped."""
    cols = (list(c) for c in zip(*rows, strict=True)) if rows else ([], [], [], [])
    isin, avail, cat, stage = cols
    table = pa.table(
        {
            "isin": pa.array(isin, STR),
            "available_at": pa.array(avail, DATE),
            "category": pa.array(cat, STR),
            "stage": pa.array(stage, I32),
        }
    )
    return table.to_pandas(types_mapper=pd.ArrowDtype)


def index_tri_bytes(
    rows: list[tuple[str, str]], *, response_index_name: str = "Nifty 50", wrap_d: bool = False
) -> bytes:
    """Raw niftyindices TR response bytes from (HistoricalDate 'DD Mon YYYY', value) rows (P0-15).

    Mirrors the confirmed niftyindices array shape (probe 2026-08-09). The TR level rides in
    `TotalReturnsIndex` — the parser reads ONLY genuine TR fields; the price OHLC (incl. CLOSE) is
    emitted as a DECOY `"0.01"` so every test that asserts `tri_value == value` also proves the
    parser never reads CLOSE-as-TRI (the ADR-008/ADR-028 price-as-TRI lie). `wrap_d=True` wraps the
    array in the `{"d": "<json string>"}` page-method envelope (exercises the dual-envelope path).
    Values are SYNTHETIC — no real TRI sample is obtainable (sourcing blocker, ops/journal.md
    2026-08-10).
    """
    payload = [
        {
            "RequestNumber": "His0",
            "Index Name": "",
            "INDEX_NAME": response_index_name,
            "HistoricalDate": hd,
            "TotalReturnsIndex": value,  # the TR level the parser reads
            "OPEN": "0.01",
            "HIGH": "0.01",
            "LOW": "0.01",
            "CLOSE": "0.01",  # price decoy — parser must never read this as the TRI level
        }
        for hd, value in rows
    ]
    body = json.dumps(payload)
    return json.dumps({"d": body}).encode() if wrap_d else body.encode()


def asm_snapshot_bytes(
    entries: list[tuple[str, str, str, str]], groups: tuple[str, ...] = ("longterm",)
) -> bytes:
    """Raw asm.json bytes from (isin, symbol, company_name, asmSurvIndicator) rows.

    All entries land in the first named group (default 'longterm'); pass a longer `groups`
    tuple to also emit trailing EMPTY groups (proves the generic non-'columns'-key iteration
    handles an unconfirmed 'shortterm' key without hardcoding it, P0-14).
    """
    rows = [
        {
            "asmSurvIndicator": stage_text,
            "asmTime": "01-Jan-2026",
            "companyName": name,
            "isin": isin,
            "series": None,
            "survCode": "x",
            "survDesc": "x",
            "symbol": sym,
            "srno": i,
        }
        for i, (isin, sym, name, stage_text) in enumerate(entries, start=1)
    ]
    payload: dict[str, object] = {"columns": []}
    for i, g in enumerate(groups):
        payload[g] = {"data": rows if i == 0 else []}
    return json.dumps(payload).encode()


def gsm_snapshot_bytes(
    entries: list[tuple[str, str, str, str, str]], *, wrapper_key: str | None = "data"
) -> bytes:
    """Raw gsm.json bytes from (isin, symbol, company_name, survDesc, survCode) rows.

    `wrapper_key=None` emits a BARE top-level array (the other real-shape hypothesis, P0-14).
    """
    rows = [
        {
            "companyName": name,
            "gsmStage": "X",  # the known trap field — never the real stage (P0-14)
            "gsmTime": "01-Jan-2026 08:06:02",
            "isin": isin,
            "survCode": surv_code,
            "survDesc": surv_desc,
            "symbol": sym,
            "srno": i,
        }
        for i, (isin, sym, name, surv_desc, surv_code) in enumerate(entries, start=1)
    ]
    if wrapper_key is None:
        return json.dumps(rows).encode()
    return json.dumps({"columns": [], wrapper_key: rows}).encode()
