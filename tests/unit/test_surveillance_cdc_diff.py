"""P0-14 `_cdc_diff` unit cases: full-snapshot sequences -> minimal change-only event log.

ASM/GSM lists are FULL DAILY SNAPSHOTS, not event logs -- `_cdc_diff` is the mechanism that
turns "who's on the list today" into "what changed since last time," including detecting
disappearance (removal) as an explicit event, which the P0-13-shipped `_surveillance_flags`
had no way to represent at all.
"""

from datetime import date

from quant.curate.surveillance import REMOVED, _cdc_diff

D1, D2, D3, D4 = date(2026, 1, 1), date(2026, 1, 8), date(2026, 1, 15), date(2026, 1, 22)
A, B = "INE0000000A0", "INE0000000B0"


def test_first_snapshot_emits_add_for_everyone_present() -> None:
    events = _cdc_diff([(D1, {A: 3, B: 1})])
    assert sorted(events) == sorted([(A, D1, 3), (B, D1, 1)])


def test_first_snapshot_empty_emits_nothing() -> None:
    assert _cdc_diff([(D1, {})]) == []


def test_unchanged_isin_emits_no_event_on_later_snapshots() -> None:
    events = _cdc_diff([(D1, {A: 3}), (D2, {A: 3}), (D3, {A: 3})])
    assert events == [(A, D1, 3)]  # only the initial ADD -- no redundant re-emission


def test_stage_change_emits_a_new_event() -> None:
    events = _cdc_diff([(D1, {A: 1}), (D2, {A: 2})])
    assert events == [(A, D1, 1), (A, D2, 2)]


def test_disappearance_emits_removed_sentinel() -> None:
    events = _cdc_diff([(D1, {A: 3}), (D2, {})])
    assert events == [(A, D1, 3), (A, D2, REMOVED)]


def test_readd_after_removal_emits_a_fresh_add() -> None:
    events = _cdc_diff([(D1, {A: 3}), (D2, {}), (D3, {A: 3})])
    assert events == [(A, D1, 3), (A, D2, REMOVED), (A, D3, 3)]


def test_readd_after_removal_with_different_stage_is_still_an_event() -> None:
    events = _cdc_diff([(D1, {A: 3}), (D2, {}), (D3, {A: 1})])
    assert events == [(A, D1, 3), (A, D2, REMOVED), (A, D3, 1)]


def test_multiple_isins_independent_timelines() -> None:
    events = _cdc_diff([(D1, {A: 1}), (D2, {A: 1, B: 5}), (D3, {B: 5}), (D4, {})])
    assert events == [(A, D1, 1), (B, D2, 5), (A, D3, REMOVED), (B, D4, REMOVED)]


def test_empty_snapshot_sequence_emits_nothing() -> None:
    assert _cdc_diff([]) == []


def test_golden_scenario_asm_full_trace() -> None:
    # Matches the P0-14 golden scenario (docstring in tests/golden/test_golden_surveillance.py).
    snapshots = [
        (D1, {"B": 3}),
        (D2, {"B": 3, "A": 1}),
        (D3, {"B": 3, "A": 2, "D": 3}),
        (D4, {"B": 3, "D": 3}),  # A removed
    ]
    events = _cdc_diff(snapshots)
    assert events == [
        ("B", D1, 3),
        ("A", D2, 1),
        ("A", D3, 2),
        ("D", D3, 3),
        ("A", D4, REMOVED),
    ]


def test_golden_scenario_gsm_full_trace() -> None:
    snapshots = [(D1, {}), (D2, {"C": 0}), (D3, {"C": 0, "D": 2}), (D4, {"C": 0, "D": 2})]
    events = _cdc_diff(snapshots)
    assert events == [("C", D2, 0), ("D", D3, 2)]
