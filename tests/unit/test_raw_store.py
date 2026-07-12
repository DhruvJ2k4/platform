"""P0-04 DoD suite: idempotent re-ingest is a no-op; supersession, atomicity, immutability."""

import hashlib
import stat
from datetime import date, datetime
from pathlib import Path

import pytest

from quant.config import Settings
from quant.errors import ConfigError, SourceError
from quant.ingest import RawStore

D = date(2026, 7, 10)
T1 = datetime(2026, 7, 10, 19, 30, 0)
T2 = datetime(2026, 7, 11, 9, 0, 0)
CONTENT = b"SYMBOL,SERIES,CLOSE\nRELIANCE,EQ,2931.55\n"


@pytest.fixture
def store(tmp_path: Path) -> RawStore:
    return RawStore(Settings(data_dir=tmp_path / "data"))


def _registry_rows(store: RawStore) -> int:
    with store._connect() as con:
        row = con.execute("SELECT count(*) FROM raw_registry").fetchone()
    return int(row[0])


def _raw_files(tmp_path: Path) -> list[Path]:
    return sorted(p for p in (tmp_path / "data" / "raw").rglob("*") if p.is_file())


class TestIdempotentReingest:
    def test_first_put_writes_file_and_row(self, store: RawStore, tmp_path: Path) -> None:
        artifact, created = store.put("bhavcopy", D, CONTENT, fetched_at=T1)
        assert created is True
        assert artifact.path.is_file()
        assert artifact.sha256 == hashlib.sha256(CONTENT).hexdigest()
        assert artifact.sha256[:12] in artifact.path.name
        assert artifact.fetched_at == T1
        assert _registry_rows(store) == 1
        assert len(_raw_files(tmp_path)) == 1

    def test_reingest_same_bytes_is_noop(self, store: RawStore, tmp_path: Path) -> None:
        first, created_first = store.put("bhavcopy", D, CONTENT, fetched_at=T1)
        mtime_before = first.path.stat().st_mtime_ns

        second, created_second = store.put("bhavcopy", D, CONTENT, fetched_at=T2)

        assert created_first is True
        assert created_second is False
        assert second.path == first.path
        assert second.sha256 == first.sha256
        assert second.fetched_at == T1  # provenance of the original ingest, not the retry
        assert _registry_rows(store) == 1
        assert len(_raw_files(tmp_path)) == 1
        assert first.path.stat().st_mtime_ns == mtime_before
        assert first.path.read_bytes() == CONTENT


class TestSupersession:
    def test_changed_bytes_append_new_version(self, store: RawStore, tmp_path: Path) -> None:
        changed = CONTENT + b"INFY,EQ,1614.20\n"
        old, _ = store.put("bhavcopy", D, CONTENT, fetched_at=T1)
        new, created = store.put("bhavcopy", D, changed, fetched_at=T2)

        assert created is True
        assert new.path != old.path
        assert _registry_rows(store) == 2
        assert len(_raw_files(tmp_path)) == 2
        assert old.path.read_bytes() == CONTENT  # nothing mutated or deleted

        latest = store.latest("bhavcopy", D)
        assert latest is not None
        assert latest.sha256 == new.sha256
        history = store.history("bhavcopy", D)
        assert [a.sha256 for a in history] == [old.sha256, new.sha256]

    def test_latest_none_for_unknown(self, store: RawStore) -> None:
        assert store.latest("bhavcopy", D) is None


class TestAtomicity:
    def test_no_tmp_residue_after_success(self, store: RawStore, tmp_path: Path) -> None:
        store.put("bhavcopy", D, CONTENT, fetched_at=T1)
        assert not list((tmp_path / "data").rglob("*.tmp"))

    def test_failed_rename_leaves_no_file_and_no_row(
        self, store: RawStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(src: str, dst: str) -> None:
            raise OSError("simulated rename failure")

        monkeypatch.setattr("quant.ingest.store.os.replace", boom)
        with pytest.raises(OSError, match="simulated"):
            store.put("bhavcopy", D, CONTENT, fetched_at=T1)
        assert _registry_rows(store) == 0
        assert not _raw_files(tmp_path)
        assert not list((tmp_path / "data").rglob("*.tmp"))


class TestImmutability:
    def test_landed_file_is_readonly(self, store: RawStore) -> None:
        artifact, _ = store.put("bhavcopy", D, CONTENT, fetched_at=T1)
        mode = stat.S_IMODE(artifact.path.stat().st_mode)
        assert mode == 0o444


class TestRegistryIntegrity:
    def test_table_matches_authoritative_ddl(self, store: RawStore) -> None:
        store.put("bhavcopy", D, CONTENT, fetched_at=T1)
        with store._connect() as con:
            cols = [r[0] for r in con.execute("DESCRIBE raw_registry").fetchall()]
        assert cols == ["source", "logical_date", "path", "sha256", "fetched_at"]

    def test_history_roundtrips_through_contract(self, store: RawStore) -> None:
        store.put("bhavcopy", D, CONTENT, fetched_at=T1)
        artifact = store.history("bhavcopy", D)[0]
        assert artifact.source == "bhavcopy"
        assert artifact.logical_date == D
        assert artifact.fetched_at == T1


class TestFailureModes:
    def test_empty_content_rejected(self, store: RawStore) -> None:
        with pytest.raises(SourceError, match="empty download"):
            store.put("bhavcopy", D, b"", fetched_at=T1)

    def test_unsafe_source_name_rejected(self, store: RawStore) -> None:
        with pytest.raises(ConfigError, match="invalid source name"):
            store.put("../evil", D, CONTENT, fetched_at=T1)
