"""P0-11 property suite: adjustment-timing invariance, PIT closure, pre-ex-block closure.

The doc 21 §1 invariant (the DoD's "invariance property"): daily returns computed from
adjusted prices are identical whether adjustment is applied today or after appending future
data. Hypothesis generates random action sets over a fixed price path and asserts the
returns on the early window never move when later actions/prices arrive.
"""

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP
from decimal import Decimal as D
from fractions import Fraction
from itertools import pairwise

from hypothesis import given
from hypothesis import strategies as st

from conftest import ca_frame, panel_frame
from quant.curate.adjust import adjust_prices

ISIN = "INE000PROPA1"
START = date(2025, 1, 1)
N_DAYS = 12
DAYS = [START + timedelta(days=i) for i in range(N_DAYS)]
FLOOR = date(2024, 1, 1)
CEILING = date(2026, 12, 31)

_action = st.tuples(
    st.integers(min_value=1, max_value=N_DAYS - 1),  # ex-date index into DAYS
    st.sampled_from(["split", "bonus"]),
    st.integers(min_value=1, max_value=10),  # ratio_num
    st.integers(min_value=1, max_value=10),  # ratio_den
)
_actions = st.lists(_action, max_size=4)


def _panel(n: int):
    return panel_frame([(DAYS[i], "P", "EQ", ISIN, D(100 + i), 10) for i in range(n)])


def _ca(actions, extra=()):
    entries = [
        (
            ISIN,
            DAYS[i],
            kind,
            num,
            den,
            None,
            "auto",
            "gen",
            datetime(DAYS[i].year, DAYS[i].month, DAYS[i].day),
        )
        for i, kind, num, den in actions
    ]
    entries.extend(extra)
    return ca_frame(entries)


def _exact_returns(frame):
    """Returns on the EXACT path: close_unadj x adj_factor as rationals (ADR-024).

    Doc 21 §1's invariance is exact on this path. The paisa-quantized `c` column cannot
    satisfy it bit-for-bit — independent half-paisa roundings on each price perturb the
    ratio (found by this very suite, 2026-07-18) — so exactness claims live here and the
    quantized path gets a rounding bound below.
    """
    mine = frame[frame["isin"] == ISIN].sort_values("d")
    vals = [
        Fraction(str(cu)) * Fraction(f).limit_denominator(10**9)
        for cu, f in zip(mine["close_unadj"], mine["adj_factor"], strict=True)
    ]
    return [b / a for a, b in pairwise(vals)]


@given(_actions, st.integers(min_value=3, max_value=N_DAYS - 1))
def test_timing_invariance_is_exact_on_the_factor_path(actions, cut) -> None:
    """Returns from close_unadj x adj_factor on days < cut never move when the future arrives."""
    early_actions = [a for a in actions if a[0] < cut]
    early = adjust_prices(
        _panel(cut),
        _ca(early_actions),
        coverage_floor=FLOOR,
        coverage_ceiling=CEILING,
        asof=DAYS[cut - 1],
    ).prices_adj
    full = adjust_prices(
        _panel(N_DAYS), _ca(actions), coverage_floor=FLOOR, coverage_ceiling=CEILING, asof=DAYS[-1]
    ).prices_adj
    early_returns = _exact_returns(early)
    full_returns = _exact_returns(full)[: len(early_returns)]
    assert full_returns == early_returns


@given(_actions)
def test_published_closes_are_the_half_up_quantization_of_the_exact_path(actions) -> None:
    """Every published c is exactly quantize(close_unadj x exact factor, 0.01, HALF_UP).

    Together with the exact-path invariance above this pins the quantized column completely:
    its only deviation from the invariant is deterministic half-paisa rounding, so a consumer
    needing exact long-horizon returns uses close_unadj x adj_factor (ADR-024; doc 21 §1).
    """
    out = adjust_prices(
        _panel(N_DAYS), _ca(actions), coverage_floor=FLOOR, coverage_ceiling=CEILING, asof=DAYS[-1]
    ).prices_adj
    mine = out[out["isin"] == ISIN].sort_values("d").reset_index(drop=True)
    for row_i in range(len(mine)):
        d = mine.loc[row_i, "d"]
        exact = Fraction(str(mine.loc[row_i, "close_unadj"]))
        for i, kind, num, den in actions:
            if DAYS[i] > d:
                exact *= Fraction(den, num) if kind == "split" else Fraction(den, num + den)
        expected = (D(exact.numerator) / D(exact.denominator)).quantize(
            D("0.01"), rounding=ROUND_HALF_UP
        )
        assert mine.loc[row_i, "c"] == expected


@given(_actions)
def test_adj_factor_is_exactly_the_product_of_future_action_factors(actions) -> None:
    out = adjust_prices(
        _panel(N_DAYS), _ca(actions), coverage_floor=FLOOR, coverage_ceiling=CEILING, asof=DAYS[-1]
    ).prices_adj
    mine = out[out["isin"] == ISIN].sort_values("d").reset_index(drop=True)
    for row_i in range(len(mine)):
        d = mine.loc[row_i, "d"]
        expected = Fraction(1)
        for i, kind, num, den in actions:
            if DAYS[i] > d:
                expected *= Fraction(den, num) if kind == "split" else Fraction(den, num + den)
        assert mine.loc[row_i, "adj_factor"] == float(expected)


@given(_actions, st.integers(min_value=1, max_value=N_DAYS - 1))
def test_pre_ex_block_closure_no_published_row_precedes_a_pending_action(
    actions, pending_i
) -> None:
    pending = (
        ISIN,
        DAYS[pending_i],
        "demerger",
        None,
        None,
        None,
        "needs_review",
        "d",
        datetime(DAYS[pending_i].year, DAYS[pending_i].month, DAYS[pending_i].day),
    )
    res = adjust_prices(
        _panel(N_DAYS),
        _ca(actions, extra=[pending]),
        coverage_floor=FLOOR,
        coverage_ceiling=CEILING,
        asof=DAYS[-1],
    )
    mine = res.prices_adj[res.prices_adj["isin"] == ISIN]
    assert all(d >= DAYS[pending_i] for d in mine["d"])
    s = res.stats
    assert s["panel_rows"] == (
        s["published"] + s["pre_ex_blocked"] + s["coverage_excluded"] + s["after_asof_excluded"]
    )


@given(_actions)
def test_pit_future_actions_are_invisible_to_an_earlier_asof(actions) -> None:
    """An asof=k build equals a build whose CA table was truncated to available_at <= k."""
    cut = N_DAYS // 2
    asof = DAYS[cut - 1]
    full_ca = _ca(actions)
    visible_ca = full_ca[full_ca["available_at"] <= datetime(asof.year, asof.month, asof.day)]
    if len(visible_ca) == 0:
        visible_ca = _ca([])
    via_asof = adjust_prices(
        _panel(N_DAYS), full_ca, coverage_floor=FLOOR, coverage_ceiling=CEILING, asof=asof
    ).prices_adj
    via_truncation = adjust_prices(
        _panel(cut), visible_ca, coverage_floor=FLOOR, coverage_ceiling=CEILING, asof=asof
    ).prices_adj
    assert list(via_asof["c"]) == list(via_truncation["c"])
    assert list(via_asof["adj_factor"]) == list(via_truncation["adj_factor"])
