"""P0-15 unit: index_tri gap-check semantics + the build_index_tri assembly over a raw vault."""

from datetime import date
from decimal import Decimal as D
from pathlib import Path

from conftest import calendar_frame, index_tri_bytes
from quant.config import Settings
from quant.curate.index_tri import _gap_stats, build_index_tri
from quant.ingest import RawStore

JAN = [date(2026, 1, d) for d in (1, 2, 5, 6, 7, 8, 9)]  # a 7-session mock calendar (Mon-Fri x2)


def _store(tmp_path: Path) -> tuple[RawStore, Settings]:
    s = Settings(data_dir=tmp_path / "data")
    return RawStore(s), s


class TestGapStats:
    def test_full_coverage_is_all_zero(self) -> None:
        assert _gap_stats(JAN, JAN) == {
            "missing_sessions": 0,
            "gap_days_max": 0,
            "extraneous_dates": 0,
        }

    def test_single_missing_session_is_gap_one(self) -> None:
        tri = [d for d in JAN if d != date(2026, 1, 6)]
        g = _gap_stats(tri, JAN)
        assert g["missing_sessions"] == 1 and g["gap_days_max"] == 1

    def test_consecutive_missing_run_is_counted(self) -> None:
        tri = [d for d in JAN if d not in (date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8))]
        assert _gap_stats(tri, JAN)["gap_days_max"] == 3

    def test_extraneous_non_session_date_flagged(self) -> None:
        # 2026-01-04 is a Sunday: present in TRI, absent from the calendar -> real drift
        assert _gap_stats([date(2026, 1, 4), *JAN], JAN)["extraneous_dates"] == 1

    def test_only_overlap_counts_missing_not_trailing_calendar(self) -> None:
        # TRI covers only the first three sessions; sessions after its last date are NOT "missing"
        tri = JAN[:3]
        assert _gap_stats(tri, JAN)["missing_sessions"] == 0

    def test_empty_tri_is_all_zero(self) -> None:
        assert _gap_stats([], JAN) == {
            "missing_sessions": 0,
            "gap_days_max": 0,
            "extraneous_dates": 0,
        }


class TestBuildIndexTri:
    def test_empty_vault_publishes_zero_rows(self, tmp_path: Path) -> None:
        _, s = _store(tmp_path)
        result = build_index_tri(calendar_frame(JAN), date(2026, 6, 30), s)
        assert len(result.frame) == 0
        assert result.stats["rows"] == 0
        assert result.stats["nifty50_tri_rows"] == 0

    def test_both_series_load_and_sort(self, tmp_path: Path) -> None:
        store, s = _store(tmp_path)
        store.put(
            "nifty50_tri",
            date(2026, 1, 9),
            index_tri_bytes([("09 Jan 2026", "38000.5"), ("08 Jan 2026", "37900.25")]),
            suffix=".json",
        )
        store.put(
            "midcap150_tri",
            date(2026, 1, 9),
            index_tri_bytes([("09 Jan 2026", "21000.75")]),
            suffix=".json",
        )
        result = build_index_tri(calendar_frame(JAN), date(2026, 6, 30), s)
        assert result.stats["rows"] == 3
        assert set(result.frame["index_name"]) == {"NIFTY 50 TR", "NIFTY MIDCAP 150 TR"}
        # deterministic order: (index_name, d) ascending -- "NIFTY 50 TR" < "NIFTY MIDCAP 150 TR"
        assert list(result.frame["index_name"]) == [
            "NIFTY 50 TR",
            "NIFTY 50 TR",
            "NIFTY MIDCAP 150 TR",
        ]
        n50 = result.frame[result.frame["index_name"] == "NIFTY 50 TR"]
        assert list(n50["tri_value"]) == [D("37900.250000"), D("38000.500000")]

    def test_gap_against_calendar_is_reported(self, tmp_path: Path) -> None:
        store, s = _store(tmp_path)
        # TRI present for all sessions EXCEPT 2026-01-06 (a planted hole in the covered span)
        rows = [(f"{d.day:02d} Jan 2026", "100") for d in JAN if d != date(2026, 1, 6)]
        store.put("nifty50_tri", date(2026, 1, 9), index_tri_bytes(rows), suffix=".json")
        result = build_index_tri(calendar_frame(JAN), date(2026, 6, 30), s)
        assert result.stats["nifty50_tri_missing_sessions"] == 1
        assert result.stats["nifty50_tri_gap_days_max"] == 1
        assert result.stats["gap_days_max"] == 1

    def test_asof_excludes_future_chunks(self, tmp_path: Path) -> None:
        store, s = _store(tmp_path)
        store.put(
            "nifty50_tri", date(2026, 1, 9), index_tri_bytes([("09 Jan 2026", "1")]), suffix=".json"
        )
        result = build_index_tri(calendar_frame(JAN), date(2026, 1, 5), s)  # asof before the chunk
        assert result.stats["rows"] == 0

    def test_conflicting_overlapping_values_quarantine_not_abort(self, tmp_path: Path) -> None:
        store, s = _store(tmp_path)
        # two chunks (different end dates) disagree on the SAME (index, day) -> drift. The offending
        # series is QUARANTINED (published empty + conflict stat), NOT aborting the whole rebuild
        # (ADR-028: a benchmark glitch must never take down the money path). The other series is
        # unaffected.
        store.put(
            "nifty50_tri",
            date(2026, 1, 8),
            index_tri_bytes([("08 Jan 2026", "100")]),
            suffix=".json",
        )
        store.put(
            "nifty50_tri",
            date(2026, 1, 9),
            index_tri_bytes([("08 Jan 2026", "999")]),
            suffix=".json",
        )
        store.put(
            "midcap150_tri",
            date(2026, 1, 9),
            index_tri_bytes([("09 Jan 2026", "21000.0")]),
            suffix=".json",
        )
        result = build_index_tri(calendar_frame(JAN), date(2026, 6, 30), s)  # no exception
        assert result.stats["conflicts"] == 1
        assert result.stats["nifty50_tri_conflict"] == 1
        assert result.stats["nifty50_tri_rows"] == 0  # quarantined to empty
        assert result.stats["midcap150_tri_rows"] == 1  # other series survives
        assert set(result.frame["index_name"]) == {"NIFTY MIDCAP 150 TR"}

    def test_identical_overlapping_values_collapse(self, tmp_path: Path) -> None:
        store, s = _store(tmp_path)
        store.put(
            "nifty50_tri",
            date(2026, 1, 8),
            index_tri_bytes([("08 Jan 2026", "100")]),
            suffix=".json",
        )
        store.put(
            "nifty50_tri",
            date(2026, 1, 9),
            index_tri_bytes([("08 Jan 2026", "100"), ("09 Jan 2026", "101")]),
            suffix=".json",
        )
        result = build_index_tri(calendar_frame(JAN), date(2026, 6, 30), s)
        assert result.stats["rows"] == 2  # 08 collapses, 09 kept
