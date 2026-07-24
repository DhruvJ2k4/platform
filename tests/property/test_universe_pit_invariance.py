"""P0-13 PIT asof-invariance property (CLAUDE.md "PIT no-future-rows"; PM review CRITICAL).

A universe_membership row for date d must not depend on any data after d. Equivalently: building
from the panel truncated at T1 yields, for every d <= T1, exactly the rows a build over the full
panel produces. This is what the per-(isin,d) PIT scoping of pending_ca_review (available_at<=d,
never the build asof) buys — a needs_review CA whose ex_date lands after T1 cannot retroactively
exclude an earlier session. Holds the CA-resolution config fixed (per-manifest-version, ADR-026).
"""

from datetime import date, datetime, timedelta
from decimal import Decimal as D

import numpy as np
import pandas as pd
from hypothesis import given
from hypothesis import strategies as st

from conftest import ca_frame, calendar_frame, prices_adj_frame, security_frame
from quant.config import LiquidityConfig
from quant.curate.universe import build_universe

ISINS = ["INE00000PIT0", "INE00000PIT1", "INE00000PIT2"]
DAYS = [date(2025, 1, 1) + timedelta(days=i) for i in range(12)]
CFG = LiquidityConfig(
    window_trading_days=5,
    price_floor_rupees=D("20"),
    min_age_trading_days=3,
    max_zero_days_pct=D("0.05"),
    mdtv_floor_rupees=D("1000000"),
    p_max=D("0.01"),
)
_cell = st.tuples(st.booleans(), st.integers(5, 1000), st.integers(0, 200_000))
N = len(ISINS) * len(DAYS)


def _key(r) -> tuple:  # type: ignore[no-untyped-def]
    inv = None if pd.isna(r.investable) else bool(r.investable)
    amihud = "nan" if (isinstance(r.amihud, float) and np.isnan(r.amihud)) else r.amihud
    surv = None if pd.isna(r.surveillance) else str(r.surveillance)
    return (inv, str(r.mdtv), amihud, r.zero_days_pct, surv, tuple(r.excl_reasons))


@given(
    cells=st.lists(_cell, min_size=N, max_size=N),
    cut=st.integers(min_value=3, max_value=len(DAYS) - 1),
    review_day=st.integers(min_value=0, max_value=len(DAYS) - 1),
)
def test_future_sessions_never_change_a_past_universe_row(cells, cut, review_day) -> None:
    rows = []
    for i, isin in enumerate(ISINS):
        for j, d in enumerate(DAYS):
            present, close, vol = cells[i * len(DAYS) + j]
            if present:
                rows.append((isin, d, "EQ", D(close), vol, D(close * vol), 1.0))
    sec = security_frame([(i, i, None, None, None, None) for i in ISINS])
    # A needs_review CA on ISINS[0] whose ex_date may fall on either side of the cut — its
    # available_at governs; a post-cut review must not touch pre-cut rows.
    rd = DAYS[review_day]
    ca = ca_frame(
        [
            (
                ISINS[0],
                rd,
                "other",
                None,
                None,
                None,
                "needs_review",
                "x",
                datetime(rd.year, rd.month, rd.day),
            )
        ]
    )
    cal = calendar_frame(DAYS)
    t1 = DAYS[cut]
    early_rows = [r for r in rows if r[1] <= t1]

    full = build_universe(prices_adj_frame(rows), ca, cal, sec, CFG).frame
    early = build_universe(prices_adj_frame(early_rows), ca, cal, sec, CFG).frame

    full_early = {(r.isin, r.d): _key(r) for r in full.itertuples() if r.d <= t1}
    early_map = {(r.isin, r.d): _key(r) for r in early.itertuples()}
    assert early_map.keys() == full_early.keys()  # same candidate rows on d <= T1
    for k in early_map:
        assert early_map[k] == full_early[k], (k, early_map[k], full_early[k])
