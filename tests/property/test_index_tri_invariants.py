"""P0-15 property invariants: TR parser value-preservation + gap-check bounds (hypothesis)."""

from datetime import date
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from conftest import index_tri_bytes
from quant.curate.index_tri import _gap_stats
from quant.curate.parsers.index_tri import parse_index_tri
from quant.ingest.index_tri import _MONTHS_ABBR

_DATES = st.dates(min_value=date(2015, 1, 1), max_value=date(2026, 12, 31))
_VALUES = st.decimals(
    min_value=Decimal("0.000001"), max_value=Decimal("999999.999999"), places=6,
    allow_nan=False, allow_infinity=False,
)  # fmt: skip


def _fmt(d: date) -> str:
    return f"{d.day:02d} {_MONTHS_ABBR[d.month - 1]} {d.year}"


@given(rows=st.lists(st.tuples(_DATES, _VALUES), max_size=25))
def test_parser_preserves_dates_and_values_in_order(rows: list[tuple[date, Decimal]]) -> None:
    raw = index_tri_bytes([(_fmt(d), str(v)) for d, v in rows])
    df = parse_index_tri(raw, "NIFTY 50 TR")
    assert list(df["d"]) == [d for d, _ in rows]
    assert list(df["tri_value"]) == [v for _, v in rows]  # DECIMAL(18,6) exact, no float drift


@given(data=st.data())
def test_gap_stats_are_bounded_and_extraneous_free_when_present_subset_of_calendar(
    data: st.DataObject,
) -> None:
    cal = sorted(data.draw(st.lists(_DATES, unique=True, min_size=1, max_size=30)))
    present = data.draw(st.lists(st.sampled_from(cal), unique=True))
    g = _gap_stats(present, cal)
    # a run of missing sessions can never exceed the total missing, itself bounded by the calendar
    assert 0 <= g["gap_days_max"] <= g["missing_sessions"] <= len(cal)
    assert g["extraneous_dates"] == 0  # every present date was drawn from the calendar


@given(data=st.data())
def test_non_session_date_within_overlap_is_extraneous(data: st.DataObject) -> None:
    # extraneous is counted only WITHIN the overlapping span (ADR-028); non-session dates strictly
    # between the calendar's min and max, added to the full calendar (so the overlap spans them),
    # are the only extraneous ones — out-of-coverage leading/trailing TR dates never count.
    cal = sorted(data.draw(st.lists(_DATES, unique=True, min_size=2, max_size=30)))
    interior = sorted(
        {
            d
            for d in data.draw(st.lists(_DATES, unique=True))
            if cal[0] < d < cal[-1] and d not in cal
        }
    )
    if not interior:
        return  # no genuine interior non-session date drawn this example
    g = _gap_stats(cal + interior, cal)  # tri ⊇ cal so missing=0; interior intruders are extraneous
    assert g["missing_sessions"] == 0
    assert g["extraneous_dates"] == len(interior)
