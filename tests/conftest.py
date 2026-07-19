"""Shared pytest configuration: deterministic hypothesis profiles + typed frame factories.

Hypothesis does not read HYPOTHESIS_PROFILE itself, so this conftest both registers
the "ci" profile and loads whichever profile the environment selects. CI sets
HYPOTHESIS_PROFILE=ci for derandomized, reproducible property runs (doc 23).

The frame factories build arrow-typed ParsedBhavcopy-shaped panels and doc-10
corporate_actions frames for the adjuster suites (golden/unit/property share them via
`from conftest import …`, which works in pytest's prepend import mode because this
directory joins sys.path).
"""

import os
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import pyarrow as pa
from hypothesis import settings

from quant.schemas import DATE, I32, I64, STR, TS, dec

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
