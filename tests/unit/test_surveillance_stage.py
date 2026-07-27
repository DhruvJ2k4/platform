"""P0-14 stage classification (curate/surveillance.py): ASM strict, GSM lenient, plus the
ASM/IBC text-leak detector and the multi-tier max(stage) collision rule.

ASM's `asmSurvIndicator` gates the doc-21 §4 ASM>=2 exclusion threshold directly, so drift is a
ParseError (never a guess). GSM's exclusion is presence-only (any stage excludes), so its stage
number is informational — a miss falls back to a distinct sentinel, never a crash, never a
fabricated real stage.
"""

import pandas as pd
import pytest

from quant.curate.surveillance import (
    _GSM_UNKNOWN,
    REMOVED,
    _aggregate_snapshot,
    _asm_stage,
    _gsm_stage,
    _mentions_asm_ibc,
)
from quant.errors import ParseError


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Stage I", 1),
        ("Stage II", 2),
        ("Stage III", 3),
        ("Stage IV", 4),
        ("Stage V", 5),
        ("Stage X", 10),
    ],
)
def test_asm_stage_roman_round_trip(text: str, expected: int) -> None:
    assert _asm_stage(text) == expected


@pytest.mark.parametrize("text", ["Stage Zero", "Stage", "ASM Stage I", "Stage IIII", "", "1"])
def test_asm_stage_drift_is_parse_error(text: str) -> None:
    with pytest.raises(ParseError, match="unrecognized asmSurvIndicator"):
        _asm_stage(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Graded Surveillance Measure - Stage VI GSM - VI (6)", 6),
        (
            "Insolvency and Bankruptcy Code (IBC) - Receipt of Disclosure or Recommenced scrip "
            "and GSM stage 0 IBC - Receipt & GSM 0 (62)",
            0,
        ),
        ("GSM stage I and Insolvency... GSM I & IBC - Receipt (63)", 1),
        (
            "High promoter/Non Promoter Encumbrance & GSM Stage 0 "
            "High promoter/Non Promoter Encumbrance & GSM 0 (56)",
            0,
        ),
        ("ASM IBC Stage I and GSM Stage 0 IBC I & GSM 0 (58)", 0),
    ],
)
def test_gsm_stage_real_samples(text: str, expected: int) -> None:
    assert _gsm_stage(text) == expected


def test_gsm_stage_unparseable_falls_back_to_unknown_sentinel_not_a_raise() -> None:
    # GSM's exclusion is presence-only -- a miss must never crash, and must never guess a real
    # stage; the sentinel is distinct from REMOVED so an unparseable-but-present row still excludes.
    assert _gsm_stage("no gsm mention anywhere in this text") == _GSM_UNKNOWN
    assert _GSM_UNKNOWN != REMOVED


def test_gsm_stage_never_reads_the_trap_field() -> None:
    # gsmStage="LVIII" (58, the sequence number) must never leak into this text -- only
    # survDesc/survCode are ever concatenated into raw_stage_text upstream (parsers module).
    assert _gsm_stage("GSM - VI (6)") == 6  # LVIII would wrongly parse as roman 58 if mis-fed


def test_mentions_asm_ibc() -> None:
    assert _mentions_asm_ibc("ASM IBC Stage I and GSM Stage 0") is True
    no_asm_token = "Insolvency and Bankruptcy Code (IBC) - Receipt"
    assert _mentions_asm_ibc(no_asm_token) is False
    assert _mentions_asm_ibc("Graded Surveillance Measure - Stage VI") is False


def test_aggregate_snapshot_asm_multi_tier_collision_max_wins() -> None:
    # Same isin, two rows (e.g. longterm Stage III + shortterm Stage I) -> max(3,1)=3, counted.
    frame = pd.DataFrame(
        {"isin": ["INE0000000A0", "INE0000000A0"], "raw_stage_text": ["Stage III", "Stage I"]}
    )
    stats: dict[str, int] = {}
    state = _aggregate_snapshot(frame, _asm_stage, stats, "asm_multi_tier_isins")
    assert state == {"INE0000000A0": 3}
    assert stats["asm_multi_tier_isins"] == 1


def test_aggregate_snapshot_no_collision_no_counter() -> None:
    frame = pd.DataFrame({"isin": ["INE0000000A0"], "raw_stage_text": ["Stage II"]})
    stats: dict[str, int] = {}
    state = _aggregate_snapshot(frame, _asm_stage, stats, "asm_multi_tier_isins")
    assert state == {"INE0000000A0": 2}
    assert stats.get("asm_multi_tier_isins", 0) == 0
