"""P0-06 suite: bhavcopy adapter — no-op re-fetch, holiday 404, block/corrupt rejects, CLI."""

import io
import json
import zipfile
from datetime import date
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

import quant.cli
from quant.cli import app
from quant.config import Settings, source_spec
from quant.errors import ConfigError, SourceError
from quant.ingest import RawStore, bhavcopy

FIXTURE = (
    Path(__file__).parent.parent
    / "fixtures"
    / "bhavcopy"
    / "BhavCopy_NSE_CM_0_0_0_20260708_F_0000.csv.zip"
)
D = date(2026, 7, 8)  # Wednesday; matches the fixture's date


@pytest.fixture
def store(tmp_path: Path) -> RawStore:
    return RawStore(Settings(data_dir=tmp_path / "data"))


@pytest.fixture
def spec():
    return source_spec("bhavcopy")  # the real committed yaml — doubles as its regression test


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _serve(content: bytes, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=content)

    return handler


def _no_sleep(_: float) -> None:
    return None


class TestFetch:
    def test_stores_then_refetch_is_noop(self, store: RawStore, spec) -> None:
        client = _client(_serve(FIXTURE.read_bytes()))
        first = bhavcopy.fetch(D, store=store, spec=spec, client=client, sleep=_no_sleep)
        second = bhavcopy.fetch(D, store=store, spec=spec, client=client, sleep=_no_sleep)
        assert first is not None and first[1] is True
        assert second is not None and second[1] is False
        assert second[0].sha256 == first[0].sha256
        assert len(store.history("bhavcopy", D)) == 1  # doc 13 F1: re-run is a no-op

    def test_holiday_404_is_expected_absence(self, store: RawStore, spec) -> None:
        client = _client(_serve(b"", status=404))
        assert bhavcopy.fetch(D, store=store, spec=spec, client=client, sleep=_no_sleep) is None
        assert store.history("bhavcopy", D) == []

    @pytest.mark.parametrize("status", [403, 429])
    def test_block_aborts_without_retry(self, store: RawStore, spec, status: int) -> None:
        client = _client(_serve(b"denied", status=status))
        with pytest.raises(SourceError, match="blocked"):
            bhavcopy.fetch(D, store=store, spec=spec, client=client, sleep=_no_sleep)

    def test_unexpected_status_raises(self, store: RawStore, spec) -> None:
        client = _client(_serve(b"oops", status=500))
        with pytest.raises(SourceError, match="unexpected HTTP 500"):
            bhavcopy.fetch(D, store=store, spec=spec, client=client, sleep=_no_sleep)

    def test_block_page_html_rejected_nothing_stored(self, store: RawStore, spec) -> None:
        client = _client(_serve(b"<html>Access Denied</html>"))
        with pytest.raises(SourceError, match="not a zip"):
            bhavcopy.fetch(D, store=store, spec=spec, client=client, sleep=_no_sleep)
        assert store.history("bhavcopy", D) == []

    def test_crc_corruption_rejected(self, store: RawStore, spec) -> None:
        buf = io.BytesIO()
        info = zipfile.ZipInfo("x.csv", date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_STORED
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(info, "A,B\n1,2\n" * 10)
        corrupt = bytearray(buf.getvalue())
        corrupt[30 + len("x.csv") + 5] ^= 0xFF  # flip a byte inside the stored member data
        client = _client(_serve(bytes(corrupt)))
        with pytest.raises(SourceError, match="CRC check failed"):
            bhavcopy.fetch(D, store=store, spec=spec, client=client, sleep=_no_sleep)
        assert store.history("bhavcopy", D) == []


class TestFetchRange:
    def test_week_skips_weekend_counts_holiday_sleeps_per_request(
        self,
        store: RawStore,
        spec,
    ) -> None:
        requested: list[str] = []
        events: list[str] = []
        fixture_bytes = FIXTURE.read_bytes()

        def handler(request: httpx.Request) -> httpx.Response:
            events.append("request")
            requested.append(str(request.url))
            if "20260603" in str(request.url):  # injected mid-week holiday
                return httpx.Response(404)
            return httpx.Response(200, content=fixture_bytes)

        summary = bhavcopy.fetch_range(
            date(2026, 6, 1),  # Monday
            date(2026, 6, 7),  # Sunday
            store=store,
            spec=spec,
            client=_client(handler),
            sleep=lambda _: events.append("sleep"),
        )
        assert summary.stored == 4 and summary.holiday == 1 and summary.noop == 0
        # politeness fires BEFORE every request, strictly interleaved
        assert events == ["sleep", "request"] * 5
        assert not any("20260606" in u or "20260607" in u for u in requested)  # Sat/Sun

        again = bhavcopy.fetch_range(
            date(2026, 6, 1),
            date(2026, 6, 7),
            store=store,
            spec=spec,
            client=_client(handler),
            sleep=lambda _: events.append("sleep"),
        )
        assert again.stored == 0 and again.noop == 4 and again.holiday == 1

    def test_until_before_since_rejected(self, store: RawStore, spec) -> None:
        with pytest.raises(ConfigError, match="before"):
            bhavcopy.fetch_range(
                date(2026, 6, 2),
                date(2026, 6, 1),
                store=store,
                spec=spec,
                client=_client(_serve(b"")),
                sleep=_no_sleep,
            )


class TestCli:
    @pytest.fixture(autouse=True)
    def _no_real_sleep(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The CLI path uses the committed 3.5s delay; unit tests must stay fast (doc 16)."""
        monkeypatch.setattr("quant.ingest.bhavcopy.time.sleep", lambda _: None)

    def test_ingest_date_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PLATFORM_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setattr(
            quant.cli, "_make_client", lambda: _client(_serve(FIXTURE.read_bytes()))
        )
        result = CliRunner().invoke(app, ["ingest", "bhavcopy", "--date", "2026-07-08", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["stored"] == 1 and payload["holiday"] == 0

    def test_ingest_range_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PLATFORM_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setattr(
            quant.cli, "_make_client", lambda: _client(_serve(FIXTURE.read_bytes()))
        )
        result = CliRunner().invoke(
            app,
            ["ingest", "bhavcopy", "--since", "2026-06-01", "--until", "2026-06-03", "--json"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["stored"] == 3 and payload["until"] == "2026-06-03"

    def test_unknown_source_exits_nonzero(self) -> None:
        result = CliRunner().invoke(app, ["ingest", "mystery", "--date", "2026-07-08"])
        assert result.exit_code == 1
        assert "no adapter" in result.output

    def test_exactly_one_selector_required(self) -> None:
        result = CliRunner().invoke(app, ["ingest", "bhavcopy"])
        assert result.exit_code == 1
        assert "exactly one" in result.output

    def test_both_selectors_rejected(self) -> None:
        result = CliRunner().invoke(
            app, ["ingest", "bhavcopy", "--date", "2026-07-08", "--since", "2026-07-01"]
        )
        assert result.exit_code == 1
        assert "exactly one" in result.output

    def test_malformed_date_rejected(self) -> None:
        result = CliRunner().invoke(app, ["ingest", "bhavcopy", "--date", "not-a-date"])
        assert result.exit_code == 1
        assert "ISO date" in result.output


def test_sources_yaml_pins_the_four_required_headers() -> None:
    """Regression-encodes the P0-05 finding: a bare UA gets 403 from NSE's edge."""
    headers = source_spec("bhavcopy").headers
    assert set(headers) == {"User-Agent", "Accept", "Accept-Language", "Referer"}
    assert all(v.strip() for v in headers.values())  # names alone aren't the finding
    assert headers["User-Agent"].startswith("Mozilla/5.0")
    assert headers["Referer"].startswith("https://www.nseindia.com")
