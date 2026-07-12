"""Pandera contracts for the five operational tables (append-only; in the backup set, doc 08).

Operational rows are the only data rebuild cannot heal — proposals, orders, fills, lots, and run
manifests. Same contract regime as curated (ADR-021): strict columns, exact arrow dtypes,
DECIMAL(p,s) pinned; JSON columns surface as arrow strings.
"""

import pandas as pd

from quant.schemas._dtypes import DATE, I32, STR, TS, Contract, dec, field


class Proposal(Contract):
    """proposal: one human-approvable order set; status/human_action values firm up in P2."""

    proposal_id: pd.ArrowDtype = field(STR, nullable=False, unique=True)
    book_id: pd.ArrowDtype = field(STR, nullable=False)
    asof: pd.ArrowDtype = field(DATE, nullable=True)
    run_id: pd.ArrowDtype = field(STR, nullable=True)
    status: pd.ArrowDtype = field(STR, nullable=True)
    human_action: pd.ArrowDtype = field(STR, nullable=True)
    override_reason: pd.ArrowDtype = field(STR, nullable=True)
    created_at: pd.ArrowDtype = field(TS, nullable=True)


class Order(Contract):
    """order: one proposed trade; reasons carries the doc-14 explainability JSON."""

    order_id: pd.ArrowDtype = field(STR, nullable=False, unique=True)
    proposal_id: pd.ArrowDtype = field(STR, nullable=False)
    isin: pd.ArrowDtype = field(STR, nullable=False)
    side: pd.ArrowDtype = field(STR, nullable=False, isin=["buy", "sell"])
    qty: pd.ArrowDtype = field(I32, nullable=True)
    limit_hint: pd.ArrowDtype = field(dec(12, 2), nullable=True)
    reasons: pd.ArrowDtype = field(STR, nullable=True)  # JSON surfaces as arrow string


class Fill(Contract):
    """fill: an executed slice of an order, from contract notes or manual entry."""

    fill_id: pd.ArrowDtype = field(STR, nullable=False, unique=True)
    order_id: pd.ArrowDtype = field(STR, nullable=False)
    d: pd.ArrowDtype = field(DATE, nullable=False)
    qty: pd.ArrowDtype = field(I32, nullable=True)
    price: pd.ArrowDtype = field(dec(12, 2), nullable=True)
    charges: pd.ArrowDtype = field(STR, nullable=True)  # JSON surfaces as arrow string
    source: pd.ArrowDtype = field(STR, nullable=True, isin=["contract_note", "manual"])


class Lot(Contract):
    """lot: open FIFO tax lot; open_price includes pro-rated buy charges (sub-paisa, 12,4)."""

    lot_id: pd.ArrowDtype = field(STR, nullable=False, unique=True)
    book_id: pd.ArrowDtype = field(STR, nullable=False)
    isin: pd.ArrowDtype = field(STR, nullable=False)
    open_d: pd.ArrowDtype = field(DATE, nullable=False)
    open_price: pd.ArrowDtype = field(dec(12, 4), nullable=True)
    qty_open: pd.ArrowDtype = field(I32, nullable=True)
    qty_remaining: pd.ArrowDtype = field(I32, nullable=True)


class Run(Contract):
    """run: manifest header pinning (code, config, raw watermarks) lineage (ADR-016)."""

    run_id: pd.ArrowDtype = field(STR, nullable=False, unique=True)
    kind: pd.ArrowDtype = field(STR, nullable=False)
    book_id: pd.ArrowDtype = field(STR, nullable=True)
    code_hash: pd.ArrowDtype = field(STR, nullable=True)
    config_hash: pd.ArrowDtype = field(STR, nullable=True)
    raw_watermarks: pd.ArrowDtype = field(STR, nullable=True)  # JSON surfaces as arrow string
    started_at: pd.ArrowDtype = field(TS, nullable=True)
    status: pd.ArrowDtype = field(STR, nullable=True)
