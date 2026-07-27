"""P0-13 monotonicity property (the DoD's "monotonicity green"), threshold leg.

Tightening every liquidity threshold uniformly can only SHRINK the investable set and GROW each
name's reason list — never the reverse. The stats (MDTV/age/zero_days) are identical across the
two configs (same panel, same window), so the only moving part is the thresholds, and each
threshold reason is individually monotone. The book-corpus monotonicity leg ships with the
deferred investable(book) overlay (ADR-026). Surveillance is checked (empty frame, WITH an
explicit floor/ceiling bounding every DAYS — P0-14: floor/ceiling, not frame presence alone,
gate the affirmative path) so investable is a genuine bool here, not the undetermined NULL.
"""

from datetime import date, timedelta
from decimal import Decimal as D

from hypothesis import given
from hypothesis import strategies as st

from conftest import ca_frame, calendar_frame, prices_adj_frame, security_frame, surveillance_frame
from quant.config import LiquidityConfig
from quant.curate.universe import build_universe

ISINS = ["INE0000000M0", "INE0000000M1", "INE0000000M2"]
DAYS = [date(2025, 1, 1) + timedelta(days=i) for i in range(10)]
WINDOW = 5
N = len(ISINS) * len(DAYS)

_cell = st.tuples(st.booleans(), st.integers(5, 1000), st.integers(0, 200_000))


def _cfg(price: int, age: int, mdtv: int, zero_pct: int) -> LiquidityConfig:
    return LiquidityConfig(
        window_trading_days=WINDOW,
        price_floor_rupees=D(price),
        min_age_trading_days=age,
        max_zero_days_pct=D(zero_pct) / D(100),
        mdtv_floor_rupees=D(mdtv),
        p_max=D("0.01"),
    )


def _rows(cells: list[tuple[bool, int, int]]) -> list[tuple]:
    rows = []
    for i, isin in enumerate(ISINS):
        for j, d in enumerate(DAYS):
            present, close, vol = cells[i * len(DAYS) + j]
            if present:
                rows.append((isin, d, "EQ", D(close), vol, D(close * vol), 1.0))
    return rows


@given(
    cells=st.lists(_cell, min_size=N, max_size=N),
    price=st.tuples(st.integers(10, 100), st.integers(10, 100)),
    age=st.tuples(st.integers(1, 8), st.integers(1, 8)),
    mdtv=st.tuples(st.integers(1000, 5_000_000), st.integers(1000, 5_000_000)),
    zero=st.tuples(st.integers(1, 100), st.integers(1, 100)),
)
def test_tightening_thresholds_shrinks_investable_and_grows_reasons(
    cells, price, age, mdtv, zero
) -> None:
    rows = _rows(cells)
    sec = security_frame([(i, i, None, None, None, None) for i in ISINS])
    surv = surveillance_frame([])  # checked-but-empty → investable is a real bool
    surv_kwargs = {
        "surveillance": surv,
        "surveillance_coverage_floor": DAYS[0],
        "surveillance_coverage_ceiling": DAYS[-1],
    }
    args = (ca_frame([]), calendar_frame(DAYS), sec)
    # A = the looser config; B = uniformly at-least-as-strict on every threshold.
    a = _cfg(min(price), min(age), min(mdtv), max(zero))
    b = _cfg(max(price), max(age), max(mdtv), min(zero))
    fa = build_universe(prices_adj_frame(rows), *args, a, **surv_kwargs).frame
    fb = build_universe(prices_adj_frame(rows), *args, b, **surv_kwargs).frame

    ra = {(r.isin, r.d): (set(r.excl_reasons), r.investable) for r in fa.itertuples()}
    rb = {(r.isin, r.d): (set(r.excl_reasons), r.investable) for r in fb.itertuples()}
    assert ra.keys() == rb.keys()  # same candidate set (same panel)
    for key in ra:
        reasons_a, inv_a = ra[key]
        reasons_b, inv_b = rb[key]
        assert reasons_a <= reasons_b, (key, reasons_a, reasons_b)  # reasons only grow
        if inv_b is True:  # stricter config investable ⟹ looser config investable
            assert inv_a is True, (key, inv_a, inv_b)
