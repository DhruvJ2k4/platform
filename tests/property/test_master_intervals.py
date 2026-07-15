"""P0-09 property suite: security-master interval invariants (doc 16; ADR-022).

Hypothesis generates random observation histories (multiple ISINs, multi-era symbol chains,
parallel series, optional in-gap rename rows, pre-observation chain rows, and pure-noise
renames) and asserts the four invariants: (1) every observed (symbol, series, day) resolves
to exactly its own ISIN; (2) no two listing intervals of one (symbol, series) overlap;
(3) the build is deterministic; (4) snapshot-truncation invariance — a build from inputs
truncated at D resolves every observed row dated ≤ D identically to the full-history build
(the time-consistency property: a decision at D sees what a D-time observer would).
"""

from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise

import pandas as pd
import pyarrow as pa
from hypothesis import given, settings
from hypothesis import strategies as st

from quant.curate.master import build_master_frames, resolve_isin
from quant.schemas import DATE, STR, dec

_BASE = date(2018, 1, 1)
_SERIES = ["EQ", "BL"]


def _obs_frame(rows: list[tuple[date, str, str, str]]) -> pd.DataFrame:
    table = pa.table(
        {
            "trade_date": pa.array([r[0] for r in rows], DATE),
            "symbol": pa.array([r[1] for r in rows], STR),
            "series": pa.array([r[2] for r in rows], STR),
            "isin": pa.array([r[3] for r in rows], STR),
            "security_name": pa.array([None] * len(rows), STR),
            "close": pa.array([Decimal("100.00")] * len(rows), dec(12, 2)),
            "prev_close": pa.array([Decimal("100.00")] * len(rows), dec(12, 2)),
        }
    )
    return table.to_pandas(types_mapper=pd.ArrowDtype)


def _chg_frame(rows: list[tuple[str, str, date]]) -> pd.DataFrame:
    table = pa.table(
        {
            "company_name": pa.array([None] * len(rows), STR),
            "old_symbol": pa.array([r[0] for r in rows], STR),
            "new_symbol": pa.array([r[1] for r in rows], STR),
            "applicable_from": pa.array([r[2] for r in rows], DATE),
        }
    )
    return table.to_pandas(types_mapper=pd.ArrowDtype)


History = tuple[pd.DataFrame, pd.DataFrame, list[tuple[date, str, str, str]]]


@st.composite
def _history(draw: st.DrawFn) -> History:
    """One random market history: observations, symbolchange rows, and the observed truth."""
    observations: list[tuple[date, str, str, str]] = []
    changes: list[tuple[str, str, date]] = []
    n_isins = draw(st.integers(min_value=1, max_value=3))
    for i in range(n_isins):
        isin = f"INE{i:03d}X0100{i}"
        n_eras = draw(st.integers(min_value=1, max_value=3))
        cursor = draw(st.integers(min_value=0, max_value=60))
        prev_symbol: str | None = None
        prev_last: date | None = None
        for era in range(n_eras):
            symbol = f"S{i}E{era}"
            n_days = draw(st.integers(min_value=1, max_value=4))
            days: list[date] = []
            for _ in range(n_days):
                days.append(_BASE + timedelta(days=cursor))
                cursor += draw(st.integers(min_value=1, max_value=5))
            for d in days:
                series_set = draw(
                    st.lists(st.sampled_from(_SERIES), min_size=1, max_size=2, unique=True)
                )
                for series in series_set:
                    observations.append((d, symbol, series, isin))
            if prev_symbol is not None and prev_last is not None:
                gap_days = (days[0] - prev_last).days
                if draw(st.booleans()) and gap_days >= 1:
                    offset = draw(st.integers(min_value=1, max_value=gap_days))
                    changes.append((prev_symbol, symbol, prev_last + timedelta(days=offset)))
            prev_symbol, prev_last = symbol, days[-1]
            cursor += draw(st.integers(min_value=1, max_value=5))
        # optional pre-observation chain behind the first era
        first_obs = min(d for d, _, _, s in observations if s == isin)
        if draw(st.booleans()):
            chain_len = draw(st.integers(min_value=1, max_value=2))
            anchor_symbol = f"S{i}E0"
            anchor = first_obs
            for link in range(chain_len):
                back = draw(st.integers(min_value=30, max_value=300))
                e = anchor - timedelta(days=back)
                old = f"P{i}L{link}"
                changes.append((old, anchor_symbol, e))
                anchor_symbol, anchor = old, e - timedelta(days=1)
    # pure-noise renames between symbols nothing ever traded under
    n_noise = draw(st.integers(min_value=0, max_value=3))
    for k in range(n_noise):
        offset = draw(st.integers(min_value=0, max_value=2000))
        changes.append((f"ZZOLD{k}", f"ZZNEW{k}", _BASE + timedelta(days=offset)))
    return _obs_frame(observations), _chg_frame(changes), observations


@given(_history())
@settings(max_examples=60, deadline=None)
def test_every_observed_row_resolves_to_its_own_isin(
    history: History,
) -> None:
    obs, changes, truth = history
    listing = build_master_frames(obs, changes).listing
    for d, symbol, series, isin in truth:
        assert resolve_isin(listing, symbol, series, d) == isin


@given(_history())
@settings(max_examples=60, deadline=None)
def test_no_overlapping_intervals_per_symbol_series(
    history: History,
) -> None:
    obs, changes, _ = history
    listing = build_master_frames(obs, changes).listing
    for (_, _), group in listing.groupby(["symbol", "series"], sort=True):
        spans = [
            (
                row.valid_from if pd.notna(row.valid_from) else date.min,
                row.valid_to if pd.notna(row.valid_to) else date.max,
            )
            for row in group.itertuples(index=False)
        ]
        spans.sort()
        for (_, a_end), (b_start, _) in pairwise(spans):
            assert a_end < b_start, f"overlap in {group.to_string()}"


@given(_history())
@settings(max_examples=30, deadline=None)
def test_rebuild_is_deterministic(
    history: History,
) -> None:
    obs, changes, _ = history
    first = build_master_frames(obs, changes)
    second = build_master_frames(obs.copy(), changes.copy())
    pd.testing.assert_frame_equal(first.listing, second.listing)
    pd.testing.assert_frame_equal(first.security, second.security)
    assert first.stats == second.stats


@given(_history(), st.integers(min_value=0, max_value=500))
@settings(max_examples=60, deadline=None)
def test_snapshot_truncation_invariance(
    history: History,
    cut_offset: int,
) -> None:
    obs, changes, truth = history
    cut = _BASE + timedelta(days=cut_offset)
    full = build_master_frames(obs, changes).listing
    trunc_obs = obs[obs["trade_date"] <= cut]
    if trunc_obs.empty:
        return  # nothing observed by D; nothing for a D-time observer to resolve
    trunc_changes = changes[changes["applicable_from"] <= cut]
    truncated = build_master_frames(trunc_obs, trunc_changes).listing
    for d, symbol, series, isin in truth:
        if d <= cut:
            assert (
                resolve_isin(truncated, symbol, series, d)
                == resolve_isin(full, symbol, series, d)
                == isin
            )
