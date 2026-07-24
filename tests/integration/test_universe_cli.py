"""P0-13 integration: mini vault → curate --rebuild → `universe --date` (the DoD path).

No network. A five-session, two-name UDiFF vault proves the whole surface end to end: the
universe is materialised inside the rebuild and published as the 6th table, `universe --date`
reads it as-of in well under a second, emits per-name exclusion reasons + a query-time capacity,
and distinguishes an out-of-coverage date from a present-but-all-excluded one. A permissive
liquidity.yaml lets one name come through clean (undetermined — surveillance unwired) while a
cheap, illiquid name carries multiple reasons.
"""

import io
import json
import time
import zipfile
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

import quant.curate.build as build_mod
from quant.cli import app
from quant.config import Settings
from quant.curate.build import curate_rebuild
from quant.curate.parsers.bhavcopy import UDIFF_34
from quant.ingest import RawStore

GOOD, BADD = "INE0000GOOD1", "INE00000BAD1"
DAYS = [date(2026, 6, d) for d in (1, 2, 3, 4, 5)]
ASOF = date(2026, 6, 30)
# name → (series, close, volume, traded_value)
BOOKS = {
    GOOD: ("EQ", "500.00", 100000, "50000000.00"),  # priced, liquid, seasoned → clean
    BADD: ("EQ", "10.00", 50, "500.00"),  # < ₹20 and tiny MDTV → 2 reasons
}
# Permissive thresholds so a five-session vault can produce a clean name and a multi-reason one.
LIQUIDITY_YAML = (
    "window_trading_days: 3\nprice_floor_rupees: 20\nmin_age_trading_days: 3\n"
    "max_zero_days_pct: 0.5\nmdtv_floor_rupees: 1000000\np_max: 0.01\n"
)
SYMBOLCHANGE_CSV = b"Good Co,GOOD,GOOD,01-JAN-2020\nBad Co,BADD,BADD,01-JAN-2020\n"
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
    lines = [UDIFF_34]
    for isin, (series, close, vol, tv) in BOOKS.items():
        row = [""] * 34
        row[idx["TradDt"]] = d.isoformat()
        row[idx["BizDt"]] = d.isoformat()
        row[idx["Sgmt"]] = "CM"
        row[idx["Src"]] = "NSE"
        row[idx["FinInstrmTp"]] = "STK"
        row[idx["ISIN"]] = isin
        row[idx["TckrSymb"]] = "GOOD" if isin == GOOD else "BADD"
        row[idx["SctySrs"]] = series
        row[idx["FinInstrmNm"]] = "Good Co" if isin == GOOD else "Bad Co"
        for col in ("OpnPric", "HghPric", "LwPric", "ClsPric", "LastPric", "PrvsClsgPric"):
            row[idx[col]] = close
        row[idx["TtlTradgVol"]] = str(vol)
        row[idx["TtlTrfVal"]] = tv
        row[idx["TtlNbOfTxsExctd"]] = "10"
        row[idx["SsnId"]] = "F1"
        lines.append(",".join(row))
    csv_text = "\r\n".join(lines) + "\r\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"BhavCopy_NSE_CM_0_0_0_{d.strftime('%Y%m%d')}_F_0000.csv", csv_text)
    return buf.getvalue()


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    from datetime import datetime

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
    store.put("symbolchange", ASOF, SYMBOLCHANGE_CSV, suffix=".csv", fetched_at=fetched)
    store.put("corp_actions", ASOF, CA_JSON, suffix=".json", fetched_at=fetched)
    monkeypatch.setattr(build_mod, "_code_ref", lambda: "test:frozen")
    monkeypatch.setenv("PLATFORM_DATA_DIR", str(s.data_dir))
    monkeypatch.setenv("PLATFORM_CONFIG_DIR", str(s.config_dir))
    return s


def _run_universe(args: list[str]) -> dict:
    result = CliRunner().invoke(app, ["universe", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.output.strip().splitlines()[-1])


def test_universe_cli_emits_reasons_capacity_and_is_fast(settings: Settings) -> None:
    curate_rebuild(ASOF, settings)
    start = time.perf_counter()
    payload = _run_universe(["--date", "2026-06-05", "--json"])
    assert time.perf_counter() - start < 1.0  # DoD: <1s

    assert payload["out_of_coverage"] is False
    assert payload["candidates"] == 2
    by_isin = {n["isin"]: n for n in payload["names"]}
    # GOOD: clean on every RUN filter → undetermined (surveillance unwired), never True.
    assert by_isin[GOOD]["investable"] is None and by_isin[GOOD]["excl_reasons"] == []
    # BADD: below the price floor AND below the MDTV floor → both reasons, in fixed order.
    assert by_isin[BADD]["investable"] is False
    assert by_isin[BADD]["excl_reasons"] == ["price_below_floor", "ff_mcap_proxy"]
    # capacity is the query-time raw material p_max·MDTV (0.01 x 50,000,000 = 500,000).
    assert by_isin[GOOD]["capacity_pmax_mdtv"] == "500000.0000"
    assert payload["undetermined"] == 1 and payload["excluded"] == 1


def test_universe_cli_out_of_coverage_is_distinct_from_all_excluded(settings: Settings) -> None:
    curate_rebuild(ASOF, settings)
    payload = _run_universe(["--date", "2020-01-01", "--json"])  # no session / out of coverage
    assert payload["out_of_coverage"] is True
    assert payload["candidates"] == 0 and payload["names"] == []


def test_universe_cli_book_flag_is_accepted_with_deferral_note(settings: Settings) -> None:
    curate_rebuild(ASOF, settings)
    result = CliRunner().invoke(app, ["universe", "--date", "2026-06-05", "--book", "core"])
    assert result.exit_code == 0, result.output
    assert "investable(book)" in result.output  # loud base≠book banner (stderr captured together)
