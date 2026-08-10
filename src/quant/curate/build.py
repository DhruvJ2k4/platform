"""Curation rebuild driver: raw vault → validated curated tables → atomic publish (doc 06 §6.2).

`curate_rebuild(asof)` executes the doc-06 workflow in order — parse (once; the vault is read
in a single pass and the frames are shared by every consumer) → security-master resolution →
trading calendar → corporate actions (+ operator resolutions from config) → raw price panel →
CA adjustment (pre-ex blocking, coverage floor/ceiling) → surveillance event build (P0-14; full
ASM/GSM raw history → PIT frame + coverage bounds) → PIT universe build → validation gate →
atomic publish.
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
from quant.curate.index_tri import build_index_tri
from quant.curate.master import build_master_frames
from quant.curate.parsers.bhavcopy import parse_bhavcopy
from quant.curate.parsers.symbolchange import parse_symbolchange
from quant.curate.prices import build_price_panel_frames
from quant.curate.publish import PublishResult, publish
from quant.curate.surveillance import build_surveillance
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

    # Surveillance (P0-14): full-history ASM/GSM event frame + coverage bounds. `surv.frame` is
    # always a real (possibly empty) DataFrame and floor/ceiling are None together whenever
    # either category has zero raw snapshots ever — passed through UNCONDITIONALLY (no special-
    # casing needed): on the real vault today this is a strict no-op vs. surveillance=None,
    # because build_universe's floor/ceiling gate only the affirmative path (curate/universe.py).
    surv = build_surveillance(s)
    if surv.stats["surveillance_gap_days_max"] > 14:
        log.warning(
            "surveillance_ingestion_gap",
            gap_days=surv.stats["surveillance_gap_days_max"],
            note="intra-gap blind spot — see curate/surveillance.py module docstring",
        )
    if surv.stats["gsm_survdesc_mentions_asm_ibc"] > 0:
        log.warning(
            "surveillance_gsm_asm_ibc_signal",
            count=surv.stats["gsm_survdesc_mentions_asm_ibc"],
            note="possible ASM signal inside GSM text, not mined for exclusion — operator review",
        )
    # Staleness relative to THIS build (execution-trader review): surveillance_gap_days_max only
    # catches a gap BETWEEN two ingested snapshots — if ingestion stops entirely and never
    # resumes, that stat freezes and stays silent while every later rebuild's asof drifts further
    # past coverage_ceiling. investable already degrades safely either way (bounded=False once
    # d>ceiling — curate/universe.py), but a live-dark ingestion pipeline deserves its own signal
    # now rather than waiting on unscheduled P0-17 absence-of-data alarm work.
    days_since_ceiling = (asof - surv.coverage_ceiling).days if surv.coverage_ceiling else -1
    surv.stats["surveillance_days_since_ceiling"] = days_since_ceiling  # -1 = no ceiling yet
    if days_since_ceiling > 14:
        log.warning(
            "surveillance_ceiling_stale",
            days_since_ceiling=days_since_ceiling,
            coverage_ceiling=str(surv.coverage_ceiling),
            note="no ASM/GSM snapshot ingested in >14d relative to this build's asof",
        )

    # PIT universe build (doc 06 §6.2): liquidity stats + exclusions over the adjusted panel.
    # Delisting signals (security.status) stay a tested-but-inert hook — no NSE source identified.
    universe = build_universe(
        adjusted.prices_adj,
        ca.corporate_actions,
        calendar,
        master.security,
        load_liquidity(s),
        surveillance=surv.frame,
        surveillance_coverage_floor=surv.coverage_floor,
        surveillance_coverage_ceiling=surv.coverage_ceiling,
    )

    # Benchmark TR series (P0-15, ADR-008): parse every raw TR chunk -> index_tri, gap-checked
    # vs the calendar. On the real vault today both sources are empty (sourcing blocker,
    # ops/journal.md 2026-08-10), so this publishes zero rows -- honest, inert on real data.
    index_tri_result = build_index_tri(calendar, asof, s)
    its = index_tri_result.stats
    if its["rows"] == 0:  # loud zero-state (PM review, P0-14): never a silent absent benchmark
        log.warning(
            "index_tri_benchmark_unavailable",
            note="no TRI rows -- niftyindices sourcing blocked (ADR-028); P1-10/§14 blocked",
        )
    if its["gap_days_max"] > 14:
        log.warning(
            "index_tri_gap",
            gap_days=its["gap_days_max"],
            note="longest run of consecutive trading sessions with no TRI value in the overlap",
        )
    if its["conflicts"] > 0:  # a series with drifting values across chunks was quarantined (empty)
        log.warning(
            "index_tri_value_conflict",
            conflicts=its["conflicts"],
            note="a TRI series had conflicting values across chunks -- quarantined (empty)",
        )
    # extraneous_dates is recorded (stats/manifest) but NOT alarmed: under the sampled vault it is
    # dominated by calendar incompleteness, meaningful only once P0-19 densifies it (ADR-028).

    manifest: dict[str, object] = {
        "asof": str(asof),
        "code_ref": _code_ref(),
        "config_hashes": _config_hashes(s),
        "raw_watermarks": _raw_watermarks(store),
        "coverage": {
            "floor": str(ca.coverage_floor),
            "ceiling": str(ca.coverage_ceiling),
            "surveillance_floor": str(surv.coverage_floor) if surv.coverage_floor else None,
            "surveillance_ceiling": str(surv.coverage_ceiling) if surv.coverage_ceiling else None,
        },
        # Benchmark quality persisted in-band (risk-manager review): a read_current("index_tri")
        # consumer (P1-10 relative performance) reads these from manifest.json to gate on gaps,
        # rather than depending on the operator having watched the build log's WARNs.
        "index_tri": {
            "rows": its["rows"],
            "gap_days_max": its["gap_days_max"],
            "extraneous_dates": its["extraneous_dates"],
            "conflicts": its["conflicts"],
        },
    }
    tables = {
        "security": master.security,
        "listing": master.listing,
        "trading_calendar": calendar,
        "corporate_actions": ca.corporate_actions,
        "prices_adj": adjusted.prices_adj,
        "universe_membership": universe.frame,
        "index_tri": index_tri_result.frame,
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
            "surveillance": {k: int(v) for k, v in surv.stats.items()},
            "universe": {k: int(v) for k, v in universe.stats.items()},
            "index_tri": {k: int(v) for k, v in index_tri_result.stats.items()},
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
    for source in (
        "bhavcopy",
        "symbolchange",
        "corp_actions",
        "asm",
        "gsm",
        "nifty50_tri",
        "midcap150_tri",
    ):
        artifacts = store.latest_per_date(source)
        if artifacts:
            marks[source] = {
                "files": str(len(artifacts)),
                "max_fetched_at": max(a.fetched_at for a in artifacts).isoformat(),
                "max_logical_date": str(max(a.logical_date for a in artifacts)),
            }
    return marks
