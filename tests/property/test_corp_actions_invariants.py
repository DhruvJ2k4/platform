"""P0-10 property suite: classifier totality + build determinism + conservation (doc 16).

Invariants: classify() is total (never raises, valid shape) over arbitrary text; the review-bucket
kinds are always needs_review; auto kinds always carry their required terms; the build is
order-independent; and every parsed row is conserved (kept or dropped for exactly one reason).
"""

from pathlib import Path

import pandas as pd
from hypothesis import given
from hypothesis import strategies as st

from quant.curate.corp_actions import build_corp_actions_frames, classify
from quant.curate.parsers.corp_actions import parse_corp_actions

FIXTURE = Path(__file__).parent.parent / "fixtures" / "corp_actions" / "corp_actions-trimmed.json"
VALID_KINDS = {"split", "bonus", "dividend", "demerger", "rights", "buyback", "other"}
_REVIEW_ONLY = {"demerger", "rights", "other"}

_PARSED = parse_corp_actions(FIXTURE.read_bytes())
_CANON = build_corp_actions_frames(_PARSED).corporate_actions.reset_index(drop=True)

# Fuzz pure text (totality) AND keyword-bearing subjects (so the closure invariant is actually
# exercised — random text almost never contains "demerger"/"rights"/etc).
_KEYWORDS = [
    "Demerger",
    "Scheme Of Arrangement",
    "Capital Reduction",
    "Rights 1:2 @ Premium Rs 5",
    "Rights Issue 3:4",
    "Bonus 1:1",
    "Bonus Ncrps 1:10",
    "Dividend - Rs 2 Per Share",
    "Interim Dividend",
    "Buy Back",
    "Face Value Split From Rs 10 To Rs 2",
    "Annual General Meeting",
    "Zephyr Novel Event",
]
_SUBJECTS = st.one_of(
    st.text(),
    st.builds(lambda kw, n: f"{kw} {n}", st.sampled_from(_KEYWORDS), st.text(max_size=12)),
)


@given(_SUBJECTS)
def test_classify_is_total_and_well_shaped(subject: str) -> None:
    c = classify(subject)
    assert c.kind is None or c.kind in VALID_KINDS
    assert c.status in (None, "auto", "needs_review")
    if c.kind is None:  # a dropped meeting has no status
        assert c.status is None
    if c.kind in _REVIEW_ONLY:  # review-bucket closure
        assert c.status == "needs_review"


@given(_SUBJECTS)
def test_auto_kinds_always_carry_their_terms(subject: str) -> None:
    c = classify(subject)
    if c.status != "auto":
        return
    if c.kind in ("split", "bonus"):
        assert c.ratio_num is not None and c.ratio_den is not None
    if c.kind == "dividend":
        assert c.cash_amount is not None  # an auto dividend never has a fabricated/absent amount


@given(st.permutations(list(range(len(_PARSED)))))
def test_build_is_order_independent(perm: list[int]) -> None:
    shuffled = _PARSED.iloc[perm].reset_index(drop=True)
    out = build_corp_actions_frames(shuffled).corporate_actions.reset_index(drop=True)
    pd.testing.assert_frame_equal(out, _CANON)


def test_every_parsed_row_is_conserved() -> None:
    s = build_corp_actions_frames(_PARSED).stats
    drops = (
        s["non_equity_dropped"]
        + s["no_isin_dropped"]
        + s["no_ex_date_dropped"]
        + s["meetings_dropped"]
    )
    assert s["parsed_rows"] == s["kept"] + drops


def test_built_table_is_enum_closed_and_pit_stamped() -> None:
    ca = build_corp_actions_frames(_PARSED).corporate_actions
    assert set(ca["kind"]).issubset(VALID_KINDS)
    assert not ca["available_at"].isna().any()  # every fact is PIT-stamped
    review = ca[ca["kind"].isin(list(_REVIEW_ONLY))]
    assert bool((review["status"] == "needs_review").all())
