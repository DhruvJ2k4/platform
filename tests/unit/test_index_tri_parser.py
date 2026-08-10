"""P0-15 unit: niftyindices TR parser — structural decoding, dual envelope, loud on drift."""

import json
from decimal import Decimal as D

import pytest

from conftest import index_tri_bytes
from quant.curate.parsers.index_tri import parse_index_tri
from quant.errors import ParseError


class TestParseIndexTri:
    def test_parses_confirmed_array_shape_to_index_tri(self) -> None:
        raw = index_tri_bytes([("20 Jan 2026", "38000.123456"), ("19 Jan 2026", "37950.5")])
        df = parse_index_tri(raw, "NIFTY 50 TR")
        assert list(df["index_name"]) == ["NIFTY 50 TR", "NIFTY 50 TR"]
        assert [str(v) for v in df["d"]] == ["2026-01-20", "2026-01-19"]
        # DECIMAL(18,6) preserved exactly — no float degradation on the benchmark value
        assert list(df["tri_value"]) == [D("38000.123456"), D("37950.500000")]

    def test_index_name_argument_overrides_response_index_name(self) -> None:
        raw = index_tri_bytes([("01 Jan 2026", "100")], response_index_name="Nifty 50")
        df = parse_index_tri(raw, "NIFTY 50 TR")  # curated key comes from the argument, not payload
        assert set(df["index_name"]) == {"NIFTY 50 TR"}

    def test_d_envelope_wrapper_is_unwrapped(self) -> None:
        raw = index_tri_bytes([("01 Jan 2026", "100.0")], wrap_d=True)
        df = parse_index_tri(raw, "NIFTY 50 TR")
        assert len(df) == 1 and df["tri_value"].iloc[0] == D("100.000000")

    def test_empty_array_is_zero_rows_not_an_error(self) -> None:
        assert len(parse_index_tri(b"[]", "NIFTY 50 TR")) == 0

    def test_tr_field_read_and_close_ignored(self) -> None:
        # a response carrying both price CLOSE and a TR field reads the TR field, never price
        raw = json.dumps(
            [{"HistoricalDate": "01 Jan 2026", "CLOSE": "100", "TotalReturnsIndex": "155.5"}]
        ).encode()
        df = parse_index_tri(raw, "NIFTY 50 TR")
        assert df["tri_value"].iloc[0] == D("155.500000")

    def test_close_only_is_parse_error_never_price_as_tri(self) -> None:
        # THE guard (quant-researcher CRITICAL): a price-table row with CLOSE but no genuine TR
        # field must FAIL LOUD, never silently emit price CLOSE as the benchmark TRI (ADR-008/028).
        raw = json.dumps(
            [
                {
                    "HistoricalDate": "01 Jan 2026",
                    "OPEN": "100",
                    "HIGH": "1",
                    "LOW": "1",
                    "CLOSE": "100",
                }
            ]
        ).encode()
        with pytest.raises(ParseError, match="no TRI level field"):
            parse_index_tri(raw, "NIFTY 50 TR")

    def test_binary_float_value_rejected(self) -> None:
        # Money-is-Decimal (doc 23): a JSON number level must not route through a binary float
        raw = json.dumps([{"HistoricalDate": "01 Jan 2026", "TotalReturnsIndex": 155.5}]).encode()
        with pytest.raises(ParseError, match="binary float"):
            parse_index_tri(raw, "NIFTY 50 TR")

    def test_over_precise_value_rejected(self) -> None:
        raw = json.dumps(
            [{"HistoricalDate": "01 Jan 2026", "TotalReturnsIndex": "1.0000005"}]
        ).encode()
        with pytest.raises(ParseError, match="6 decimal places"):
            parse_index_tri(raw, "NIFTY 50 TR")

    def test_missing_date_field_raises(self) -> None:
        raw = json.dumps([{"CLOSE": "100"}]).encode()
        with pytest.raises(ParseError, match="HistoricalDate"):
            parse_index_tri(raw, "NIFTY 50 TR")

    def test_no_value_field_raises_naming_keys(self) -> None:
        raw = json.dumps([{"HistoricalDate": "01 Jan 2026", "OPEN": "100"}]).encode()
        with pytest.raises(ParseError, match="no TRI level field"):
            parse_index_tri(raw, "NIFTY 50 TR")

    def test_bad_date_raises(self) -> None:
        raw = index_tri_bytes([("32 Xxx 2026", "100")])
        with pytest.raises(ParseError, match="date"):
            parse_index_tri(raw, "NIFTY 50 TR")

    def test_bad_value_raises(self) -> None:
        raw = index_tri_bytes([("01 Jan 2026", "not-a-number")])
        with pytest.raises(ParseError, match="bad TRI value"):
            parse_index_tri(raw, "NIFTY 50 TR")

    def test_non_array_payload_raises(self) -> None:
        with pytest.raises(ParseError, match="expected a JSON array"):
            parse_index_tri(json.dumps({"unexpected": 1}).encode(), "NIFTY 50 TR")

    def test_non_json_raises(self) -> None:
        with pytest.raises(ParseError, match="not valid JSON"):
            parse_index_tri(b"<!DOCTYPE html>", "NIFTY 50 TR")
