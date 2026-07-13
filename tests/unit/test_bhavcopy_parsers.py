"""P0-07 suite: one fixture per epoch parses; counts exact; money is Decimal; loud unknowns."""

import io
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

from quant.curate.parsers import ParsedBhavcopy, parse_bhavcopy
from quant.errors import ParseError

FIXTURES = Path(__file__).parent.parent / "fixtures" / "bhavcopy"
CLASSIC_11_FIXTURE = FIXTURES / "cm13JAN2010bhav.csv.zip"
CLASSIC_13_FIXTURE = FIXTURES / "cm16JAN2019bhav.csv.zip"
UDIFF_FIXTURE = FIXTURES / "BhavCopy_NSE_CM_0_0_0_20260708_F_0000.csv.zip"


def _zip_with(member: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(member, text)
    return buf.getvalue()


class TestClassic11:
    def test_fixture_parses_exactly(self) -> None:
        frame = parse_bhavcopy(CLASSIC_11_FIXTURE.read_bytes())
        assert len(frame) == 6
        row = frame[frame["symbol"] == "20MICRONS"].iloc[0]
        assert row["trade_date"] == date(2010, 1, 13)
        assert row["close"] == Decimal("48.55")
        assert row["open"] == Decimal("50.50")
        assert row["volume"] == 23147
        assert row["traded_value"] == Decimal("1128767.35")
        assert frame["isin"].isna().all()  # the whole classic-11 era has no ISIN
        assert frame["total_trades"].isna().all()

    def test_non_eq_series_survives_parsing(self) -> None:
        """Regression lock for the doc-09 refinement: filtering lives in universe, not here."""
        frame = parse_bhavcopy(CLASSIC_11_FIXTURE.read_bytes())
        assert "BE" in set(frame["series"])


class TestClassic13:
    def test_fixture_parses_exactly(self) -> None:
        frame = parse_bhavcopy(CLASSIC_13_FIXTURE.read_bytes())
        assert len(frame) == 6
        row = frame[frame["symbol"] == "20MICRONS"].iloc[0]
        assert row["trade_date"] == date(2019, 1, 16)
        assert row["close"] == Decimal("41.75")
        assert row["total_trades"] == 216
        assert row["isin"] == "INE144J01027"
        assert "BZ" in set(frame["series"])


class TestUdiff:
    def test_fixture_parses_exactly(self) -> None:
        frame = parse_bhavcopy(UDIFF_FIXTURE.read_bytes())
        assert len(frame) == 6
        row = frame[frame["symbol"] == "20MICRONS"].iloc[0]
        assert row["trade_date"] == date(2026, 7, 8)
        assert row["close"] == Decimal("192.33")
        assert row["isin"] == "INE144J01027"
        assert row["volume"] == 194575
        assert "GB" in set(frame["series"])  # gold bond retained; universe excludes it later

    def test_invariant_drift_is_a_new_epoch_alarm(self) -> None:
        with zipfile.ZipFile(io.BytesIO(UDIFF_FIXTURE.read_bytes())) as zf:
            text = zf.read(zf.namelist()[0]).decode()
        drifted = text.replace("CM,NSE,STK", "FO,NSE,STK", 1)
        with pytest.raises(ParseError, match=r"Sgmt='FO'.*new epoch"):
            parse_bhavcopy(_zip_with("BhavCopy_x.csv", drifted))


class TestMoneyDiscipline:
    @pytest.mark.parametrize("fixture", [CLASSIC_11_FIXTURE, CLASSIC_13_FIXTURE, UDIFF_FIXTURE])
    def test_money_columns_are_decimal128(self, fixture: Path) -> None:
        frame = parse_bhavcopy(fixture.read_bytes())
        for col in ("open", "high", "low", "close", "last", "prev_close"):
            assert frame[col].dtype == pd.ArrowDtype(pa.decimal128(12, 2)), col
        assert frame["traded_value"].dtype == pd.ArrowDtype(pa.decimal128(18, 2))
        validated = ParsedBhavcopy.validate(frame, lazy=True)
        assert len(validated) == len(frame)

    def test_sub_paisa_price_rejects_never_rounds(self) -> None:
        """Money-auditor lock: a 3dp price must fail loudly, not silently rescale."""
        hdr = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,"
        row = "X,EQ,48.555,49,48,48.5,48.5,48,100,4850.00,13-JAN-2010,"
        with pytest.raises(ParseError, match="violate the column types"):
            parse_bhavcopy(_zip_with("cm13JAN2010bhav.csv", f"{hdr}\n{row}\n"))

    def test_empty_price_is_none_not_zero(self) -> None:
        hdr = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,"
        row = "X,EQ,,49,48,48.5,48.5,48,100,4850.00,13-JAN-2010,"
        frame = parse_bhavcopy(_zip_with("cm13JAN2010bhav.csv", f"{hdr}\n{row}\n"))
        assert frame["open"].isna().all()
        assert frame["close"].iloc[0] == Decimal("48.50")


class TestLoudFailures:
    def test_unknown_header_is_refused(self) -> None:
        content = _zip_with("weird.csv", "COL_A,COL_B\n1,2\n")
        with pytest.raises(ParseError, match="unknown bhavcopy header signature"):
            parse_bhavcopy(content)

    def test_two_member_zip_refused(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("a.csv", "x")
            zf.writestr("b.csv", "y")
        with pytest.raises(ParseError, match="exactly one member"):
            parse_bhavcopy(buf.getvalue())

    def test_wrong_field_count_names_the_row(self) -> None:
        with zipfile.ZipFile(io.BytesIO(CLASSIC_11_FIXTURE.read_bytes())) as zf:
            text = zf.read(zf.namelist()[0]).decode()
        broken = text.replace("23.5,24.5,22.8", "23.5,24.5", 1)  # drop a field from row 7
        with pytest.raises(ParseError, match="row 7"):
            parse_bhavcopy(_zip_with("cm13JAN2010bhav.csv", broken))

    def test_bad_decimal_names_the_row(self) -> None:
        with zipfile.ZipFile(io.BytesIO(CLASSIC_11_FIXTURE.read_bytes())) as zf:
            text = zf.read(zf.namelist()[0]).decode()
        broken = text.replace("48.55,48.7", "oops,48.7", 1)
        with pytest.raises(ParseError, match="bad decimal 'oops'"):
            parse_bhavcopy(_zip_with("cm13JAN2010bhav.csv", broken))

    def test_corrupt_zip_refused(self) -> None:
        with pytest.raises(ParseError, match="corrupt bhavcopy zip"):
            parse_bhavcopy(b"PK\x03\x04not really a zip")
