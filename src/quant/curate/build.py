"""Curation rebuild driver: raw vault → validated curated tables → atomic publish (doc 06 §6.2).

`curate_rebuild(asof)` executes the doc-06 workflow in order — parse (once; the vault is read
in a single pass and the frames are shared by every consumer) → security-master resolution →
trading calendar → corporate actions (+ operator resolutions from config) → raw price panel →
CA adjustment (pre-ex blocking, coverage floor/ceiling) → validation gate → atomic publish.
The build is a deterministic function of (raw vault, code, config, asof): the manifest digests
exactly that identity, so rebuilding unchanged inputs re-derives the same run_id and the
publish is a verified no-op. Any gate breach raises (publish blocked — stale-but-consistent
beats fresh-but-wrong); jobs exit nonzero on unhandled errors (doc 23).
"""

import hashlib
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import structlog

from quant import __version__
from quant.config import Settings, load_ca_resolutions, load_liquidity
from quant.curate import corp_actions as ca_mod
from quant.curate.adjust import adjust_prices
from quant.curate.calendar import build_calendar
from quant.curate.master import build_master_frames
from quant.curate.parsers.bhavcopy import parse_bhavcopy
from quant.curate.parsers.symbolchange import parse_symbolchange
from quant.curate.prices import build_price_panel_frames
from quant.curate.publish import PublishResult, publish
from quant.curate.universe import build_universe
from quant.errors import ContractViolation
from quant.ingest import RawStore

log = structlog.get_logger()

_CONFIG_FILES = ("sources.yaml", "calendar.yaml", "ca-resolutions.yaml", "liquidity.yaml")


@dataclass(frozen=True)
class CurateReport:
    """One rebuild's outcome: publish identity plus the per-stage accounting counters."""

    run_id: str
    path: str
    created: bool
    asof: str
    stats: dict[str, dict[str, int]]

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "path": self.path,
            "created": self.created,
            "asof": self.asof,
            "stats": self.stats,
        }


def curate_rebuild(asof: date, settings: Settings | None = None) -> CurateReport:
    """Full deterministic rebuild of the curated store as of `asof`; publishes atomically."""
    s = settings or Settings()
    store = RawStore(s)

    # Parse once — every downstream consumer shares these frames (the vault is the slow part).
    bhav_artifacts = [a for a in store.latest_per_date("bhavcopy") if a.logical_date <= asof]
    if not bhav_artifacts:
        raise ContractViolation("no bhavcopy raw files at or before asof; nothing to curate")
    rows = pd.concat(
        [parse_bhavcopy(a.path.read_bytes()) for a in bhav_artifacts], ignore_index=True
    )
    snapshots = store.latest_per_date("symbolchange")
    changes = parse_symbolchange(snapshots[-1].path.read_bytes()) if snapshots else None

    obs_columns = ["trade_date", "symbol", "series", "isin", "security_name", "close", "prev_close"]
    master = build_master_frames(rows[obs_columns], changes)
    calendar = build_calendar(s)
    calendar = calendar[calendar["d"] <= asof].reset_index(drop=True)

    resolutions = load_ca_resolutions(s)
    ca = ca_mod.build_corp_actions(s, resolutions=resolutions)
    if ca.coverage_floor is None or ca.coverage_ceiling is None:
        raise ContractViolation("corporate-actions coverage bounds unavailable; cannot adjust")

    panel = build_price_panel_frames(rows, master.listing)
    adjusted = adjust_prices(
        panel.panel,
        ca.corporate_actions,
        coverage_floor=ca.coverage_floor,
        coverage_ceiling=min(ca.coverage_ceiling, asof),
        asof=asof,
    )

    # PIT universe build (doc 06 §6.2): liquidity stats + exclusions over the adjusted panel.
    # Surveillance (P0-14) and delisting signals (security.status) are seams, inert until wired.
    universe = build_universe(
        adjusted.prices_adj,
        ca.corporate_actions,
        calendar,
        master.security,
        load_liquidity(s),
    )

    manifest: dict[str, object] = {
        "asof": str(asof),
        "code_ref": _code_ref(),
        "config_hashes": _config_hashes(s),
        "raw_watermarks": _raw_watermarks(store),
        "coverage": {"floor": str(ca.coverage_floor), "ceiling": str(ca.coverage_ceiling)},
    }
    tables = {
        "security": master.security,
        "listing": master.listing,
        "trading_calendar": calendar,
        "corporate_actions": ca.corporate_actions,
        "prices_adj": adjusted.prices_adj,
        "universe_membership": universe.frame,
    }
    result: PublishResult = publish(tables, asof=asof, manifest=manifest, settings=s)
    report = CurateReport(
        run_id=result.run_id,
        path=str(result.path),
        created=result.created,
        asof=str(asof),
        stats={
            "master": {k: int(v) for k, v in master.stats.items()},
            "corp_actions": {k: int(v) for k, v in ca.stats.items()},
            "price_panel": panel.stats,
            "adjust": adjusted.stats,
            "universe": {k: int(v) for k, v in universe.stats.items()},
            "tables": {name: len(frame) for name, frame in tables.items()},
        },
    )
    log.info("curate_rebuild_done", run_id=result.run_id, created=result.created)
    return report


def _code_ref() -> str:
    """Code identity for the manifest: git commit when available, else the package version.

    Two code states with equal identity but different outputs are caught downstream — the
    publish path byte-verifies any run_id collision (determinism breach raises loudly).
    """
    try:
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[3],
            timeout=10,
        ).stdout.strip()
        return f"git:{rev}"
    except (OSError, subprocess.SubprocessError):
        return f"version:{__version__}"


def _config_hashes(settings: Settings) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in _CONFIG_FILES:
        path = settings.config_dir / name
        if path.is_file():
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return hashes


def _raw_watermarks(store: RawStore) -> dict[str, dict[str, str]]:
    marks: dict[str, dict[str, str]] = {}
    for source in ("bhavcopy", "symbolchange", "corp_actions"):
        artifacts = store.latest_per_date(source)
        if artifacts:
            marks[source] = {
                "files": str(len(artifacts)),
                "max_fetched_at": max(a.fetched_at for a in artifacts).isoformat(),
                "max_logical_date": str(max(a.logical_date for a in artifacts)),
            }
    return marks
