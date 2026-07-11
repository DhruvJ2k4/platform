"""Drivers: the two consumers of the pure engine — backtest replay and live proposal (ADR-016).

Contract (doc 06 §6.5): BacktestDriver replays the trading calendar over curated history, applies
the execution model, maintains the simulated ledger, and emits run artifacts plus a manifest;
LiveDriver loads the real ledger and curated-as-of-today, enforces the freshness gate, and emits a
human-approvable Proposal. Drivers inject all data and time into the engine; skew between them is
a defect by definition.
"""
