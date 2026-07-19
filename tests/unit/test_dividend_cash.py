"""P0-12 suite: dividend cash surface — summing, ambiguity exclusion, review exclusion.

Cases mirror the live probe: distinct-amount same-day pairs are genuine (interim+special)
and SUM; equal-amount pairs are indistinguishable from feed re-announcements and are
surfaced, never guessed; needs_review dividends and rights premiums never credit.
"""

from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from conftest import ca_frame
from quant.config import CAResolution
from quant.curate.corp_actions import build_corp_actions_frames
from quant.curate.dividends import build_dividend_cash
from quant.curate.parsers.corp_actions import parse_corp_actions
from quant.errors import ContractViolation

FIXTURE = Path(__file__).parent.parent / "fixtures" / "corp_actions" / "corp_actions-trimmed.json"
A, B = "INE000DIVAA1", "INE000DIVBB2"
EX = date(2023, 8, 2)
AVAIL = datetime(2023, 8, 2)


class TestCredits:
    def test_single_dividend_credits_its_amount(self) -> None:
        res = build_dividend_cash(
            ca_frame([(A, EX, "dividend", None, None, D("24.00"), "auto", "d", AVAIL)])
        )
        row = res.credits.iloc[0]
        assert (row["isin"], row["ex_date"], row["amount_per_share"]) == (A, EX, D("24.00"))

    def test_distinct_same_day_amounts_sum(self) -> None:
        # the L&T live case: Dividend 24 + Special Dividend 6 -> one 30.00 credit
        res = build_dividend_cash(
            ca_frame(
                [
                    (A, EX, "dividend", None, None, D("24.00"), "auto", "Dividend - Rs 24", AVAIL),
                    (A, EX, "dividend", None, None, D("6.00"), "auto", "Special - Rs 6", AVAIL),
                ]
            )
        )
        assert len(res.credits) == 1
        assert res.credits.iloc[0]["amount_per_share"] == D("30.00")

    def test_resolved_dividend_credits_too(self) -> None:
        res = build_dividend_cash(
            ca_frame([(A, EX, "dividend", None, None, D("5.00"), "resolved", "d|res", AVAIL)])
        )
        assert res.credits.iloc[0]["amount_per_share"] == D("5.00")

    def test_config_cash_resolution_flows_into_credits(self) -> None:
        # ADR-025 end to end: the fixture's REAL amount-less "Interim Dividend" row credits
        # exactly the operator's circular total once cash-resolved via config.
        resolution = CAResolution(
            isin="INE054A01019",
            ex_date=date(2022, 3, 8),
            kind="dividend",
            cash_amount=D("20.00"),
            source_ref="circular",
        )
        ca = build_corp_actions_frames(
            parse_corp_actions(FIXTURE.read_bytes()), resolutions=[resolution]
        ).corporate_actions
        res = build_dividend_cash(ca)
        assert res.stats["needs_review_excluded"] == 0  # the fixture's only such row resolved
        row = res.credits[res.credits["isin"] == "INE054A01019"].iloc[0]
        assert (row["ex_date"], row["amount_per_share"]) == (date(2022, 3, 8), D("20.00"))


class TestExclusions:
    def test_equal_amount_pair_is_ambiguous_never_summed(self) -> None:
        # the INE961D01019 live case: "Dividend 0.60" + "Interim Dividend 0.60" — a feed
        # re-announcement is indistinguishable from two genuine equal dividends.
        res = build_dividend_cash(
            ca_frame(
                [
                    (A, EX, "dividend", None, None, D("0.60"), "auto", "Dividend - Re 0.60", AVAIL),
                    (A, EX, "dividend", None, None, D("0.60"), "auto", "Interim - Re 0.60", AVAIL),
                ]
            )
        )
        assert len(res.credits) == 0
        assert len(res.ambiguous) == 2  # surfaced verbatim for the operator
        assert res.stats["ambiguous_rows"] == 2

    def test_equal_pair_plus_distinct_row_excludes_the_whole_group(self) -> None:
        res = build_dividend_cash(
            ca_frame(
                [
                    (A, EX, "dividend", None, None, D("2.00"), "auto", "a", AVAIL),
                    (A, EX, "dividend", None, None, D("2.00"), "auto", "b", AVAIL),
                    (A, EX, "dividend", None, None, D("5.00"), "auto", "c", AVAIL),
                ]
            )
        )
        assert len(res.credits) == 0 and len(res.ambiguous) == 3

    def test_resolved_amount_distinct_from_auto_sibling_sums(self) -> None:
        # ADR-025 row-not-total semantics: the resolved row's amount joins the group sum.
        res = build_dividend_cash(
            ca_frame(
                [
                    (A, EX, "dividend", None, None, D("5.00"), "auto", "Special - Rs 5", AVAIL),
                    (A, EX, "dividend", None, None, D("25.00"), "resolved", "d|res", AVAIL),
                ]
            )
        )
        assert len(res.credits) == 1
        assert res.credits.iloc[0]["amount_per_share"] == D("30.00")

    def test_resolved_amount_equal_to_auto_sibling_degrades_to_ambiguous(self) -> None:
        # An operator amount colliding with a payable sibling is indistinguishable from a
        # re-announced duplicate — conservative exclusion, surfaced; RB-4 checks the stats.
        res = build_dividend_cash(
            ca_frame(
                [
                    (A, EX, "dividend", None, None, D("20.00"), "auto", "Div - Rs 20", AVAIL),
                    (A, EX, "dividend", None, None, D("20.00"), "resolved", "d|res", AVAIL),
                ]
            )
        )
        assert len(res.credits) == 0
        assert len(res.ambiguous) == 2 and res.stats["ambiguous_rows"] == 2

    def test_available_at_after_ex_date_is_a_contract_violation(self) -> None:
        # Credit-time PIT rests on available_at <= ex_date (ADR-023/025); a P0-21
        # broadcast-timestamp refinement must trip this loudly, never leak.
        with pytest.raises(ContractViolation, match="available_at"):
            build_dividend_cash(
                ca_frame(
                    [(A, EX, "dividend", None, None, D("5.00"), "auto", "d", datetime(2023, 8, 3))]
                )
            )

    def test_needs_review_dividend_never_credits(self) -> None:
        res = build_dividend_cash(
            ca_frame([(A, EX, "dividend", None, None, None, "needs_review", "amtless", AVAIL)])
        )
        assert len(res.credits) == 0
        assert res.stats["needs_review_excluded"] == 1

    def test_rights_premium_never_credits(self) -> None:
        res = build_dividend_cash(
            ca_frame([(A, EX, "rights", 1, 2, D("390.00"), "needs_review", "r", AVAIL)])
        )
        assert len(res.credits) == 0 and res.stats["dividend_rows"] == 0

    def test_other_isins_unaffected_by_one_ambiguous_group(self) -> None:
        res = build_dividend_cash(
            ca_frame(
                [
                    (A, EX, "dividend", None, None, D("1.00"), "auto", "a", AVAIL),
                    (A, EX, "dividend", None, None, D("1.00"), "auto", "b", AVAIL),
                    (B, EX, "dividend", None, None, D("7.00"), "auto", "c", AVAIL),
                ]
            )
        )
        assert list(res.credits["isin"]) == [B]
        assert res.credits.iloc[0]["amount_per_share"] == D("7.00")


class TestConservationAndFixture:
    def test_every_dividend_row_is_accounted_for(self) -> None:
        ca = build_corp_actions_frames(parse_corp_actions(FIXTURE.read_bytes())).corporate_actions
        res = build_dividend_cash(ca)
        s = res.stats
        assert s["dividend_rows"] == (
            s["credited_source_rows"] + s["ambiguous_rows"] + s["needs_review_excluded"]
        )

    def test_fixture_credits_match_the_ca_source(self) -> None:
        # the DoD clause in miniature: derived credits equal the source rows' cash amounts
        ca = build_corp_actions_frames(parse_corp_actions(FIXTURE.read_bytes())).corporate_actions
        res = build_dividend_cash(ca)
        src = ca[(ca["kind"] == "dividend") & (ca["status"] == "auto")]
        for row in res.credits.itertuples(index=False):
            mine = src[(src["isin"] == row.isin) & (src["ex_date"] == row.ex_date)]
            assert sum((D(str(a)) for a in mine["cash_amount"]), D(0)) == row.amount_per_share

    def test_credits_are_decimal_paisa(self) -> None:
        ca = build_corp_actions_frames(parse_corp_actions(FIXTURE.read_bytes())).corporate_actions
        res = build_dividend_cash(ca)
        assert all(isinstance(a, D) for a in res.credits["amount_per_share"])
