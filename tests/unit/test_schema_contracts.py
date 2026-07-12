"""P0-02 round-trip suite: authoritative DDL <-> pandera contracts on empty tables (doc 20 DoD)."""

import re

import duckdb
import pytest

from quant.schemas import SCHEMAS_DIR, TABLES, arrow_frame, ddl_sql


def test_registry_bijection() -> None:
    """Every DDL file has a model and vice versa — contracts are importable and complete."""
    sql_tables = {p.stem for p in SCHEMAS_DIR.glob("*.sql")}
    assert sql_tables == set(TABLES)
    assert len(TABLES) == 15


@pytest.mark.parametrize("table", sorted(TABLES))
def test_empty_roundtrip(table: str) -> None:
    """DDL -> DuckDB -> arrow-backed frame -> pandera -> INSERT back, on the empty table."""
    con = duckdb.connect()
    con.execute(ddl_sql(table))
    df = arrow_frame(con.sql(f'SELECT * FROM "{table}"'))
    validated = TABLES[table].validate(df, lazy=True)
    con.register("validated_df", validated)
    con.execute(f'INSERT INTO "{table}" SELECT * FROM validated_df')
    assert con.sql(f'SELECT count(*) FROM "{table}"').fetchone()[0] == 0


BARE_DECIMAL = re.compile(r"DECIMAL(?!\s*\()", re.IGNORECASE)


def test_no_bare_decimals() -> None:
    """Bare DECIMAL silently means DECIMAL(18,3) in DuckDB — banned in authoritative DDL."""
    for path in sorted(SCHEMAS_DIR.glob("*.sql")):
        assert not BARE_DECIMAL.search(path.read_text(encoding="utf-8")), path.name
