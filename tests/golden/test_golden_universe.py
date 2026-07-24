"""Golden PIT-universe scenario (doc 21 §3-4): 4 names x 7 sessions, hand-computed.

Every expected value was computed BY HAND before the code ran; sacred (doc 16) — never edit an
expected to make a run pass without written justification. Config: window=3, price_floor=₹20,
min_age=3 td, max_zero=5%, mdtv_floor=₹1,000,000. Surveillance is UNWIRED (default build), so a
name clean on every RUN filter is investable=NULL / surveillance="UNVERIFIED" — never True.

Sessions S1..S7 = 2025-03-03 .. 2025-03-09 (indices 0..6).

LIQUID (INE00LIQUID0) — clean, and the axis-maker (present every session):
  present all 7, close ₹100, volume 10000, traded_value ₹2,000,000, adj 1.0.
  MDTV(S7)=median(2,000,000 over S5..S7)=2,000,000 (≥ floor) · zero_days(S7)=0 · age(S7)=7 (≥3)
  · returns all 0 (flat adjusted) → amihud(S7)=0. No filter fires → investable NULL, UNVERIFIED.

CHEAP (INE000CHEAP0) — one reason:
  present all 7, close ₹15 (< ₹20), else liquid. Only price_below_floor. investable False.

THIN (INE0000THIN00) — three reasons, present only S6,S7:
  close ₹50, volume 10000, traded_value ₹500,000. first-observed S6 → age(S7)=2 (<3) →
  age_below_min · MDTV(S7)=median(500,000 over S5..S7 present S6,S7)=500,000 (< floor) →
  ff_mcap_proxy · zero_days(S7) over S5..S7 = (absent S5, present S6, present S7)=1/3 (>5%) →
  zero_days_gt_max. investable False.

PENDING (INE00PENDING0) — PIT-scoped review, present all 7:
  close ₹100, liquid; a needs_review 'other' CA with available_at = S3.
  S1,S2: age 1,2 (<3) → age_below_min; review not yet known (available_at S3 > S1,S2).
  S3..S7: age ≥3, review known (available_at S3 ≤ d) → pending_ca_review (sole reason).
"""

from datetime import date, datetime
from decimal import Decimal as D

import pandas as pd

from conftest import ca_frame, calendar_frame, prices_adj_frame, security_frame
from quant.config import LiquidityConfig
from quant.curate.universe import build_universe

DAYS = [date(2025, 3, 3 + i) for i in range(7)]
LIQUID, CHEAP, THIN, PENDING = "INE00LIQUID0", "INE000CHEAP0", "INE0000THIN00", "INE00PENDING0"
CFG = LiquidityConfig(
    window_trading_days=3,
    price_floor_rupees=D("20"),
    min_age_trading_days=3,
    max_zero_days_pct=D("0.05"),
    mdtv_floor_rupees=D("1000000"),
    p_max=D("0.01"),
)


def _scenario():  # type: ignore[no-untyped-def]
    rows = []
    for d in DAYS:
        rows.append((LIQUID, d, "EQ", D("100.00"), 10000, D("2000000.00"), 1.0))
        rows.append((CHEAP, d, "EQ", D("15.00"), 10000, D("2000000.00"), 1.0))
        rows.append((PENDING, d, "EQ", D("100.00"), 10000, D("2000000.00"), 1.0))
    for d in DAYS[5:]:  # THIN present only S6, S7
        rows.append((THIN, d, "EQ", D("50.00"), 10000, D("500000.00"), 1.0))
    sec = security_frame([(i, i, None, None, None, None) for i in (LIQUID, CHEAP, THIN, PENDING)])
    ca = ca_frame(
        [
            (
                PENDING,
                DAYS[2],
                "other",
                None,
                None,
                None,
                "needs_review",
                "scheme",
                datetime(2025, 3, 5),
            )
        ]
    )
    res = build_universe(prices_adj_frame(rows), ca, calendar_frame(DAYS), sec, CFG)
    return {(r.isin, r.d): r for r in res.frame.itertuples()}, res.stats


def test_golden_liquid_is_clean_and_undetermined() -> None:
    by_key, _ = _scenario()
    r = by_key[(LIQUID, DAYS[6])]
    assert list(r.excl_reasons) == []
    assert pd.isna(r.investable) and r.surveillance == "UNVERIFIED"
    assert r.mdtv == D("2000000.00")
    assert r.zero_days_pct == 0.0
    assert r.amihud == 0.0


def test_golden_cheap_single_reason() -> None:
    by_key, _ = _scenario()
    r = by_key[(CHEAP, DAYS[6])]
    assert list(r.excl_reasons) == ["price_below_floor"]
    assert r.investable is False


def test_golden_thin_three_reasons_exact_stats() -> None:
    by_key, _ = _scenario()
    r = by_key[(THIN, DAYS[6])]
    assert list(r.excl_reasons) == ["age_below_min", "ff_mcap_proxy", "zero_days_gt_max"]
    assert r.mdtv == D("500000.00")
    assert abs(r.zero_days_pct - 1 / 3) < 1e-12
    assert r.investable is False


def test_golden_pending_review_is_pit_scoped() -> None:
    by_key, _ = _scenario()
    assert list(by_key[(PENDING, DAYS[0])].excl_reasons) == ["age_below_min"]  # S1, review unknown
    assert list(by_key[(PENDING, DAYS[1])].excl_reasons) == ["age_below_min"]  # S2, review unknown
    assert list(by_key[(PENDING, DAYS[2])].excl_reasons) == [
        "pending_ca_review"
    ]  # S3 = available_at
    assert list(by_key[(PENDING, DAYS[6])].excl_reasons) == ["pending_ca_review"]  # S7


def test_golden_accounting_sums() -> None:
    _, stats = _scenario()
    # 3 names x 7 sessions + THIN x 2 = 23 candidate rows; all EQ so no non-candidates.
    assert stats["candidates"] == 23
    assert stats["non_candidate_rows"] == 0
    assert stats["sessions"] == 7
    assert stats["investable_true"] == 0  # surveillance unwired → clean names are NULL, not True
    assert stats["investable_false"] + stats["investable_null"] == 23
