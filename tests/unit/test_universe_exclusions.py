"""P0-13 exclusion pipeline (doc 21 §4): ALL reasons emitted, tri-state investable, PIT scoping.

Covers the DoD's "exclusion reasons per name" (every failing filter listed, never just the
first), the risk-manager's tri-state investable veto (NULL when clean-but-surveillance-unchecked,
never True), the PIT scoping of pending_ca_review (available_at <= d), and the two seams built
now but inert in production: delisting from security.status and GSM*/ASM>=2 surveillance.
"""

from datetime import date, datetime
from decimal import Decimal as D

import pandas as pd

from conftest import ca_frame, calendar_frame, prices_adj_frame, security_frame, surveillance_frame
from quant.config import LiquidityConfig
from quant.curate.surveillance import _GSM_UNKNOWN
from quant.curate.universe import build_universe

DAYS = [date(2024, 1, d) for d in (2, 3, 4, 5, 8, 9)]  # six consecutive sessions
AXIS = "INE00000AXIS"  # present every session so all six dates are real sessions

BASE = LiquidityConfig(
    window_trading_days=3,
    price_floor_rupees=D("20"),
    min_age_trading_days=3,
    max_zero_days_pct=D("0.05"),
    mdtv_floor_rupees=D("1000000"),
    p_max=D("0.01"),
)


def _axis_rows() -> list[tuple]:
    return [(AXIS, d, "EQ", D("500.00"), 100000, D("50000000.00"), 1.0) for d in DAYS]


def _clean(isin: str) -> list[tuple]:
    """A name clean on every filter (present all sessions, liquid, priced, seasoned)."""
    return [(isin, d, "EQ", D("500.00"), 100000, D("50000000.00"), 1.0) for d in DAYS]


def _build(  # type: ignore[no-untyped-def]
    rows, ca=None, sec=None, surveillance=None, cfg=BASE, surv_floor=None, surv_ceiling=None
):
    isins = {r[0] for r in rows}
    if sec is None:
        sec = security_frame([(i, i, None, None, None, None) for i in sorted(isins)])
    res = build_universe(
        prices_adj_frame(rows),
        ca_frame(ca or []),
        calendar_frame(DAYS),
        sec,
        cfg,
        surveillance=surveillance,
        surveillance_coverage_floor=surv_floor,
        surveillance_coverage_ceiling=surv_ceiling,
    )
    return {(r.isin, r.d): r for r in res.frame.itertuples()}, res.stats


def test_all_reasons_emitted_together_in_fixed_order() -> None:
    # "Worst" name present only on the last two sessions: fails price, age, ff_mcap, zero_days;
    # plus delisted (status), GSM surveillance, and a needs_review CA known before the date.
    w = "INE0000WORST"
    rows = _axis_rows()
    rows += [
        (w, DAYS[4], "EQ", D("5.00"), 1, D("100.00"), 1.0),
        (w, DAYS[5], "EQ", D("5.00"), 1, D("100.00"), 1.0),
    ]
    sec = security_frame(
        [(AXIS, AXIS, None, None, None, None), (w, w, "delisted", None, None, D("5.00"))]
    )
    ca = [(w, DAYS[1], "other", None, None, None, "needs_review", "scheme", datetime(2024, 1, 3))]
    surv = surveillance_frame([(w, DAYS[0], "GSM", 1)])
    rows_by_key, _ = _build(rows, ca=ca, sec=sec, surveillance=surv)
    reasons = list(rows_by_key[(w, DAYS[5])].excl_reasons)
    assert reasons == [
        "price_below_floor",
        "age_below_min",
        "ff_mcap_proxy",
        "zero_days_gt_max",
        "delisted",
        "surveillance",
        "pending_ca_review",
    ]
    assert rows_by_key[(w, DAYS[5])].investable is False


def test_each_reason_fires_in_isolation() -> None:
    cheap = "INE000CHEAP0"  # only price fails
    tiny = "INE0000TINY0"  # only ff_mcap fails
    rows = (
        _axis_rows()
        + [(cheap, d, "EQ", D("10.00"), 100000, D("50000000.00"), 1.0) for d in DAYS]
        + [(tiny, d, "EQ", D("500.00"), 100000, D("500000.00"), 1.0) for d in DAYS]
    )
    by_key, _ = _build(rows)
    assert list(by_key[(cheap, DAYS[5])].excl_reasons) == ["price_below_floor"]
    assert list(by_key[(tiny, DAYS[5])].excl_reasons) == ["ff_mcap_proxy"]


def test_pending_ca_review_is_pit_scoped_by_available_at() -> None:
    # needs_review CA becomes known (available_at) on DAYS[3]; earlier sessions must NOT carry it.
    name = "INE0000PEND0"
    rows = _axis_rows() + _clean(name)
    ca = [(name, DAYS[3], "demerger", None, None, None, "needs_review", "x", datetime(2024, 1, 5))]
    by_key, _ = _build(rows, ca=ca)
    assert "pending_ca_review" not in by_key[(name, DAYS[2])].excl_reasons  # before available_at
    assert "pending_ca_review" in by_key[(name, DAYS[3])].excl_reasons  # on available_at
    assert "pending_ca_review" in by_key[(name, DAYS[5])].excl_reasons  # after


def test_surveillance_gsm_and_asm2_fire_but_not_asm1() -> None:
    gsm, asm1, asm2 = "INE00000GSM0", "INE0000ASM10", "INE0000ASM20"
    rows = _axis_rows() + _clean(gsm) + _clean(asm1) + _clean(asm2)
    surv = surveillance_frame(
        [(gsm, DAYS[0], "GSM", 1), (asm1, DAYS[0], "ASM", 1), (asm2, DAYS[0], "ASM", 2)]
    )
    by_key, _ = _build(rows, surveillance=surv)
    assert by_key[(gsm, DAYS[5])].surveillance == "GSM_1"  # GSM at any stage excludes
    assert "surveillance" in by_key[(gsm, DAYS[5])].excl_reasons
    assert "surveillance" in by_key[(asm2, DAYS[5])].excl_reasons  # ASM stage>=2 excludes
    assert "surveillance" not in by_key[(asm1, DAYS[5])].excl_reasons  # ASM stage 1 does not


def test_surveillance_unparseable_gsm_stage_still_excludes_end_to_end() -> None:
    # quant-researcher review, P0-14: _gsm_stage's UNKNOWN sentinel (99) and _excludes' pure
    # boolean logic were separately unit-tested, but nothing threaded an actual unparseable-GSM
    # row through build_universe's real composition (_surveillance_flags -> masks -> excl_reasons
    # -> investable). Closes that composition gap: a GSM row whose stage the classifier couldn't
    # parse (curate/surveillance.py's _GSM_UNKNOWN sentinel) must STILL exclude -- GSM's rule is
    # presence-only, not stage-gated, so an uninformative label must never mean "not excluded."
    unknown = "INE0000UNKN0"
    rows = _axis_rows() + _clean(unknown)
    surv = surveillance_frame([(unknown, DAYS[0], "GSM", _GSM_UNKNOWN)])
    by_key, _ = _build(rows, surveillance=surv)
    assert "surveillance" in by_key[(unknown, DAYS[5])].excl_reasons
    assert by_key[(unknown, DAYS[5])].surveillance == f"GSM_{_GSM_UNKNOWN}"
    assert by_key[(unknown, DAYS[5])].investable is False


def test_surveillance_categories_track_independently_gsm_removal_keeps_asm_exclusion() -> None:
    # P0-14: a prior draft merged both categories into ONE per-isin "latest row wins" tracker,
    # which would let a GSM removal event wrongly clear a still-active ASM exclusion. Confirmed
    # via this exact shape by the PM/risk-manager plan review.
    both = "INE0000BOTH0"
    rows = _axis_rows() + _clean(both)
    surv = surveillance_frame(
        [
            (both, DAYS[0], "ASM", 3),  # ASM stage 3: fires, never superseded
            (both, DAYS[0], "GSM", 1),  # GSM present at DAYS[0]...
            (both, DAYS[3], "GSM", -1),  # ...removed at DAYS[3] (later available_at)
        ]
    )
    by_key, _ = _build(rows, surveillance=surv)
    # Before the GSM removal: both categories fire; ASM wins the tie-break is irrelevant here
    # since GSM also fires -- just confirm BOTH still exclude at DAYS[1].
    assert "surveillance" in by_key[(both, DAYS[1])].excl_reasons
    # After the GSM removal (DAYS[3] onward): GSM is cleared, but ASM's DAYS[0] row is untouched
    # and must STILL fire -- this is the gap a merged-category tracker would get wrong.
    assert "surveillance" in by_key[(both, DAYS[5])].excl_reasons
    assert by_key[(both, DAYS[5])].surveillance == "ASM_3"  # GSM cleared; only ASM remains active


def test_surveillance_simultaneous_categories_deterministic_tie_break() -> None:
    # Both categories fire at the IDENTICAL available_at -- the flag string must be deterministic
    # (fixed ASM-then-GSM iteration order, GSM wins the max() tie on an exact available_at match).
    tie = "INE00000TIE0"
    rows = _axis_rows() + _clean(tie)
    surv = surveillance_frame([(tie, DAYS[0], "ASM", 3), (tie, DAYS[0], "GSM", 2)])
    by_key, _ = _build(rows, surveillance=surv)
    assert by_key[(tie, DAYS[5])].surveillance == "GSM_2"


def test_price_date_past_surveillance_ceiling_stays_undetermined() -> None:
    # execution-trader review, P0-14: every OTHER surveillance test keeps the coverage ceiling in
    # lockstep with the price panel's last date, so none exercise "prices exist for d, but the
    # last ASM/GSM snapshot is older than d" -- exactly the live-risk scenario (ingestion stalls
    # while prices keep flowing) the staleness gate exists to protect against. A clean name whose
    # LAST price date is strictly after the ceiling must stay undetermined there, never wrongly
    # True (investable degrading safely is the whole point of the floor<=d<=ceiling bound).
    clean = "INE000STALE0"
    rows = _axis_rows() + _clean(clean)
    surv = surveillance_frame([])  # checked, but only up through DAYS[3]
    by_key, _ = _build(rows, surveillance=surv, surv_floor=DAYS[0], surv_ceiling=DAYS[3])
    assert by_key[(clean, DAYS[3])].investable is True  # within [floor,ceiling]: affirmatively True
    assert by_key[(clean, DAYS[3])].excl_reasons == []
    for stale_day in DAYS[4:]:  # DAYS[4], DAYS[5]: past the ceiling, still otherwise clean
        row = by_key[(clean, stale_day)]
        assert row.excl_reasons == []  # nothing actually fired
        assert pd.isna(row.investable)  # yet NEVER wrongly True -- staleness degrades safely
        assert row.surveillance == "UNVERIFIED"


def test_investable_tristate_null_true_false() -> None:
    clean = "INE000CLEAN0"
    cheap = "INE000CHEAP0"
    rows = (
        _axis_rows()
        + _clean(clean)
        + [(cheap, d, "EQ", D("10.00"), 100000, D("50000000.00"), 1.0) for d in DAYS]
    )
    # (a) surveillance UNCHECKED: a clean name is UNDETERMINED (NULL), sentinel column, never True.
    unchecked, stats = _build(rows)
    row = unchecked[(clean, DAYS[5])]
    assert pd.isna(row.investable) and row.surveillance == "UNVERIFIED"
    assert unchecked[(cheap, DAYS[5])].investable is False  # a real filter still decides False
    assert stats["investable_true"] == 0 and stats["investable_null"] > 0
    # (b) surveillance CHECKED (frame present AND floor/ceiling bound this date) and name not
    # flagged: clean -> investable True, no sentinel. Floor/ceiling gate ONLY this affirmative
    # path (P0-14) -- an empty frame alone is not enough, matching build_surveillance's real
    # contract where floor/ceiling come from actual ingested-snapshot coverage, not frame content.
    checked, _ = _build(
        rows, surveillance=surveillance_frame([]), surv_floor=DAYS[0], surv_ceiling=DAYS[-1]
    )
    row2 = checked[(clean, DAYS[5])]
    assert row2.investable is True and pd.isna(row2.surveillance)


def test_delisting_hook_fires_from_security_status() -> None:
    dl, sp = "INE00000DEL0", "INE0000SUSP0"
    rows = _axis_rows() + _clean(dl) + _clean(sp)
    sec = security_frame(
        [
            (AXIS, AXIS, None, None, None, None),
            (dl, dl, "delisted", None, date(2024, 1, 9), D("5.00")),
            (sp, sp, "suspended", None, None, None),
        ]
    )
    by_key, _ = _build(rows, sec=sec)
    assert list(by_key[(dl, DAYS[5])].excl_reasons) == ["delisted"]
    assert list(by_key[(sp, DAYS[5])].excl_reasons) == ["suspended"]
