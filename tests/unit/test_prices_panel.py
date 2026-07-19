"""P0-11 suite: raw price panel — include-list, primary-series pick, classic-11 resolution."""

from datetime import date
from decimal import Decimal as D

import pandas as pd
import pyarrow as pa
import pytest

from conftest import panel_frame
from quant.curate.prices import EQUITY_SERIES_PRIORITY, build_price_panel_frames
from quant.errors import ContractViolation
from quant.schemas import DATE, STR

DAY = date(2025, 1, 2)


def _listing(entries: list[tuple[str, str, str, date | None, date | None]]) -> pd.DataFrame:
    isin, sym, ser, vf, vt = (
        (list(c) for c in zip(*entries, strict=True)) if entries else ([], [], [], [], [])
    )
    table = pa.table(
        {
            "isin": pa.array(isin, STR),
            "exchange": pa.array(["NSE"] * len(isin), STR),
            "symbol": pa.array(sym, STR),
            "series": pa.array(ser, STR),
            "valid_from": pa.array(vf, DATE),
            "valid_to": pa.array(vt, DATE),
        }
    )
    return table.to_pandas(types_mapper=pd.ArrowDtype)


def _rows(*rows):
    return panel_frame(list(rows))


class TestIncludeList:
    def test_bond_and_unit_series_are_excluded(self) -> None:
        frame = _rows(
            (DAY, "X", "EQ", "INE000TESTA1", D("10.00"), 1),
            (DAY, "Y", "N6", "INE000BONDN6", D("99.00"), 1),
            (DAY, "Z", "GS", "IN0000000GS1", D("98.00"), 1),
            (DAY, "W", "IV", "INE000UNITI1", D("97.00"), 1),
        )
        res = build_price_panel_frames(frame, _listing([]))
        assert list(res.panel["isin"]) == ["INE000TESTA1"]
        assert res.stats["non_primary_series_excluded"] == 3

    def test_auxiliary_window_rows_are_excluded_even_for_equity_isins(self) -> None:
        # BL (block window) coexists with EQ for the same ISIN-day (probed: 1,040 cases).
        frame = _rows(
            (DAY, "X", "EQ", "INE000TESTA1", D("10.00"), 1),
            (DAY, "X", "BL", "INE000TESTA1", D("10.50"), 9),
        )
        res = build_price_panel_frames(frame, _listing([]))
        assert len(res.panel) == 1
        assert res.panel.iloc[0]["series"] == "EQ"

    def test_every_equity_family_series_is_kept(self) -> None:
        frame = _rows(
            *[
                (DAY, f"S{i}", s, f"INE000TES{i}A1", D("10.00"), 1)
                for i, s in enumerate(EQUITY_SERIES_PRIORITY)
            ]
        )
        res = build_price_panel_frames(frame, _listing([]))
        assert len(res.panel) == len(EQUITY_SERIES_PRIORITY)


class TestPrimarySeries:
    def test_priority_collapse_prefers_eq(self) -> None:
        frame = _rows(
            (DAY, "X", "BE", "INE000TESTA1", D("9.00"), 1),
            (DAY, "X", "EQ", "INE000TESTA1", D("10.00"), 1),
        )
        res = build_price_panel_frames(frame, _listing([]))
        assert len(res.panel) == 1
        assert res.panel.iloc[0]["series"] == "EQ"
        assert res.stats["lower_priority_series_collapsed"] == 1

    def test_duplicate_same_series_rows_are_drift(self) -> None:
        frame = _rows(
            (DAY, "X", "EQ", "INE000TESTA1", D("10.00"), 1),
            (DAY, "X", "EQ", "INE000TESTA1", D("11.00"), 2),
        )
        with pytest.raises(ContractViolation, match="duplicate bhavcopy rows"):
            build_price_panel_frames(frame, _listing([]))

    def test_pk_is_unique_after_selection(self) -> None:
        frame = _rows(
            (DAY, "X", "EQ", "INE000TESTA1", D("10.00"), 1),
            (DAY, "X", "BE", "INE000TESTA1", D("9.00"), 1),
            (date(2025, 1, 3), "X", "BE", "INE000TESTA1", D("9.50"), 1),
        )
        res = build_price_panel_frames(frame, _listing([]))
        assert not res.panel.duplicated(subset=["isin", "trade_date"]).any()
        assert len(res.panel) == 2  # EQ day + BE-only day (series transitions survive, P0-07)


class TestClassic11Resolution:
    def test_isin_less_row_resolves_via_listing(self) -> None:
        frame = panel_frame([(DAY, "OLDCO", "EQ", None, D("10.00"), 1)])
        listing = _listing([("INE000TESTA1", "OLDCO", "EQ", None, None)])
        res = build_price_panel_frames(frame, listing)
        assert list(res.panel["isin"]) == ["INE000TESTA1"]

    def test_unresolvable_row_is_excluded_and_counted_never_guessed(self) -> None:
        frame = panel_frame([(DAY, "GHOST", "EQ", None, D("10.00"), 1)])
        res = build_price_panel_frames(frame, _listing([]))
        assert len(res.panel) == 0
        assert res.stats["unresolvable_no_isin_excluded"] == 1

    def test_conservation_balances(self) -> None:
        frame = _rows(
            (DAY, "X", "EQ", "INE000TESTA1", D("10.00"), 1),
            (DAY, "X", "BL", "INE000TESTA1", D("10.50"), 9),
            (DAY, "Y", "N6", "INE000BONDN6", D("99.00"), 1),
        )
        res = build_price_panel_frames(frame, _listing([]))
        s = res.stats
        assert s["input_rows"] == (
            s["kept"]
            + s["non_primary_series_excluded"]
            + s["unresolvable_no_isin_excluded"]
            + s["lower_priority_series_collapsed"]
        )
