"""Format-epoch bhavcopy parsers: raw zip bytes → validated arrow-backed frame (doc 06 §6.2).

Dispatch is by EXACT header signature against an explicit allowlist — an unknown signature is
a ParseError (the new-epoch alarm), never a guess (doc 09 P0-05 parser plan). Every row parses
faithfully with its series retained: ADR-006's structural EQ-only exclusion lives in universe
candidates (doc 21 §4), not here — filtering at parse would sever EQ→BE→EQ price history.
Money is Decimal from the first parse and lands as decimal128(p,s) (ADR-021); every failure
raises ParseError with a row number.
"""

import csv
import io
import zipfile
from datetime import date
from decimal import Decimal, InvalidOperation

import pandas as pd
import pyarrow as pa

from quant.curate.parsers.common import parse_dmy_date
from quant.errors import ParseError
from quant.schemas import DATE, I64, STR, Contract, dec, field

CLASSIC_11 = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,"
CLASSIC_13 = CLASSIC_11 + "TOTALTRADES,ISIN,"
UDIFF_34 = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
    "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,"
    "LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,"
    "TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4"
)

_UDIFF_IDX = {name: i for i, name in enumerate(UDIFF_34.split(","))}
_UDIFF_INVARIANTS = {"Sgmt": "CM", "Src": "NSE", "FinInstrmTp": "STK"}


class ParsedBhavcopy(Contract):
    """Parser→curation interface contract (NOT a doc-10 table; outside TABLES governance)."""

    trade_date: pd.ArrowDtype = field(DATE, nullable=False)
    symbol: pd.ArrowDtype = field(STR, nullable=False)
    series: pd.ArrowDtype = field(STR, nullable=True)
    isin: pd.ArrowDtype = field(STR, nullable=True)  # None for the whole classic-11 era
    open: pd.ArrowDtype = field(dec(12, 2), nullable=True)
    high: pd.ArrowDtype = field(dec(12, 2), nullable=True)
    low: pd.ArrowDtype = field(dec(12, 2), nullable=True)
    close: pd.ArrowDtype = field(dec(12, 2), nullable=True)
    last: pd.ArrowDtype = field(dec(12, 2), nullable=True)
    prev_close: pd.ArrowDtype = field(dec(12, 2), nullable=True)
    volume: pd.ArrowDtype = field(I64, nullable=True)
    traded_value: pd.ArrowDtype = field(dec(18, 2), nullable=True)
    total_trades: pd.ArrowDtype = field(I64, nullable=True)  # absent in classic-11
    security_name: pd.ArrowDtype = field(STR, nullable=True)  # UDiFF FinInstrmNm; classic: None


_COLUMNS = [
    "trade_date",
    "symbol",
    "series",
    "isin",
    "open",
    "high",
    "low",
    "close",
    "last",
    "prev_close",
    "volume",
    "traded_value",
    "total_trades",
    "security_name",
]
_ARROW_TYPES = {
    "trade_date": DATE,
    "symbol": STR,
    "series": STR,
    "isin": STR,
    "open": dec(12, 2),
    "high": dec(12, 2),
    "low": dec(12, 2),
    "close": dec(12, 2),
    "last": dec(12, 2),
    "prev_close": dec(12, 2),
    "volume": I64,
    "traded_value": dec(18, 2),
    "total_trades": I64,
    "security_name": STR,
}


def parse_bhavcopy(zip_bytes: bytes) -> pd.DataFrame:
    """Parse one raw bhavcopy zip into the validated ParsedBhavcopy frame."""
    lines = _extract_csv_lines(zip_bytes)
    header = lines[0]
    if header == CLASSIC_11:
        rows = _parse_classic(lines[1:], has_isin=False)
    elif header == CLASSIC_13:
        rows = _parse_classic(lines[1:], has_isin=True)
    elif header == UDIFF_34:
        rows = _parse_udiff(lines[1:])
    else:
        raise ParseError(
            f"unknown bhavcopy header signature: {header[:100]!r} — known epochs: "
            "classic-11, classic-13, udiff-34 (doc 09 P0-05 epoch map); a new NSE format "
            "needs a new versioned parser, never a guess"
        )
    return _to_frame(rows)


def _extract_csv_lines(zip_bytes: bytes) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            members = zf.namelist()
            if len(members) != 1:
                raise ParseError(f"bhavcopy zip must have exactly one member, got {members}")
            text = zf.read(members[0]).decode("utf-8")
    except zipfile.BadZipFile as exc:
        raise ParseError(f"corrupt bhavcopy zip: {exc}") from exc
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ParseError("bhavcopy csv is empty")
    return lines


def _parse_classic(data_lines: list[str], *, has_isin: bool) -> dict[str, list[object]]:
    expected = 14 if has_isin else 12  # includes the trailing empty field
    cols: dict[str, list[object]] = {name: [] for name in _COLUMNS}
    for rownum, row in enumerate(csv.reader(data_lines), start=2):
        if len(row) != expected:
            raise ParseError(f"classic row {rownum}: expected {expected} fields, got {len(row)}")
        cols["symbol"].append(_req(row[0], "SYMBOL", rownum))
        cols["series"].append(row[1] or None)
        cols["open"].append(_decimal(row[2], rownum))
        cols["high"].append(_decimal(row[3], rownum))
        cols["low"].append(_decimal(row[4], rownum))
        cols["close"].append(_decimal(row[5], rownum))
        cols["last"].append(_decimal(row[6], rownum))
        cols["prev_close"].append(_decimal(row[7], rownum))
        cols["volume"].append(_integer(row[8], rownum))
        cols["traded_value"].append(_decimal(row[9], rownum))
        cols["trade_date"].append(parse_dmy_date(row[10], rownum))
        cols["total_trades"].append(_integer(row[11], rownum) if has_isin else None)
        cols["isin"].append((row[12] or None) if has_isin else None)
        cols["security_name"].append(None)  # classic epochs carry no instrument name
    return cols


def _parse_udiff(data_lines: list[str]) -> dict[str, list[object]]:
    idx = _UDIFF_IDX
    cols: dict[str, list[object]] = {name: [] for name in _COLUMNS}
    for rownum, row in enumerate(csv.reader(data_lines), start=2):
        if len(row) != 34:
            raise ParseError(f"udiff row {rownum}: expected 34 fields, got {len(row)}")
        for col, expected_value in _UDIFF_INVARIANTS.items():
            if row[idx[col]] != expected_value:
                raise ParseError(
                    f"udiff row {rownum}: {col}={row[idx[col]]!r}, expected "
                    f"{expected_value!r} — possible new epoch, refusing to guess"
                )
        cols["trade_date"].append(_iso_date(row[idx["TradDt"]], rownum))
        cols["symbol"].append(_req(row[idx["TckrSymb"]], "TckrSymb", rownum))
        cols["series"].append(row[idx["SctySrs"]] or None)
        cols["isin"].append(row[idx["ISIN"]] or None)
        cols["open"].append(_decimal(row[idx["OpnPric"]], rownum))
        cols["high"].append(_decimal(row[idx["HghPric"]], rownum))
        cols["low"].append(_decimal(row[idx["LwPric"]], rownum))
        cols["close"].append(_decimal(row[idx["ClsPric"]], rownum))
        cols["last"].append(_decimal(row[idx["LastPric"]], rownum))
        cols["prev_close"].append(_decimal(row[idx["PrvsClsgPric"]], rownum))
        cols["volume"].append(_integer(row[idx["TtlTradgVol"]], rownum))
        cols["traded_value"].append(_decimal(row[idx["TtlTrfVal"]], rownum))
        cols["total_trades"].append(_integer(row[idx["TtlNbOfTxsExctd"]], rownum))
        cols["security_name"].append(row[idx["FinInstrmNm"]] or None)
    return cols


def _to_frame(cols: dict[str, list[object]]) -> pd.DataFrame:
    try:
        table = pa.table({name: pa.array(cols[name], type=_ARROW_TYPES[name]) for name in _COLUMNS})
    except (pa.ArrowInvalid, pa.ArrowTypeError) as exc:
        raise ParseError(f"parsed values violate the column types: {exc}") from exc
    frame = table.to_pandas(types_mapper=pd.ArrowDtype)
    return ParsedBhavcopy.validate(frame, lazy=True)


def _req(value: str, name: str, rownum: int) -> str:
    if not value:
        raise ParseError(f"row {rownum}: required field {name} is empty")
    return value


def _decimal(value: str, rownum: int) -> Decimal | None:
    if not value.strip():
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ParseError(f"row {rownum}: bad decimal {value!r}") from exc


def _integer(value: str, rownum: int) -> int | None:
    if not value.strip():
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ParseError(f"row {rownum}: bad integer {value!r}") from exc


def _iso_date(value: str, rownum: int) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ParseError(f"row {rownum}: bad ISO date {value!r}") from exc
