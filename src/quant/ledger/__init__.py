"""FIFO tax-lot ledger: buys, sells, dividends, delistings, charges, and reconciliation.

Contract (doc 06 §6.7): money is Decimal end-to-end (floats are banned on this path), lots are
FIFO-ordered, and conservation (cash + positions + costs + taxes == initial + P&L) is a property
test, not an assumption. Contract notes are parsed and reconciled against modeled costs; gaps
above 5 bps open a ticket and feed slippage recalibration (ADR-017).
"""
