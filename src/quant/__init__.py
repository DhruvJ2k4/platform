"""Quant platform: single-operator quantitative research and portfolio system for NSE equities.

One pure portfolio engine with two drivers (backtest replay / live), point-in-time curated data
derived deterministically from immutable raw archives, and human-gated execution. Layering is
one-directional (ingest -> curate -> features -> engine -> drivers -> reports) and CI-enforced;
the import package is ``quant`` while the CLI command and distribution are ``platform`` (ADR-020).
"""

__version__ = "0.1.0"
