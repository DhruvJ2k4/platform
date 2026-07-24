"""P0-13 liquidity statistics (doc 21 §3): MDTV / amihud / zero_days_pct / age, hand-computed.

Locks the two library behaviours the design rests on (probed 2026-07-23): pandas rolling
median/mean skip NaN under min_periods=1, and the amihud return uses the ADJUSTED (factor) path
so a split ex-date does NOT inject a spurious ~return spike (the raw-close trap, ADR-024).
"""

from datetime import date
from decimal import Decimal as D

import numpy as np
import pandas as pd

from conftest import ca_frame, calendar_frame, prices_adj_frame, security_frame
from quant.config import LiquidityConfig
from quant.curate.universe import _age_matrix, build_universe

DAYS = [date(2024, 1, d) for d in (2, 3, 4, 5, 8)]  # five consecutive NSE sessions
A, B = "INE0000000A0", "INE0000000B0"  # A = subject; B = axis-maker (present every session)

# Permissive thresholds: nothing is excluded, so every candidate row carries its raw stats.
PERMISSIVE = LiquidityConfig(
    window_trading_days=3,
    price_floor_rupees=D("1"),
    min_age_trading_days=1,
    max_zero_days_pct=D("1"),
    mdtv_floor_rupees=D("1"),
    p_max=D("0.01"),
)


def _b_rows() -> list[tuple]:
    """Axis-maker B: present every session so all five dates are real sessions."""
    return [(B, d, "EQ", D("500.00"), 100000, D("50000000.00"), 1.0) for d in DAYS]


def _stats_by_date(rows: list[tuple], isin: str) -> dict[date, pd.Series]:
    px = prices_adj_frame(rows)
    sec = security_frame([(A, "A", None, None, None, None), (B, "B", None, None, None, None)])
    res = build_universe(px, ca_frame([]), calendar_frame(DAYS), sec, PERMISSIVE)
    sub = res.frame[res.frame["isin"] == isin]
    return {r.d: r for r in sub.itertuples()}


def test_pandas_rolling_skips_nan_under_min_periods_1() -> None:
    # The design reindexes each ISIN onto the session axis with NaN for absent days and relies
    # on rolling to skip them. A pandas change here would silently corrupt every stat.
    s = pd.Series([100.0, np.nan, 300.0, np.nan, np.nan, 600.0])
    assert list(s.rolling(3, min_periods=1).median()) == [100.0, 100.0, 200.0, 300.0, 300.0, 600.0]
    assert list(s.rolling(3, min_periods=1).mean()) == [100.0, 100.0, 200.0, 300.0, 300.0, 600.0]
    allnan = pd.Series([np.nan, np.nan])
    assert allnan.rolling(2, min_periods=1).median().isna().all()  # all-absent window → NaN


def test_mdtv_is_rolling_median_of_present_traded_value() -> None:
    tv = [D("10.00"), D("20.00"), D("30.00"), D("40.00"), D("50.00")]
    rows = _b_rows()
    rows += [(A, d, "EQ", D("500.00"), 1000, v, 1.0) for d, v in zip(DAYS, tv, strict=True)]
    by_d = _stats_by_date(rows, A)
    # window=3: medians of trailing present traded_value (hand-computed).
    expected = [D("10.00"), D("15.00"), D("20.00"), D("30.00"), D("40.00")]
    assert [by_d[d].mdtv for d in DAYS] == expected


def test_amihud_uses_adjusted_returns_not_raw_close() -> None:
    # 5:1 split at DAYS[2]: raw close 100->20 but the adjusted series is flat 20 → returns ~0.
    # Raw-close returns would inject |-0.8| and spike amihud on the split day; adjusted must not.
    rows = _b_rows()
    rows += [
        (A, DAYS[0], "EQ", D("100.00"), 1000, D("1000000.00"), 0.2),
        (A, DAYS[1], "EQ", D("100.00"), 1000, D("1000000.00"), 0.2),
        (A, DAYS[2], "EQ", D("20.00"), 1000, D("1000000.00"), 1.0),  # split ex-date
        (A, DAYS[3], "EQ", D("20.00"), 1000, D("1000000.00"), 1.0),
        (A, DAYS[4], "EQ", D("20.00"), 1000, D("1000000.00"), 1.0),
    ]
    by_d = _stats_by_date(rows, A)
    # adjusted close is constant 20.00 → every return is 0 → amihud is 0 from the 2nd session on.
    assert by_d[DAYS[2]].amihud == 0.0  # the split day carries NO spurious spike
    assert by_d[DAYS[4]].amihud == 0.0
    assert np.isnan(by_d[DAYS[0]].amihud)  # first observation: no prior close → NaN (skipped)


def test_zero_days_pct_counts_absent_and_zero_volume_sessions() -> None:
    # A present on sessions 0,2,4 (absent 1,3) with volume 100,0,100. B keeps all five sessions.
    rows = _b_rows()
    rows += [
        (A, DAYS[0], "EQ", D("500.00"), 100, D("50000.00"), 1.0),
        (A, DAYS[2], "EQ", D("500.00"), 0, D("0.00"), 1.0),  # traded zero
        (A, DAYS[4], "EQ", D("500.00"), 100, D("50000.00"), 1.0),
    ]
    by_d = _stats_by_date(rows, A)
    # window=3 over zeroabs=[0,1,1,1,0]: D0=0, D2=(0+1+1)/3, D4=(1+1+0)/3.
    assert by_d[DAYS[0]].zero_days_pct == 0.0
    assert abs(by_d[DAYS[2]].zero_days_pct - 2 / 3) < 1e-12
    assert abs(by_d[DAYS[4]].zero_days_pct - 2 / 3) < 1e-12


def test_null_traded_value_window_stores_null_mdtv_and_excludes() -> None:
    # A candidate whose traded_value is null across its whole window (a data hole; the column is
    # nullable) yields NaN MDTV. It must NOT crash the DECIMAL write — mdtv stores NULL — and it
    # must be ff_mcap-excluded conservatively (liquidity can't be confirmed). Review 2026-07-23.
    rows = _b_rows()
    rows += [(A, d, "EQ", D("500.00"), 1000, None, 1.0) for d in DAYS]  # traded_value all NULL
    by_d = _stats_by_date(rows, A)
    r = by_d[DAYS[4]]
    assert pd.isna(r.mdtv)  # stored NULL, not a crashed build
    assert "ff_mcap_proxy" in list(r.excl_reasons)  # NaN MDTV → conservative exclude
    assert r.investable is False


def test_age_matrix_is_span_since_first_observation() -> None:
    # Two ISINs (columns); col0 first seen at row1, col1 first seen at row0.
    present = np.array([[False, True], [True, True], [False, True], [True, False], [True, True]])
    age = _age_matrix(present)
    # col0: rows 1,3,4 present → age 1,3,4 (span from first at row1); absent rows are NaN.
    assert age[1, 0] == 1 and age[3, 0] == 3 and age[4, 0] == 4
    assert np.isnan(age[0, 0]) and np.isnan(age[2, 0])
    # col1: first at row0 → ages 1..5 across present rows (row3 absent → NaN).
    assert age[0, 1] == 1 and age[4, 1] == 5 and np.isnan(age[3, 1])
