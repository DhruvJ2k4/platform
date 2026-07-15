"""NSE symbol-change snapshot parser: raw CSV bytes → validated ParsedSymbolChange frame.

The live file (probed 2026-07-15, doc 09) has NO header row — every line is a data row of
exactly (company_name, old_symbol, new_symbol, applicable_from DD-MMM-YYYY). With no header
signature to allowlist, the new-epoch alarm is strict per-row shape validation: any row that
deviates in field count, empty symbol, or date format is a ParseError, never a guess. Rows
are kept faithfully — including NSE's self-rename artifacts (old==new; the master builder
drops those as policy) — then canonically sorted and exact-deduped so downstream builds are
order-independent (doc 08 determinism).
"""

import csv

import pandas as pd
import pyarrow as pa

from quant.curate.parsers.common import parse_dmy_date
from quant.errors import ParseError
from quant.schemas import DATE, STR, Contract, field

_FIELD_COUNT = 4


class ParsedSymbolChange(Contract):
    """Parser→curation interface contract (NOT a doc-10 table; outside TABLES governance)."""

    company_name: pd.ArrowDtype = field(STR, nullable=True)
    old_symbol: pd.ArrowDtype = field(STR, nullable=False)
    new_symbol: pd.ArrowDtype = field(STR, nullable=False)
    applicable_from: pd.ArrowDtype = field(DATE, nullable=False)


def parse_symbolchange(raw_bytes: bytes) -> pd.DataFrame:
    """Parse one raw symbolchange CSV into the validated, canonically ordered frame."""
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError(f"symbolchange file is not UTF-8: {exc}") from exc
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ParseError("symbolchange csv is empty")
    records = []
    for rownum, row in enumerate(csv.reader(lines), start=1):
        if len(row) != _FIELD_COUNT:
            raise ParseError(
                f"symbolchange row {rownum}: expected {_FIELD_COUNT} fields "
                f"(company, old, new, DD-MMM-YYYY), got {len(row)} — a changed layout is a "
                "new format epoch, never a guess"
            )
        company = row[0].strip()
        old_symbol = row[1].strip()
        new_symbol = row[2].strip()
        if not old_symbol or not new_symbol:
            raise ParseError(f"symbolchange row {rownum}: empty symbol field")
        applicable_from = parse_dmy_date(row[3], rownum)
        records.append((company or None, old_symbol, new_symbol, applicable_from))
    # Canonical order + exact dedupe: the file is unsorted and snapshots may re-publish rows.
    unique = sorted(set(records), key=lambda r: (r[3], r[1], r[2], r[0] or ""))
    table = pa.table(
        {
            "company_name": pa.array([r[0] for r in unique], STR),
            "old_symbol": pa.array([r[1] for r in unique], STR),
            "new_symbol": pa.array([r[2] for r in unique], STR),
            "applicable_from": pa.array([r[3] for r in unique], DATE),
        }
    )
    frame = table.to_pandas(types_mapper=pd.ArrowDtype)
    return ParsedSymbolChange.validate(frame, lazy=True)
