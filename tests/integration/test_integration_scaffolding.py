"""P0-01 placeholder: the full skeleton imports; fixture-driven pipelines land with P0-06+.

Integration tests run committed fixture files through the real pipeline — never live
exchange endpoints (doc 15).
"""

import importlib

PACKAGES = [
    "quant",
    "quant.agents",
    "quant.cli",
    "quant.curate",
    "quant.curate.parsers",
    "quant.drivers",
    "quant.engine",
    "quant.evaluation",
    "quant.features",
    "quant.ingest",
    "quant.ledger",
    "quant.ops",
    "quant.reports",
    "quant.schemas",
]


def test_all_layer_packages_import() -> None:
    for name in PACKAGES:
        importlib.import_module(name)
