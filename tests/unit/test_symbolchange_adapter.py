"""P0-09 suite: symbolchange snapshot adapter — idempotent store, block rejects, CLI rules."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

import quant.cli
from quant.cli import app
from quant.config import Settings, source_spec
from quant.errors import SourceError
from quant.ingest import RawStore, symbolchange

CSV = b"New Co Ltd,OLDCO,NEWCO,24-AUG-2023\n"
D = date(2026, 7, 15)


@pytest.fixture
def store(tmp_path: Path) -> RawStore:
    return RawStore(Settings(data_dir=tmp_path / "data"))


@pytest.fixture
def spec():
    return source_spec("symbolchange")  # the real committed yaml — doubles as its regression test


def _client(content: bytes, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=content)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _no_sleep(_: float) -> None:
    return None


class TestFetchSnapshot:
    def test_stores_then_refetch_is_noop(self, store: RawStore, spec) -> None:
        client = _client(CSV)
        kwargs = {"store": store, "spec": spec, "client": client, "sleep": _no_sleep}
        first = symbolchange.fetch_snapshot(D, **kwargs)
        second = symbolchange.fetch_snapshot(D, **kwargs)
        assert first[1] is True
        assert second[1] is False
        assert second[0].sha256 == first[0].sha256

    def test_grown_snapshot_supersedes(self, store: RawStore, spec) -> None:
        symbolchange.fetch_snapshot(D, store=store, spec=spec, client=_client(CSV), sleep=_no_sleep)
        grown = CSV + b"Another Co,AAA,BBB,01-JAN-2024\n"
        artifact, created = symbolchange.fetch_snapshot(
            D, store=store, spec=spec, client=_client(grown), sleep=_no_sleep
        )
        assert created is True
        assert len(store.history("symbolchange", D)) == 2
        assert artifact.path.read_bytes() == grown

    @pytest.mark.parametrize("status", [403, 429])
    def test_block_status_aborts_loudly(self, store: RawStore, spec, status: int) -> None:
        with pytest.raises(SourceError, match="blocked"):
            symbolchange.fetch_snapshot(
                D, store=store, spec=spec, client=_client(b"x", status), sleep=_no_sleep
            )

    def test_404_is_an_error_not_a_holiday(self, store: RawStore, spec) -> None:
        with pytest.raises(SourceError, match="unexpected HTTP 404"):
            symbolchange.fetch_snapshot(
                D, store=store, spec=spec, client=_client(b"x", 404), sleep=_no_sleep
            )

    def test_html_block_page_is_rejected(self, store: RawStore, spec) -> None:
        with pytest.raises(SourceError, match="block page"):
            symbolchange.fetch_snapshot(
                D,
                store=store,
                spec=spec,
                client=_client(b"<!DOCTYPE html><html>denied</html>"),
                sleep=_no_sleep,
            )

    def test_empty_body_is_rejected(self, store: RawStore, spec) -> None:
        with pytest.raises(SourceError, match="empty"):
            symbolchange.fetch_snapshot(
                D, store=store, spec=spec, client=_client(b"  \n"), sleep=_no_sleep
            )


class TestCli:
    def test_snapshot_rejects_range_flags(self) -> None:
        runner = CliRunner()
        result = runner.invoke(app, ["ingest", "symbolchange", "--since", "2026-01-01"])
        assert result.exit_code == 1
        assert "snapshot source" in result.output

    def test_snapshot_ingest_with_date_emits_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLATFORM_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setattr(quant.cli, "_make_client", lambda: _client(CSV))
        monkeypatch.setattr(symbolchange.time, "sleep", _no_sleep)
        runner = CliRunner()
        result = runner.invoke(app, ["ingest", "symbolchange", "--date", "2026-07-15", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output.strip().splitlines()[-1])
        assert payload["source"] == "symbolchange"
        assert payload["logical_date"] == "2026-07-15"
        assert payload["stored"] is True
