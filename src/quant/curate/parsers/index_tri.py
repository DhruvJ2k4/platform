"""niftyindices TRI JSON parser: raw response bytes -> validated ParsedIndexTri frame (P0-15).

STRUCTURAL only -- decodes and canonicalises one index's daily TR levels, never gap-checks or
publishes (that is curate/index_tri.py, the build module; mirrors parsers/surveillance.py's split).

The raw response is the niftyindices historical index table: a JSON array of row objects (confirmed
price-endpoint shape, probe 2026-08-09 -- `{"INDEX_NAME","HistoricalDate":"DD Mon YYYY","OPEN",
"HIGH","LOW","CLOSE"}`). Some page-methods wrap the array as `{"d": "<json string>"}`, so both
envelopes are accepted. The daily TR LEVEL is read ONLY from a genuine TR field (`_VALUE_KEYS`).
`CLOSE` is DELIBERATELY NOT accepted: in that price-table shape CLOSE is the PRICE close, and
silently reading it as the TR level would inflate the benchmark by ~dividend yield -- a
return-magnitude honesty defect ADR-008/ADR-028 forbid, and one the doc-21 §14 ≥0.995 correlation
gate cannot catch (price/TR DAILY returns correlate ~0.9999; they diverge only by slow reinvestment
drift). A row with no TR field is a loud ParseError naming its keys -- the P0-09 reconcile-on-first-
real-data pattern: the day the live TR endpoint (currently walled, ops/journal.md 2026-08-10) is
reachable, its actual value-field is confirmed and added to `_VALUE_KEYS` in ONE spot, never guessed
here. Values must be JSON strings/ints (never binary floats -- Money-is-Decimal, doc 23) at <=6dp
(DECIMAL(18,6)); a float or an over-precise value raises. `d` comes from `HistoricalDate`; the
`index_name` argument tags every row (the response's own INDEX_NAME is informational, not the key).
"""

import json
from decimal import Decimal, InvalidOperation

import pandas as pd
import pyarrow as pa

from quant.curate.parsers.common import parse_dmy_date
from quant.errors import ParseError
from quant.schemas import DATE, STR, Contract, dec, field

# Daily TR level: ONLY genuine total-return fields. CLOSE is intentionally excluded -- in the
# niftyindices price-table shape CLOSE is the PRICE close, and admitting it would let a price
# response masquerade as TRI (ADR-008/028). An unknown-but-real TR field fails loud (see docstring).
_VALUE_KEYS = ("TotalReturnsIndex", "total_returns_index")
_DATE_KEY = "HistoricalDate"
_TRI_QUANTUM = Decimal("0.000001")  # index_tri.tri_value is DECIMAL(18,6)


class ParsedIndexTri(Contract):
    """Parser->curation interface contract (NOT a doc-10 table; outside TABLES governance)."""

    index_name: pd.ArrowDtype = field(STR, nullable=False)
    d: pd.ArrowDtype = field(DATE, nullable=False)
    tri_value: pd.ArrowDtype = field(dec(18, 6), nullable=True)


def _rows_from(content: bytes) -> list[dict[str, object]]:
    """Decode the response to a list of row dicts, unwrapping the `{"d": ...}` envelope if used."""
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParseError(f"index_tri: response is not valid JSON: {exc}") from exc
    if isinstance(payload, dict) and "d" in payload:
        inner = payload["d"]
        payload = json.loads(inner) if isinstance(inner, str) else inner
    if not isinstance(payload, list):
        raise ParseError(f"index_tri: expected a JSON array of rows, got {type(payload).__name__}")
    if any(not isinstance(row, dict) for row in payload):
        raise ParseError("index_tri: every response row must be a JSON object")
    return payload


def _tri_value(row: dict[str, object], rownum: int) -> Decimal | None:
    for key in _VALUE_KEYS:
        raw = row.get(key)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            continue
        if isinstance(raw, float):  # Money-is-Decimal (doc 23): never route a level through a float
            raise ParseError(
                f"row {rownum}: TRI level for {key!r} arrived as a binary float {raw!r}; "
                "niftyindices emits strings -- refusing to float-convert a money-adjacent value"
            )
        try:
            value = Decimal(str(raw))
        except InvalidOperation as exc:
            raise ParseError(f"row {rownum}: bad TRI value {raw!r} for key {key!r}") from exc
        if value.as_tuple().exponent < -6:  # >6dp would be silently rounded into DECIMAL(18,6)
            raise ParseError(
                f"row {rownum}: TRI value {raw!r} has >6 decimal places (DECIMAL(18,6))"
            )
        return value.quantize(_TRI_QUANTUM)  # lossless upscale to 6dp (source is 2dp today)
    raise ParseError(
        f"row {rownum}: no TRI level field; expected one of {_VALUE_KEYS}, got keys {sorted(row)}"
    )


def parse_index_tri(content: bytes, index_name: str) -> pd.DataFrame:
    """Parse one index's raw niftyindices TR response into validated (index_name, d, tri_value)."""
    rows = _rows_from(content)
    dates: list[object] = []
    values: list[Decimal | None] = []
    for i, row in enumerate(rows, start=1):
        raw_date = row.get(_DATE_KEY)
        if not isinstance(raw_date, str) or not raw_date.strip():
            raise ParseError(f"row {i}: missing {_DATE_KEY!r}")
        dates.append(parse_dmy_date(raw_date.replace(" ", "-"), i))
        values.append(_tri_value(row, i))
    table = pa.table(
        {
            "index_name": pa.array([index_name] * len(rows), STR),
            "d": pa.array(dates, DATE),
            "tri_value": pa.array(values, dec(18, 6)),
        }
    )
    frame: pd.DataFrame = ParsedIndexTri.validate(
        table.to_pandas(types_mapper=pd.ArrowDtype), lazy=True
    )
    return frame
