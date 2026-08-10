"""P0-15 integration: mini vault incl. TRI chunks → curate --rebuild → published index_tri.

No network. Proves both benchmark series load through the full pipeline to the paisa-precise
(DECIMAL(18,6)) published table, the gap-check surfaces a planted hole against the calendar, and
the whole rebuild (index_tri included) is byte-identical on repeat (doc 08 determinism).
"""

import io
import json
import zipfile
from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

import quant.curate.build as build_mod
from conftest import index_tri_bytes
from quant.config import Settings
from quant.curate.build import curate_rebuild
from quant.curate.parsers.bhavcopy import UDIFF_34
from quant.curate.publish import read_current
from quant.ingest import RawStore

ISIN = "INE000ITESTA"
DAYS = [date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)]  # Mon/Tue/Wed — three normal sessions
ASOF = date(2026, 6, 30)
FETCHED = datetime(2026, 6, 30, 12, 0, 0)  # frozen so identical rebuilds digest identically

CA_JSON = json.dumps(
    [
        {
            "isin": ISIN, "symbol": "ITEST", "series": "EQ", "exDate": "05-Jan-2026",
            "subject": "Dividend - Rs 1 Per Share", "faceVal": "10", "recDate": "-",
        }
    ]
).encode()  # fmt: skip
SYMBOLCHANGE_CSV = b"Integration Test Co,ITEST,ITEST,01-JAN-2020\n"


def _udiff_zip(d: date, close: str) -> bytes:
    row = [""] * 34
    idx = {name: i for i, name in enumerate(UDIFF_34.split(","))}
    row[idx["TradDt"]] = d.isoformat()
    row[idx["BizDt"]] = d.isoformat()
    row[idx["Sgmt"]], row[idx["Src"]], row[idx["FinInstrmTp"]] = "CM", "NSE", "STK"
    row[idx["ISIN"]], row[idx["TckrSymb"]], row[idx["SctySrs"]] = ISIN, "ITEST", "EQ"
    row[idx["FinInstrmNm"]] = "Integration Test Co"
    for col in ("OpnPric", "HghPric", "LwPric", "ClsPric", "LastPric", "PrvsClsgPric"):
        row[idx[col]] = close
    row[idx["TtlTradgVol"]], row[idx["TtlTrfVal"]], row[idx["TtlNbOfTxsExctd"]] = (
        "1000",
        "100000.00",
        "10",
    )
    row[idx["SsnId"]] = "F1"
    csv_text = UDIFF_34 + "\r\n" + ",".join(row) + "\r\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"BhavCopy_NSE_CM_0_0_0_{d.strftime('%Y%m%d')}_F_0000.csv", csv_text)
    return buf.getvalue()


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    repo_config = Path(__file__).resolve().parents[2] / "config"
    for name in ("calendar.yaml", "liquidity.yaml"):
        (config_dir / name).write_bytes((repo_config / name).read_bytes())
    (config_dir / "ca-resolutions.yaml").write_text("resolutions: []\n")
    s = Settings(data_dir=tmp_path / "data", config_dir=config_dir)
    store = RawStore(s)
    for d, close in zip(DAYS, ["100.00", "101.00", "102.00"], strict=True):
        store.put("bhavcopy", d, _udiff_zip(d, close), suffix=".zip", fetched_at=FETCHED)
    store.put("symbolchange", ASOF, SYMBOLCHANGE_CSV, suffix=".csv", fetched_at=FETCHED)
    store.put("corp_actions", ASOF, CA_JSON, suffix=".json", fetched_at=FETCHED)
    # TRI: nifty50 covers all three sessions; midcap150 is missing 02-Jun (a planted gap).
    store.put(
        "nifty50_tri", date(2026, 6, 3),
        index_tri_bytes(
            [("01 Jun 2026", "38000.50"), ("02 Jun 2026", "38010.75"), ("03 Jun 2026", "38025.00")],
            response_index_name="Nifty 50",
        ),
        suffix=".json", fetched_at=FETCHED,
    )  # fmt: skip
    store.put(
        "midcap150_tri", date(2026, 6, 3),
        index_tri_bytes(
            [("01 Jun 2026", "21000.00"), ("03 Jun 2026", "21050.00")],
            response_index_name="Nifty Midcap 150",
        ),
        suffix=".json", fetched_at=FETCHED,
    )  # fmt: skip
    monkeypatch.setattr(build_mod, "_code_ref", lambda: "test:frozen")
    return s


def test_tri_series_loaded_and_gap_checked(settings: Settings) -> None:
    report = curate_rebuild(ASOF, settings)
    tri = read_current("index_tri", settings)
    assert set(tri["index_name"]) == {"NIFTY 50 TR", "NIFTY MIDCAP 150 TR"}
    n50 = tri[tri["index_name"] == "NIFTY 50 TR"].sort_values("d")
    assert list(n50["tri_value"]) == [D("38000.500000"), D("38010.750000"), D("38025.000000")]
    stats = report.stats["index_tri"]
    assert stats["rows"] == 5
    assert stats["nifty50_tri_missing_sessions"] == 0
    assert stats["midcap150_tri_missing_sessions"] == 1  # the planted 02-Jun hole
    assert stats["midcap150_tri_gap_days_max"] == 1


def test_rebuild_twice_is_byte_identical_with_tri(settings: Settings) -> None:
    first = curate_rebuild(ASOF, settings)
    second = curate_rebuild(ASOF, settings)
    assert second.run_id == first.run_id
    assert second.created is False  # idempotent no-op incl. index_tri
