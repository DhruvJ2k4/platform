"""P0-15 suite: index TRI adapter — cookie-prime + POST, 364-day chunking, gate, CLI.

niftyindices' TR endpoint is walled to scripted clients (HTML shell / tarpit, ops/journal.md
2026-08-09): the content gate refuses the shell so a live run stores nothing. These tests use a
MockTransport standing in for the day the endpoint answers — proving the adapter stores, chunks,
is idempotent, and rejects non-data.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

import quant.cli
from conftest import index_tri_bytes
from quant.cli import app
from quant.config import Settings, SourceSpec, source_spec
from quant.errors import ConfigError, SourceError
from quant.ingest import RawStore, index_tri

SOURCE = "nifty50_tri"
BODY = index_tri_bytes([("09 Jan 2026", "38000.5"), ("08 Jan 2026", "37900.25")])


@pytest.fixture
def store(tmp_path: Path) -> RawStore:
    return RawStore(Settings(data_dir=tmp_path / "data"))


@pytest.fixture
def spec() -> SourceSpec:
    return source_spec(SOURCE)  # the real committed yaml — doubles as its regression test


def _client(body: bytes = BODY, status: int = 200, *, timeout: bool = False) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            if timeout:
                raise httpx.ReadTimeout("tarpit", request=request)
            return httpx.Response(status, content=body)
        return httpx.Response(200, content=b"<html>prime</html>")  # cookie-prime GET

    return httpx.Client(transport=httpx.MockTransport(handler))


def _no_sleep(_: float) -> None:
    return None


class TestFetchWindow:
    def test_primes_then_stores_chunk(self, store: RawStore, spec: SourceSpec) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.method)
            if request.method == "POST":
                return httpx.Response(200, content=BODY)
            return httpx.Response(200)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        summary = index_tri.fetch_window(
            SOURCE, date(2026, 1, 1), date(2026, 1, 20),
            store=store, spec=spec, client=client, sleep=_no_sleep,
        )  # fmt: skip
        assert summary.stored == 1 and summary.noop == 0
        assert seen[0] == "GET"  # prime happened first
        stored = store.latest_per_date(SOURCE)
        assert len(stored) == 1 and stored[0].logical_date == date(2026, 1, 20)

    def test_long_span_chunks_by_364_days(self, store: RawStore, spec: SourceSpec) -> None:
        summary = index_tri.fetch_window(
            SOURCE, date(2020, 1, 1), date(2021, 12, 31),
            store=store, spec=spec, client=_client(), sleep=_no_sleep,
        )  # fmt: skip
        assert summary.stored == 3  # 364 + 364 + remainder
        # chunk-end logical_dates are contiguous, no dropped/overlapped day, last == until
        e1 = date(2020, 1, 1) + timedelta(days=363)
        e2 = e1 + timedelta(days=364)
        assert sorted(a.logical_date for a in store.latest_per_date(SOURCE)) == [
            e1,
            e2,
            date(2021, 12, 31),
        ]

    def test_refetch_is_noop(self, store: RawStore, spec: SourceSpec) -> None:
        kwargs = {"store": store, "spec": spec, "sleep": _no_sleep}
        first = index_tri.fetch_window(
            SOURCE, date(2026, 1, 1), date(2026, 1, 20), client=_client(), **kwargs
        )
        second = index_tri.fetch_window(
            SOURCE, date(2026, 1, 1), date(2026, 1, 20), client=_client(), **kwargs
        )
        assert first.stored == 1 and second.stored == 0 and second.noop == 1

    @pytest.mark.parametrize("status", [403, 429])
    def test_block_status_aborts(self, store: RawStore, spec: SourceSpec, status: int) -> None:
        with pytest.raises(SourceError, match="blocked"):
            index_tri.fetch_window(
                SOURCE, date(2026, 1, 1), date(2026, 1, 20),
                store=store, spec=spec, client=_client(status=status), sleep=_no_sleep,
            )  # fmt: skip

    def test_unexpected_status_aborts(self, store: RawStore, spec: SourceSpec) -> None:
        with pytest.raises(SourceError, match="unexpected HTTP 500"):
            index_tri.fetch_window(
                SOURCE, date(2026, 1, 1), date(2026, 1, 20),
                store=store, spec=spec, client=_client(status=500), sleep=_no_sleep,
            )  # fmt: skip

    def test_html_shell_rejected(self, store: RawStore, spec: SourceSpec) -> None:
        with pytest.raises(SourceError, match="not JSON"):
            index_tri.fetch_window(
                SOURCE, date(2026, 1, 1), date(2026, 1, 20),
                store=store, spec=spec, client=_client(b"<!DOCTYPE html><html>shell</html>"),
                sleep=_no_sleep,
            )  # fmt: skip

    def test_empty_body_rejected(self, store: RawStore, spec: SourceSpec) -> None:
        with pytest.raises(SourceError, match="empty response body"):
            index_tri.fetch_window(
                SOURCE, date(2026, 1, 1), date(2026, 1, 20),
                store=store, spec=spec, client=_client(b""), sleep=_no_sleep,
            )  # fmt: skip

    def test_empty_json_array_passes_gate_and_stores(
        self, store: RawStore, spec: SourceSpec
    ) -> None:
        # a well-formed empty [] is a curate-layer concern (zero-row window), not a fetch failure
        summary = index_tri.fetch_window(
            SOURCE, date(2026, 1, 1), date(2026, 1, 20),
            store=store, spec=spec, client=_client(b"[]"), sleep=_no_sleep,
        )  # fmt: skip
        assert summary.stored == 1

    def test_midcap_source_stores_via_its_own_spec(self, store: RawStore) -> None:
        # regression-cover the midcap150_tri committed spec on the adapter path (test-warden)
        spec = source_spec("midcap150_tri")
        assert spec.index_label == "NIFTY MIDCAP 150"
        summary = index_tri.fetch_window(
            "midcap150_tri", date(2026, 1, 1), date(2026, 1, 20),
            store=store, spec=spec, client=_client(), sleep=_no_sleep,
        )  # fmt: skip
        assert summary.stored == 1
        assert store.latest_per_date("midcap150_tri")[0].logical_date == date(2026, 1, 20)

    def test_timeout_is_source_error(self, store: RawStore, spec: SourceSpec) -> None:
        with pytest.raises(SourceError, match=r"tarpit|request failed"):
            index_tri.fetch_window(
                SOURCE, date(2026, 1, 1), date(2026, 1, 20),
                store=store, spec=spec, client=_client(timeout=True), sleep=_no_sleep,
            )  # fmt: skip

    def test_until_before_since_is_config_error(self, store: RawStore, spec: SourceSpec) -> None:
        with pytest.raises(ConfigError, match="before"):
            index_tri.fetch_window(
                SOURCE, date(2026, 1, 20), date(2026, 1, 1),
                store=store, spec=spec, client=_client(), sleep=_no_sleep,
            )  # fmt: skip

    def test_non_post_spec_is_config_error(self, store: RawStore) -> None:
        bad = SourceSpec(url_template="https://x", delay_seconds=0, timeout_seconds=1, headers={})
        with pytest.raises(ConfigError, match="method=POST"):
            index_tri.fetch_window(
                SOURCE, date(2026, 1, 1), date(2026, 1, 20),
                store=store, spec=bad, client=_client(), sleep=_no_sleep,
            )  # fmt: skip


class TestCli:
    def test_rejects_date_flag(self) -> None:
        result = CliRunner().invoke(app, ["ingest", SOURCE, "--date", "2026-01-20"])
        assert result.exit_code == 1
        assert "windowed source" in result.output

    def test_requires_since(self) -> None:
        result = CliRunner().invoke(app, ["ingest", SOURCE])
        assert result.exit_code == 1
        assert "requires --since" in result.output

    def test_windowed_ingest_emits_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLATFORM_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setattr(quant.cli, "_make_client", _client)
        monkeypatch.setattr(index_tri.time, "sleep", _no_sleep)
        result = CliRunner().invoke(
            app, ["ingest", SOURCE, "--since", "2026-01-01", "--until", "2026-01-20", "--json"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output.strip().splitlines()[-1])
        assert payload["source"] == SOURCE and payload["stored"] == 1
