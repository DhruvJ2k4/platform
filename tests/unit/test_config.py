"""P0-03 DoD suite: effective-dated rate lookup by date + bad config fails loudly."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import quant.schemas
from quant.config import RateSchedule, Settings, TaxRates, load_costs, load_tax
from quant.errors import (
    ConfigError,
    ContractViolation,
    LedgerError,
    ParseError,
    PlatformError,
    SourceError,
)

EPOCH_1 = date(2024, 7, 23)
EPOCH_2 = date(2025, 4, 1)


def _tax_entry(effective_from: date, stcg: str = "0.20") -> dict[str, Any]:
    return {
        "effective_from": effective_from,
        "stcg_rate": stcg,
        "ltcg_rate": "0.125",
        "ltcg_exemption_per_fy": "125000",
        "stcg_holding_days_max": 365,
        "dividend_slab_rate": "0.30",
    }


def _two_epoch_schedule() -> RateSchedule[TaxRates]:
    return RateSchedule[TaxRates](
        entries=[_tax_entry(EPOCH_1, "0.20"), _tax_entry(EPOCH_2, "0.25")]  # type: ignore[list-item]
    )


class TestRateLookupByDate:
    def test_boundary_day_gets_new_epoch(self) -> None:
        sched = _two_epoch_schedule()
        assert sched.asof(EPOCH_1).stcg_rate == Decimal("0.20")
        assert sched.asof(EPOCH_2).stcg_rate == Decimal("0.25")

    def test_mid_epoch_and_day_before_switch(self) -> None:
        sched = _two_epoch_schedule()
        assert sched.asof(date(2024, 12, 31)).stcg_rate == Decimal("0.20")
        assert sched.asof(date(2025, 3, 31)).stcg_rate == Decimal("0.20")

    def test_far_future_gets_latest_epoch(self) -> None:
        assert _two_epoch_schedule().asof(date(2040, 1, 1)).stcg_rate == Decimal("0.25")

    def test_before_first_epoch_fails_loudly(self) -> None:
        with pytest.raises(ConfigError, match="no rate epoch in force on 2024-07-22"):
            _two_epoch_schedule().asof(date(2024, 7, 22))


class TestScheduleValidation:
    def test_unsorted_entries_rejected(self, tmp_path: Path) -> None:
        self._write_and_expect_error(tmp_path, [_tax_entry(EPOCH_2), _tax_entry(EPOCH_1)])

    def test_duplicate_dates_rejected(self, tmp_path: Path) -> None:
        self._write_and_expect_error(tmp_path, [_tax_entry(EPOCH_1), _tax_entry(EPOCH_1)])

    def test_empty_entries_rejected(self, tmp_path: Path) -> None:
        self._write_and_expect_error(tmp_path, [])

    @staticmethod
    def _write_and_expect_error(tmp_path: Path, entries: list[dict[str, Any]]) -> None:
        lines = ["entries:"]
        for e in entries:
            lines.append(f"  - effective_from: {e['effective_from']}")
            lines.extend(f"    {k}: {v}" for k, v in e.items() if k != "effective_from")
        (tmp_path / "tax.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        settings = Settings(config_dir=tmp_path)
        with pytest.raises(ConfigError, match=r"tax\.yaml"):
            load_tax(settings)


class TestCommittedFilesLoadExactly:
    def test_costs_decimal_exact(self) -> None:
        rates = load_costs().asof(date(2026, 7, 12))
        assert isinstance(rates.stt_buy_rate, Decimal)
        assert rates.stt_buy_rate == Decimal("0.001")
        assert rates.stt_sell_rate == Decimal("0.001")
        assert rates.stamp_buy_rate == Decimal("0.00015")
        assert rates.exchange_txn_rate == Decimal("0.0000297")
        assert rates.sebi_rate == Decimal("0.000001")
        assert rates.gst_rate == Decimal("0.18")
        assert rates.dp_per_isin_sell_day == Decimal("15.9")
        assert rates.amc_per_year == Decimal("300")
        assert rates.brokerage_delivery_rate == Decimal("0")

    def test_tax_decimal_exact(self) -> None:
        rates = load_tax().asof(date(2026, 7, 12))
        assert isinstance(rates.ltcg_rate, Decimal)
        assert rates.stcg_rate == Decimal("0.20")
        assert rates.ltcg_rate == Decimal("0.125")
        assert rates.ltcg_exemption_per_fy == Decimal("125000")
        assert rates.stcg_holding_days_max == 365
        assert rates.dividend_slab_rate == Decimal("0.30")

    def test_committed_epoch_starts_2024_07_23(self) -> None:
        with pytest.raises(ConfigError):
            load_tax().asof(date(2024, 7, 22))


class TestBadConfigFailsLoudly:
    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="config file missing"):
            load_costs(Settings(config_dir=tmp_path))

    def test_malformed_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "costs.yaml").write_text("entries: [", encoding="utf-8")
        with pytest.raises(ConfigError, match="unparseable YAML"):
            load_costs(Settings(config_dir=tmp_path))

    def test_unknown_key_rejected(self, tmp_path: Path) -> None:
        good = (quant.schemas.SCHEMAS_DIR.parent / "config" / "tax.yaml").read_text("utf-8")
        (tmp_path / "tax.yaml").write_text(good + "    surprise_rate: 0.1\n", encoding="utf-8")
        with pytest.raises(ConfigError, match=r"tax\.yaml"):
            load_tax(Settings(config_dir=tmp_path))

    def test_negative_rate_rejected(self, tmp_path: Path) -> None:
        good = (quant.schemas.SCHEMAS_DIR.parent / "config" / "tax.yaml").read_text("utf-8")
        (tmp_path / "tax.yaml").write_text(
            good.replace("stcg_rate: 0.20", "stcg_rate: -0.20"), encoding="utf-8"
        )
        with pytest.raises(ConfigError, match=r"tax\.yaml"):
            load_tax(Settings(config_dir=tmp_path))

    def test_rate_above_one_rejected(self, tmp_path: Path) -> None:
        good = (quant.schemas.SCHEMAS_DIR.parent / "config" / "tax.yaml").read_text("utf-8")
        (tmp_path / "tax.yaml").write_text(
            good.replace("ltcg_rate: 0.125", "ltcg_rate: 1.125"), encoding="utf-8"
        )
        with pytest.raises(ConfigError, match=r"tax\.yaml"):
            load_tax(Settings(config_dir=tmp_path))


class TestSettings:
    def test_env_override_redirects_loading(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLATFORM_CONFIG_DIR", str(tmp_path))
        with pytest.raises(ConfigError, match=str(tmp_path)):
            load_costs()  # default Settings() must pick up the env var


class TestErrorTaxonomy:
    def test_all_five_subclass_platform_error(self) -> None:
        for exc in (SourceError, ParseError, ContractViolation, LedgerError, ConfigError):
            assert issubclass(exc, PlatformError)

    def test_ddl_loader_raises_config_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(quant.schemas, "SCHEMAS_DIR", tmp_path)
        with pytest.raises(ConfigError, match="authoritative DDL missing"):
            quant.schemas.ddl_sql("security")
