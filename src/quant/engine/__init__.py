"""Portfolio engine: the pure, deterministic decision core shared by both drivers (ADR-016).

Contract (doc 06 §6.4): ``decide(state, market_view, book_config) -> Decision`` performs selection
with buffered membership, capped inverse-vol weights, drift bands, the drawdown governor, the tax
overlay, and hard exclusions. Purity is CI-enforced: wall-clock reads, network, storage, and any
other I/O are forbidden here — timestamps and data arrive as function arguments, and every order
carries machine-readable reasons.
"""
