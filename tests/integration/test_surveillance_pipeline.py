"""P0-14 integration: real ASM/GSM snapshots -> curate_rebuild -> published universe_membership,
demonstrating the doc-20 DoD literally -- "list-add flips investability next build" -- AND its
necessary complement, list-*removal* flips it back (the correctness gap this task fixed in the
P0-13-shipped `_surveillance_flags`). No network; RawStore.put mirrors how a real `ingest asm`/
`ingest gsm` run would land raw bytes (the CLI transport layer itself is separately smoke-tested).

Ten trading sessions give three build cycles room to move: build 1 (asof session 3) sees no
surveillance data for GOOD; build 2 (asof session 6, after an ASM-flagging snapshot lands)
excludes it; build 3 (asof session 9, after a removal snapshot lands) un-excludes it again.
"""

import io
import json
import zipfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from quant.config import Settings
from quant.curate.build import curate_rebuild
from quant.curate.parsers.bhavcopy import UDIFF_34
from quant.curate.publish import read_current
from quant.ingest import RawStore

GOOD = "INE0000GOOD1"
DAYS = [date(2026, 6, d) for d in range(1, 11)]  # ten consecutive sessions
LIQUIDITY_YAML = (
    "window_trading_days: 3\nprice_floor_rupees: 20\nmin_age_trading_days: 1\n"
    "max_zero_days_pct: 0.5\nmdtv_floor_rupees: 1\np_max: 0.01\n"
)
SYMBOLCHANGE_CSV = b"Good Co,GOOD,GOOD,01-JAN-2020\n"
# A far-past dividend (auto) pins the CA coverage floor below the June price window.
CA_JSON = json.dumps(
    [
        {
            "isin": GOOD,
            "symbol": "GOOD",
            "series": "EQ",
            "exDate": "05-Jan-2026",
            "subject": "Dividend - Rs 1 Per Share",
            "faceVal": "10",
            "recDate": "-",
        }
    ]
).encode()


def _udiff_zip(d: date) -> bytes:
    idx = {name: i for i, name in enumerate(UDIFF_34.split(","))}
    row = [""] * 34
    row[idx["TradDt"]] = d.isoformat()
    row[idx["BizDt"]] = d.isoformat()
    row[idx["Sgmt"]] = "CM"
    row[idx["Src"]] = "NSE"
    row[idx["FinInstrmTp"]] = "STK"
    row[idx["ISIN"]] = GOOD
    row[idx["TckrSymb"]] = "GOOD"
    row[idx["SctySrs"]] = "EQ"
    row[idx["FinInstrmNm"]] = "Good Co"
    for col in ("OpnPric", "HghPric", "LwPric", "ClsPric", "LastPric", "PrvsClsgPric"):
        row[idx[col]] = "500.00"
    row[idx["TtlTradgVol"]] = "100000"
    row[idx["TtlTrfVal"]] = "50000000.00"
    row[idx["TtlNbOfTxsExctd"]] = "10"
    row[idx["SsnId"]] = "F1"
    csv_text = UDIFF_34 + "\r\n" + ",".join(row) + "\r\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"BhavCopy_NSE_CM_0_0_0_{d.strftime('%Y%m%d')}_F_0000.csv", csv_text)
    return buf.getvalue()


def _asm_bytes(entries: list[tuple[str, str]]) -> bytes:
    rows = [
        {
            "asmSurvIndicator": stage,
            "asmTime": "01-Jan-2026",
            "companyName": "Good Co",
            "isin": isin,
            "series": None,
            "survCode": "x",
            "survDesc": "x",
            "symbol": "GOOD",
            "srno": i,
        }
        for i, (isin, stage) in enumerate(entries, start=1)
    ]
    return json.dumps({"columns": [], "longterm": {"data": rows}}).encode()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    repo_config = Path(__file__).resolve().parents[2] / "config"
    (config_dir / "calendar.yaml").write_bytes((repo_config / "calendar.yaml").read_bytes())
    (config_dir / "ca-resolutions.yaml").write_text("resolutions: []\n")
    (config_dir / "liquidity.yaml").write_text(LIQUIDITY_YAML)
    s = Settings(data_dir=tmp_path / "data", config_dir=config_dir)
    store = RawStore(s)
    fetched = datetime(2026, 6, 30, 12, 0, 0)
    for d in DAYS:
        store.put("bhavcopy", d, _udiff_zip(d), suffix=".zip", fetched_at=fetched)
    store.put("symbolchange", DAYS[-1], SYMBOLCHANGE_CSV, suffix=".csv", fetched_at=fetched)
    store.put("corp_actions", DAYS[-1], CA_JSON, suffix=".json", fetched_at=fetched)
    return s


def _universe_row(settings: Settings, d: date):
    frame = read_current("universe_membership", settings)
    match = frame[(frame["isin"] == GOOD) & (frame["d"] == d)]
    assert len(match) == 1, f"expected exactly one row for {GOOD} on {d}"
    return match.iloc[0]


def test_list_add_flips_investability_next_build(settings: Settings) -> None:
    store = RawStore(settings)

    # Build 1: no surveillance data ingested at all yet -- clean, undetermined (no coverage).
    store.put("asm", DAYS[0], _asm_bytes([]), suffix=".json")
    store.put("gsm", DAYS[0], json.dumps({"columns": [], "data": []}).encode(), suffix=".json")
    curate_rebuild(DAYS[2], settings)
    row1 = _universe_row(settings, DAYS[2])
    assert "surveillance" not in row1["excl_reasons"]

    # Build 2: a NEW asm.json snapshot lands, flagging GOOD at Stage III -- the DoD's core claim.
    store.put("asm", DAYS[3], _asm_bytes([(GOOD, "Stage III")]), suffix=".json")
    store.put("gsm", DAYS[3], json.dumps({"columns": [], "data": []}).encode(), suffix=".json")
    curate_rebuild(DAYS[5], settings)
    row2 = _universe_row(settings, DAYS[5])
    assert "surveillance" in row2["excl_reasons"]
    assert row2["surveillance"] == "ASM_3"
    assert row2["investable"] is False

    # Build 3: the NEXT asm.json snapshot (ingested up to the rebuild date, matching a realistic
    # nightly cadence) no longer lists GOOD -- removal must flip it back. This is the necessary
    # complement the DoD's literal wording doesn't spell out but requires for the mechanism to
    # be trustworthy (the P0-13 `_surveillance_flags` bug this task fixed).
    store.put("asm", DAYS[8], _asm_bytes([]), suffix=".json")
    store.put("gsm", DAYS[8], json.dumps({"columns": [], "data": []}).encode(), suffix=".json")
    curate_rebuild(DAYS[8], settings)
    row3 = _universe_row(settings, DAYS[8])
    assert "surveillance" not in row3["excl_reasons"]
    assert row3["investable"] is True  # bounded (coverage now extends to DAYS[8]) and clean -> True


def test_real_vault_no_surveillance_ingest_is_a_noop(settings: Settings) -> None:
    # No asm/gsm raw data at all -- confirms curate_rebuild's surveillance wiring is a strict
    # no-op when nothing has ever been ingested (closes the CRITICAL finding both the PM and
    # risk-manager plan reviews caught: build_surveillance's empty state must never trip
    # build_universe's tri-state logic into anything other than the pre-P0-14 NULL behaviour).
    report = curate_rebuild(DAYS[2], settings)
    assert report.stats["surveillance"]["asm_snapshots"] == 0
    assert report.stats["surveillance"]["gsm_snapshots"] == 0
    row = _universe_row(settings, DAYS[2])
    assert row["excl_reasons"] == []  # otherwise clean (permissive liquidity config)
    assert row["surveillance"] == "UNVERIFIED"
    assert pd.isna(row["investable"])  # undetermined, never wrongly True
