"""Contract plumbing: arrow-backed field helpers and the shared model base (ADR-021).

Every column in quant.schemas is a pyarrow-backed pandas dtype so DECIMAL precision/scale from
the authoritative DDL survives the read path exactly; these helpers keep the 100+ column
declarations readable, and the shared base enforces strict column sets with no coercion.
"""

from typing import Any

import pandera.pandas as pan
import pyarrow as pa

STR = pa.string()
DATE = pa.date32()
TS = pa.timestamp("us")
I32 = pa.int32()
I64 = pa.int64()
F64 = pa.float64()
BOOL = pa.bool_()
STR_LIST = pa.list_(pa.string())


def dec(precision: int, scale: int) -> pa.DataType:
    """decimal128 with explicit precision/scale — bare DECIMAL is banned (ADR-021)."""
    return pa.decimal128(precision, scale)


def field(pa_type: pa.DataType, **kwargs: Any) -> Any:
    """Pandera Field pinned to an exact pyarrow dtype (annotate the column pd.ArrowDtype)."""
    return pan.Field(dtype_kwargs={"pyarrow_dtype": pa_type}, **kwargs)


class Contract(pan.DataFrameModel):
    """Shared base: exact column set, no coercion — dtypes must arrive correct (ADR-021)."""

    class Config:
        strict = True
        coerce = False
