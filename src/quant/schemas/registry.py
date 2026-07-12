"""Pandera contract for the raw_registry ledger (doc 08).

Raw is the only irreplaceable asset: every row records one immutable downloaded file. No
uniqueness constraint exists on (source, logical_date) by design — re-downloads append
supersession rows; nothing is ever mutated or deleted.
"""

import pandas as pd

from quant.schemas._dtypes import DATE, STR, TS, Contract, field


class RawRegistry(Contract):
    """raw_registry: immutable ledger of as-downloaded raw files."""

    source: pd.ArrowDtype = field(STR, nullable=False)
    logical_date: pd.ArrowDtype = field(DATE, nullable=False)
    path: pd.ArrowDtype = field(STR, nullable=False)
    sha256: pd.ArrowDtype = field(STR, nullable=False)
    fetched_at: pd.ArrowDtype = field(TS, nullable=False)
