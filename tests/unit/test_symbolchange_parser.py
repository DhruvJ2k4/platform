"""P0-09 suite: symbolchange snapshot parser — headerless shape validation as the drift alarm.

The live file (probed 2026-07-15) has no header row; every line must be exactly
(company, old, new, DD-MMM-YYYY). Any deviation is a ParseError, never a guess.
"""

from datetime import date
from pathlib import Path

import pytest

from quant.curate.parsers.symbolchange import parse_symbolchange
from quant.errors import ParseError

FIXTURE = Path(__file__).parent.parent / "fixtures" / "symbolchange" / "symbolchange-trimmed.csv"


class TestRealFixture:
    def test_fixture_parses_exactly(self) -> None:
        frame = parse_symbolchange(FIXTURE.read_bytes())
        assert len(frame) == 9
        assert list(frame.columns) == [
            "company_name",
            "old_symbol",
            "new_symbol",
            "applicable_from",
        ]
        adani = frame[frame["old_symbol"] == "ADANITRANS"].iloc[0]
        assert adani["new_symbol"] == "ADANIENSOL"
        assert adani["applicable_from"] == date(2023, 8, 24)
        assert adani["company_name"] == "Adani Energy Solutions Limited"

    def test_canonical_order_is_by_date_then_symbols(self) -> None:
        frame = parse_symbolchange(FIXTURE.read_bytes())
        keys = list(
            zip(frame["applicable_from"], frame["old_symbol"], frame["new_symbol"], strict=True)
        )
        assert keys == sorted(keys)

    def test_self_rename_rows_are_kept_faithfully(self) -> None:
        # NSE publishes X→X artifact rows; the parser keeps them (policy lives in the builder).
        frame = parse_symbolchange(FIXTURE.read_bytes())
        selfies = frame[frame["old_symbol"] == frame["new_symbol"]]
        assert list(selfies["new_symbol"]) == ["QUALITY30"]


class TestShapeAlarm:
    def test_wrong_field_count_is_refused(self) -> None:
        with pytest.raises(ParseError, match="expected 4 fields"):
            parse_symbolchange(b"Some Co,OLD,NEW,01-JAN-2020,EXTRA\n")

    def test_three_fields_is_refused(self) -> None:
        with pytest.raises(ParseError, match="expected 4 fields"):
            parse_symbolchange(b"OLD,NEW,01-JAN-2020\n")

    def test_bad_date_is_refused(self) -> None:
        with pytest.raises(ParseError, match="bad DD-MMM-YYYY date"):
            parse_symbolchange(b"Some Co,OLD,NEW,2020-01-01\n")

    def test_empty_symbol_is_refused(self) -> None:
        with pytest.raises(ParseError, match="empty symbol"):
            parse_symbolchange(b"Some Co,,NEW,01-JAN-2020\n")

    def test_empty_file_is_refused(self) -> None:
        with pytest.raises(ParseError, match="empty"):
            parse_symbolchange(b"\n\n")

    def test_non_utf8_is_refused(self) -> None:
        with pytest.raises(ParseError, match="not UTF-8"):
            parse_symbolchange(b"Some Co,OLD,NEW,01-JAN-2020\n\xff\xfe")


class TestCanonicalisation:
    def test_exact_duplicates_collapse_to_one_row(self) -> None:
        line = b"Some Co,OLD,NEW,01-JAN-2020\n"
        frame = parse_symbolchange(line + line)
        assert len(frame) == 1

    def test_whitespace_is_stripped(self) -> None:
        frame = parse_symbolchange(b" Some Co , OLD , NEW , 01-JAN-2020 \n")
        row = frame.iloc[0]
        assert row["company_name"] == "Some Co"
        assert row["old_symbol"] == "OLD"
        assert row["new_symbol"] == "NEW"
        assert row["applicable_from"] == date(2020, 1, 1)
