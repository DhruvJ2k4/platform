"""P0-14 `_cdc_diff` property: for ANY snapshot sequence, replaying the emitted events against
`_surveillance_flags`-style "latest row <= d wins" reproduces the SAME active state as a naive
full-recompute directly from the snapshots — this is the DoD's actual "flips next build"
guarantee, proven for both add and remove, not just eyeballed on the golden scenario.
"""

from datetime import date, timedelta

from hypothesis import given
from hypothesis import strategies as st

from quant.curate.surveillance import REMOVED, _cdc_diff

ISINS = ["A", "B", "C"]
BASE = date(2025, 1, 1)


def _naive_active_state(
    snapshots: list[tuple[date, dict[str, int]]], query: date
) -> dict[str, int]:
    """Direct truth: the LATEST snapshot at-or-before `query`, verbatim (no event log at all)."""
    applicable = [s for s in snapshots if s[0] <= query]
    if not applicable:
        return {}
    return applicable[-1][1]


def _replay_active_state(events: list[tuple[str, date, int]], query: date) -> dict[str, int]:
    """Reconstruct "active as of query" purely from _cdc_diff's emitted events, mirroring
    _surveillance_flags' own per-isin "latest available_at <= d wins" lookup."""
    latest: dict[str, tuple[date, int]] = {}
    for isin, avail, stage in events:
        if avail > query:
            continue
        if isin not in latest or avail >= latest[isin][0]:
            latest[isin] = (avail, stage)
    return {isin: stage for isin, (avail, stage) in latest.items() if stage != REMOVED}


_snapshot_state = st.dictionaries(
    keys=st.sampled_from(ISINS), values=st.integers(min_value=0, max_value=6), max_size=3
)
_snapshot_seq = st.lists(_snapshot_state, min_size=1, max_size=6)


@given(states=_snapshot_seq)
def test_replay_matches_naive_recompute_at_every_snapshot_boundary(states: list) -> None:
    snapshots = [(BASE + timedelta(days=7 * i), state) for i, state in enumerate(states)]
    events = _cdc_diff(snapshots)
    for query, _ in snapshots:
        assert _replay_active_state(events, query) == _naive_active_state(snapshots, query)


@given(states=_snapshot_seq)
def test_replay_matches_naive_recompute_between_snapshots(states: list) -> None:
    snapshots = [(BASE + timedelta(days=7 * i), state) for i, state in enumerate(states)]
    events = _cdc_diff(snapshots)
    for i in range(len(snapshots)):
        query = snapshots[i][0] + timedelta(days=3)  # a date strictly between snapshots
        assert _replay_active_state(events, query) == _naive_active_state(snapshots, query)


@given(states=_snapshot_seq)
def test_replay_matches_naive_recompute_before_first_snapshot(states: list) -> None:
    snapshots = [(BASE + timedelta(days=7 * i), state) for i, state in enumerate(states)]
    events = _cdc_diff(snapshots)
    query = BASE - timedelta(days=1)
    assert _replay_active_state(events, query) == _naive_active_state(snapshots, query) == {}
