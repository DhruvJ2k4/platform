"""Importable data contracts: pandera models mirroring the authoritative DDL in schemas/.

One model per doc-10 table plus raw_registry (doc 08) — see ADR-021. The canonical typed read
is the Arrow path (arrow_frame), which preserves DECIMAL(p,s) exactly; the float64-degrading
.df() shortcut is banned for money-bearing reads. TABLES maps exact table name -> model and
ddl_sql() returns the authoritative DDL, so DuckDB tables, models, and doc 10 cannot drift
silently. This package imports no platform modules and no duckdb, keeping every layer above it
(engine included) free to import contracts without violating purity rules.
"""

from pathlib import Path
from typing import Any

import pandas as pd
import pandera.pandas as pan

from quant.schemas.curated import (
    CorporateActions,
    Events,
    FundamentalsPit,
    IndexTri,
    Listing,
    PricesAdj,
    Security,
    TradingCalendar,
    UniverseMembership,
)
from quant.schemas.operational import Fill, Lot, Order, Proposal, Run
from quant.schemas.registry import RawRegistry

SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "schemas"

TABLES: dict[str, type[pan.DataFrameModel]] = {
    "security": Security,
    "listing": Listing,
    "trading_calendar": TradingCalendar,
    "prices_adj": PricesAdj,
    "corporate_actions": CorporateActions,
    "universe_membership": UniverseMembership,
    "fundamentals_pit": FundamentalsPit,
    "events": Events,
    "index_tri": IndexTri,
    "raw_registry": RawRegistry,
    "proposal": Proposal,
    "order": Order,
    "fill": Fill,
    "lot": Lot,
    "run": Run,
}


def ddl_sql(table: str) -> str:
    """Return the authoritative CREATE TABLE statement for a known table."""
    if table not in TABLES:
        raise KeyError(f"unknown table {table!r}; known: {sorted(TABLES)}")
    path = SCHEMAS_DIR / f"{table}.sql"
    if not path.is_file():
        # ConfigError replaces this when the P0-03 exception taxonomy lands.
        raise FileNotFoundError(
            f"authoritative DDL missing at {path}; quant.schemas requires a repo checkout"
        )
    return path.read_text(encoding="utf-8")


def arrow_frame(rel: Any) -> pd.DataFrame:
    """Canonical typed read of a DuckDB relation: arrow-backed frame preserving DECIMAL(p,s).

    Deliberately duck-typed so this package never imports duckdb — engine may import contracts
    without picking up a transitive purity violation (ADR-016 / ADR-021).
    """
    return rel.to_arrow_table().to_pandas(types_mapper=pd.ArrowDtype)


__all__ = [
    "SCHEMAS_DIR",
    "TABLES",
    "CorporateActions",
    "Events",
    "Fill",
    "FundamentalsPit",
    "IndexTri",
    "Listing",
    "Lot",
    "Order",
    "PricesAdj",
    "Proposal",
    "RawRegistry",
    "Run",
    "Security",
    "TradingCalendar",
    "UniverseMembership",
    "arrow_frame",
    "ddl_sql",
]
