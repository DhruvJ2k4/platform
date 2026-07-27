"""P0-14 `build_surveillance` coverage floor/ceiling: max()/min() correctness under ASYMMETRIC
ASM vs GSM ingestion history -- the scenario a red-green proof found no other test exercised
(the all-empty real-vault case and the PIT property test's synchronized-date snapshots both
short-circuit before min() vs max() ever diverges). A `min()` here would let dates where only
ONE of the two lists was ever actually verified wrongly count as "fully surveillance checked" --
exactly the over-claiming failure this mechanism exists to prevent, moved up one level.
"""

import json
from datetime import date

from quant.config import Settings
from quant.curate.surveillance import build_surveillance
from quant.ingest import RawStore

EARLY, MID, LATE, LATEST = (
    date(2026, 1, 1),
    date(2026, 1, 8),
    date(2026, 1, 15),
    date(2026, 1, 22),
)
_EMPTY_ASM = json.dumps({"columns": [], "longterm": {"data": []}}).encode()
_EMPTY_GSM = json.dumps({"columns": [], "data": []}).encode()


def test_floor_is_max_not_min_under_asymmetric_coverage(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # ASM ingested from EARLY; GSM only starts at LATE -- floor must be the LATER (max) date,
    # since GSM genuinely has zero coverage before LATE, regardless of ASM's longer history.
    s = Settings(data_dir=tmp_path / "data", config_dir=tmp_path / "config")
    store = RawStore(s)
    store.put("asm", EARLY, _EMPTY_ASM, suffix=".json")
    store.put("asm", MID, _EMPTY_ASM, suffix=".json")
    store.put("gsm", LATE, _EMPTY_GSM, suffix=".json")

    result = build_surveillance(s)
    assert result.coverage_floor == LATE  # max(EARLY, LATE) == LATE, never EARLY


def test_ceiling_is_min_not_max_under_asymmetric_coverage(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # ASM ingested through LATEST; GSM's last ingest is only MID -- ceiling must be the EARLIER
    # (min) date, since GSM hasn't been re-verified past MID even though ASM has fresher data.
    s = Settings(data_dir=tmp_path / "data", config_dir=tmp_path / "config")
    store = RawStore(s)
    store.put("asm", EARLY, _EMPTY_ASM, suffix=".json")
    store.put("asm", LATEST, _EMPTY_ASM, suffix=".json")
    store.put("gsm", EARLY, _EMPTY_GSM, suffix=".json")
    store.put("gsm", MID, _EMPTY_GSM, suffix=".json")

    result = build_surveillance(s)
    assert result.coverage_ceiling == MID  # min(LATEST, MID) == MID, never LATEST


def test_one_category_entirely_unsourced_yields_no_coverage_at_all(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # ASM has real history; GSM has NEVER been ingested -- floor/ceiling must be None (not a
    # fallback to ASM's own bounds), since GSM has literally never been checked.
    s = Settings(data_dir=tmp_path / "data", config_dir=tmp_path / "config")
    store = RawStore(s)
    store.put("asm", EARLY, _EMPTY_ASM, suffix=".json")
    store.put("asm", LATEST, _EMPTY_ASM, suffix=".json")

    result = build_surveillance(s)
    assert result.coverage_floor is None
    assert result.coverage_ceiling is None


def test_available_at_is_ingestion_day_never_the_payloads_self_reported_date(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # PIT ANCHOR regression guard (quant-researcher review, 2026-07-27): the row's own
    # asmTime/gsmTime must NEVER be used for available_at -- only artifact.logical_date (when
    # the platform actually ingested it). Constructs a snapshot whose payload self-reports a
    # WILDLY different (much earlier) date than the real ingestion day, and proves the emitted
    # event is dated by ingestion, not the payload -- a future edit that swaps the source would
    # fail this test immediately (a textbook look-ahead: back-dating knowledge to a date before
    # it was ever observed).
    s = Settings(data_dir=tmp_path / "data", config_dir=tmp_path / "config")
    store = RawStore(s)
    ingested_on = date(2026, 6, 1)
    payload_claims = date(2020, 1, 1)  # absurdly different from ingested_on -- any mix-up is loud
    asm = json.dumps(
        {
            "columns": [],
            "longterm": {
                "data": [
                    {
                        "asmSurvIndicator": "Stage III",
                        "asmTime": payload_claims.strftime("%d-%b-%Y"),
                        "companyName": "Trap Co",
                        "isin": "INE0000TRAP01",
                        "series": None,
                        "survCode": "x",
                        "survDesc": "x",
                        "symbol": "TRAP",
                        "srno": 1,
                    }
                ]
            },
        }
    ).encode()
    store.put("asm", ingested_on, asm, suffix=".json")

    result = build_surveillance(s)
    asm_events = result.frame[result.frame["category"] == "ASM"]
    assert len(asm_events) == 1
    assert asm_events.iloc[0]["available_at"] == ingested_on
    assert asm_events.iloc[0]["available_at"] != payload_claims
