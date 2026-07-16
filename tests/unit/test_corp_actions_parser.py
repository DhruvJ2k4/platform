"""P0-10 suite: corporate-actions JSON parser — structural drift alarm, faithful passthrough.

The parser decodes and canonicalises only; a non-list body or a row missing a consumed key is a
ParseError (a changed envelope is a new epoch), but the messy `subject` passes through untouched.
"""

from datetime import date
from pathlib import Path

import pytest

from quant.curate.parsers.corp_actions import parse_corp_actions
from quant.errors import ParseError

FIXTURE = Path(__file__).parent.parent / "fixtures" / "corp_actions" / "corp_actions-trimmed.json"

_ROW = (
    '[{"isin":"INE001A01036","symbol":"X","series":"EQ","exDate":"05-Jan-2021",'
    '"subject":"Dividend - Rs 2 Per Share","faceVal":"10","recDate":"06-Jan-2021"}]'
)


class TestRealFixture:
    def test_fixture_parses(self) -> None:
        frame = parse_corp_actions(FIXTURE.read_bytes())
        assert len(frame) == 24
        assert list(frame.columns) == [
            "isin",
            "symbol",
            "series",
            "ex_date",
            "subject",
            "face_val",
            "rec_date",
        ]

    def test_ex_date_decoded_and_dash_becomes_null(self) -> None:
        frame = parse_corp_actions(_ROW.encode())
        row = frame.iloc[0]
        assert row["ex_date"] == date(2021, 1, 5)
        assert row["rec_date"] == date(2021, 1, 6)

    def test_dash_rec_date_is_null(self) -> None:
        payload = _ROW.replace('"recDate":"06-Jan-2021"', '"recDate":"-"')
        frame = parse_corp_actions(payload.encode())
        assert bool(frame["rec_date"].isna().iloc[0])


class TestStructuralAlarm:
    def test_non_json_is_refused(self) -> None:
        with pytest.raises(ParseError, match="not valid JSON"):
            parse_corp_actions(b"<html>block</html>")

    def test_top_level_object_is_refused(self) -> None:
        with pytest.raises(ParseError, match="expected a JSON list"):
            parse_corp_actions(b'{"error": "nope"}')

    def test_missing_consumed_key_is_refused(self) -> None:
        with pytest.raises(ParseError, match="missing key"):
            parse_corp_actions(b'[{"isin":"X","series":"EQ","exDate":"05-Jan-2021","subject":"D"}]')

    def test_empty_subject_is_refused(self) -> None:
        payload = _ROW.replace('"subject":"Dividend - Rs 2 Per Share"', '"subject":"  "')
        with pytest.raises(ParseError, match="empty subject"):
            parse_corp_actions(payload.encode())

    def test_bad_ex_date_is_refused(self) -> None:
        payload = _ROW.replace('"exDate":"05-Jan-2021"', '"exDate":"2021-01-05"')
        with pytest.raises(ParseError, match="bad DD-MMM-YYYY"):
            parse_corp_actions(payload.encode())

    def test_non_utf8_is_refused(self) -> None:
        with pytest.raises(ParseError, match="not UTF-8"):
            parse_corp_actions(b"\xff\xfe[]")

    def test_extra_keys_are_tolerated(self) -> None:
        payload = _ROW.replace('"recDate":"06-Jan-2021"', '"recDate":"06-Jan-2021","newKey":1')
        assert len(parse_corp_actions(payload.encode())) == 1


class TestCanonicalisation:
    def test_exact_duplicates_collapse(self) -> None:
        both = _ROW[:-1] + "," + _ROW[1:]  # two identical objects in one array
        assert len(parse_corp_actions(both.encode())) == 1

    def test_canonical_order_is_stable(self) -> None:
        frame = parse_corp_actions(FIXTURE.read_bytes())
        keys = list(
            zip(frame["ex_date"], frame["isin"], frame["series"], frame["subject"], strict=True)
        )
        assert keys == sorted(keys)
