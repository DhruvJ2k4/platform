"""Feature library: pure factor functions over curated as-of views with strict PIT semantics.

Contract (doc 06 §6.3): every feature is ``f(curated_view_asof(D), params) -> DataFrame[isin,
value]`` registered as ``feature_id -> (function, params, version)``; results are cached
content-addressed by (feature_id, version, asof, curated_watermark) and are always safe to delete.
Look-ahead is prevented physically by the as-of views, never procedurally.
"""
