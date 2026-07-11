"""Curation build: the deterministic raw -> curated transform and the only writer of curated tables.

Contract (doc 06 §6.2): parse via format-epoch-versioned parsers, resolve the security master,
apply corporate-action adjustments (demergers go to the review queue, never auto-adjusted), build
the PIT universe, diff events, and publish atomically behind the validation gate. Every curated
fact row carries ``available_at``; rebuilds are bit-reproducible (ADR-016).
"""
