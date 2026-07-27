"""NSE ASM/GSM JSON parsers: raw snapshot bytes → validated ParsedSurveillance frame (P0-14).

STRUCTURAL only — decodes and canonicalises, never classifies (mirrors parsers/corp_actions.py's
split: stage classification lives in curate/surveillance.py, the build module, not here).

ASM (`asm.json`, probe 2026-07-27) is a combined object: `{"columns": [...], "longterm":
{"data": [...]}, ...}` — a `"shortterm"` key (NSE's real ASM has LT/ST tiers) is expected but was
never actually observed live, so `parse_asm` iterates EVERY top-level key except `"columns"`
generically (each must map to an object with a `"data"` list) rather than hardcoding `"longterm"`
— correct whether or not `"shortterm"` appears. A row's stage lives in `asmSurvIndicator`
("Stage I" etc — a clean structured field, not free text).

GSM (`gsm.json`) — the exact wrapper key for the data array was ambiguous from the live probe
(the user's paste may have concatenated two separate requests, or it is one object like
`{"columns": [...], "data": [...]}`). `parse_gsm` handles BOTH a bare top-level array and an
object with exactly one non-`"columns"` key holding a list; 0 or 2+ such candidates is structural
drift (`ParseError`), never a guess. A row's REAL stage is NOT in `gsmStage` (a trap caught this
session: that field is a Roman-numeral encoding of an unrelated internal sequence number, e.g.
`"LVIII"`=58=the `(58)` in `survCode:"IBC I & GSM 0 (58)"`) — the genuine stage (0-6) is only in
free text within `survDesc`/`survCode`, so both are carried into `raw_stage_text` for the
curate-layer classifier to search.

Every row requires a non-blank `isin` (ParseError otherwise) — the identity key the whole
mechanism keys off; unlike corp_actions' softer nullable-isin structural stance, a surveillance
row with no isin carries no actionable information at all.
"""

import json
from datetime import date

import pandas as pd
import pyarrow as pa

from quant.curate.parsers.common import parse_dmy_date
from quant.errors import ParseError
from quant.schemas import DATE, STR, Contract, field

_ASM_ROW_KEYS = ("isin", "symbol", "companyName", "asmSurvIndicator", "asmTime")
_GSM_ROW_KEYS = ("isin", "symbol", "companyName", "survDesc", "survCode", "gsmTime")
_COLUMNS_KEY = "columns"

# (isin, symbol, company_name, category, raw_stage_text, snapshot_date)
_Row = tuple[str, str | None, str | None, str, str, date | None]


class ParsedSurveillance(Contract):
    """Parser→curation interface contract (NOT a doc-10 table; outside TABLES governance)."""

    isin: pd.ArrowDtype = field(STR, nullable=False)
    symbol: pd.ArrowDtype = field(STR, nullable=True)
    company_name: pd.ArrowDtype = field(STR, nullable=True)
    category: pd.ArrowDtype = field(STR, nullable=False, isin=["ASM", "GSM"])
    raw_stage_text: pd.ArrowDtype = field(STR, nullable=False)
    snapshot_date: pd.ArrowDtype = field(DATE, nullable=True)


def parse_asm(raw_bytes: bytes) -> pd.DataFrame:
    """Parse one raw ASM snapshot into the validated, canonical frame (category='ASM').

    A security appearing in more than one tier group (e.g. both `longterm` and `shortterm`) in
    the same snapshot emits ONE row per group — collision handling (max stage wins) is the
    classifier's job (curate/surveillance.py), not this structural parser's.
    """
    payload = _decode_object(raw_bytes, "asm")
    groups = {k: v for k, v in payload.items() if k != _COLUMNS_KEY}
    if not groups:
        raise ParseError("asm payload has no data groups besides 'columns' — a changed envelope")
    records: list[_Row] = []
    for group_name, group in groups.items():
        if not isinstance(group, dict) or not isinstance(group.get("data"), list):
            raise ParseError(
                f"asm group {group_name!r} is not an object with a 'data' list — a changed"
                " envelope is a new format epoch, never a guess"
            )
        for rownum, row in enumerate(group["data"], start=1):
            records.append(_asm_row(row, group_name, rownum))
    return _to_frame(records)


def parse_gsm(raw_bytes: bytes) -> pd.DataFrame:
    """Parse one raw GSM snapshot into the validated, canonical frame (category='GSM')."""
    try:
        payload = json.loads(_decode_text(raw_bytes, "gsm"))
    except json.JSONDecodeError as exc:
        raise ParseError(f"gsm payload is not valid JSON: {exc}") from exc
    if isinstance(payload, list):
        data = payload
    elif isinstance(payload, dict):
        candidates = {k: v for k, v in payload.items() if k != _COLUMNS_KEY and isinstance(v, list)}
        if len(candidates) != 1:
            raise ParseError(
                f"gsm payload has {len(candidates)} non-'columns' list-valued key(s)"
                f" ({sorted(candidates)}), expected exactly 1 — ambiguous data location,"
                " never a guess"
            )
        data = next(iter(candidates.values()))
    else:
        raise ParseError(f"gsm payload is a {type(payload).__name__}, expected a list or object")
    records = [_gsm_row(row, rownum) for rownum, row in enumerate(data, start=1)]
    return _to_frame(records)


def _decode_text(raw_bytes: bytes, source: str) -> str:
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError(f"{source} payload is not UTF-8: {exc}") from exc


def _decode_object(raw_bytes: bytes, source: str) -> dict:
    try:
        payload = json.loads(_decode_text(raw_bytes, source))
    except json.JSONDecodeError as exc:
        raise ParseError(f"{source} payload is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ParseError(
            f"{source} payload is a {type(payload).__name__}, expected a JSON object — a changed"
            " envelope is a new format epoch, never a guess"
        )
    return payload


def _clean(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _required(row: dict, key: str, source: str, rownum: int) -> str:
    value = _clean(row.get(key))
    if value is None:
        raise ParseError(f"{source} row {rownum}: missing or blank {key!r}")
    return value


def _asm_row(row: object, group_name: str, rownum: int) -> _Row:
    if not isinstance(row, dict):
        raise ParseError(
            f"asm.{group_name} row {rownum}: expected an object, got {type(row).__name__}"
        )
    missing = [k for k in _ASM_ROW_KEYS if k not in row]
    if missing:
        raise ParseError(f"asm.{group_name} row {rownum}: missing key(s) {missing}")
    isin = _required(row, "isin", f"asm.{group_name}", rownum)
    stage_text = _required(row, "asmSurvIndicator", f"asm.{group_name}", rownum)
    snap = _opt_date(row["asmTime"], f"asm.{group_name}", rownum)
    return (isin, _clean(row["symbol"]), _clean(row["companyName"]), "ASM", stage_text, snap)


def _gsm_row(row: object, rownum: int) -> _Row:
    if not isinstance(row, dict):
        raise ParseError(f"gsm row {rownum}: expected an object, got {type(row).__name__}")
    missing = [k for k in _GSM_ROW_KEYS if k not in row]
    if missing:
        raise ParseError(f"gsm row {rownum}: missing key(s) {missing}")
    isin = _required(row, "isin", "gsm", rownum)
    surv_desc = _clean(row["survDesc"]) or ""
    surv_code = _clean(row["survCode"]) or ""
    # Both carried through — the real stage lives in free text across either field (probed
    # 2026-07-27: some rows state it in survDesc's prose, others in survCode's compact form).
    stage_text = f"{surv_desc} {surv_code}".strip()
    if not stage_text:
        raise ParseError(f"gsm row {rownum}: both survDesc and survCode are blank")
    snap = _opt_datetime_date(row["gsmTime"], rownum)
    return (isin, _clean(row["symbol"]), _clean(row["companyName"]), "GSM", stage_text, snap)


def _opt_date(value: object, source: str, rownum: int) -> date | None:
    """Decode a DD-MMM-YYYY field (ASM's asmTime); blank/'-' -> None."""
    text = _clean(value)
    if text is None or text == "-":
        return None
    try:
        return parse_dmy_date(text, rownum)
    except ParseError as exc:
        raise ParseError(f"{source}: {exc}") from exc


def _opt_datetime_date(value: object, rownum: int) -> date | None:
    """Decode GSM's 'DD-MMM-YYYY HH:MM:SS' field, keeping only the date part."""
    text = _clean(value)
    if text is None or text == "-":
        return None
    date_part = text.split(" ", 1)[0]
    try:
        return parse_dmy_date(date_part, rownum)
    except ParseError as exc:
        raise ParseError(f"gsm: {exc}") from exc


def _to_frame(records: list[_Row]) -> pd.DataFrame:
    # Canonical order + exact dedupe, matching parsers/corp_actions.py's determinism discipline.
    unique = sorted(set(records), key=lambda r: (r[0], r[3], r[4], r[1] or "", r[2] or ""))
    table = pa.table(
        {
            "isin": pa.array([r[0] for r in unique], STR),
            "symbol": pa.array([r[1] for r in unique], STR),
            "company_name": pa.array([r[2] for r in unique], STR),
            "category": pa.array([r[3] for r in unique], STR),
            "raw_stage_text": pa.array([r[4] for r in unique], STR),
            "snapshot_date": pa.array([r[5] for r in unique], DATE),
        }
    )
    frame = table.to_pandas(types_mapper=pd.ArrowDtype)
    return ParsedSurveillance.validate(frame, lazy=True)
