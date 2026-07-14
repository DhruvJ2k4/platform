"""Immutable raw store: atomic content-addressed writes + the raw_registry ledger (doc 06 §6.1).

put() is idempotent by (source, logical_date, sha256): identical bytes are a no-op; changed
bytes append a supersession row and a new file — nothing is ever overwritten or deleted
(doc 08). A file lands atomically (tmp + fsync + rename) BEFORE its registry row, so a crash
between the two heals on the next ingest; landed files are chmod'd read-only. Timestamps are
naive UTC, matching the raw_registry contract's timestamp[us].
"""

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import structlog

from quant.config import Settings
from quant.errors import ConfigError, SourceError
from quant.schemas import RawRegistry, arrow_frame, ddl_sql

log = structlog.get_logger()

_SHA_PREFIX_LEN = 12
_SOURCE_NAME = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True, slots=True)
class RawArtifact:
    """One immutable raw file — the doc-06 fetch() result shape."""

    source: str
    logical_date: date
    path: Path
    sha256: str
    fetched_at: datetime


class RawStore:
    """Content-addressed immutable raw-file store over a DuckDB raw_registry ledger."""

    def __init__(self, settings: Settings | None = None) -> None:
        s = settings or Settings()
        self._raw_dir = s.data_dir / "raw"
        self._db_path = s.data_dir / "operational.duckdb"

    def put(
        self,
        source: str,
        logical_date: date,
        content: bytes,
        suffix: str = ".csv",
        fetched_at: datetime | None = None,
    ) -> tuple[RawArtifact, bool]:
        """Store one downloaded file; returns (artifact, created).

        created is True only when a new content version was registered. Identical bytes for
        the same (source, logical_date) are a complete no-op; changed bytes append a
        supersession row. A registered-but-missing file (forbidden manual deletion) is
        restored from content without a new row, logged as a warning, created=False.
        """
        _validate_source(source)
        if not content:
            raise SourceError(f"refusing empty download for {source} {logical_date}")
        sha = hashlib.sha256(content).hexdigest()
        path = self._path_for(source, logical_date, sha, suffix)
        existing_fetched = self._find_row(source, logical_date, sha)
        file_exists = path.is_file()

        if file_exists and existing_fetched is not None:
            log.info("raw_noop", source=source, logical_date=str(logical_date), sha256=sha)
            return RawArtifact(source, logical_date, path, sha, existing_fetched), False

        if not file_exists:
            self._atomic_write(path, content)

        if existing_fetched is not None:
            log.warning(
                "raw_file_restored",
                source=source,
                logical_date=str(logical_date),
                sha256=sha,
                path=str(path),
            )
            return RawArtifact(source, logical_date, path, sha, existing_fetched), False

        fetched = fetched_at or datetime.now(tz=UTC).replace(tzinfo=None)
        superseded = self._count_rows(source, logical_date) > 0
        self._append_row(source, logical_date, path, sha, fetched)
        log.info(
            "raw_superseded" if superseded else "raw_written",
            source=source,
            logical_date=str(logical_date),
            sha256=sha,
            path=str(path),
        )
        return RawArtifact(source, logical_date, path, sha, fetched), True

    def latest(self, source: str, logical_date: date) -> RawArtifact | None:
        """The registered artifact currently in force (max fetched_at), if any."""
        rows = self.history(source, logical_date)
        return rows[-1] if rows else None

    def latest_per_date(self, source: str) -> list[RawArtifact]:
        """The artifact in force (max fetched_at) for EVERY logical_date of a source, ascending."""
        _validate_source(source)
        with self._connect() as con:
            rel = con.sql(
                "SELECT * FROM raw_registry WHERE source = ? QUALIFY row_number() "
                "OVER (PARTITION BY logical_date ORDER BY fetched_at DESC) = 1 "
                "ORDER BY logical_date",
                params=[source],
            )
            frame = arrow_frame(rel)
        validated = RawRegistry.validate(frame, lazy=True)
        return [self._artifact_from(row) for row in validated.itertuples(index=False)]

    def history(self, source: str, logical_date: date) -> list[RawArtifact]:
        """All registered artifacts for (source, logical_date), ascending by fetched_at."""
        _validate_source(source)
        with self._connect() as con:
            rel = con.sql(
                "SELECT * FROM raw_registry WHERE source = ? AND logical_date = ? "
                "ORDER BY fetched_at",
                params=[source, logical_date],
            )
            frame = arrow_frame(rel)
        validated = RawRegistry.validate(frame, lazy=True)
        return [self._artifact_from(row) for row in validated.itertuples(index=False)]

    @staticmethod
    def _artifact_from(row: object) -> RawArtifact:
        logical = row.logical_date  # type: ignore[attr-defined]
        if isinstance(logical, datetime):
            logical = logical.date()
        fetched = row.fetched_at  # type: ignore[attr-defined]
        if hasattr(fetched, "to_pydatetime"):
            fetched = fetched.to_pydatetime()
        return RawArtifact(
            row.source,  # type: ignore[attr-defined]
            logical,
            Path(row.path),  # type: ignore[attr-defined]
            row.sha256,  # type: ignore[attr-defined]
            fetched,
        )

    def _path_for(self, source: str, logical_date: date, sha: str, suffix: str) -> Path:
        name = f"{source}-{logical_date.isoformat()}-{sha[:_SHA_PREFIX_LEN]}{suffix}"
        return self._raw_dir / source / f"{logical_date.year:04d}" / name

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            with open(tmp, "wb") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise
        path.chmod(0o444)

    def _connect(self) -> duckdb.DuckDBPyConnection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(self._db_path))
        table_count = con.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE table_name = 'raw_registry'"
        ).fetchone()
        if table_count is None or table_count[0] == 0:
            con.execute(ddl_sql("raw_registry"))
        return con

    def _find_row(self, source: str, logical_date: date, sha: str) -> datetime | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT fetched_at FROM raw_registry "
                "WHERE source = ? AND logical_date = ? AND sha256 = ?",
                [source, logical_date, sha],
            ).fetchone()
        return row[0] if row else None

    def _count_rows(self, source: str, logical_date: date) -> int:
        with self._connect() as con:
            row = con.execute(
                "SELECT count(*) FROM raw_registry WHERE source = ? AND logical_date = ?",
                [source, logical_date],
            ).fetchone()
        return int(row[0]) if row else 0

    def _append_row(
        self, source: str, logical_date: date, path: Path, sha: str, fetched: datetime
    ) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO raw_registry VALUES (?, ?, ?, ?, ?)",
                [source, logical_date, str(path), sha, fetched],
            )


def _validate_source(source: str) -> None:
    if not _SOURCE_NAME.fullmatch(source):
        raise ConfigError(f"invalid source name {source!r}: must match [a-z0-9_]+")
