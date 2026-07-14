"""Trading calendar derived from bhavcopy presence (doc 20 P0-08; doc 10 trading_calendar).

A date is a trading day iff a bhavcopy exists for it — presence IS the calendar, never a
scraped holiday list. Session values (defined here, closing doc 10's open note):
"normal" | "special" | "muhurat". Evidence (2026-07-14, 498 UDiFF files): SsnId is F1 on
EVERY file including Diwali Muhurat days, so the data alone cannot identify Muhurat — and
weekend presence also matches NSE's DR-drill and Budget-day sessions. Therefore: muhurat
comes from the operator-maintained config/calendar.yaml (NSE-circular-sourced almanac facts);
any other weekend presence, or a non-F1 SsnId (kept as a drift alarm), classifies "special";
everything else is "normal".
"""

import zipfile
from datetime import date

import pandas as pd
import pyarrow as pa
import structlog

from quant.config import Settings, load_muhurat_dates
from quant.ingest import RawArtifact, RawStore
from quant.schemas import DATE, STR, TradingCalendar

log = structlog.get_logger()

SESSION_NORMAL = "normal"
SESSION_SPECIAL = "special"
SESSION_MUHURAT = "muhurat"
_NORMAL_SSN_ID = "F1"


def build_calendar(settings: Settings | None = None) -> pd.DataFrame:
    """Build the trading_calendar frame from bhavcopy presence; validated by the contract."""
    store = RawStore(settings)
    muhurat_dates = load_muhurat_dates(settings)
    artifacts = store.latest_per_date("bhavcopy")
    days: list[date] = []
    sessions: list[str] = []
    for artifact in artifacts:
        days.append(artifact.logical_date)
        sessions.append(_classify(artifact, muhurat_dates))
    table = pa.table({"d": pa.array(days, DATE), "session": pa.array(sessions, STR)})
    frame = table.to_pandas(types_mapper=pd.ArrowDtype)
    validated = TradingCalendar.validate(frame, lazy=True)
    log.info(
        "calendar_built",
        trading_days=len(validated),
        muhurat_days=int((validated["session"] == SESSION_MUHURAT).sum()),
        special_days=int((validated["session"] == SESSION_SPECIAL).sum()),
    )
    return validated


def _classify(artifact: RawArtifact, muhurat_dates: frozenset[date]) -> str:
    if artifact.logical_date in muhurat_dates:
        return SESSION_MUHURAT
    if artifact.logical_date.weekday() >= 5:
        return SESSION_SPECIAL  # DR drills, Budget-day sessions — real but not Muhurat
    ssn_id = _udiff_session_id(artifact)
    if ssn_id is not None and ssn_id != _NORMAL_SSN_ID:
        log.warning(
            "calendar_nonstandard_ssnid",
            logical_date=str(artifact.logical_date),
            ssn_id=ssn_id,
        )
        return SESSION_SPECIAL
    return SESSION_NORMAL


def _udiff_session_id(artifact: RawArtifact) -> str | None:
    """First data row's SsnId for UDiFF files; None for classic-era files."""
    with zipfile.ZipFile(artifact.path) as zf:
        member = zf.namelist()[0]
        if not member.startswith("BhavCopy_"):
            return None
        with zf.open(member) as fh:
            header = fh.readline().decode("utf-8").strip().split(",")
            first_row = fh.readline().decode("utf-8").strip().split(",")
    if "SsnId" not in header or len(first_row) <= header.index("SsnId"):
        return None
    return first_row[header.index("SsnId")]
