"""Dividend cash surface: per-(isin, ex_date) credits derived from corporate_actions (P0-12).

Doc 10's table set is frozen — dividends are NOT a new schema table; docs 12 and 21 §11 credit
cash "on ex-date from the CA table", so this module derives that surface from the published
corporate_actions rows (kind=dividend only — a rights row's cash_amount is a subscription
premium, never a credit). Multiple dividend rows on one (isin, ex_date) are real (probed:
18 groups / 5y — interim+special/final pairs like 24+6 → 30) and SUM; but the feed also
re-announces the SAME dividend under different purpose text (5/18 groups are equal-amount
pairs, e.g. "Dividend Rs 0.60" + "Interim Dividend Rs 0.60"), and no field distinguishes a
duplicate from two genuine equal dividends — summing would silently double-credit backtest
cash. Policy (the platform's ambiguity rule): any (isin, ex_date) group containing an
equal-amount pair is AMBIGUOUS — excluded from credits, returned separately, counted and
warned; the operator resolves from the company circular (carried to P1-03 for a resolution
mechanism if a held name ever hits one). AMOUNT-LESS needs_review dividends never credit
until the operator cash-resolves them via config/ca-resolutions.yaml (cash_amount = that
row's per-share amount, ADR-025) — a resolved row credits like any other, and a resolved
amount equal to a payable sibling's degrades the group to ambiguous (conservative; RB-4
checks the stats after rebuild). Preference/cumulative-dividend review rows must NEVER
credit equity cash and so have no resolution shape yet (none live; P1-03). Credit-time PIT
rests on available_at <= ex_date (ADR-023 sets them equal) — enforced here so a P0-21
broadcast-timestamp refinement trips loudly instead of leaking. Every input dividend row
is accounted for: credited-source + ambiguous + needs_review rows sum to the input.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd
import pyarrow as pa
import structlog

from quant.config import Settings
from quant.errors import ContractViolation
from quant.schemas import DATE, STR, Contract, dec, field

log = structlog.get_logger()


class DividendCredit(Contract):
    """Derived credit surface (NOT a doc-10 table; outside TABLES governance)."""

    isin: pd.ArrowDtype = field(STR, nullable=False)
    ex_date: pd.ArrowDtype = field(DATE, nullable=False)
    amount_per_share: pd.ArrowDtype = field(dec(12, 2), nullable=False)


@dataclass(frozen=True)
class DividendCash:
    """Credits (one row per isin+ex_date), ambiguous CA rows excluded from credit, counters."""

    credits: pd.DataFrame
    ambiguous: pd.DataFrame  # original corporate_actions rows, surfaced verbatim
    stats: dict[str, int]


def build_dividend_cash(corporate_actions: pd.DataFrame) -> DividendCash:
    """Pure derivation: published corporate_actions frame → per-ex-date cash credits."""
    div = corporate_actions[corporate_actions["kind"] == "dividend"]
    stats: dict[str, int] = {
        "dividend_rows": len(div),
        "needs_review_excluded": int((div["status"] == "needs_review").sum()),
        "ambiguous_rows": 0,
        "credited_source_rows": 0,
        "credits": 0,
    }
    payable = div[div["status"] != "needs_review"]
    for row in payable.itertuples(index=False):
        # PIT guard: crediting at ex_date is only honest if the fact was known by then.
        # ADR-023 sets available_at == ex_date; P0-21 refinements must trip this loudly.
        if pd.Timestamp(row.available_at) > pd.Timestamp(row.ex_date):
            raise ContractViolation(
                f"dividend row ({row.isin}, {row.ex_date}) has available_at "
                f"{row.available_at} AFTER its ex_date — crediting at ex_date would leak; "
                "carry available_at onto the credit surface before relaxing this (ADR-025)"
            )

    keys: list[tuple[str, date]] = []
    amounts: list[Decimal] = []
    ambiguous_index: list[object] = []
    for (isin, ex), group in payable.groupby(["isin", "ex_date"], sort=True):
        vals = [Decimal(str(a)) for a in group["cash_amount"]]
        if len(vals) != len(set(vals)):
            # An equal-amount pair: a re-announced duplicate is indistinguishable from two
            # genuine equal dividends — crediting either guess silently corrupts cash.
            # A 'resolved' status here means an operator amount collided with a sibling —
            # the group still degrades conservatively; RB-4's post-rebuild stats check
            # surfaces it (no disambiguation mechanism exists until P1-03).
            ambiguous_index.extend(group.index)
            log.warning(
                "dividend_ambiguous_equal_amounts",
                isin=str(isin),
                ex_date=str(ex),
                amounts=[str(v) for v in vals],
                statuses=[str(s) for s in group["status"]],
            )
            continue
        keys.append((str(isin), ex))
        amounts.append(sum(vals, Decimal(0)))
        stats["credited_source_rows"] += len(group)

    stats["ambiguous_rows"] = len(ambiguous_index)
    stats["credits"] = len(keys)
    ambiguous = payable.loc[ambiguous_index]

    table = pa.table(
        {
            "isin": pa.array([k[0] for k in keys], STR),
            "ex_date": pa.array([k[1] for k in keys], DATE),
            "amount_per_share": pa.array(amounts, dec(12, 2)),
        }
    )
    credits = DividendCredit.validate(table.to_pandas(types_mapper=pd.ArrowDtype), lazy=True)
    log.info("dividend_cash_built", **stats)
    return DividendCash(credits=credits, ambiguous=ambiguous, stats=stats)


def load_dividend_cash(settings: Settings | None = None) -> DividendCash:
    """Derive the credit surface from the CURRENT published corporate_actions table."""
    from quant.curate.publish import read_current  # local import keeps module deps minimal

    return build_dividend_cash(read_current("corporate_actions", settings))
