"""P0-11 suite: operator CA resolutions — config loading + deterministic application (RB-4)."""

from datetime import date, datetime
from pathlib import Path

import pytest

from conftest import ca_frame
from quant.config import CAResolution, Settings, load_ca_resolutions
from quant.curate.corp_actions import build_corp_actions_frames
from quant.curate.parsers.corp_actions import parse_corp_actions
from quant.errors import ConfigError

FIXTURE = Path(__file__).parent.parent / "fixtures" / "corp_actions" / "corp_actions-trimmed.json"


def _config(tmp_path: Path, body: str) -> Settings:
    (tmp_path / "ca-resolutions.yaml").write_text(body)
    return Settings(config_dir=tmp_path)


class TestLoader:
    def test_committed_scaffold_loads_empty(self) -> None:
        assert load_ca_resolutions() == []  # the real config/ca-resolutions.yaml

    def test_valid_entry_loads(self, tmp_path: Path) -> None:
        s = _config(
            tmp_path,
            "resolutions:\n"
            "  - isin: INE000TESTA1\n"
            "    ex_date: 2025-01-30\n"
            "    kind: demerger\n"
            "    ratio_num: 10\n"
            "    ratio_den: 7\n"
            '    source_ref: "NSE circular X"\n',
        )
        (res,) = load_ca_resolutions(s)
        assert res.ex_date == date(2025, 1, 30) and res.ratio_den == 7

    def test_missing_source_ref_is_rejected(self, tmp_path: Path) -> None:
        s = _config(
            tmp_path,
            "resolutions:\n"
            "  - isin: INE000TESTA1\n"
            "    ex_date: 2025-01-30\n"
            "    kind: demerger\n"
            "    ratio_num: 10\n"
            "    ratio_den: 7\n",
        )
        with pytest.raises(ConfigError, match="source_ref"):
            load_ca_resolutions(s)

    def test_zero_ratio_is_rejected(self, tmp_path: Path) -> None:
        s = _config(
            tmp_path,
            "resolutions:\n"
            "  - {isin: INE000TESTA1, ex_date: 2025-01-30, kind: demerger,"
            ' ratio_num: 10, ratio_den: 0, source_ref: "c"}\n',
        )
        with pytest.raises(ConfigError, match="ratio_den"):
            load_ca_resolutions(s)

    def test_duplicate_keys_are_rejected(self, tmp_path: Path) -> None:
        entry = (
            "  - {isin: INE000TESTA1, ex_date: 2025-01-30, kind: demerger,"
            ' ratio_num: 10, ratio_den: 7, source_ref: "c"}\n'
        )
        s = _config(tmp_path, "resolutions:\n" + entry + entry)
        with pytest.raises(ConfigError, match="duplicate"):
            load_ca_resolutions(s)

    def test_missing_resolutions_key_is_rejected(self, tmp_path: Path) -> None:
        s = _config(tmp_path, "entries: []\n")
        with pytest.raises(ConfigError, match="resolutions"):
            load_ca_resolutions(s)


def _resolution(**overrides) -> CAResolution:
    base = {
        "isin": "INE000TESTA1",
        "ex_date": date(2025, 1, 30),
        "kind": "demerger",
        "ratio_num": 10,
        "ratio_den": 7,
        "source_ref": "circular",
    }
    return CAResolution(**{**base, **overrides})


class TestApplication:
    def test_resolution_flips_status_and_fills_ratio(self) -> None:
        parsed = _parsed_with_demerger()
        res = build_corp_actions_frames(
            parsed, resolutions=[_resolution(isin=_DEMERGER_ISIN, ex_date=_DEMERGER_EX)]
        )
        row = res.corporate_actions[
            (res.corporate_actions["kind"] == "demerger")
            & (res.corporate_actions["status"] == "resolved")
        ].iloc[0]
        assert int(row["ratio_num"]) == 10 and int(row["ratio_den"]) == 7
        assert "resolved: circular" in row["source_ref"]
        assert res.stats["resolved"] == 1

    def test_unmatched_resolution_is_config_error(self) -> None:
        with pytest.raises(ConfigError, match="matched 0"):
            build_corp_actions_frames(
                _parsed_with_demerger(), resolutions=[_resolution(isin="INE000GHOST1")]
            )

    def test_resolution_against_auto_row_is_unmatched(self) -> None:
        # Resolving a row that is not needs_review is an operator error, not a silent flip.
        parsed = _parsed_with_demerger()
        auto_split = parsed[parsed["subject"].str.contains("Face Value Split")].iloc[0]
        with pytest.raises(ConfigError, match="matched 0"):
            build_corp_actions_frames(
                parsed,
                resolutions=[
                    _resolution(
                        isin=str(auto_split["isin"]), ex_date=auto_split["ex_date"], kind="split"
                    )
                ],
            )


_DEMERGER_ISIN = "INE0DEMERGE1"
_DEMERGER_EX = date(2025, 3, 3)


def _parsed_with_demerger():
    import json

    rows = json.loads(FIXTURE.read_text())
    rows.append(
        {
            "isin": _DEMERGER_ISIN,
            "symbol": "DMG",
            "series": "EQ",
            "exDate": "03-Mar-2025",
            "subject": "Demerger",
            "faceVal": "10",
            "recDate": "-",
        }
    )
    return parse_corp_actions(json.dumps(rows).encode())


def test_coverage_bounds_travel_with_the_tables() -> None:
    parsed = _parsed_with_demerger()
    res = build_corp_actions_frames(parsed, coverage_ceiling=date(2026, 7, 15))
    assert res.coverage_floor is not None and res.coverage_floor <= date(2025, 3, 3)
    assert res.coverage_ceiling == date(2026, 7, 15)


def test_ca_frame_factory_matches_contract() -> None:
    # keep the conftest factory honest against the real pandera contract
    from quant.schemas import CorporateActions

    frame = ca_frame(
        [
            (
                "INE000TESTA1",
                date(2025, 1, 2),
                "split",
                10,
                2,
                None,
                "auto",
                "s",
                datetime(2025, 1, 2),
            )
        ]
    )
    CorporateActions.validate(frame, lazy=True)
