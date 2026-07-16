"""NSE corporate-actions JSON parser: raw API bytes → validated ParsedCorporateActions frame.

The source (P0-10 probe 2026-07-15, doc 09) is the www corporate-actions JSON API: a bare list
of objects, each carrying isin, symbol, series, exDate (DD-MMM-YYYY), subject (free-text
purpose), faceVal, recDate. This parser is STRUCTURAL only — it decodes and canonicalises,
never classifies. The drift alarm is deliberately narrow: a non-list body or a row missing a
consumed key is a ParseError (a changed envelope is a new epoch, never a guess); but the messy
human-entered `subject` is passed through untouched, because content ambiguity is the
classifier's job to route to needs_review (curate/corp_actions.py), not to crash on. `faceVal`
is carried verbatim but is anachronistic (the current face value, not the value at ex_date —
251/263 splits confirm it equals the POST-split face value); downstream must never derive a
ratio from it. Rows are canonically sorted and exact-deduped so builds are order-independent.
"""

import json
from datetime import date

import pandas as pd
import pyarrow as pa

from quant.curate.parsers.common import parse_dmy_date
from quant.errors import ParseError
from quant.schemas import DATE, STR, Contract, field

# The keys this parser consumes; a missing one is structural drift. NSE may add keys freely.
_REQUIRED_KEYS = ("isin", "symbol", "series", "exDate", "subject", "faceVal", "recDate")
_DASH = "-"

# (isin, symbol, series, ex_date, subject, face_val, rec_date)
_Row = tuple[str | None, str | None, str | None, date | None, str, str | None, date | None]


class ParsedCorporateActions(Contract):
    """Parser→curation interface contract (NOT a doc-10 table; outside TABLES governance)."""

    isin: pd.ArrowDtype = field(STR, nullable=True)
    symbol: pd.ArrowDtype = field(STR, nullable=True)
    series: pd.ArrowDtype = field(STR, nullable=True)
    ex_date: pd.ArrowDtype = field(DATE, nullable=True)
    subject: pd.ArrowDtype = field(STR, nullable=False)
    face_val: pd.ArrowDtype = field(STR, nullable=True)
    rec_date: pd.ArrowDtype = field(DATE, nullable=True)


def _clean(value: object) -> str | None:
    """Trim a scalar string field; NSE's ``-`` placeholder and blanks decode to None."""
    text = str(value).strip() if value is not None else ""
    return text or None if text != _DASH else None


def _opt_date(value: object, rownum: int) -> date | None:
    """Decode a DD-MMM-YYYY field; blank/``-`` → None; a malformed non-blank date is drift."""
    text = _clean(value)
    return None if text is None else parse_dmy_date(text, rownum)


def parse_corp_actions(raw_bytes: bytes) -> pd.DataFrame:
    """Parse one raw corporate-actions JSON payload into the validated, canonical frame."""
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ParseError(f"corp_actions payload is not UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ParseError(f"corp_actions payload is not valid JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise ParseError(
            f"corp_actions payload is a {type(payload).__name__}, expected a JSON list — a changed"
            " envelope is a new format epoch, never a guess"
        )
    records: list[_Row] = []
    for rownum, row in enumerate(payload, start=1):
        if not isinstance(row, dict):
            raise ParseError(
                f"corp_actions row {rownum}: expected an object, got {type(row).__name__}"
            )
        missing = [k for k in _REQUIRED_KEYS if k not in row]
        if missing:
            raise ParseError(
                f"corp_actions row {rownum}: missing key(s) {missing} — a changed record shape is a"
                " new format epoch, never a guess"
            )
        subject = str(row["subject"]).strip()
        if not subject:
            raise ParseError(f"corp_actions row {rownum}: empty subject")
        records.append(
            (
                _clean(row["isin"]),
                _clean(row["symbol"]),
                _clean(row["series"]),
                _opt_date(row["exDate"], rownum),
                subject,
                _clean(row["faceVal"]),
                _opt_date(row["recDate"], rownum),
            )
        )
    # Canonical order + exact dedupe: overlapping fetch windows re-publish identical rows. The
    # key spans ALL fields (None→sentinel) so the order is total — no residual set-iteration
    # dependence when rows tie on the leading fields (determinism, CLAUDE.md / doc 16).
    unique = sorted(
        set(records),
        key=lambda r: (
            r[3] or date.min,  # ex_date
            r[0] or "",  # isin
            r[2] or "",  # series
            r[4],  # subject
            r[1] or "",  # symbol
            r[5] or "",  # face_val
            r[6] or date.min,  # rec_date
        ),
    )
    table = pa.table(
        {
            "isin": pa.array([r[0] for r in unique], STR),
            "symbol": pa.array([r[1] for r in unique], STR),
            "series": pa.array([r[2] for r in unique], STR),
            "ex_date": pa.array([r[3] for r in unique], DATE),
            "subject": pa.array([r[4] for r in unique], STR),
            "face_val": pa.array([r[5] for r in unique], STR),
            "rec_date": pa.array([r[6] for r in unique], DATE),
        }
    )
    frame = table.to_pandas(types_mapper=pd.ArrowDtype)
    return ParsedCorporateActions.validate(frame, lazy=True)
