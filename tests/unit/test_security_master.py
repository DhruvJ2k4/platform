"""P0-09 suite: security master construction + effective-dated listing resolver (ADR-022).

The DoD test is test_known_rename_resolves_correctly_across_boundary. Policy under test:
observations win; the symbolchange file pins boundaries inside observation gaps and backdates
pre-observation chains; open past = NULL valid_from; identity conflicts raise; misses return
None, never a guess.
"""

from datetime import date
from decimal import Decimal

import pandas as pd
import pyarrow as pa
import pytest

from quant.curate.master import build_master_frames, resolve_isin
from quant.errors import ContractViolation
from quant.schemas import DATE, STR, dec

ISIN_A = "INE000A01001"
ISIN_B = "INE222C01003"

Obs = tuple[date, str, str, str, str | None, Decimal | None, Decimal | None]
Chg = tuple[str | None, str, str, date]


def obs_frame(rows: list[Obs]) -> pd.DataFrame:
    cols = list(zip(*rows, strict=True))
    table = pa.table(
        {
            "trade_date": pa.array(cols[0], DATE),
            "symbol": pa.array(cols[1], STR),
            "series": pa.array(cols[2], STR),
            "isin": pa.array(cols[3], STR),
            "security_name": pa.array(cols[4], STR),
            "close": pa.array(cols[5], dec(12, 2)),
            "prev_close": pa.array(cols[6], dec(12, 2)),
        }
    )
    return table.to_pandas(types_mapper=pd.ArrowDtype)


def chg_frame(rows: list[Chg]) -> pd.DataFrame:
    cols = list(zip(*rows, strict=True))
    table = pa.table(
        {
            "company_name": pa.array(cols[0], STR),
            "old_symbol": pa.array(cols[1], STR),
            "new_symbol": pa.array(cols[2], STR),
            "applicable_from": pa.array(cols[3], DATE),
        }
    )
    return table.to_pandas(types_mapper=pd.ArrowDtype)


def _row(
    d: date,
    symbol: str,
    isin: str = ISIN_A,
    series: str = "EQ",
    name: str | None = None,
    close: str = "100.00",
    prev_close: str = "99.00",
) -> Obs:
    return (d, symbol, series, isin, name, Decimal(close), Decimal(prev_close))


class TestKnownRenameAcrossBoundary:
    """The P0-09 DoD: a known rename resolves correctly across its boundary."""

    # Friday 2023-08-18 and Wednesday 2023-08-23 trade as OLDCO; the file says the rename
    # applies from Thursday 2023-08-24 — exactly the ADANITRANS→ADANIENSOL shape.
    E = date(2023, 8, 24)

    def _build(self) -> pd.DataFrame:
        obs = obs_frame(
            [
                _row(date(2023, 8, 18), "OLDCO"),
                _row(date(2023, 8, 23), "OLDCO", close="101.00"),
                _row(self.E, "NEWCO", prev_close="101.00"),
                _row(date(2023, 8, 25), "NEWCO"),
            ]
        )
        changes = chg_frame([("New Co Ltd", "OLDCO", "NEWCO", self.E)])
        return build_master_frames(obs, changes).listing

    def test_known_rename_resolves_correctly_across_boundary(self) -> None:
        listing = self._build()
        eve = date(2023, 8, 23)  # E - 1
        assert resolve_isin(listing, "OLDCO", "EQ", eve) == ISIN_A
        assert resolve_isin(listing, "NEWCO", "EQ", self.E) == ISIN_A
        assert resolve_isin(listing, "OLDCO", "EQ", self.E) is None
        assert resolve_isin(listing, "NEWCO", "EQ", eve) is None

    def test_boundary_is_file_pinned_not_observation_derived(self) -> None:
        # The gap 2023-08-19..23 has no NEWCO observation; only the file knows E exactly.
        listing = self._build()
        assert resolve_isin(listing, "OLDCO", "EQ", date(2023, 8, 20)) == ISIN_A

    def test_file_pinned_boundary_is_counted(self) -> None:
        obs = obs_frame(
            [
                _row(date(2023, 8, 23), "OLDCO"),
                _row(self.E, "NEWCO", prev_close="100.00"),
            ]
        )
        changes = chg_frame([("New Co Ltd", "OLDCO", "NEWCO", self.E)])
        stats = build_master_frames(obs, changes).stats
        assert stats["file_pinned_boundaries"] == 1
        assert stats["fallback_boundaries"] == 0


class TestFallbackBoundary:
    def test_without_file_row_gap_days_resolve_to_none(self) -> None:
        obs = obs_frame(
            [
                _row(date(2023, 8, 18), "OLDCO"),
                _row(date(2023, 8, 24), "NEWCO"),
            ]
        )
        result = build_master_frames(obs, None)
        listing = result.listing
        assert resolve_isin(listing, "OLDCO", "EQ", date(2023, 8, 18)) == ISIN_A
        assert resolve_isin(listing, "NEWCO", "EQ", date(2023, 8, 24)) == ISIN_A
        # A miss is safer than a guess: nobody owns the unobserved gap.
        assert resolve_isin(listing, "OLDCO", "EQ", date(2023, 8, 21)) is None
        assert resolve_isin(listing, "NEWCO", "EQ", date(2023, 8, 21)) is None
        assert result.stats["fallback_boundaries"] == 1

    def test_file_row_outside_gap_falls_back(self) -> None:
        obs = obs_frame(
            [
                _row(date(2023, 8, 18), "OLDCO"),
                _row(date(2023, 8, 24), "NEWCO"),
            ]
        )
        # File claims the rename applied while OLDCO was still observed trading: contradiction.
        changes = chg_frame([("New Co Ltd", "OLDCO", "NEWCO", date(2023, 8, 10))])
        result = build_master_frames(obs, changes)
        assert result.stats["fallback_boundaries"] == 1
        assert result.stats["file_pinned_boundaries"] == 0


class TestChainBackdating:
    def _build(self) -> tuple[pd.DataFrame, dict[str, int]]:
        obs = obs_frame([_row(date(2023, 8, 24), "CURRENT", name="Current Ltd")])
        changes = chg_frame(
            [
                (None, "MIDDLE", "CURRENT", date(2015, 3, 10)),
                (None, "ANCIENT", "MIDDLE", date(2009, 5, 4)),
            ]
        )
        result = build_master_frames(obs, changes)
        return result.listing, result.stats

    def test_pre_observation_symbols_resolve_through_the_chain(self) -> None:
        listing, stats = self._build()
        assert resolve_isin(listing, "CURRENT", "EQ", date(2023, 8, 24)) == ISIN_A
        assert resolve_isin(listing, "MIDDLE", "EQ", date(2012, 1, 5)) == ISIN_A
        assert resolve_isin(listing, "ANCIENT", "EQ", date(2001, 7, 2)) == ISIN_A
        assert stats["synthetic_eras"] == 2

    def test_chain_boundaries_are_exact_file_facts(self) -> None:
        listing, _ = self._build()
        assert resolve_isin(listing, "MIDDLE", "EQ", date(2015, 3, 9)) == ISIN_A
        assert resolve_isin(listing, "MIDDLE", "EQ", date(2015, 3, 10)) is None
        assert resolve_isin(listing, "CURRENT", "EQ", date(2015, 3, 10)) == ISIN_A
        assert resolve_isin(listing, "ANCIENT", "EQ", date(2009, 5, 4)) is None

    def test_oldest_chain_era_has_open_past(self) -> None:
        listing, stats = self._build()
        ancient = listing[listing["symbol"] == "ANCIENT"]
        assert ancient["valid_from"].isna().all()
        assert stats["chain_stops"] == 0

    def test_self_renames_never_enter_chains(self) -> None:
        obs = obs_frame([_row(date(2023, 8, 24), "CURRENT")])
        changes = chg_frame([(None, "CURRENT", "CURRENT", date(2015, 3, 10))])
        result = build_master_frames(obs, changes)
        assert result.stats["self_renames_dropped"] == 1
        assert result.stats["synthetic_eras"] == 0

    def test_rename_cycle_stops_with_counter_not_forever(self) -> None:
        obs = obs_frame([_row(date(2023, 8, 24), "PING")])
        changes = chg_frame(
            [
                (None, "PONG", "PING", date(2015, 3, 10)),
                (None, "PING", "PONG", date(2010, 2, 1)),
            ]
        )
        result = build_master_frames(obs, changes)
        assert result.stats["chain_stops"] == 1
        assert result.stats["synthetic_eras"] == 1

    def test_chain_tie_refuses_to_pick(self) -> None:
        obs = obs_frame([_row(date(2023, 8, 24), "CURRENT")])
        changes = chg_frame(
            [
                (None, "OLD1", "CURRENT", date(2015, 3, 10)),
                (None, "OLD2", "CURRENT", date(2015, 3, 10)),
            ]
        )
        with pytest.raises(ContractViolation, match="tie"):
            build_master_frames(obs, changes)


class TestSeriesHandling:
    def test_parallel_series_same_day_are_normal(self) -> None:
        # Probe finding (2026-07-15): EQ+BL / EQ+T0 coexist — must NOT be a violation.
        obs = obs_frame(
            [
                _row(date(2024, 8, 7), "TRENT", series="EQ"),
                _row(date(2024, 8, 7), "TRENT", series="BL"),
            ]
        )
        listing = build_master_frames(obs, None).listing
        assert resolve_isin(listing, "TRENT", "EQ", date(2024, 8, 7)) == ISIN_A
        assert resolve_isin(listing, "TRENT", "BL", date(2024, 8, 7)) == ISIN_A

    def test_synthetic_eras_inherit_first_day_series_only(self) -> None:
        obs = obs_frame(
            [
                _row(date(2023, 8, 24), "CURRENT", series="EQ"),
                _row(date(2024, 1, 5), "CURRENT", series="BL"),
            ]
        )
        changes = chg_frame([(None, "FORMER", "CURRENT", date(2015, 3, 10))])
        listing = build_master_frames(obs, changes).listing
        former = listing[listing["symbol"] == "FORMER"]
        assert sorted(former["series"]) == ["EQ"]


class TestIdentityConflicts:
    def test_recycled_symbol_is_clipped_to_evidence(self) -> None:
        obs = obs_frame(
            [
                _row(date(2020, 1, 6), "SYM", isin=ISIN_A),
                _row(date(2021, 6, 30), "SYM", isin=ISIN_A),
                _row(date(2023, 2, 1), "SYM", isin=ISIN_B),
            ]
        )
        result = build_master_frames(obs, None)
        listing = result.listing
        assert resolve_isin(listing, "SYM", "EQ", date(2020, 6, 1)) == ISIN_A
        assert resolve_isin(listing, "SYM", "EQ", date(2024, 1, 1)) == ISIN_B
        assert resolve_isin(listing, "SYM", "EQ", date(2022, 1, 1)) is None
        assert result.stats["recycled_clips"] == 1

    def test_isin_change_clips_the_backdated_claim_to_after_observations(self) -> None:
        # Real shape (live demo 2026-07-15): AARVEEDEN kept its symbol across an ISIN change
        # (INE273D01019 → INE273D01027). The new ISIN's chain-backdated era must start only
        # after the old ISIN's last observation; the old ISIN's open end retreats to evidence.
        obs = obs_frame(
            [
                _row(date(2020, 1, 6), "AARVEE", isin=ISIN_A),
                _row(date(2024, 5, 10), "AARVEE", isin=ISIN_A),
                _row(date(2025, 11, 3), "NEWSYM", isin=ISIN_B),
            ]
        )
        changes = chg_frame([(None, "AARVEE", "NEWSYM", date(2025, 10, 13))])
        result = build_master_frames(obs, changes)
        listing = result.listing
        assert resolve_isin(listing, "AARVEE", "EQ", date(2023, 1, 5)) == ISIN_A
        # ISIN_A keeps its open past; ISIN_B owns only the post-clip window.
        assert resolve_isin(listing, "AARVEE", "EQ", date(2019, 1, 5)) == ISIN_A
        assert resolve_isin(listing, "AARVEE", "EQ", date(2025, 1, 15)) == ISIN_B
        assert resolve_isin(listing, "NEWSYM", "EQ", date(2025, 10, 13)) == ISIN_B
        assert resolve_isin(listing, "AARVEE", "EQ", date(2026, 1, 5)) is None

    def test_rename_coinciding_with_isin_change_double_claim_resolves_honestly(self) -> None:
        # Real shape (live demo 2026-07-15, AARVEEDEN): one file row (AARVEE→NEWSYM, E)
        # creates paper claims from BOTH ISINs for the rename-gap days — the old ISIN's
        # pinned era-end E-1 and the new ISIN's backdated chain start. Neither is
        # observation-backed there; both must retreat to evidence, never raise.
        e = date(2025, 10, 13)
        obs = obs_frame(
            [
                _row(date(2020, 1, 6), "AARVEE", isin=ISIN_A),
                _row(date(2025, 10, 10), "AARVEE", isin=ISIN_A),
                _row(e, "NEWSYM", isin=ISIN_A),  # ISIN switch lags the symbol switch
                _row(date(2025, 10, 20), "NEWSYM", isin=ISIN_B),
            ]
        )
        changes = chg_frame([(None, "AARVEE", "NEWSYM", e)])
        listing = build_master_frames(obs, changes).listing
        assert resolve_isin(listing, "AARVEE", "EQ", date(2025, 10, 10)) == ISIN_A
        assert resolve_isin(listing, "NEWSYM", "EQ", e) == ISIN_A  # observed truth wins
        assert resolve_isin(listing, "NEWSYM", "EQ", date(2025, 10, 20)) == ISIN_B
        # The unobserved switch window is a miss, never a guess.
        assert resolve_isin(listing, "NEWSYM", "EQ", date(2025, 10, 15)) is None

    def test_boundary_pin_consumes_the_record_before_later_chains(self) -> None:
        # Real shape (live demo 2026-07-15, IPAPPM→ANDHRAPAP): the rename is an in-window
        # boundary of the OLD ISIN, and the symbol later moved to a NEW ISIN (ISIN change).
        # The new ISIN's chain must not steal the record and claim the old ISIN's history.
        obs = obs_frame(
            [
                _row(date(2019, 1, 16), "IPAPPM", isin=ISIN_A),
                _row(date(2022, 1, 12), "ANDHRAPAP", isin=ISIN_A),
                _row(date(2024, 9, 10), "ANDHRAPAP", isin=ISIN_A),
                _row(date(2024, 9, 11), "ANDHRAPAP", isin=ISIN_B),
            ]
        )
        changes = chg_frame([(None, "IPAPPM", "ANDHRAPAP", date(2019, 11, 20))])
        result = build_master_frames(obs, changes)
        listing = result.listing
        assert result.stats["file_pinned_boundaries"] == 1
        assert result.stats["chain_stops"] == 1
        assert resolve_isin(listing, "IPAPPM", "EQ", date(2018, 6, 1)) == ISIN_A
        assert resolve_isin(listing, "ANDHRAPAP", "EQ", date(2020, 1, 6)) == ISIN_A  # pinned head
        assert resolve_isin(listing, "ANDHRAPAP", "EQ", date(2023, 6, 1)) == ISIN_A
        assert resolve_isin(listing, "ANDHRAPAP", "EQ", date(2025, 6, 2)) == ISIN_B

    def test_multi_hop_bridge_through_unobserved_intermediate(self) -> None:
        # Real shape (live demo 2026-07-15, IPAPPM→ANDPAPER→ANDHRAPAP): the intermediate
        # symbol was never observed (sparse sample days). The whole in-gap path is exact:
        # it pins both era bounds, creates the intermediate era, and consumes both records
        # so a later ISIN (the 2024 ISIN change) cannot steal the history.
        obs = obs_frame(
            [
                _row(date(2016, 1, 13), "IPAPPM", isin=ISIN_A),
                _row(date(2019, 1, 16), "IPAPPM", isin=ISIN_A),
                _row(date(2022, 1, 12), "ANDHRAPAP", isin=ISIN_A),
                _row(date(2024, 9, 10), "ANDHRAPAP", isin=ISIN_A),
                _row(date(2024, 9, 11), "ANDHRAPAP", isin=ISIN_B),
            ]
        )
        changes = chg_frame(
            [
                (None, "IPAPPM", "ANDPAPER", date(2020, 1, 22)),
                (None, "ANDPAPER", "ANDHRAPAP", date(2020, 3, 5)),
            ]
        )
        result = build_master_frames(obs, changes)
        listing = result.listing
        assert result.stats["file_pinned_boundaries"] == 1
        assert result.stats["synthetic_eras"] == 1  # the bridged ANDPAPER era
        assert resolve_isin(listing, "IPAPPM", "EQ", date(2019, 6, 3)) == ISIN_A
        assert resolve_isin(listing, "ANDPAPER", "EQ", date(2020, 2, 3)) == ISIN_A
        assert resolve_isin(listing, "ANDHRAPAP", "EQ", date(2021, 6, 1)) == ISIN_A
        assert resolve_isin(listing, "ANDHRAPAP", "EQ", date(2023, 6, 1)) == ISIN_A
        assert resolve_isin(listing, "ANDHRAPAP", "EQ", date(2025, 6, 2)) == ISIN_B

    def test_one_rename_record_seeds_only_the_earliest_isin_chain(self) -> None:
        # Real shape (live demo 2026-07-15, ABSHEKINDS→TRIDENT): the new symbol was observed
        # under TWO ISINs across time (an ISIN change), and both chains grabbed the same
        # rename record — two open-past claims to one symbol. The earliest-observed ISIN
        # keeps the pre-history; the later chain stops.
        obs = obs_frame(
            [
                _row(date(2011, 7, 13), "TRIDENT", isin=ISIN_A),
                _row(date(2013, 1, 4), "TRIDENT", isin=ISIN_A),
                _row(date(2016, 1, 13), "TRIDENT", isin=ISIN_B),
            ]
        )
        changes = chg_frame([(None, "ABSHEK", "TRIDENT", date(2011, 5, 3))])
        result = build_master_frames(obs, changes)
        listing = result.listing
        assert result.stats["synthetic_eras"] == 1
        assert result.stats["chain_stops"] == 1
        assert resolve_isin(listing, "ABSHEK", "EQ", date(2010, 1, 13)) == ISIN_A
        assert resolve_isin(listing, "TRIDENT", "EQ", date(2012, 1, 5)) == ISIN_A
        assert resolve_isin(listing, "TRIDENT", "EQ", date(2016, 1, 13)) == ISIN_B

    def test_falsified_backdated_claim_is_dropped(self) -> None:
        # The file says AARVEE moved to NEWSYM in 2025, but ISIN_A is still OBSERVED trading
        # as AARVEE after that: the synthetic claim is falsified by observations and dropped.
        obs = obs_frame(
            [
                _row(date(2020, 1, 6), "AARVEE", isin=ISIN_A),
                _row(date(2026, 5, 22), "AARVEE", isin=ISIN_A),
                _row(date(2025, 11, 3), "NEWSYM", isin=ISIN_B),
            ]
        )
        changes = chg_frame([(None, "AARVEE", "NEWSYM", date(2025, 10, 13))])
        result = build_master_frames(obs, changes)
        assert result.stats["synthetic_dropped"] == 1
        listing = result.listing
        assert resolve_isin(listing, "AARVEE", "EQ", date(2024, 1, 5)) == ISIN_A
        assert resolve_isin(listing, "AARVEE", "EQ", date(2026, 5, 22)) == ISIN_A

    def test_same_day_two_isin_conflict_is_a_violation(self) -> None:
        obs = obs_frame(
            [
                _row(date(2024, 1, 5), "SYM", isin=ISIN_A),
                _row(date(2024, 1, 5), "SYM", isin=ISIN_B),
            ]
        )
        with pytest.raises(ContractViolation, match="overlapping days"):
            build_master_frames(obs, None)

    def test_same_isin_parallel_span_is_evidence_bounded_not_fatal(self) -> None:
        # Real shape (probe 2026-07-15): bond INE148I07ND6 published ONE day as SAMMAANCAP
        # inside its 965IHFL25C span, then moved to 965SCL25C. Same-ISIN overlap is not an
        # identity ambiguity; it must not block the build.
        obs = obs_frame(
            [
                _row(date(2024, 7, 1), "OLDBOND", series="N0"),
                _row(date(2024, 7, 26), "SAMMAANCAP", series="N0"),
                _row(date(2024, 7, 29), "OLDBOND", series="N0"),
                _row(date(2024, 7, 30), "NEWBOND", series="N0"),
            ]
        )
        result = build_master_frames(obs, None)
        listing = result.listing
        assert result.stats["parallel_spans"] == 1
        assert resolve_isin(listing, "OLDBOND", "N0", date(2024, 7, 15)) == ISIN_A
        assert resolve_isin(listing, "SAMMAANCAP", "N0", date(2024, 7, 26)) == ISIN_A
        assert resolve_isin(listing, "NEWBOND", "N0", date(2024, 7, 30)) == ISIN_A
        # The blip is evidence-bounded: it never claims days it was not published on.
        assert resolve_isin(listing, "SAMMAANCAP", "N0", date(2024, 7, 27)) is None

    def test_outliving_overlap_swaps_into_the_chain(self) -> None:
        # A [Jan..Mar], B starts inside A but outlives it: B is the chain, A parallel.
        obs = obs_frame(
            [
                _row(date(2024, 1, 5), "AAA"),
                _row(date(2024, 3, 5), "AAA"),
                _row(date(2024, 2, 1), "BBB"),
                _row(date(2024, 6, 2), "BBB"),
            ]
        )
        result = build_master_frames(obs, None)
        listing = result.listing
        assert result.stats["parallel_spans"] == 1
        assert resolve_isin(listing, "AAA", "EQ", date(2024, 2, 15)) == ISIN_A
        assert resolve_isin(listing, "BBB", "EQ", date(2024, 5, 1)) == ISIN_A
        # AAA is evidence-bounded; BBB carries the open end.
        assert resolve_isin(listing, "AAA", "EQ", date(2024, 4, 1)) is None
        assert resolve_isin(listing, "BBB", "EQ", date(2025, 1, 1)) == ISIN_A

    def test_ambiguous_listing_rows_raise_on_resolve(self) -> None:
        table = pa.table(
            {
                "isin": pa.array([ISIN_A, ISIN_B], STR),
                "exchange": pa.array(["NSE", "NSE"], STR),
                "symbol": pa.array(["SYM", "SYM"], STR),
                "series": pa.array(["EQ", "EQ"], STR),
                "valid_from": pa.array([None, None], DATE),
                "valid_to": pa.array([None, None], DATE),
            }
        )
        listing = table.to_pandas(types_mapper=pd.ArrowDtype)
        with pytest.raises(ContractViolation, match="ambiguous"):
            resolve_isin(listing, "SYM", "EQ", date(2024, 1, 1))


class TestSecurityFrame:
    def test_name_is_latest_udiff_name_and_lifecycle_stays_null(self) -> None:
        obs = obs_frame(
            [
                _row(date(2023, 8, 18), "OLDCO", name=None),
                _row(date(2024, 8, 18), "OLDCO", name="Old Name Ltd"),
                _row(date(2025, 8, 18), "OLDCO", name="Newer Name Ltd"),
            ]
        )
        security = build_master_frames(obs, None).security
        row = security.iloc[0]
        assert row["isin"] == ISIN_A
        assert row["name"] == "Newer Name Ltd"
        assert pd.isna(row["status"])
        assert pd.isna(row["first_listed"])
        assert pd.isna(row["delisted_on"])
        assert pd.isna(row["delist_terminal_price"])


class TestSpliceValidator:
    def test_clean_splice_counts_pass(self) -> None:
        obs = obs_frame(
            [
                _row(date(2023, 8, 23), "OLDCO", close="101.00"),
                _row(date(2023, 8, 24), "NEWCO", prev_close="101.00"),
            ]
        )
        changes = chg_frame([(None, "OLDCO", "NEWCO", date(2023, 8, 24))])
        stats = build_master_frames(obs, changes).stats
        assert stats["splice_pass"] == 1
        assert stats["splice_fail"] == 0

    def test_mis_splice_counts_fail_but_does_not_block(self) -> None:
        obs = obs_frame(
            [
                _row(date(2023, 8, 23), "OLDCO", close="101.00"),
                _row(date(2023, 8, 24), "NEWCO", prev_close="55.00"),
            ]
        )
        changes = chg_frame([(None, "OLDCO", "NEWCO", date(2023, 8, 24))])
        stats = build_master_frames(obs, changes).stats
        assert stats["splice_fail"] == 1
