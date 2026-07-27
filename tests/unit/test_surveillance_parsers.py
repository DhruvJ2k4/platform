"""P0-14 structural parsers (doc 06 §6.1 style split): drift -> ParseError, never a guess.

Covers: ASM's generic non-'columns'-key iteration (works whether or not an unconfirmed
'shortterm' key appears — never hardcoded), GSM's ambiguous-wrapper-key detection (both the
'{"data": [...]}' and bare-array hypotheses, per the live probe's genuine uncertainty), the
gsmStage trap (never read as the real stage — that's the classifier's job, curate/surveillance.py,
not this parser's), and every structural-drift path (missing keys, wrong envelope shapes).
"""

import json

import pytest

from conftest import asm_snapshot_bytes, gsm_snapshot_bytes
from quant.curate.parsers.surveillance import parse_asm, parse_gsm
from quant.errors import ParseError

ISIN = "INE0000000A0"


def test_parse_asm_single_group() -> None:
    frame = parse_asm(asm_snapshot_bytes([(ISIN, "AAA", "A Co", "Stage II")]))
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["isin"] == ISIN
    assert row["category"] == "ASM"
    assert row["raw_stage_text"] == "Stage II"
    assert row["symbol"] == "AAA"


def test_parse_asm_generic_key_iteration_handles_unconfirmed_shortterm() -> None:
    # A second, EMPTY group key must not break parsing -- generic iteration, never hardcoded.
    frame = parse_asm(
        asm_snapshot_bytes([(ISIN, "AAA", "A Co", "Stage II")], groups=("longterm", "shortterm"))
    )
    assert len(frame) == 1  # the empty shortterm group contributes nothing


def test_parse_asm_multi_tier_same_isin_emits_two_rows() -> None:
    # Structural parser emits ONE row per group occurrence; collision handling (max stage wins)
    # is the classifier's job (curate/surveillance.py), not this parser's.
    b = json.dumps(
        {
            "columns": [],
            "longterm": {
                "data": [
                    {
                        "asmSurvIndicator": "Stage III",
                        "asmTime": "01-Jan-2026",
                        "companyName": "A Co",
                        "isin": ISIN,
                        "series": None,
                        "survCode": "x",
                        "survDesc": "x",
                        "symbol": "AAA",
                        "srno": 1,
                    }
                ]
            },
            "shortterm": {
                "data": [
                    {
                        "asmSurvIndicator": "Stage I",
                        "asmTime": "01-Jan-2026",
                        "companyName": "A Co",
                        "isin": ISIN,
                        "series": None,
                        "survCode": "x",
                        "survDesc": "x",
                        "symbol": "AAA",
                        "srno": 1,
                    }
                ]
            },
        }
    ).encode()
    frame = parse_asm(b)
    assert len(frame) == 2
    assert set(frame["raw_stage_text"]) == {"Stage III", "Stage I"}


def test_parse_asm_missing_key_is_parse_error() -> None:
    b = json.dumps({"columns": [], "longterm": {"data": [{"isin": ISIN}]}}).encode()
    with pytest.raises(ParseError, match="missing key"):
        parse_asm(b)


def test_parse_asm_no_groups_besides_columns_is_parse_error() -> None:
    with pytest.raises(ParseError, match="no data groups"):
        parse_asm(json.dumps({"columns": []}).encode())


def test_parse_asm_group_without_data_list_is_parse_error() -> None:
    with pytest.raises(ParseError, match="not an object with a 'data' list"):
        parse_asm(json.dumps({"columns": [], "longterm": "not-an-object"}).encode())


def test_parse_asm_non_object_payload_is_parse_error() -> None:
    with pytest.raises(ParseError, match="expected a JSON object"):
        parse_asm(json.dumps([1, 2, 3]).encode())


def test_parse_asm_malformed_json_is_parse_error() -> None:
    with pytest.raises(ParseError, match="not valid JSON"):
        parse_asm(b"not json")


def test_parse_asm_blank_isin_is_parse_error() -> None:
    b = asm_snapshot_bytes([("  ", "AAA", "A Co", "Stage I")])
    with pytest.raises(ParseError, match="missing or blank 'isin'"):
        parse_asm(b)


def test_parse_gsm_wrapped_data_key() -> None:
    frame = parse_gsm(gsm_snapshot_bytes([(ISIN, "AAA", "A Co", "desc", "code")]))
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["isin"] == ISIN
    assert row["category"] == "GSM"
    # gsmStage is the trap field -- must never appear in raw_stage_text (only survDesc+survCode do)
    assert "X" not in row["raw_stage_text"]
    assert "desc" in row["raw_stage_text"] and "code" in row["raw_stage_text"]


def test_parse_gsm_bare_top_level_array() -> None:
    frame = parse_gsm(gsm_snapshot_bytes([(ISIN, "AAA", "A Co", "desc", "code")], wrapper_key=None))
    assert len(frame) == 1
    assert frame.iloc[0]["isin"] == ISIN


def test_parse_gsm_ambiguous_two_candidate_keys_is_parse_error() -> None:
    b = json.dumps({"columns": [], "data": [], "extra": []}).encode()
    with pytest.raises(ParseError, match="expected exactly 1"):
        parse_gsm(b)


def test_parse_gsm_zero_candidate_keys_is_parse_error() -> None:
    b = json.dumps({"columns": [], "meta": "not-a-list"}).encode()
    with pytest.raises(ParseError, match="expected exactly 1"):
        parse_gsm(b)


def test_parse_gsm_non_list_non_dict_payload_is_parse_error() -> None:
    with pytest.raises(ParseError, match="expected a list or object"):
        parse_gsm(json.dumps("just a string").encode())


def test_parse_gsm_missing_key_is_parse_error() -> None:
    b = json.dumps({"columns": [], "data": [{"isin": ISIN}]}).encode()
    with pytest.raises(ParseError, match="missing key"):
        parse_gsm(b)


def test_parse_gsm_blank_survdesc_and_survcode_is_parse_error() -> None:
    b = json.dumps(
        {
            "columns": [],
            "data": [
                {
                    "companyName": "A Co",
                    "gsmStage": "X",
                    "gsmTime": "01-Jan-2026 00:00:00",
                    "isin": ISIN,
                    "survCode": "",
                    "survDesc": "",
                    "symbol": "AAA",
                    "srno": 1,
                }
            ],
        }
    ).encode()
    with pytest.raises(ParseError, match="both survDesc and survCode are blank"):
        parse_gsm(b)


def test_parse_gsm_malformed_json_is_parse_error() -> None:
    with pytest.raises(ParseError, match="not valid JSON"):
        parse_gsm(b"not json")
