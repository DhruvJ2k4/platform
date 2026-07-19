"""Raw equity price panel: bhavcopy vault → one primary-series row per (isin, day) (ADR-024).

prices_adj's PK is (isin, d) but a bhavcopy day can hold parallel series rows for one ISIN
(probed: 1,381/2.2M — auxiliary window series BL/T0/BO/IL always coexisting with exactly one
main series). This module keeps only the EQUITY family via an include-list (the vault census
found 162 distinct series — a huge bond/warrant tail makes an exclude-list unmaintainable),
picks the highest-priority equity series per (isin, day), and resolves classic-11 rows (no
ISIN) through the P0-09 effective-dated listing resolver — an unresolvable row is excluded
and counted, never guessed. Two equity rows in the SAME series on one day would be feed drift
→ ContractViolation. The result is the validated raw panel the adjuster consumes; every input
row is accounted for (kept or excluded for exactly one counted reason).
"""

from dataclasses import dataclass
from datetime import date

import pandas as pd
import structlog

from quant.config import Settings
from quant.curate.master import resolve_isin
from quant.curate.parsers.bhavcopy import ParsedBhavcopy, parse_bhavcopy
from quant.errors import ContractViolation
from quant.ingest import RawStore

log = structlog.get_logger()

# Equity family, priority-ordered: the primary row per (isin, day) is the first series in this
# list that exists that day. EQ rolling; BE/BZ trade-to-trade; SM/ST/SZ SME board (ADR-024).
EQUITY_SERIES_PRIORITY = ("EQ", "BE", "BZ", "SM", "ST", "SZ")
_PRIORITY_RANK = {s: i for i, s in enumerate(EQUITY_SERIES_PRIORITY)}


@dataclass(frozen=True)
class PricePanel:
    """The validated one-row-per-(isin,day) raw panel plus accounting counters."""

    panel: pd.DataFrame  # ParsedBhavcopy-shaped, equity-primary rows only, isin non-null
    stats: dict[str, int]


def build_price_panel(
    listing: pd.DataFrame,
    settings: Settings | None = None,
    asof: date | None = None,
) -> PricePanel:
    """Build the raw panel from every vault bhavcopy day ≤ asof; listing resolves classic-11."""
    store = RawStore(settings)
    frames = []
    for artifact in store.latest_per_date("bhavcopy"):
        if asof is not None and artifact.logical_date > asof:
            continue
        frames.append(parse_bhavcopy(artifact.path.read_bytes()))
    if not frames:
        raise ContractViolation("no bhavcopy raw files registered; nothing to curate")
    rows = pd.concat(frames, ignore_index=True)
    return build_price_panel_frames(rows, listing)


def build_price_panel_frames(rows: pd.DataFrame, listing: pd.DataFrame) -> PricePanel:
    """Pure core: parsed bhavcopy rows + listing → validated primary-series panel + stats."""
    stats: dict[str, int] = {
        "input_rows": len(rows),
        # bonds/warrants/units AND equity auxiliary window rows (BL/T0/BO/IL) — both fail the
        # equity-primary include-list; auxiliaries are duplicates of the day the main row owns.
        "non_primary_series_excluded": 0,
        "unresolvable_no_isin_excluded": 0,
        "lower_priority_series_collapsed": 0,
        "kept": 0,
    }
    equity = rows[rows["series"].isin(EQUITY_SERIES_PRIORITY)].copy()
    stats["non_primary_series_excluded"] = len(rows) - len(equity)

    # Classic-11 era rows carry no ISIN: identity comes from the effective-dated listing map.
    missing = equity["isin"].isna()
    if bool(missing.any()):
        resolved = [
            resolve_isin(listing, str(r.symbol), str(r.series), r.trade_date)
            for r in equity[missing].itertuples(index=False)
        ]
        equity.loc[missing, "isin"] = pd.array(resolved, dtype=equity["isin"].dtype)
        still_missing = equity["isin"].isna()
        stats["unresolvable_no_isin_excluded"] = int(still_missing.sum())
        equity = equity[~still_missing]

    # Primary-series selection: one row per (isin, day) by the fixed priority order. A tie in
    # the SAME series would mean duplicate feed rows — drift, never silently collapsed.
    equity["_rank"] = equity["series"].map(_PRIORITY_RANK)
    dup_same = equity.duplicated(subset=["isin", "trade_date", "series"], keep=False)
    if bool(dup_same.any()):
        sample = equity[dup_same].iloc[0]
        raise ContractViolation(
            "duplicate bhavcopy rows for one (isin, day, series): "
            f"({sample['isin']}, {sample['trade_date']}, {sample['series']}) — feed drift"
        )
    equity = equity.sort_values(["isin", "trade_date", "_rank"], kind="stable").drop_duplicates(
        subset=["isin", "trade_date"], keep="first"
    )
    stats["lower_priority_series_collapsed"] = (
        stats["input_rows"]
        - stats["non_primary_series_excluded"]
        - stats["unresolvable_no_isin_excluded"]
        - len(equity)
    )
    stats["kept"] = len(equity)

    panel = (
        equity.drop(columns=["_rank"])
        .sort_values(["isin", "trade_date"], kind="stable")
        .reset_index(drop=True)
    )
    validated = ParsedBhavcopy.validate(panel, lazy=True)
    log.info("price_panel_built", **stats)
    return PricePanel(panel=validated, stats=stats)
