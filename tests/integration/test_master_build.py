"""P0-09 integration: fixture-raw → RawStore → parse → build_master → rename resolves (DoD).

Exercises the exact operator path over committed-fixture-shaped raw files in a temp store:
two UDiFF bhavcopy zips straddling a rename, plus a symbolchange snapshot that pins the
boundary inside the weekend gap. Asserts the DoD resolution semantics, the PREVCLOSE splice
validator, and the security-name plumbing. No network, ever (doc 16).
"""

import io
import zipfile
from datetime import date
from pathlib import Path

from quant.config import Settings
from quant.curate.master import build_master, resolve_isin
from quant.curate.parsers.bhavcopy import UDIFF_34
from quant.ingest import RawStore

ISIN = "INE000A01001"
E = date(2023, 8, 28)  # Monday; last OLDCO day is Friday 2023-08-25 — a real weekend gap


def _udiff_zip(trade_date: date, symbol: str, name: str, close: str, prev_close: str) -> bytes:
    values = {
        "TradDt": trade_date.isoformat(),
        "BizDt": trade_date.isoformat(),
        "Sgmt": "CM",
        "Src": "NSE",
        "FinInstrmTp": "STK",
        "FinInstrmId": "1001",
        "ISIN": ISIN,
        "TckrSymb": symbol,
        "SctySrs": "EQ",
        "FinInstrmNm": name,
        "OpnPric": close,
        "HghPric": close,
        "LwPric": close,
        "ClsPric": close,
        "LastPric": close,
        "PrvsClsgPric": prev_close,
        "TtlTradgVol": "1000",
        "TtlTrfVal": "100000.00",
        "TtlNbOfTxsExctd": "10",
        "SsnId": "F1",
    }
    row = ",".join(values.get(col, "") for col in UDIFF_34.split(","))
    csv_text = UDIFF_34 + "\n" + row + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"BhavCopy_NSE_CM_0_0_0_{trade_date.strftime('%Y%m%d')}_F_0000.csv", csv_text)
    return buf.getvalue()


def test_master_build_resolves_known_rename_from_raw_files(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    store = RawStore(settings)
    store.put(
        "bhavcopy",
        date(2023, 8, 25),
        _udiff_zip(date(2023, 8, 25), "OLDCO", "Old Co Ltd", "101.00", "100.00"),
        suffix=".zip",
    )
    store.put(
        "bhavcopy",
        E,
        _udiff_zip(E, "NEWCO", "New Co Ltd", "102.00", "101.00"),
        suffix=".zip",
    )
    store.put(
        "symbolchange",
        date(2023, 8, 28),
        f"New Co Ltd,OLDCO,NEWCO,{E.strftime('%d-%b-%Y').upper()}\n".encode(),
        suffix=".csv",
    )

    result = build_master(settings)
    listing = result.listing

    # The DoD: the known rename resolves correctly across the boundary.
    assert resolve_isin(listing, "OLDCO", "EQ", date(2023, 8, 25)) == ISIN
    assert resolve_isin(listing, "OLDCO", "EQ", date(2023, 8, 27)) == ISIN  # file-pinned gap day
    assert resolve_isin(listing, "NEWCO", "EQ", E) == ISIN
    assert resolve_isin(listing, "OLDCO", "EQ", E) is None
    assert resolve_isin(listing, "NEWCO", "EQ", date(2023, 8, 27)) is None

    # PREVCLOSE splice validator: 101.00 == 101.00 across the boundary.
    assert result.stats["splice_pass"] == 1
    assert result.stats["splice_fail"] == 0
    assert result.stats["file_pinned_boundaries"] == 1

    # Security row: display-only name from the latest UDiFF observation; lifecycle NULL.
    row = result.security.iloc[0]
    assert row["isin"] == ISIN
    assert row["name"] == "New Co Ltd"
