"""Report renderers: Jinja2 templates to static HTML, one artifact per run (doc 06 §6.8).

Contract: proposal, quarterly review, data-quality, decay dashboard, override-alpha, and status
pages render from run artifacts and operational tables only; every page carries a mandatory data
freshness banner, and rendered HTML is archived per run_id so any report can be reproduced.
"""
