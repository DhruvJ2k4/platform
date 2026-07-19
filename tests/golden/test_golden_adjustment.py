"""P0-11 golden: the doc-16 3-stock/8-quarter adjustment scenario, reproduced to the paisa.

Expected values are hand-computed in golden_scenario.py and are sacred (doc 16): a failing
run means the CODE is wrong until a written justification says otherwise.
"""

from decimal import Decimal as D

import golden_scenario as gs

from conftest import ca_frame, panel_frame
from quant.curate.adjust import adjust_prices


def _run(demerger_status: str = "needs_review"):
    return adjust_prices(
        panel_frame(gs.panel_rows()),
        ca_frame(gs.ca_entries(demerger_status)),
        coverage_floor=gs.COVERAGE_FLOOR,
        coverage_ceiling=gs.COVERAGE_CEILING,
        asof=gs.ASOF,
    )


class TestAlphaFactorChain:
    def test_adjusted_closes_to_the_paisa(self) -> None:
        out = _run().prices_adj
        alpha = out[out["isin"] == gs.ALPHA].sort_values("d")
        assert list(alpha["c"]) == gs.ALPHA_ADJUSTED
        assert list(alpha["close_unadj"]) == gs.ALPHA_RAW

    def test_factor_steps_match_hand_computation(self) -> None:
        out = _run().prices_adj
        alpha = out[out["isin"] == gs.ALPHA].sort_values("d")
        factors = list(alpha["adj_factor"])
        assert factors[0] == factors[1] == 1 / 30
        assert factors[2] == factors[3] == factors[4] == 1 / 6
        assert factors[5] == factors[6] == 1 / 3
        assert factors[7] == 1.0

    def test_dividend_never_moves_the_factor(self) -> None:
        # The ₹5 dividend ex 2024-09-01 sits between Q3 and Q4: both carry factor 1/6.
        out = _run().prices_adj
        alpha = out[out["isin"] == gs.ALPHA].sort_values("d")
        assert alpha.iloc[2]["adj_factor"] == alpha.iloc[3]["adj_factor"]

    def test_ohl_scale_with_close(self) -> None:
        out = _run().prices_adj
        q1 = out[(out["isin"] == gs.ALPHA)].sort_values("d").iloc[0]
        assert q1["o"] == q1["h"] == q1["l"] == q1["c"] == D("3.33")


class TestBravoDemergerBlocks:
    def test_pending_demerger_withholds_pre_ex_quarters(self) -> None:
        res = _run()
        bravo = res.prices_adj[res.prices_adj["isin"] == gs.BRAVO].sort_values("d")
        assert list(bravo["d"]) == gs.QUARTERS[4:]  # Q1..Q4 blocked, Q5..Q8 published
        assert list(bravo["c"]) == gs.BRAVO_ADJUSTED_PENDING
        assert res.stats["pre_ex_blocked"] == 4
        assert res.stats["blocked_isins"] == 1

    def test_resolution_unblocks_with_hand_computed_values(self) -> None:
        res = _run(demerger_status="resolved")
        bravo = res.prices_adj[res.prices_adj["isin"] == gs.BRAVO].sort_values("d")
        assert list(bravo["d"]) == gs.QUARTERS  # all 8 quarters published
        assert list(bravo["c"]) == gs.BRAVO_ADJUSTED_RESOLVED
        assert res.stats["pre_ex_blocked"] == 0


class TestCharlieDelisting:
    def test_delisted_rows_simply_stop(self) -> None:
        out = _run().prices_adj
        charlie = out[out["isin"] == gs.CHARLIE].sort_values("d")
        assert list(charlie["d"]) == gs.QUARTERS[:5]
        assert list(charlie["c"]) == gs.CHARLIE_ADJUSTED
        assert set(charlie["adj_factor"]) == {1.0}


def test_conservation_across_the_scenario() -> None:
    res = _run()
    s = res.stats
    assert (
        s["panel_rows"]
        == s["published"] + s["pre_ex_blocked"] + s["coverage_excluded"] + s["after_asof_excluded"]
    )
