"""Security master + effective-dated listing resolver (doc 20 P0-09; doc 06 §6.2; ADR-022).

Builds the `security` and `listing` tables from ISIN-bearing bhavcopy observations refined by
the NSE symbol-change snapshot, and resolves (symbol, series, date) → ISIN. Policy (ADR-022):
observations win; the file pins rename boundaries inside observation gaps and backdates
pre-observation symbol chains; the oldest era of every chain has valid_from NULL = open past.
Listing answers IDENTITY only — never existence, age, or activity. Unrepairable identity
conflicts raise ContractViolation; a resolution miss returns None (miss beats guess). The
build is a pure deterministic function of its input frames; builders return validated frames
that curate/build.py publishes atomically (ADR-024).
"""

from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date, timedelta
from itertools import pairwise
from typing import Any

import pandas as pd
import pyarrow as pa
import structlog

from quant.config import Settings
from quant.curate.parsers.bhavcopy import parse_bhavcopy
from quant.curate.parsers.symbolchange import parse_symbolchange
from quant.errors import ContractViolation
from quant.ingest import RawStore
from quant.schemas import DATE, STR, Listing, Security, dec

log = structlog.get_logger()

_EXCHANGE = "NSE"
_CHAIN_CAP = 20  # backstop against pathological rename graphs, far above any real chain
_BRIDGE_CAP = 6  # max rename hops bridging one observation gap
_SPLICE_MAX_GAP_DAYS = 7  # splice DQ is meaningful only across (near-)adjacent trading days

_OBS_COLUMNS = ["trade_date", "symbol", "series", "isin", "security_name", "close", "prev_close"]


@dataclass(frozen=True)
class MasterTables:
    """The validated security/listing frames plus the build-report counters (ADR-022)."""

    security: pd.DataFrame
    listing: pd.DataFrame
    stats: dict[str, int] = dc_field(default_factory=dict)


@dataclass(frozen=True)
class _Era:
    """One symbol era of an ISIN: observed span plus effective bounds once boundaries settle."""

    symbol: str
    first_seen: date | None  # None for synthetic (chain-backdated) eras
    last_seen: date | None
    valid_from: date | None  # None = open past
    valid_to: date | None  # None = open-ended
    synthetic: bool
    parallel: bool = False  # coexisting span (e.g. NSE bond-symbol blips): evidence-bounded


def build_master(settings: Settings | None = None) -> MasterTables:
    """Build the master from the raw vault: every bhavcopy + the latest symbolchange snapshot."""
    store = RawStore(settings)
    frames = []
    for artifact in store.latest_per_date("bhavcopy"):
        parsed = parse_bhavcopy(artifact.path.read_bytes())
        frames.append(parsed[_OBS_COLUMNS])
    if not frames:
        raise ContractViolation("no bhavcopy raw files registered; master needs observations")
    observations = pd.concat(frames, ignore_index=True)
    snapshots = store.latest_per_date("symbolchange")
    if snapshots:
        changes = parse_symbolchange(snapshots[-1].path.read_bytes())
    else:
        log.warning("master_no_symbolchange_snapshot")  # boundaries fall back, chains skipped
        changes = None
    return build_master_frames(observations, changes)


def build_master_frames(observations: pd.DataFrame, changes: pd.DataFrame | None) -> MasterTables:
    """Pure deterministic core: observation + symbolchange frames → validated master tables."""
    stats: dict[str, int] = {
        "observation_rows": len(observations),
        "rows_no_isin": 0,
        "rows_no_series": 0,
        "self_renames_dropped": 0,
        "parallel_spans": 0,
        "file_pinned_boundaries": 0,
        "fallback_boundaries": 0,
        "synthetic_eras": 0,
        "chain_stops": 0,
        "recycled_clips": 0,
        "synthetic_dropped": 0,
        "splice_pass": 0,
        "splice_fail": 0,
        "splice_incomparable": 0,
    }
    obs = _usable_observations(observations, stats)
    renames = _usable_renames(changes, stats)
    spans = _series_spans(obs)
    # Earliest-observed ISIN first: a rename record seeds ONE chain, and the pre-history
    # belongs to the ISIN in force earliest (ISIN changes move forward in time). Real
    # precedent: ABSHEKINDS→TRIDENT would otherwise backdate into BOTH of Trident's ISINs.
    firsts = obs.groupby("isin", sort=True)["trade_date"].min()
    consumed: set[tuple[str, str, date]] = set()
    eras_by_isin: dict[str, list[_Era]] = {}
    for isin, _ in sorted(firsts.items(), key=lambda kv: (kv[1], kv[0])):
        eras_by_isin[str(isin)] = _settle_eras(str(isin), obs, renames, stats, consumed)
    _splice_check(obs, eras_by_isin, stats)
    listing = _emit_listing(eras_by_isin, spans, obs, stats)
    security = _emit_security(obs)
    stats["securities"] = len(security)
    stats["listings"] = len(listing)
    stats["open_past_listings"] = int(listing["valid_from"].isna().sum())
    log.info("master_built", **stats)
    return MasterTables(security=security, listing=listing, stats=stats)


def resolve_isin(
    listing: pd.DataFrame,
    symbol: str,
    series: str,
    d: date,
    exchange: str = _EXCHANGE,
) -> str | None:
    """Resolve (symbol, series, d) to its ISIN; None on miss; ambiguity is a ContractViolation.

    NULL valid_from means open past (-inf); NULL valid_to means open-ended (+inf).
    """
    rows = listing[
        (listing["exchange"] == exchange)
        & (listing["symbol"] == symbol)
        & (listing["series"] == series)
        & (listing["valid_from"].isna() | (listing["valid_from"] <= d))
        & (listing["valid_to"].isna() | (listing["valid_to"] >= d))
    ]
    isins = sorted(rows["isin"].unique())
    if not isins:
        return None
    if len(isins) > 1:
        raise ContractViolation(
            f"ambiguous resolution: ({exchange}, {symbol}, {series}, {d}) matches {isins}"
        )
    return str(isins[0])


def _usable_observations(observations: pd.DataFrame, stats: dict[str, int]) -> pd.DataFrame:
    """ISIN- and series-bearing rows only; classic-11 rows are resolver CONSUMERS, not inputs."""
    missing = [c for c in _OBS_COLUMNS if c not in observations.columns]
    if missing:
        raise ContractViolation(f"observations frame lacks columns {missing}")
    no_isin = observations["isin"].isna()
    no_series = observations["series"].isna() & ~no_isin
    stats["rows_no_isin"] = int(no_isin.sum())
    stats["rows_no_series"] = int(no_series.sum())
    usable = observations[~no_isin & ~no_series]
    return usable.sort_values(["isin", "trade_date", "symbol", "series"], kind="stable")


def _usable_renames(changes: pd.DataFrame | None, stats: dict[str, int]) -> pd.DataFrame:
    """Drop NSE's self-rename artifacts (old==new); keep the frame canonically ordered."""
    if changes is None or changes.empty:
        return pd.DataFrame(columns=["old_symbol", "new_symbol", "applicable_from"])
    self_renames = changes["old_symbol"] == changes["new_symbol"]
    stats["self_renames_dropped"] = int(self_renames.sum())
    return changes[~self_renames]


def _series_spans(obs: pd.DataFrame) -> pd.DataFrame:
    """Observed [first, last] per (isin, symbol, series) — parallel series are normal."""
    return (
        obs.groupby(["isin", "symbol", "series"], sort=True)["trade_date"]
        .agg(["min", "max"])
        .reset_index()
    )


def _settle_eras(
    isin: str,
    obs: pd.DataFrame,
    renames: pd.DataFrame,
    stats: dict[str, int],
    consumed: set[tuple[str, str, date]],
) -> list[_Era]:
    """Order one ISIN's symbol eras, pin boundaries, and backdate the pre-observation chain.

    Symbol spans that OVERLAP an earlier span of the same ISIN are real in official data
    (probe 2026-07-15: bond INE148I07ND6 published one day as the issuer's renamed equity
    symbol inside its own span). Same-ISIN overlap is not an identity ambiguity — every
    involved symbol maps to the same ISIN — so overlapping spans become evidence-bounded
    PARALLEL eras (counted, logged), while the disjoint remainder forms the rename chain.
    """
    mine = obs[obs["isin"] == isin]
    spans = (
        mine.groupby("symbol", sort=True)["trade_date"].agg(["min", "max"]).reset_index()
    ).sort_values(["min", "symbol"], kind="stable")
    raw_spans: list[tuple[str, date, date]] = [
        (str(r.symbol), r.min, r.max) for r in spans.itertuples(index=False)
    ]
    chain: list[tuple[str, date, date]] = []
    parallels: list[tuple[str, date, date]] = []
    for span in raw_spans:
        if not chain or span[1] > chain[-1][2]:  # starts after the current span ends
            chain.append(span)
            continue
        stats["parallel_spans"] += 1
        if span[2] <= chain[-1][2]:  # fully inside the current span's window: a blip
            parallels.append(span)
        else:  # overlapping tail that outlives the current span: it becomes the chain
            parallels.append(chain[-1])
            chain[-1] = span
        log.warning(
            "master_parallel_symbol_span",
            isin=isin,
            symbol=span[0],
            span=f"[{span[1]} .. {span[2]}]",
        )
    bounds: list[tuple[date | None, date | None]] = [(None, None)] * len(chain)
    bridge_eras: list[_Era] = []
    for i, ((old_sym, _, old_last), (new_sym, new_first, _)) in enumerate(pairwise(chain)):
        hops = _bridge_gap(renames, old_sym, new_sym, old_last, new_first, isin)
        if hops is not None:
            stats["file_pinned_boundaries"] += 1
            consumed.update(hops)  # every record on the path is explained by this ISIN
            bounds[i] = (bounds[i][0], hops[0][2] - timedelta(days=1))
            bounds[i + 1] = (hops[-1][2], bounds[i + 1][1])
            for (_, mid_sym, mid_from), (_, _, nxt_from) in pairwise(hops):
                bridge_eras.append(
                    _Era(mid_sym, None, None, mid_from, nxt_from - timedelta(days=1), True)
                )
                stats["synthetic_eras"] += 1
        else:
            stats["fallback_boundaries"] += 1
            bounds[i] = (bounds[i][0], old_last)  # unowned gap days resolve to None
            bounds[i + 1] = (new_first, bounds[i + 1][1])
    eras = [
        _Era(sym, first, last, vf, vt, synthetic=False)
        for (sym, first, last), (vf, vt) in zip(chain, bounds, strict=True)
    ]
    settled = _backdate_chain(isin, eras, renames, stats, consumed)
    settled.extend(bridge_eras)
    settled.extend(
        _Era(sym, first, last, first, last, synthetic=False, parallel=True)
        for sym, first, last in parallels
    )
    return settled


def _bridge_gap(
    renames: pd.DataFrame,
    old_sym: str,
    new_sym: str,
    old_last: date,
    new_first: date,
    isin: str,
) -> list[tuple[str, str, date]] | None:
    """Walk the rename graph backward from new_sym to old_sym inside the observation gap.

    Rename dates are exact facts only when the whole path lands inside (old_last, new_first]
    — including multi-hop paths through NEVER-OBSERVED intermediate symbols (real precedent:
    IPAPPM→ANDPAPER→ANDHRAPAP with ANDPAPER unobserved on sparse sample days). Returns the
    hop records oldest-first, or None when no in-gap path exists (fallback boundary).
    """
    hops: list[tuple[str, str, date]] = []
    current, hi = new_sym, new_first
    for _ in range(_BRIDGE_CAP):
        hits = renames[
            (renames["new_symbol"] == current)
            & (renames["applicable_from"] > old_last)
            & (renames["applicable_from"] <= hi)
        ]
        if hits.empty:
            break
        latest = hits["applicable_from"].max()
        olds = sorted(hits[hits["applicable_from"] == latest]["old_symbol"].unique())
        if len(olds) > 1:
            raise ContractViolation(
                f"{isin}: symbolchange tie — {olds} all renamed to {current!r} on {latest} "
                f"inside ({old_last}, {new_first}] — refusing to pick"
            )
        hops.append((str(olds[0]), current, latest))
        if str(olds[0]) == old_sym:
            return list(reversed(hops))
        current, hi = str(olds[0]), latest - timedelta(days=1)
    direct = renames[(renames["old_symbol"] == old_sym) & (renames["new_symbol"] == new_sym)]
    if not direct.empty:
        log.warning(
            "master_rename_outside_gap",
            isin=isin,
            old_symbol=old_sym,
            new_symbol=new_sym,
            file_dates=[str(d) for d in direct["applicable_from"].tolist()],
            gap=f"({old_last}, {new_first}]",
        )
    return None


def _backdate_chain(
    isin: str,
    eras: list[_Era],
    renames: pd.DataFrame,
    stats: dict[str, int],
    consumed: set[tuple[str, str, date]],
) -> list[_Era]:
    """Prepend synthetic eras for renames older than the first observation (doc 09 pre-2011).

    Each rename record seeds at most ONE chain across all ISINs (`consumed`); a link already
    claimed by an earlier-observed ISIN stops this chain — the pre-history is theirs.
    """
    head = eras[0]
    if head.first_seen is None:
        raise ContractViolation(f"{isin}: earliest era has no observation date")
    seen = {e.symbol for e in eras}
    anchor_symbol = head.symbol
    anchor_date: date = head.first_seen
    synthetic: list[_Era] = []
    while len(synthetic) < _CHAIN_CAP:
        hits = renames[
            (renames["new_symbol"] == anchor_symbol) & (renames["applicable_from"] <= anchor_date)
        ]
        if hits.empty:
            break
        latest = hits["applicable_from"].max()
        links = hits[hits["applicable_from"] == latest]
        olds = sorted(links["old_symbol"].unique())
        if len(olds) > 1:
            raise ContractViolation(
                f"{isin}: symbolchange tie — {olds} all renamed to {anchor_symbol!r} "
                f"on {latest}; refusing to pick a chain"
            )
        old_sym = str(olds[0])
        if old_sym in seen:
            stats["chain_stops"] += 1
            log.warning("master_chain_cycle_stop", isin=isin, symbol=old_sym)
            break
        link = (old_sym, anchor_symbol, latest)
        if link in consumed:
            stats["chain_stops"] += 1
            log.warning(
                "master_chain_link_already_claimed",
                isin=isin,
                old_symbol=old_sym,
                new_symbol=anchor_symbol,
                applicable_from=str(latest),
            )
            break
        consumed.add(link)
        # The link that created anchor_symbol pins two exact facts: the synthetic era ends the
        # day before, and the era it created gets valid_from = the rename date.
        if not synthetic:
            eras[0] = _Era(
                head.symbol, head.first_seen, head.last_seen, latest, head.valid_to, False
            )
        else:
            prev = synthetic[-1]
            synthetic[-1] = _Era(prev.symbol, None, None, latest, prev.valid_to, True)
        synthetic.append(
            _Era(old_sym, None, None, None, latest - timedelta(days=1), synthetic=True)
        )
        stats["synthetic_eras"] += 1
        seen.add(old_sym)
        anchor_symbol = old_sym
        anchor_date = latest - timedelta(days=1)
    else:
        stats["chain_stops"] += 1
        log.warning("master_chain_cap_stop", isin=isin, symbol=anchor_symbol, cap=_CHAIN_CAP)
    return list(reversed(synthetic)) + eras


def _splice_check(
    obs: pd.DataFrame, eras_by_isin: dict[str, list[_Era]], stats: dict[str, int]
) -> None:
    """PREVCLOSE splice DQ (ADR-022): first_new.prev_close must equal last_old.close.

    Comparable only when the boundary observations are (near-)adjacent trading days: with a
    sparse vault (pre-2023 sample days) a boundary can be years wide and prev_close then
    relates to an unobserved day, not to last_old. Wider gaps count as incomparable.
    """
    for isin, eras in eras_by_isin.items():
        observed = [e for e in eras if not e.synthetic and not e.parallel]
        mine = obs[obs["isin"] == isin]
        for old_era, new_era in pairwise(observed):
            if (
                new_era.first_seen is None
                or old_era.last_seen is None
                or (new_era.first_seen - old_era.last_seen).days > _SPLICE_MAX_GAP_DAYS
            ):
                stats["splice_incomparable"] += 1
                continue
            old_rows = mine[
                (mine["symbol"] == old_era.symbol) & (mine["trade_date"] == old_era.last_seen)
            ]
            new_rows = mine[
                (mine["symbol"] == new_era.symbol) & (mine["trade_date"] == new_era.first_seen)
            ]
            shared = sorted(set(old_rows["series"]) & set(new_rows["series"]))
            if not shared:
                stats["splice_incomparable"] += 1
                continue
            series = shared[0]
            close = old_rows[old_rows["series"] == series]["close"].iloc[0]
            prev_close = new_rows[new_rows["series"] == series]["prev_close"].iloc[0]
            if close is None or prev_close is None or pd.isna(close) or pd.isna(prev_close):
                stats["splice_incomparable"] += 1
            elif close == prev_close:
                stats["splice_pass"] += 1
            else:
                stats["splice_fail"] += 1
                log.warning(
                    "master_splice_mismatch",
                    isin=isin,
                    old_symbol=old_era.symbol,
                    new_symbol=new_era.symbol,
                    close=str(close),
                    prev_close=str(prev_close),
                )


def _emit_listing(
    eras_by_isin: dict[str, list[_Era]],
    spans: pd.DataFrame,
    obs: pd.DataFrame,
    stats: dict[str, int],
) -> pd.DataFrame:
    """Per era, one row per series; era bounds apply; then repair symbol recycling."""
    rows: list[dict[str, Any]] = []
    for isin, eras in eras_by_isin.items():
        mine = spans[spans["isin"] == isin]
        first_day_series = _first_day_series(obs, isin, eras)
        for era in eras:
            if era.synthetic:
                series_list = first_day_series
            else:
                series_list = sorted(mine[mine["symbol"] == era.symbol]["series"].unique())
            for series in series_list:
                rows.append(
                    {
                        "isin": isin,
                        "exchange": _EXCHANGE,
                        "symbol": era.symbol,
                        "series": series,
                        "valid_from": era.valid_from,
                        "valid_to": era.valid_to,
                        "first_obs": era.first_seen,
                        "last_obs": era.last_seen,
                    }
                )
    repaired = _repair_recycled(rows, stats)
    table = pa.table(
        {
            "isin": pa.array([r["isin"] for r in repaired], STR),
            "exchange": pa.array([r["exchange"] for r in repaired], STR),
            "symbol": pa.array([r["symbol"] for r in repaired], STR),
            "series": pa.array([r["series"] for r in repaired], STR),
            "valid_from": pa.array([r["valid_from"] for r in repaired], DATE),
            "valid_to": pa.array([r["valid_to"] for r in repaired], DATE),
        }
    )
    frame = table.to_pandas(types_mapper=pd.ArrowDtype)
    return Listing.validate(frame, lazy=True)


def _first_day_series(obs: pd.DataFrame, isin: str, eras: list[_Era]) -> list[str]:
    """Series observed on the earliest observed era's first day (synthetic-era approximation)."""
    head = next(e for e in eras if not e.synthetic and not e.parallel)
    mine = obs[
        (obs["isin"] == isin)
        & (obs["symbol"] == head.symbol)
        & (obs["trade_date"] == head.first_seen)
    ]
    return sorted(mine["series"].unique())


def _repair_recycled(rows: list[dict[str, Any]], stats: dict[str, int]) -> list[dict[str, Any]]:
    """Deterministically clip (symbol, series) intervals of different ISINs so none overlap.

    Precedence: observed facts > exact file dates > open ends. Two intervals whose OBSERVED
    spans overlap are broken identity data → ContractViolation.
    """

    def sort_key(r: dict[str, Any]) -> tuple[date, date, str]:
        anchor = r["valid_from"] or r["first_obs"] or date.min
        tail = r["valid_to"] or r["last_obs"] or date.max
        return (anchor, tail, r["isin"])

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault((r["symbol"], r["series"]), []).append(r)
    out: list[dict[str, Any]] = []
    for key in sorted(grouped):
        group = sorted(grouped[key], key=sort_key)
        # Pass 1 — a synthetic (never-observed) claim yields to another ISIN's observations:
        # observations win globally, not just per ISIN. Real precedent: an ISIN CHANGE
        # (AARVEEDEN kept its symbol across INE273D01019→INE273D01027), where the new
        # ISIN's backdated chain era overlaps the old ISIN's observed era.
        survivors = [
            r
            for r in group
            if r["first_obs"] is not None or not _synthetic_yields(r, group, stats, key)
        ]
        survivors.sort(key=sort_key)
        # Pass 2 — observed conflicts are fatal; open ends retreat to their own evidence,
        # so unowned gap days resolve to None.
        for a, b in pairwise(survivors):
            if a["isin"] == b["isin"]:
                continue  # same ISIN's eras already bounded by _settle_eras
            if (
                a["first_obs"] is not None
                and b["first_obs"] is not None
                and max(a["first_obs"], b["first_obs"]) <= min(a["last_obs"], b["last_obs"])
            ):
                raise ContractViolation(
                    f"{key}: ISINs {a['isin']} and {b['isin']} observed on overlapping days "
                    "for one (symbol, series) — identity history is broken data"
                )
            if (
                a["valid_to"] is not None
                and b["valid_from"] is not None
                and a["valid_to"] < b["valid_from"]
            ):
                continue  # disjoint by exact bounds
            # Under conflict, bounds not backed by one's OWN observations retreat to
            # evidence — file-derived tails/heads included. Real precedents: a rename
            # coinciding with an ISIN change double-claims the rename-gap days, and a
            # later-listed ISIN's paper head can reach back across an earlier ISIN's
            # observed span. EVIDENCE decides who is early: the row observed first keeps
            # its head and retreats its unobserved tail; the other retreats its head.
            early, late = sorted(
                (a, b),
                key=lambda r: (
                    r["first_obs"] or r["valid_from"] or date.min,
                    r["isin"],
                ),
            )
            clipped = False
            if early["last_obs"] is not None and (
                early["valid_to"] is None or early["valid_to"] > early["last_obs"]
            ):
                early["valid_to"] = early["last_obs"]
                clipped = True
            if late["first_obs"] is not None and (
                late["valid_from"] is None or late["valid_from"] < late["first_obs"]
            ):
                late["valid_from"] = late["first_obs"]
                clipped = True
            if clipped:
                stats["recycled_clips"] += 1
        # Pass 3 — verify: any overlap that survived repair is unrepairable identity data.
        for a, b in pairwise(sorted(survivors, key=sort_key)):
            if a["isin"] == b["isin"]:
                continue
            a_end = a["valid_to"] or a["last_obs"]
            b_start = b["valid_from"] or b["first_obs"]
            if a_end is None or b_start is None or a_end >= b_start:
                raise ContractViolation(
                    f"{key}: ISINs {a['isin']} (until {a_end}) and {b['isin']} "
                    f"(from {b_start}) claim overlapping identity and neither bound "
                    "is repairable"
                )
        out.extend(survivors)
    for r in out:
        r.pop("first_obs")
        r.pop("last_obs")
    return sorted(
        out, key=lambda r: (r["isin"], r["valid_from"] or date.min, r["symbol"], r["series"])
    )


def _synthetic_yields(
    r: dict[str, Any], group: list[dict[str, Any]], stats: dict[str, int], key: tuple[str, str]
) -> bool:
    """Clip or drop a never-observed interval colliding with another ISIN's observations.

    Returns True when the file-backdated claim is falsified outright (dropped); False when
    kept, possibly clipped to start only after the other ISIN's last observation.
    """
    for other in group:
        if other["isin"] == r["isin"] or other["first_obs"] is None:
            continue
        starts_inside = r["valid_from"] is None or r["valid_from"] <= other["last_obs"]
        ends_after_start = r["valid_to"] is None or r["valid_to"] >= other["first_obs"]
        if not (starts_inside and ends_after_start):
            continue
        if r["valid_to"] is not None and r["valid_to"] <= other["last_obs"]:
            stats["synthetic_dropped"] += 1
            log.warning(
                "master_synthetic_claim_dropped",
                symbol=key[0],
                series=key[1],
                isin=r["isin"],
                falsified_by=other["isin"],
            )
            return True
        r["valid_from"] = other["last_obs"] + timedelta(days=1)
        if other["valid_to"] is None:
            other["valid_to"] = other["last_obs"]  # the open end retreats to its evidence
        stats["recycled_clips"] += 1
        log.warning(
            "master_synthetic_claim_clipped",
            symbol=key[0],
            series=key[1],
            isin=r["isin"],
            clipped_to_start=str(r["valid_from"]),
            against=other["isin"],
        )
    return False


def _emit_security(obs: pd.DataFrame) -> pd.DataFrame:
    """One row per ISIN; name = latest observed UDiFF instrument name (display-only, ADR-022).

    Lifecycle fields stay NULL: the vault is left-censored and delisting/status facts arrive
    with later surveillance work (P0-14), not P0-10 (corporate actions) — writing "active" or
    first-seen dates would be guessed facts.
    """
    named = obs[obs["security_name"].notna()]
    latest_name: dict[str, str] = {}
    for row in named.sort_values(["trade_date", "symbol", "series"], kind="stable").itertuples(
        index=False
    ):
        latest_name[str(row.isin)] = str(row.security_name)
    isins = sorted(obs["isin"].unique())
    n = len(isins)
    table = pa.table(
        {
            "isin": pa.array(isins, STR),
            "name": pa.array([latest_name.get(i) for i in isins], STR),
            "status": pa.array([None] * n, STR),
            "first_listed": pa.array([None] * n, DATE),
            "delisted_on": pa.array([None] * n, DATE),
            "delist_terminal_price": pa.array([None] * n, dec(12, 2)),
        }
    )
    frame = table.to_pandas(types_mapper=pd.ArrowDtype)
    return Security.validate(frame, lazy=True)
