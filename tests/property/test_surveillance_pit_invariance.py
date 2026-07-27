"""P0-14 PIT asof-invariance for `build_surveillance`, mirroring
tests/property/test_universe_pit_invariance.py's shape: truncating the raw vault to artifacts
with logical_date <= T1 must reproduce, for every snapshot <= T1, exactly the same event rows
a full-vault run produces. No `asof` parameter exists on `build_surveillance` by design (it
mirrors `build_corp_actions`'s unconditional-scan shape) -- PIT safety instead comes from
`RawStore.latest_per_date` only ever returning artifacts that actually exist, so "truncate the
vault" and "truncate what's been ingested so far" are the same operation; this property proves
that operation is safe.
"""

import json
from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from quant.config import Settings
from quant.curate.surveillance import build_surveillance
from quant.ingest import RawStore

ISINS = ["INE00000PITA", "INE00000PITB", "INE00000PITC"]
BASE = date(2025, 1, 1)


def _asm_bytes(state: dict) -> bytes:
    rows = [
        {
            "asmSurvIndicator": f"Stage {['I', 'II', 'III', 'IV'][stage]}",
            "asmTime": "01-Jan-2025",
            "companyName": isin,
            "isin": isin,
            "series": None,
            "survCode": "x",
            "survDesc": "x",
            "symbol": isin,
            "srno": i,
        }
        for i, (isin, stage) in enumerate(state.items(), start=1)
        if stage > 0  # stage 0 unused for ASM (roman has no zero) -- treated as "absent"
    ]
    return json.dumps({"columns": [], "longterm": {"data": rows}}).encode()


_state = st.dictionaries(
    keys=st.sampled_from(ISINS), values=st.integers(min_value=0, max_value=3), max_size=3
)


@settings(
    # real disk+DuckDB I/O per example -- _cdc_diff itself is already property-tested at
    # pure-function speed (test_surveillance_cdc_diff_property.py); this test proves the I/O
    # ASSEMBLY doesn't leak future data, not the diff algorithm itself.
    deadline=None,
    # max_examples=50 (test-warden review, 2026-07-27): the state space is small and bounded
    # (<=5 snapshots x <=3 isins x 4 stage values), so 50 gives strong coverage without paying
    # hypothesis's full default (100) in real per-example I/O for diminishing returns -- ~13s
    # wall time, verified acceptable for the fast test loop.
    max_examples=50,
)
@given(states=st.lists(_state, min_size=1, max_size=5), cut=st.integers(min_value=0, max_value=4))
def test_truncated_vault_reproduces_identical_events_at_or_before_cut(states, cut) -> None:
    if cut >= len(states):
        cut = len(states) - 1

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp_full, tempfile.TemporaryDirectory() as tmp_trunc:
        s_full = Settings(data_dir=Path(tmp_full) / "data", config_dir=Path(tmp_full) / "config")
        s_trunc = Settings(data_dir=Path(tmp_trunc) / "data", config_dir=Path(tmp_trunc) / "config")
        store_full = RawStore(s_full)
        store_trunc = RawStore(s_trunc)

        dates = [BASE + timedelta(days=7 * i) for i in range(len(states))]
        cut_date = dates[cut]
        for d, state in zip(dates, states, strict=True):
            content = _asm_bytes(state)
            store_full.put("asm", d, content, suffix=".json")
            if d <= cut_date:
                store_trunc.put("asm", d, content, suffix=".json")
            gsm_content = json.dumps({"columns": [], "data": []}).encode()
            store_full.put("gsm", d, gsm_content, suffix=".json")
            if d <= cut_date:
                store_trunc.put("gsm", d, gsm_content, suffix=".json")

        full = build_surveillance(s_full)
        trunc = build_surveillance(s_trunc)

        full_at_or_before_cut = full.frame[full.frame["available_at"] <= cut_date]
        full_keyed = {
            (r.isin, r.available_at, r.category): r.stage
            for r in full_at_or_before_cut.itertuples()
        }
        trunc_keyed = {
            (r.isin, r.available_at, r.category): r.stage for r in trunc.frame.itertuples()
        }
        assert trunc_keyed == full_keyed
