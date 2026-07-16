"""P0-10 suite: free-text CA classifier — the money-critical rules engine (doc 21 §1; ADR-023).

Every case uses a real `subject` string harvested from the live 5y feed. The governing rules:
content ambiguity → needs_review (never a crash); nothing price-affecting is silently dropped
(only pure meetings drop); column conventions are pinned so the P0-11 adjuster cannot invert a
factor.
"""

from decimal import Decimal

import pytest

from quant.curate.corp_actions import classify


class TestDividend:
    def test_plain_dividend_sums_to_cash_auto(self) -> None:
        c = classify("Dividend - Rs 2 Per Share")
        assert (c.kind, c.status, c.cash_amount) == ("dividend", "auto", Decimal("2.00"))
        assert c.ratio_num is None and c.ratio_den is None

    def test_compound_dividend_amounts_are_summed(self) -> None:
        c = classify(
            "Annual General Meeting/Dividend - Rs 5 Per Share/Special Dividend - Rs 2.50 Per Share"
        )
        assert c.kind == "dividend" and c.status == "auto"
        assert c.cash_amount == Decimal("7.50")

    def test_divdend_typo_still_classifies(self) -> None:
        c = classify("Divdend - Rs 0.50 Per Share/Interim Dividend - Rs 0.75 Per Share")
        assert c.kind == "dividend" and c.cash_amount == Decimal("1.25")

    def test_div_abbreviation_classifies(self) -> None:
        c = classify("Div - Rs 0.50 Per Sh")
        assert c.kind == "dividend" and c.cash_amount == Decimal("0.50")

    def test_amount_less_dividend_is_needs_review_not_zero(self) -> None:
        c = classify("Interim Dividend")
        assert c.kind == "dividend" and c.status == "needs_review"
        assert c.cash_amount is None  # never fabricate 0 on a money path

    def test_division_is_not_mistaken_for_a_dividend(self) -> None:
        # "sub-division" contains "div" but must classify as a split, not a dividend.
        assert classify("Face Value Split (Sub-Division) - From Rs 10 To Rs 2").kind == "split"

    def test_face_value_is_not_summed_into_dividend_cash(self) -> None:
        # over-sum guard: the Rs 10 face value must NOT be added to the Rs 2.50 dividend.
        c = classify("Dividend - Rs 2.50 Per Equity Share Of Face Value Of Rs 10/-")
        assert c.kind == "dividend" and c.status == "auto" and c.cash_amount == Decimal("2.50")

    def test_face_value_only_subject_is_needs_review_not_fabricated(self) -> None:
        c = classify("Dividend (On Face Value Of Rs 10)")
        assert c.kind == "dividend" and c.status == "needs_review" and c.cash_amount is None

    def test_zero_dividend_is_needs_review(self) -> None:
        c = classify("Dividend - Rs 0 Per Share")
        assert c.kind == "dividend" and c.status == "needs_review" and c.cash_amount is None

    def test_compound_with_trailing_per_share_sums_all_components(self) -> None:
        # only the last component says "Per Share" but both are dividends — sum both.
        c = classify("Final Dividend - Rs 194/ Special Dividend - Rs 183 Per Share")
        assert c.status == "auto" and c.cash_amount == Decimal("377.00")

    def test_preference_dividend_is_needs_review(self) -> None:
        c = classify("Preference Dividend - Rs 10 Per Share")
        assert c.kind == "dividend" and c.status == "needs_review"


class TestSplit:
    def test_face_value_split_ratio_is_old_then_new(self) -> None:
        c = classify("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share")
        # doc 21 factor = den/num = new/old = 2/10 = 1/5
        assert (c.kind, c.status, c.ratio_num, c.ratio_den) == ("split", "auto", 10, 2)

    def test_consolidation_is_a_reverse_split(self) -> None:
        c = classify("Consolidation Of Equity Shares From Re 1 Per Share To Rs 10 Per Share")
        assert (c.kind, c.ratio_num, c.ratio_den) == ("split", 1, 10)  # factor den/num = 10

    def test_split_without_readable_ratio_is_needs_review(self) -> None:
        c = classify("Face Value Split")
        assert c.kind == "split" and c.status == "needs_review"

    def test_zero_face_value_is_needs_review_not_a_zero_factor(self) -> None:
        # den=0 would make the P0-11 factor 0 (zeroes the ISIN's whole price history) — block it.
        c = classify("Face Value Split - From Rs 10 To Rs 0")
        assert c.kind == "split" and c.status == "needs_review"

    def test_sub_rupee_face_value_is_needs_review(self) -> None:
        # "To Re 0.50" has no integer I32 ratio — must not truncate to 0.
        c = classify("Face Value Split - From Rs 10 To Re 0.50")
        assert c.kind == "split" and c.status == "needs_review"

    def test_partly_paid_split_is_needs_review(self) -> None:
        c = classify("Face Value Split - From Rs 10 To Rs 2 (Partly Paid Shares)")
        assert c.kind == "split" and c.status == "needs_review"


class TestBonus:
    @pytest.mark.parametrize(
        ("subject", "num", "den"),
        [("Bonus 1:1", 1, 1), ("Bonus 1: 1", 1, 1), ("Bonus- 1:2", 1, 2), ("Bonus 2:1", 2, 1)],
    )
    def test_bonus_ratio_new_then_held(self, subject: str, num: int, den: int) -> None:
        c = classify(subject)
        assert (c.kind, c.status, c.ratio_num, c.ratio_den) == ("bonus", "auto", num, den)

    def test_preference_share_bonus_never_auto_adjusts(self) -> None:
        # "Ncrps" = preference shares; a bonus of these does not dilute equity → needs_review.
        c = classify("Bonus Ncrps 1:116")
        assert c.kind == "bonus" and c.status == "needs_review"

    def test_zero_denominator_bonus_is_needs_review(self) -> None:
        # den=0 would divide-by-zero / zero-factor in the P0-11 adjuster.
        c = classify("Bonus 1:0")
        assert c.kind == "bonus" and c.status == "needs_review"


class TestRightsAlwaysReview:
    @pytest.mark.parametrize(
        "subject",
        ["Rights 11:8 @ Premium Rs 6.35/-", "Rights Issue 4:17@ Premium Rs 390/-", "Rights 1:1"],
    )
    def test_rights_is_always_needs_review(self, subject: str) -> None:
        # Feed faceVal is anachronistic ⇒ issue price S can't be reconstructed → operator factor.
        assert classify(subject).status == "needs_review"

    def test_rights_stores_ratio_and_premium(self) -> None:
        c = classify("Rights 11:8 @ Premium Rs 6.35/-")
        assert (c.kind, c.ratio_num, c.ratio_den, c.cash_amount) == (
            "rights",
            11,
            8,
            Decimal("6.35"),
        )

    def test_rights_without_premium_has_no_cash(self) -> None:
        c = classify("Rights 1:1")
        assert c.kind == "rights" and c.cash_amount is None


class TestReviewBucket:
    def test_demerger(self) -> None:
        assert classify("Demerger") == _review("demerger")

    def test_capital_reduction_is_other(self) -> None:
        c = classify("Capital Reduction Pursuant To Nclt Order")
        assert c.kind == "other" and c.status == "needs_review"

    def test_scheme_plus_bonus_is_a_compound_other(self) -> None:
        c = classify("Scheme Of Arrangement - Bonus Ncrps 1:10")
        assert c.kind == "other" and c.status == "needs_review"

    def test_unknown_non_meeting_falls_through_to_other(self) -> None:
        c = classify("Some Entirely Novel Corporate Event")
        assert c.kind == "other" and c.status == "needs_review"


class TestBuyback:
    @pytest.mark.parametrize("subject", ["Buy Back", "Buyback"])
    def test_buyback_auto_no_terms(self, subject: str) -> None:
        c = classify(subject)
        assert (c.kind, c.status, c.ratio_num, c.cash_amount) == ("buyback", "auto", None, None)


class TestMeetingsDrop:
    @pytest.mark.parametrize(
        "subject", ["Annual General Meeting", "Extra Ordinary General Meeting"]
    )
    def test_pure_meetings_are_dropped(self, subject: str) -> None:
        assert classify(subject).kind is None

    def test_meeting_with_dividend_is_a_dividend(self) -> None:
        # the "/Dividend" wins over the meeting drop (precedence).
        assert classify("Annual General Meeting/Dividend - Rs 3 Per Share").kind == "dividend"


class TestFactorConventions:
    """Anchor the ratio→factor conventions numerically (doc 21 §1) so a notation flip is caught."""

    def test_split_factor_is_den_over_num(self) -> None:
        c = classify("Face Value Split (Sub-Division) - From Rs 10/- To Rs 2/-")
        assert c.ratio_num is not None and c.ratio_den is not None
        # 10-to-2 face-value split = 5-for-1: historical price x den/num = 2/10 = 0.2.
        assert Decimal(c.ratio_den) / Decimal(c.ratio_num) == Decimal("0.2")

    def test_bonus_factor_is_den_over_num_plus_den(self) -> None:
        c = classify("Bonus 1:1")
        assert c.ratio_num is not None and c.ratio_den is not None
        # 1:1 bonus: hold 1 get 1, price x den/(num+den) = 1/2 = 0.5.
        assert Decimal(c.ratio_den) / Decimal(c.ratio_num + c.ratio_den) == Decimal("0.5")


def _review(kind: str) -> object:
    from quant.curate.corp_actions import Classification

    return Classification(kind, None, None, None, "needs_review")
