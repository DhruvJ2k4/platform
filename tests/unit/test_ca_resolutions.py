"""P0-11/P0-12 suite: operator CA resolutions — config loading + deterministic application
(RB-4): ratio resolutions for the factor kinds, cash resolutions for amount-less dividends
(ADR-025), and the pre-ex price window unblocking that a resolution buys."""

from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from conftest import ca_frame, panel_frame
from quant.config import CAResolution, Settings, load_ca_resolutions
from quant.curate.adjust import adjust_prices
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


_DIV_ENTRY = (
    "  - {{isin: INE000TESTA1, ex_date: 2022-06-01, kind: dividend,"
    ' {fields} source_ref: "circular"}}\n'
)


class TestDividendResolutionShape:
    """ADR-025: dividend resolutions carry cash_amount only; ratio kinds carry ratio only."""

    def test_dividend_cash_entry_loads_exactly(self, tmp_path: Path) -> None:
        s = _config(tmp_path, "resolutions:\n" + _DIV_ENTRY.format(fields="cash_amount: 20.10,"))
        (res,) = load_ca_resolutions(s)
        assert res.cash_amount == D("20.10")  # Decimal-exact through the YAML loader
        assert res.ratio_num is None and res.ratio_den is None

    def test_dividend_entry_without_cash_is_rejected(self, tmp_path: Path) -> None:
        s = _config(tmp_path, "resolutions:\n" + _DIV_ENTRY.format(fields=""))
        with pytest.raises(ConfigError, match="cash_amount"):
            load_ca_resolutions(s)

    def test_dividend_entry_with_ratio_is_rejected(self, tmp_path: Path) -> None:
        s = _config(
            tmp_path,
            "resolutions:\n"
            + _DIV_ENTRY.format(fields="cash_amount: 20.00, ratio_num: 1, ratio_den: 1,"),
        )
        with pytest.raises(ConfigError, match="no ratio"):
            load_ca_resolutions(s)

    def test_ratio_kind_with_cash_is_rejected(self, tmp_path: Path) -> None:
        s = _config(
            tmp_path,
            "resolutions:\n  - {isin: INE000TESTA1, ex_date: 2025-01-30, kind: demerger,"
            ' ratio_num: 10, ratio_den: 7, cash_amount: 5.00, source_ref: "c"}\n',
        )
        with pytest.raises(ConfigError, match="no cash_amount"):
            load_ca_resolutions(s)

    @pytest.mark.parametrize("bad", ["0", "-1", "0.00"])
    def test_nonpositive_cash_is_rejected(self, tmp_path: Path, bad: str) -> None:
        s = _config(tmp_path, "resolutions:\n" + _DIV_ENTRY.format(fields=f"cash_amount: {bad},"))
        with pytest.raises(ConfigError, match="cash_amount"):
            load_ca_resolutions(s)

    def test_subpaisa_cash_is_rejected(self, tmp_path: Path) -> None:
        # DECIMAL(12,2) is the column contract; silently rounding operator money is forbidden
        s = _config(tmp_path, "resolutions:\n" + _DIV_ENTRY.format(fields="cash_amount: 2.105,"))
        with pytest.raises(ConfigError, match="cash_amount"):
            load_ca_resolutions(s)

    def test_oversized_cash_is_rejected(self, tmp_path: Path) -> None:
        # 11 integer digits exceed DECIMAL(12,2)'s capacity — fail at load, not in pyarrow
        s = _config(
            tmp_path, "resolutions:\n" + _DIV_ENTRY.format(fields="cash_amount: 12345678901.00,")
        )
        with pytest.raises(ConfigError, match="cash_amount"):
            load_ca_resolutions(s)

    def test_unknown_kind_is_rejected_at_load(self, tmp_path: Path) -> None:
        # A typo'd kind must say so, not misdirect the operator toward the ratio shape.
        s = _config(
            tmp_path,
            "resolutions:\n  - {isin: INE000TESTA1, ex_date: 2022-06-01, kind: divdend,"
            ' cash_amount: 20.00, source_ref: "c"}\n',
        )
        with pytest.raises(ConfigError, match="unknown kind"):
            load_ca_resolutions(s)

    def test_programmatic_float_cash_is_rejected(self) -> None:
        # The YAML loader never yields floats; the constructor path must be just as closed.
        with pytest.raises(ValidationError, match="float"):
            CAResolution(
                isin="INE000TESTA1",
                ex_date=date(2022, 6, 1),
                kind="dividend",
                cash_amount=20.10,  # type: ignore[arg-type]
                source_ref="c",
            )


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


# The fixture's REAL amount-less dividend (live probe: 16 such rows block 16 ISINs' windows).
_AMOUNTLESS_ISIN = "INE054A01019"
_AMOUNTLESS_EX = date(2022, 3, 8)


def _dividend_resolution(cash: str = "20.00") -> CAResolution:
    return CAResolution(
        isin=_AMOUNTLESS_ISIN,
        ex_date=_AMOUNTLESS_EX,
        kind="dividend",
        cash_amount=D(cash),
        source_ref="circular",
    )


class TestDividendResolutionApplication:
    def test_dividend_resolution_fills_cash_not_ratio(self) -> None:
        parsed = parse_corp_actions(FIXTURE.read_bytes())
        res = build_corp_actions_frames(parsed, resolutions=[_dividend_resolution()])
        ca = res.corporate_actions
        row = ca[(ca["isin"] == _AMOUNTLESS_ISIN) & (ca["kind"] == "dividend")].iloc[0]
        assert row["status"] == "resolved"
        assert D(str(row["cash_amount"])) == D("20.00")
        assert pd.isna(row["ratio_num"]) and pd.isna(row["ratio_den"])  # never fabricated
        assert "resolved: circular" in row["source_ref"]
        assert res.stats["resolved"] == 1

    def test_dividend_resolution_against_auto_row_is_unmatched(self) -> None:
        parsed = parse_corp_actions(FIXTURE.read_bytes())
        auto = build_corp_actions_frames(parsed).corporate_actions
        auto_div = auto[(auto["kind"] == "dividend") & (auto["status"] == "auto")].iloc[0]
        stale = CAResolution(
            isin=str(auto_div["isin"]),
            ex_date=auto_div["ex_date"],
            kind="dividend",
            cash_amount=D("1.00"),
            source_ref="stale",
        )
        with pytest.raises(ConfigError, match="matched 0"):
            build_corp_actions_frames(parsed, resolutions=[stale])

    def test_two_amountless_dividends_same_key_are_unresolvable_loudly(self) -> None:
        # The exactly-1 rule has no discriminator for this: the ConfigError is the honest
        # outcome (ADR-025 records the reach limit; none of the 16 live rows collide).
        import json

        rows = json.loads(FIXTURE.read_text())
        for subject in ("Interim Dividend", "Final Dividend"):
            rows.append(
                {
                    "isin": "INE0TWINDIV1",
                    "symbol": "TWIN",
                    "series": "EQ",
                    "exDate": "01-Jun-2022",
                    "subject": subject,
                    "faceVal": "10",
                    "recDate": "-",
                }
            )
        parsed = parse_corp_actions(json.dumps(rows).encode())
        twin = CAResolution(
            isin="INE0TWINDIV1",
            ex_date=date(2022, 6, 1),
            kind="dividend",
            cash_amount=D("5.00"),
            source_ref="c",
        )
        with pytest.raises(ConfigError, match="matched 2"):
            build_corp_actions_frames(parsed, resolutions=[twin])

    def test_cash_resolution_unblocks_the_pre_ex_window(self) -> None:
        # The operational point of ADR-025: a pending amount-less dividend withholds every
        # pre-ex price of its ISIN; the cash resolution lifts the block (factor stays 1).
        panel = panel_frame(
            [
                (date(2022, 3, 4), "T", "EQ", _AMOUNTLESS_ISIN, D("100.00"), 10),
                (_AMOUNTLESS_EX, "T", "EQ", _AMOUNTLESS_ISIN, D("101.00"), 10),
            ]
        )
        kw = {
            "coverage_floor": date(2022, 1, 1),
            "coverage_ceiling": date(2026, 1, 1),
            "asof": date(2026, 1, 1),
        }
        parsed = parse_corp_actions(FIXTURE.read_bytes())

        pending = build_corp_actions_frames(parsed).corporate_actions
        blocked = adjust_prices(panel, pending, **kw)
        assert blocked.stats["pre_ex_blocked"] == 1 and blocked.stats["published"] == 1

        resolved = build_corp_actions_frames(
            parsed, resolutions=[_dividend_resolution()]
        ).corporate_actions
        lifted = adjust_prices(panel, resolved, **kw)
        assert lifted.stats["pre_ex_blocked"] == 0 and lifted.stats["published"] == 2
        pre_ex = lifted.prices_adj[lifted.prices_adj["d"] == date(2022, 3, 4)].iloc[0]
        assert D(str(pre_ex["c"])) == D("100.00")  # dividends never price-adjust


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
