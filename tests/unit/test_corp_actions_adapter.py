"""P0-10 suite: corporate-actions adapter — cookie-prime flow, idempotency, block rejects, CLI.

The www API is cookie-gated: the prime GET's 403 is tolerated (it seeds the cookie jar), then
the windowed API GET must return a JSON array. 403/429 on the API aborts; HTML block pages and
error envelopes are rejected as fetch failures, never stored as data.
"""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

import quant.cli
from quant.cli import app
from quant.config import Settings, SourceSpec, source_spec
from quant.errors import ConfigError, SourceError
from quant.ingest import RawStore, corp_actions

JSON_BODY = (
    b'[{"isin":"INE001A01036","symbol":"X","series":"EQ","exDate":"05-Jan-2021",'
    b'"subject":"Dividend - Rs 2 Per Share","faceVal":"10","recDate":"-"}]'
)
SINCE, UNTIL = date(2021, 7, 15), date(2026, 7, 15)


@pytest.fixture
def store(tmp_path: Path) -> RawStore:
    return RawStore(Settings(data_dir=tmp_path / "data"))


@pytest.fixture
def spec() -> SourceSpec:
    return source_spec("corp_actions")  # the real committed yaml — doubles as its regression test


def _client(api_body: bytes, api_status: int = 200, prime_status: int = 403) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if "api/corporates" in str(request.url):
            return httpx.Response(api_status, content=api_body)
        return httpx.Response(prime_status, content=b"<html>prime</html>")

    return httpx.Client(transport=httpx.MockTransport(handler))


def _no_sleep(_: float) -> None:
    return None


class TestFetchWindow:
    def test_primes_then_stores_json(self, store: RawStore, spec: SourceSpec) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if "api/corporates" in str(request.url):
                return httpx.Response(200, content=JSON_BODY)
            return httpx.Response(403)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        artifact, created = corp_actions.fetch_window(
            SINCE, UNTIL, store=store, spec=spec, client=client, sleep=_no_sleep
        )
        assert created is True
        assert artifact.path.suffix == ".json"
        assert artifact.logical_date == UNTIL  # stored under the window end
        assert "api/corporates" not in seen[0]  # prime happened first

    def test_refetch_is_noop(self, store: RawStore, spec: SourceSpec) -> None:
        kwargs = {"store": store, "spec": spec, "sleep": _no_sleep}
        first = corp_actions.fetch_window(SINCE, UNTIL, client=_client(JSON_BODY), **kwargs)
        second = corp_actions.fetch_window(SINCE, UNTIL, client=_client(JSON_BODY), **kwargs)
        assert first[1] is True and second[1] is False
        assert second[0].sha256 == first[0].sha256

    @pytest.mark.parametrize("status", [403, 429])
    def test_api_block_status_aborts(self, store: RawStore, spec: SourceSpec, status: int) -> None:
        with pytest.raises(SourceError, match="blocked"):
            corp_actions.fetch_window(
                SINCE, UNTIL, store=store, spec=spec, client=_client(b"x", status), sleep=_no_sleep
            )

    def test_unexpected_status_aborts(self, store: RawStore, spec: SourceSpec) -> None:
        with pytest.raises(SourceError, match="unexpected HTTP 500"):
            corp_actions.fetch_window(
                SINCE, UNTIL, store=store, spec=spec, client=_client(b"x", 500), sleep=_no_sleep
            )

    def test_html_block_page_rejected(self, store: RawStore, spec: SourceSpec) -> None:
        with pytest.raises(SourceError, match="not a JSON array"):
            corp_actions.fetch_window(
                SINCE,
                UNTIL,
                store=store,
                spec=spec,
                client=_client(b"<!DOCTYPE html><html>captcha</html>"),
                sleep=_no_sleep,
            )

    def test_error_envelope_rejected(self, store: RawStore, spec: SourceSpec) -> None:
        with pytest.raises(SourceError, match="not a JSON array"):
            corp_actions.fetch_window(
                SINCE,
                UNTIL,
                store=store,
                spec=spec,
                client=_client(b'{"error":1}'),
                sleep=_no_sleep,
            )

    def test_until_before_since_is_config_error(self, store: RawStore, spec: SourceSpec) -> None:
        with pytest.raises(ConfigError, match="before"):
            corp_actions.fetch_window(
                UNTIL, SINCE, store=store, spec=spec, client=_client(JSON_BODY), sleep=_no_sleep
            )

    def test_missing_prime_url_is_config_error(self, store: RawStore) -> None:
        spec = SourceSpec(
            url_template="https://x/api?from_date={from_date}&to_date={to_date}",
            delay_seconds=0,
            timeout_seconds=1,
            headers={},
        )
        with pytest.raises(ConfigError, match="prime_url"):
            corp_actions.fetch_window(
                SINCE, UNTIL, store=store, spec=spec, client=_client(JSON_BODY), sleep=_no_sleep
            )


class TestCli:
    def test_rejects_date_flag(self) -> None:
        result = CliRunner().invoke(app, ["ingest", "corp_actions", "--date", "2021-07-15"])
        assert result.exit_code == 1
        assert "windowed source" in result.output

    def test_requires_since(self) -> None:
        result = CliRunner().invoke(app, ["ingest", "corp_actions"])
        assert result.exit_code == 1
        assert "requires --since" in result.output

    def test_windowed_ingest_emits_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLATFORM_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setattr(quant.cli, "_make_client", lambda: _client(JSON_BODY))
        monkeypatch.setattr(corp_actions.time, "sleep", _no_sleep)
        result = CliRunner().invoke(
            app,
            ["ingest", "corp_actions", "--since", "2021-07-15", "--until", "2026-07-15", "--json"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output.strip().splitlines()[-1])
        assert payload["source"] == "corp_actions"
        assert payload["since"] == "2021-07-15"
        assert payload["until"] == "2026-07-15"
        assert payload["stored"] is True
