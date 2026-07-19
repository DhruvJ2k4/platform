"""P0-11 suite: CA adjuster unit coverage — factor conventions, blocking, coverage, PIT.

The golden scenario proves the full hand-computed chain; these tests pin each mechanism in
isolation so a regression names its broken rule directly.
"""

from datetime import date, datetime
from decimal import Decimal as D
from fractions import Fraction

import pytest

from conftest import ca_frame, panel_frame
from quant.curate.adjust import action_factor, adjust_prices
from quant.errors import ContractViolation

ISIN = "INE000TESTA1"
D1, D2, D3 = date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)
ASOF = date(2025, 6, 1)
FLOOR, CEIL = date(2024, 1, 1), date(2026, 1, 1)


def _panel():
    return panel_frame(
        [
            (D1, "T", "EQ", ISIN, D("100.00"), 10),
            (D2, "T", "EQ", ISIN, D("20.00"), 50),
            (D3, "T", "EQ", ISIN, D("10.00"), 100),
        ]
    )


def _adjust(entries, *, floor=FLOOR, ceiling=CEIL, asof=ASOF):
    return adjust_prices(
        _panel(), ca_frame(entries), coverage_floor=floor, coverage_ceiling=ceiling, asof=asof
    )


class TestActionFactor:
    @pytest.mark.parametrize(
        ("kind", "status", "num", "den", "expected"),
        [
            ("split", "auto", 10, 2, Fraction(1, 5)),
            ("split", "auto", 1, 10, Fraction(10, 1)),  # consolidation / reverse split
            ("bonus", "auto", 1, 1, Fraction(1, 2)),
            ("bonus", "auto", 1, 2, Fraction(2, 3)),
            ("bonus", "resolved", 1, 2, Fraction(2, 3)),  # kind semantics survive resolution
            ("split", "resolved", 10, 2, Fraction(1, 5)),
            ("rights", "resolved", 20, 19, Fraction(19, 20)),
            ("demerger", "resolved", 10, 7, Fraction(7, 10)),
            ("other", "resolved", 10, 9, Fraction(9, 10)),
        ],
    )
    def test_factor_conventions(self, kind, status, num, den, expected) -> None:
        assert action_factor(kind, status, num, den) == expected

    @pytest.mark.parametrize(
        ("kind", "status"),
        [
            ("dividend", "auto"),
            ("buyback", "auto"),
            ("demerger", "needs_review"),
            ("rights", "needs_review"),
            ("other", "needs_review"),
            ("split", "needs_review"),
            ("bonus", "needs_review"),
        ],
    )
    def test_never_factoring_cases(self, kind, status) -> None:
        assert action_factor(kind, status, 1, 1) is None

    def test_auto_reorganization_is_upstream_drift(self) -> None:
        # ADR-023: rights/demerger/other can never arrive auto; seeing one means the
        # classifier's guarantee broke — fail loudly, never adjust from it.
        with pytest.raises(ContractViolation, match="auto"):
            action_factor("demerger", "auto", 10, 7)

    def test_factoring_row_without_ratio_is_drift(self) -> None:
        with pytest.raises(ContractViolation, match="lacks ratio"):
            action_factor("split", "auto", None, None)


class TestReverseCumulative:
    def test_factors_compound_across_boundaries(self) -> None:
        out = _adjust(
            [
                (ISIN, D2, "split", 10, 2, None, "auto", "s", datetime(2025, 1, 2)),
                (ISIN, D3, "bonus", 1, 1, None, "auto", "b", datetime(2025, 1, 3)),
            ]
        ).prices_adj
        assert list(out["adj_factor"]) == [0.1, 0.5, 1.0]
        assert list(out["c"]) == [D("10.00"), D("10.00"), D("10.00")]

    def test_same_day_actions_multiply_order_independently(self) -> None:
        forward = [
            (ISIN, D2, "bonus", 1, 2, None, "auto", "b", datetime(2025, 1, 2)),
            (ISIN, D2, "split", 2, 1, None, "auto", "s", datetime(2025, 1, 2)),
        ]
        a = _adjust(forward).prices_adj
        b = _adjust(list(reversed(forward))).prices_adj
        assert a.iloc[0]["adj_factor"] == b.iloc[0]["adj_factor"] == 1 / 3
        assert a.iloc[0]["c"] == b.iloc[0]["c"] == D("33.33")

    def test_quantization_is_half_up_at_the_paisa(self) -> None:
        # 100.00 * 1/3 = 33.333.. -> 33.33 ; a 50.00 * ... use 0.125 factor: 100 * 1/8 = 12.50 exact
        out = _adjust(
            [(ISIN, D2, "split", 8, 1, None, "auto", "s", datetime(2025, 1, 2))]
        ).prices_adj
        assert out.iloc[0]["c"] == D("12.50")

    def test_unrelated_isin_is_untouched(self) -> None:
        out = _adjust(
            [("INE000OTHER9", D2, "split", 10, 2, None, "auto", "s", datetime(2025, 1, 2))]
        ).prices_adj
        assert set(out["adj_factor"]) == {1.0}


class TestPreExBlock:
    def test_any_needs_review_blocks_all_earlier_dates(self) -> None:
        res = _adjust([(ISIN, D3, "rights", 1, 1, None, "needs_review", "r", datetime(2025, 1, 3))])
        assert list(res.prices_adj["d"]) == [D3]
        assert res.stats["pre_ex_blocked"] == 2

    def test_latest_pending_boundary_governs(self) -> None:
        res = _adjust(
            [
                (ISIN, D2, "demerger", None, None, None, "needs_review", "d", datetime(2025, 1, 2)),
                (ISIN, D3, "rights", None, None, None, "needs_review", "r", datetime(2025, 1, 3)),
            ]
        )
        assert list(res.prices_adj["d"]) == [D3]

    def test_resolution_lifts_the_block_and_factors(self) -> None:
        res = _adjust(
            [(ISIN, D2, "demerger", 10, 7, None, "resolved", "d|res", datetime(2025, 1, 2))]
        )
        out = res.prices_adj
        assert len(out) == 3 and res.stats["pre_ex_blocked"] == 0
        assert out.iloc[0]["c"] == D("70.00")  # 100 * 7/10


class TestCoverageAndPit:
    def test_dates_outside_coverage_are_excluded_not_partially_adjusted(self) -> None:
        res = _adjust([], floor=D2, ceiling=D2)
        assert list(res.prices_adj["d"]) == [D2]
        assert res.stats["coverage_excluded"] == 2

    def test_action_after_asof_is_invisible(self) -> None:
        res = _adjust(
            [(ISIN, D3, "split", 10, 2, None, "auto", "s", datetime(2025, 1, 3))], asof=D2
        )
        out = res.prices_adj
        assert list(out["d"]) == [D1, D2]  # D3 price also gone (d <= asof)
        assert set(out["adj_factor"]) == {1.0}  # future split never touches the past

    def test_conservation_always_balances(self) -> None:
        res = _adjust(
            [(ISIN, D2, "demerger", None, None, None, "needs_review", "d", datetime(2025, 1, 2))],
            floor=D2,
            ceiling=D2,
        )
        s = res.stats
        assert s["panel_rows"] == (
            s["published"] + s["pre_ex_blocked"] + s["coverage_excluded"] + s["after_asof_excluded"]
        )
