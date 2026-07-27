"""Golden ASM/GSM surveillance scenario (doc 21 §4, P0-14): 4 weekly snapshots x 4 isins,
hand-computed BEFORE any code ran (doc 16, sacred — never edit an expected value to make a run
pass without written justification). Proves the full pipeline end to end: raw snapshots ->
build_surveillance's CDC-diff -> build_universe's per-(isin,category) exclusion-firing, covering
BOTH halves of the doc-20 DoD ("list-add flips investability next build") — add AND removal.

Sessions S1..S4 = 2026-08-03, 2026-08-10, 2026-08-17, 2026-08-24 (weekly).

A (INE0000000A0) — the DoD's core add-then-remove proof:
  S1: absent from both lists -> no data yet, clean (not excluded by surveillance).
  S2: ASM longterm adds "Stage I" (stage 1 < 2) -> NOT excluded (below the ASM>=2 threshold).
  S3: ASM escalates to "Stage II" (stage 2) -> EXCLUDED (crosses the threshold).
  S4: ASM list no longer contains A (removed) -> _cdc_diff emits stage=REMOVED -> NOT excluded.
      This is the reverse of "list-add flips investability" -- list-REMOVE flips it back.

B (INE0000000B0) — single-ever-emitted-row resolution:
  S1: ASM longterm "Stage III" (stage 3) -> EXCLUDED, and stays unchanged through S2-S4 (no new
  event emitted after S1, by _cdc_diff's change-only design). A query date BETWEEN S3 and S4
  must still resolve correctly off that one S1 row via "latest available_at <= d".

C (INE0000000C0) — GSM's any-stage-excludes wildcard (doc 21 §4's "GSM*"):
  S1: absent. S2: GSM adds "Graded Surveillance Measure - Stage 0" (stage 0) -> EXCLUDED (GSM
  excludes at ANY stage, including the mildest one -- unlike ASM's stage>=2 threshold).

D (INE0000000D0) — simultaneous ASM+GSM, deterministic tie-break:
  S1,S2: absent. S3: BOTH ASM "Stage III" and GSM "Stage II" appear the same snapshot ->
  EXCLUDED via either category; the surveillance flag string shows GSM (fixed tie-break order:
  ASM then GSM, GSM sorts after ASM on an exact available_at tie -- curate/universe.py).

AXIS (INE00000AXIS) — never on any list; the liquidity/price-panel axis-maker.

Coverage floor/ceiling = S1/S4 for both categories (four snapshots ingested for asm AND gsm),
so `investable=True` is reachable for AXIS on any date in [S1, S4] with no exclusion fired.
"""

import json
import shutil
import tempfile
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pandas as pd

from conftest import ca_frame, calendar_frame, prices_adj_frame, security_frame
from quant.config import LiquidityConfig, Settings
from quant.curate.surveillance import build_surveillance
from quant.curate.universe import build_universe
from quant.ingest import RawStore

S1, S2, S3, S4 = date(2026, 8, 3), date(2026, 8, 10), date(2026, 8, 17), date(2026, 8, 24)
DAYS = [S1, S2, S3, S4]
AXIS, A, B, C, D_ = "INE00000AXIS", "INE0000000A0", "INE0000000B0", "INE0000000C0", "INE0000000D0"
CFG = LiquidityConfig(
    window_trading_days=3,
    price_floor_rupees=D("20"),
    min_age_trading_days=1,
    max_zero_days_pct=D("1"),
    mdtv_floor_rupees=D("1"),
    p_max=D("0.01"),
)


def _asm(entries: list[tuple[str, str, str]]) -> bytes:
    """entries: (isin, symbol, asmSurvIndicator)."""
    rows = [
        {
            "asmSurvIndicator": stage,
            "asmTime": "01-Jan-2026",
            "companyName": sym + " Co",
            "isin": isin,
            "series": None,
            "survCode": "x",
            "survDesc": "x",
            "symbol": sym,
            "srno": i,
        }
        for i, (isin, sym, stage) in enumerate(entries, start=1)
    ]
    return json.dumps({"columns": [], "longterm": {"data": rows}}).encode()


def _gsm(entries: list[tuple[str, str, str, str]]) -> bytes:
    """entries: (isin, symbol, survDesc, survCode)."""
    rows = [
        {
            "companyName": sym + " Co",
            "gsmStage": "X",
            "gsmTime": "01-Jan-2026 08:06:02",
            "isin": isin,
            "survCode": code,
            "survDesc": desc,
            "symbol": sym,
            "srno": i,
        }
        for i, (isin, sym, desc, code) in enumerate(entries, start=1)
    ]
    return json.dumps({"columns": [], "data": rows}).encode()


def _scenario() -> tuple[dict, dict]:
    tmp = Path(tempfile.mkdtemp())
    s = Settings(data_dir=tmp / "data", config_dir=tmp / "config")
    store = RawStore(s)

    store.put("asm", S1, _asm([(B, "BBB", "Stage III")]), suffix=".json")
    store.put("asm", S2, _asm([(B, "BBB", "Stage III"), (A, "AAA", "Stage I")]), suffix=".json")
    store.put(
        "asm",
        S3,
        _asm([(B, "BBB", "Stage III"), (A, "AAA", "Stage II"), (D_, "DDD", "Stage III")]),
        suffix=".json",
    )
    store.put("asm", S4, _asm([(B, "BBB", "Stage III"), (D_, "DDD", "Stage III")]), suffix=".json")

    store.put("gsm", S1, _gsm([]), suffix=".json")
    store.put(
        "gsm", S2, _gsm([(C, "CCC", "Graded Surveillance Measure - Stage 0", "GSM 0 (1)")]),
        suffix=".json",
    )  # fmt: skip
    store.put(
        "gsm",
        S3,
        _gsm(
            [
                (C, "CCC", "Graded Surveillance Measure - Stage 0", "GSM 0 (1)"),
                (D_, "DDD", "Graded Surveillance Measure - Stage II", "GSM - II (2)"),
            ]
        ),
        suffix=".json",
    )
    store.put(
        "gsm",
        S4,
        _gsm(
            [
                (C, "CCC", "Graded Surveillance Measure - Stage 0", "GSM 0 (1)"),
                (D_, "DDD", "Graded Surveillance Measure - Stage II", "GSM - II (2)"),
            ]
        ),
        suffix=".json",
    )

    surv = build_surveillance(s)

    def clean(isin: str) -> list[tuple]:
        return [(isin, d, "EQ", D("500.00"), 100000, D("50000000.00"), 1.0) for d in DAYS]

    rows = clean(AXIS) + clean(A) + clean(B) + clean(C) + clean(D_)
    sec = security_frame([(i, i, None, None, None, None) for i in (AXIS, A, B, C, D_)])
    res = build_universe(
        prices_adj_frame(rows),
        ca_frame([]),
        calendar_frame(DAYS),
        sec,
        CFG,
        surveillance=surv.frame,
        surveillance_coverage_floor=surv.coverage_floor,
        surveillance_coverage_ceiling=surv.coverage_ceiling,
    )
    by_key = {(r.isin, r.d): r for r in res.frame.itertuples()}
    shutil.rmtree(tmp, ignore_errors=True)
    return by_key, surv.stats


def test_golden_coverage_bounds() -> None:
    _, stats = _scenario()
    assert stats["asm_snapshots"] == 4
    assert stats["gsm_snapshots"] == 4
    assert stats["asm_events"] == 5  # B@S1, A@S2, A@S3, D@S3, A@S4(removed)
    assert stats["gsm_events"] == 2  # C@S2, D@S3


def test_golden_a_add_escalate_then_remove() -> None:
    by = _scenario()[0]
    assert "surveillance" not in by[(A, S1)].excl_reasons  # no data yet
    assert "surveillance" not in by[(A, S2)].excl_reasons  # Stage I < 2, not excluded
    assert by[(A, S2)].investable is True  # checked-clean at S2 (bounded, nothing fired)
    assert pd.isna(by[(A, S2)].surveillance)  # no sentinel -- affirmatively checked-clean
    assert "surveillance" in by[(A, S3)].excl_reasons  # Stage II >= 2, excluded
    assert by[(A, S3)].surveillance == "ASM_2"
    assert "surveillance" not in by[(A, S4)].excl_reasons  # removed -- DoD reverse proof
    assert by[(A, S4)].investable is True  # clean on every filter, bounded -> affirmatively True


def test_golden_b_single_row_resolves_across_all_later_dates() -> None:
    by = _scenario()[0]
    for d in DAYS:
        assert "surveillance" in by[(B, d)].excl_reasons, d
        assert by[(B, d)].surveillance == "ASM_3"
    assert by[(B, S1)].investable is False


def test_golden_c_gsm_any_stage_excludes() -> None:
    by = _scenario()[0]
    assert "surveillance" not in by[(C, S1)].excl_reasons
    for d in (S2, S3, S4):
        assert "surveillance" in by[(C, d)].excl_reasons, d
        assert by[(C, d)].surveillance == "GSM_0"


def test_golden_d_simultaneous_asm_gsm_tie_break() -> None:
    by = _scenario()[0]
    assert "surveillance" not in by[(D_, S2)].excl_reasons
    assert "surveillance" in by[(D_, S3)].excl_reasons
    assert by[(D_, S3)].surveillance == "GSM_2"  # deterministic tie-break: GSM wins on exact tie
    assert "surveillance" in by[(D_, S4)].excl_reasons  # unchanged from S3


def test_golden_axis_clean_and_bounded_is_affirmatively_true() -> None:
    by = _scenario()[0]
    for d in DAYS:
        assert by[(AXIS, d)].excl_reasons == []
        assert by[(AXIS, d)].investable is True
