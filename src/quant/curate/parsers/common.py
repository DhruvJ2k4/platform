"""Shared parser primitives for NSE raw-file formats.

NSE serves dates as DD-MMM-YYYY with English month abbreviations across otherwise unrelated
files (classic bhavcopy TIMESTAMP, symbolchange applicable-from). parse_dmy_date() decodes
them with an explicit month map — never locale-dependent %b — and raises ParseError with the
offending row number, matching the doc-23 taxonomy.
"""

from datetime import date

from quant.errors import ParseError

MONTHS_DMY = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def parse_dmy_date(value: str, rownum: int) -> date:
    """Decode DD-MMM-YYYY (English month names) or raise ParseError naming the row."""
    try:
        day, mon, year = value.strip().split("-")
        return date(int(year), MONTHS_DMY[mon.upper()], int(day))
    except (ValueError, KeyError) as exc:
        raise ParseError(f"row {rownum}: bad DD-MMM-YYYY date {value!r}") from exc
