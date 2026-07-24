"""Atomic versioned publish of the curated store (doc 06 §6.2; doc 08; ADR-024).

A publish writes every curated table as parquet into an immutable version directory
`data/curated/versions/<run_id>/` (prices_adj hive-partitioned by year, files sorted
(isin, d) — doc 10), plus a `manifest.json` carrying the doc-08 identity (raw watermarks
from the registry, code/config identity, build stats). Consumers see a version only after
the one-line `data/curated/CURRENT` pointer is swapped via os.replace — atomic on POSIX, so
a reader never observes a half-written store (stale-but-consistent). run_id is
`curate-{asof}-{shorthash}` where the shorthash digests the manifest identity — fully
deterministic, no wall-clock (doc 23): rebuilding identical inputs yields the same run_id,
and publishing it again is a verified no-op (byte-compare; a content mismatch under an
identical run_id is a determinism breach → ContractViolation). Reads go through
`read_current()` on the Arrow path — never `.df()` (ADR-021).
"""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import structlog

from quant.config import Settings
from quant.errors import ConfigError, ContractViolation
from quant.schemas import TABLES

log = structlog.get_logger()

_POINTER = "CURRENT"
_MANIFEST = "manifest.json"
_SHORTHASH_LEN = 8
# Tables this publish owns; later tasks extend (TRI P0-15…). universe_membership joined in P0-13.
PUBLISHED_TABLES = (
    "security",
    "listing",
    "trading_calendar",
    "corporate_actions",
    "prices_adj",
    "universe_membership",
)
# Hive-partitioned by year, files sorted (isin, d) — doc 10 (prices_adj) generalised to the
# universe so `universe --date` reads one year-partition with a d predicate (<1s, P0-13).
_YEAR_PARTITIONED = frozenset({"prices_adj", "universe_membership"})


@dataclass(frozen=True)
class PublishResult:
    """Outcome of one publish: the version identity and whether anything new was written."""

    run_id: str
    path: Path
    created: bool  # False = identical version already published (idempotent no-op)


def _curated_root(settings: Settings | None) -> Path:
    s = settings or Settings()
    return s.data_dir / "curated"


def run_id_for(asof: date, manifest_identity: dict[str, object]) -> str:
    """Deterministic run id: curate-{yyyymmdd}-{shorthash of the canonical identity JSON}."""
    canonical = json.dumps(manifest_identity, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:_SHORTHASH_LEN]
    return f"curate-{asof.strftime('%Y%m%d')}-{digest}"


def publish(
    tables: dict[str, pd.DataFrame],
    *,
    asof: date,
    manifest: dict[str, object],
    settings: Settings | None = None,
) -> PublishResult:
    """Write one immutable curated version and atomically repoint CURRENT at it.

    tables must cover exactly PUBLISHED_TABLES, already validated by their contracts (the
    caller is the validation gate). The version directory is staged under a dot-prefixed
    name and renamed into place before the pointer swap, so a crash at any step leaves
    either the old version current or the new one — never a torn store.
    """
    missing = [t for t in PUBLISHED_TABLES if t not in tables]
    extra = [t for t in tables if t not in PUBLISHED_TABLES]
    if missing or extra:
        raise ContractViolation(
            f"publish expects exactly {list(PUBLISHED_TABLES)}; missing={missing} extra={extra}"
        )
    for name, frame in tables.items():
        TABLES[name].validate(frame, lazy=True)  # the gate's schema half, re-checked at the door

    identity = {k: manifest[k] for k in sorted(manifest)}
    rid = run_id_for(asof, identity)
    root = _curated_root(settings)
    version_dir = root / "versions" / rid

    if version_dir.exists():
        _verify_identical(version_dir, tables, identity)
        _swap_pointer(root, rid)
        log.info("publish_noop_identical", run_id=rid)
        return PublishResult(run_id=rid, path=version_dir, created=False)

    staging = root / "versions" / f".staging-{rid}"
    if staging.exists():  # a previous crash left debris; staging is disposable by design
        _rmtree(staging)
    staging.mkdir(parents=True)
    try:
        for name in PUBLISHED_TABLES:
            _write_table(staging, name, tables[name])
        (staging / _MANIFEST).write_text(
            json.dumps({"run_id": rid, **identity}, indent=2, sort_keys=True, default=str)
        )
        os.rename(staging, version_dir)  # same filesystem; atomic directory move
    except OSError:
        _rmtree(staging)
        raise
    _swap_pointer(root, rid)
    log.info("published", run_id=rid, path=str(version_dir))
    return PublishResult(run_id=rid, path=version_dir, created=True)


def _write_table(version_dir: Path, name: str, frame: pd.DataFrame) -> None:
    """One table → parquet; year-partitioned tables sorted (isin, d) and split by year — doc 10."""
    if name in _YEAR_PARTITIONED:
        frame = frame.sort_values(["isin", "d"], kind="stable").reset_index(drop=True)
        years = pd.Series([d.year for d in frame["d"]], index=frame.index)
        for year in sorted(years.unique()):
            part = frame[years == year].reset_index(drop=True)
            part_dir = version_dir / name / f"year={year}"
            part_dir.mkdir(parents=True)
            pq.write_table(
                pa.Table.from_pandas(part, preserve_index=False), part_dir / "part-0.parquet"
            )
        if len(frame) == 0:  # keep the table addressable even when empty
            (version_dir / name).mkdir(parents=True, exist_ok=True)
        return
    pq.write_table(
        pa.Table.from_pandas(frame.reset_index(drop=True), preserve_index=False),
        version_dir / f"{name}.parquet",
    )


def _swap_pointer(root: Path, rid: str) -> None:
    tmp = root / f".{_POINTER}.tmp"
    tmp.write_text(rid + "\n")
    os.replace(tmp, root / _POINTER)  # atomic on POSIX


def _verify_identical(
    version_dir: Path, tables: dict[str, pd.DataFrame], identity: dict[str, object]
) -> None:
    """An existing version under this run_id must be byte-equal to what we would write.

    The run_id digests the input identity, so a mismatch means the build is not a pure
    function of its inputs — the exact failure the rebuild-determinism property forbids.
    """
    manifest_path = version_dir / _MANIFEST
    if not manifest_path.is_file():
        raise ContractViolation(f"published version {version_dir} lacks {_MANIFEST}")
    existing = json.loads(manifest_path.read_text())
    rid = existing.pop("run_id", None)
    fresh = json.loads(json.dumps(identity, default=str))
    if existing != fresh:
        raise ContractViolation(
            f"run_id {rid} exists with a different manifest — determinism breach or hash clash"
        )


def _rmtree(path: Path) -> None:
    for child in sorted(path.rglob("*"), reverse=True):
        child.unlink() if child.is_file() else child.rmdir()
    path.rmdir()


def current_run_id(settings: Settings | None = None) -> str:
    """The run_id CURRENT points at; ConfigError when nothing has been published yet."""
    pointer = _curated_root(settings) / _POINTER
    if not pointer.is_file():
        raise ConfigError("no curated store published yet: run `platform curate --rebuild`")
    return pointer.read_text().strip()


def version_dir(settings: Settings | None = None) -> Path:
    """Absolute path of the CURRENT published version directory (public read accessor)."""
    return _curated_root(settings) / "versions" / current_run_id(settings)


def read_current(table: str, settings: Settings | None = None) -> pd.DataFrame:
    """Typed read of one published table from the CURRENT version (Arrow path, ADR-021)."""
    if table not in PUBLISHED_TABLES:
        raise ConfigError(f"unknown published table {table!r}; available: {list(PUBLISHED_TABLES)}")
    version_dir = _curated_root(settings) / "versions" / current_run_id(settings)
    if table in _YEAR_PARTITIONED:
        dataset = pq.ParquetDataset(version_dir / table)
        arrow = dataset.read()
        # hive partition column 'year' is derivational, not part of the doc-10 contract
        if "year" in arrow.column_names:
            arrow = arrow.drop_columns(["year"])
        frame = arrow.to_pandas(types_mapper=pd.ArrowDtype)
        frame = frame.sort_values(["isin", "d"], kind="stable").reset_index(drop=True)
    else:
        frame = pq.read_table(version_dir / f"{table}.parquet").to_pandas(
            types_mapper=pd.ArrowDtype
        )
    validated: pd.DataFrame = TABLES[table].validate(frame, lazy=True)
    return validated
