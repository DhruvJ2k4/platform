"""Evaluation harness: mechanical enforcement of the research validation rules (doc 11).

Contract (doc 06 §6.6): pre-registered variant budgets (the 7th variant is refused), walk-forward
evaluation, a single-shot holdout whose one look is recorded in a state file, the stress suite,
deflated-Sharpe reporting, champion/challenger comparison, and the paper-only incubation ledger
(ADR-018). Refusals are hard failures, not warnings.
"""
