"""P0-08 suite: calendar from presence — session taxonomy, uniqueness, supersession, config."""

import io
import zipfile
from datetime import date, datetime
from pathlib import Path

import pytest

from quant.config import Settings, load_muhurat_dates
from quant.curate.calendar import (
    SESSION_MUHURAT,
    SESSION_NORMAL,
    SESSION_SPECIAL,
    build_calendar,
)
from quant.errors import ConfigError
from quant.ingest import RawStore

T = datetime(2026, 7, 10, 19, 30)


def _udiff_zip(ssn_id: str, salt: str = "") -> bytes:
    csv = f"TradDt,TckrSymb,SsnId\n2026-01-01,XX{salt},{ssn_id}\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("BhavCopy_NSE_CM_0_0_0_x.csv", csv)
    return buf.getvalue()


def _classic_zip(salt: str = "") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("cm01JAN2020bhav.csv", f"SYMBOL,SERIES\nXX{salt},EQ\n")
    return buf.getvalue()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # data in tmp; config_dir stays the repo default so the committed calendar.yaml applies
    return Settings(data_dir=tmp_path / "data")


class TestSessionTaxonomy:
    def test_all_five_classifications(self, settings: Settings) -> None:
        store = RawStore(settings)
        store.put("bhavcopy", date(2026, 7, 8), _udiff_zip("F1"), fetched_at=T)  # Wed, F1
        store.put("bhavcopy", date(2026, 11, 10), _udiff_zip("M1"), fetched_at=T)  # Tue, drift
        store.put("bhavcopy", date(2023, 11, 12), _classic_zip(), fetched_at=T)  # Sun, Diwali
        store.put("bhavcopy", date(2024, 1, 20), _classic_zip("b"), fetched_at=T)  # Sat, DR drill
        store.put("bhavcopy", date(2023, 11, 13), _classic_zip("c"), fetched_at=T)  # Mon

        cal = build_calendar(settings)
        by_day = dict(zip(cal["d"], cal["session"], strict=True))
        assert by_day[date(2026, 7, 8)] == SESSION_NORMAL  # weekday, SsnId F1
        assert by_day[date(2026, 11, 10)] == SESSION_SPECIAL  # non-F1 SsnId drift alarm
        assert by_day[date(2023, 11, 12)] == SESSION_MUHURAT  # config-listed Diwali session
        assert by_day[date(2024, 1, 20)] == SESSION_SPECIAL  # weekend but NOT Muhurat
        assert by_day[date(2023, 11, 13)] == SESSION_NORMAL  # classic weekday

    def test_absent_dates_are_absent(self, settings: Settings) -> None:
        store = RawStore(settings)
        store.put("bhavcopy", date(2026, 7, 8), _udiff_zip("F1"), fetched_at=T)
        cal = build_calendar(settings)
        assert len(cal) == 1  # holidays/weekends without files simply do not appear

    def test_dates_unique_and_sorted(self, settings: Settings) -> None:
        store = RawStore(settings)
        for i, d in enumerate((date(2026, 7, 10), date(2026, 7, 8), date(2026, 7, 9))):
            store.put("bhavcopy", d, _udiff_zip("F1", salt=str(i)), fetched_at=T)
        cal = build_calendar(settings)
        assert list(cal["d"]) == sorted(cal["d"])
        assert cal["d"].is_unique

    def test_supersession_yields_single_row_from_latest(self, settings: Settings) -> None:
        store = RawStore(settings)
        d = date(2026, 7, 8)
        store.put("bhavcopy", d, _udiff_zip("F1"), fetched_at=T)
        store.put("bhavcopy", d, _udiff_zip("M1"), fetched_at=datetime(2026, 7, 11, 9, 0))
        cal = build_calendar(settings)
        assert len(cal) == 1
        assert cal["session"].iloc[0] == SESSION_SPECIAL  # the superseding file wins

    def test_empty_store_builds_empty_calendar(self, settings: Settings) -> None:
        cal = build_calendar(settings)
        assert len(cal) == 0


class TestMuhuratConfig:
    def test_committed_config_loads_three_verified_dates(self) -> None:
        dates = load_muhurat_dates()
        assert date(2023, 11, 12) in dates
        assert date(2024, 11, 1) in dates
        assert date(2025, 10, 21) in dates

    def test_missing_key_fails_loudly(self, tmp_path: Path) -> None:
        (tmp_path / "calendar.yaml").write_text("something_else: []\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="muhurat_dates"):
            load_muhurat_dates(Settings(config_dir=tmp_path))

    def test_non_date_entries_fail_loudly(self, tmp_path: Path) -> None:
        (tmp_path / "calendar.yaml").write_text('muhurat_dates: ["diwali"]\n', encoding="utf-8")
        with pytest.raises(ConfigError, match="list of ISO dates"):
            load_muhurat_dates(Settings(config_dir=tmp_path))
