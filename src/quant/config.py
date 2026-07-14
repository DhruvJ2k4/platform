"""Config system: Decimal-exact YAML loading, effective-dated rate schedules, runtime settings.

All platform configuration is kebab-case YAML under config/ (doc 20), parsed with a
Decimal-preserving loader so money rates never exist as binary floats (doc 23). Rate files are
effective-dated (doc 12): ``RateSchedule.asof(d)`` resolves the epoch in force on d and raises
ConfigError for dates before the first verified epoch — silent defaults are forbidden on money
paths. Secrets never live in configs (doc 15: OS keyring / env only).
"""

from datetime import date
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from quant.errors import ConfigError

_REPO_ROOT = Path(__file__).resolve().parents[2]

FractionRate = Annotated[Decimal, Field(ge=0, le=1)]
RupeeAmount = Annotated[Decimal, Field(ge=0)]


class Settings(BaseSettings):
    """Runtime knobs, overridable via PLATFORM_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="PLATFORM_", extra="ignore")

    config_dir: Path = _REPO_ROOT / "config"
    data_dir: Path = _REPO_ROOT / "data"


class _DecimalSafeLoader(yaml.SafeLoader):
    """SafeLoader that parses YAML floats as exact Decimals."""


def _decimal_constructor(loader: yaml.SafeLoader, node: Any) -> Decimal:
    return Decimal(str(loader.construct_scalar(node)))


_DecimalSafeLoader.add_constructor("tag:yaml.org,2002:float", _decimal_constructor)


def load_yaml(path: Path) -> Any:
    """Parse one YAML file Decimal-exactly; every failure is a loud ConfigError."""
    if not path.is_file():
        raise ConfigError(f"config file missing: {path}")
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=_DecimalSafeLoader)
    except yaml.YAMLError as exc:
        raise ConfigError(f"unparseable YAML in {path}: {exc}") from exc


class _Epoch(BaseModel):
    """One effective-dated config epoch; applies from effective_from (inclusive) onward."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    effective_from: date


class CostRates(_Epoch):
    """One epoch of Indian delivery-equity cost rates (doc 12; re-verified each budget day)."""

    brokerage_delivery_rate: FractionRate
    stt_buy_rate: FractionRate
    stt_sell_rate: FractionRate
    stamp_buy_rate: FractionRate
    exchange_txn_rate: FractionRate
    sebi_rate: FractionRate
    gst_rate: FractionRate
    dp_per_isin_sell_day: RupeeAmount
    amc_per_year: RupeeAmount


class TaxRates(_Epoch):
    """One epoch of Indian capital-gains parameters for equity delivery (doc 12)."""

    stcg_rate: FractionRate
    ltcg_rate: FractionRate
    ltcg_exemption_per_fy: RupeeAmount
    stcg_holding_days_max: int = Field(ge=1)
    dividend_slab_rate: FractionRate


class RateSchedule[E: _Epoch](BaseModel):
    """Effective-dated epochs, strictly ascending; asof(d) resolves the epoch in force on d."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: list[E] = Field(min_length=1)

    @field_validator("entries")
    @classmethod
    def _strictly_ascending(cls, v: list[E]) -> list[E]:
        dates = [e.effective_from for e in v]
        if any(b <= a for a, b in pairwise(dates)):
            raise ValueError(f"entries must be strictly ascending by effective_from, got {dates}")
        return v

    def asof(self, d: date) -> E:
        """Return the epoch in force on d; ConfigError if d predates the first verified epoch."""
        current: E | None = None
        for entry in self.entries:
            if entry.effective_from <= d:
                current = entry
            else:
                break
        if current is None:
            raise ConfigError(
                f"no rate epoch in force on {d}: earliest verified epoch starts "
                f"{self.entries[0].effective_from}. Add a golden-tested historical epoch "
                "(P1-02/P1-03) rather than guessing rates."
            )
        return current


def _load_schedule(path: Path, schedule_type: type[Any]) -> Any:
    data = load_yaml(path)
    try:
        return schedule_type.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid config {path}: {exc}") from exc


class SourceSpec(BaseModel):
    """One source-endpoint spec from config/sources.yaml (headers per doc 09 P0-05 findings)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url_template: str
    delay_seconds: float = Field(ge=0)
    timeout_seconds: float = Field(gt=0)
    headers: dict[str, str]
    # Era-aware backfill: dates <= classic_until fetch from classic_url_template instead.
    classic_url_template: str | None = None
    classic_until: date | None = None


def load_sources(settings: Settings | None = None) -> dict[str, SourceSpec]:
    """Load config/sources.yaml as {source_name: SourceSpec}; failures are loud ConfigErrors."""
    s = settings or Settings()
    path = s.config_dir / "sources.yaml"
    data = load_yaml(path)
    if not isinstance(data, dict):
        raise ConfigError(f"invalid config {path}: expected a mapping of source specs")
    try:
        return {name: SourceSpec.model_validate(spec) for name, spec in data.items()}
    except ValidationError as exc:
        raise ConfigError(f"invalid config {path}: {exc}") from exc


def source_spec(name: str, settings: Settings | None = None) -> SourceSpec:
    """Return one source's spec; unknown names fail loudly with the known list."""
    sources = load_sources(settings)
    if name not in sources:
        raise ConfigError(f"unknown source {name!r}; known sources: {sorted(sources)}")
    return sources[name]


def load_muhurat_dates(settings: Settings | None = None) -> frozenset[date]:
    """Operator-maintained Muhurat session dates from config/calendar.yaml (P0-08 finding:
    neither UDiFF SsnId nor weekend presence can identify Muhurat from data alone)."""
    s = settings or Settings()
    path = s.config_dir / "calendar.yaml"
    data = load_yaml(path)
    if not isinstance(data, dict) or "muhurat_dates" not in data:
        raise ConfigError(f"invalid config {path}: expected a 'muhurat_dates' list")
    dates = data["muhurat_dates"]
    if not isinstance(dates, list) or not all(isinstance(d, date) for d in dates):
        raise ConfigError(f"invalid config {path}: muhurat_dates must be a list of ISO dates")
    return frozenset(dates)


def load_costs(settings: Settings | None = None) -> RateSchedule[CostRates]:
    """Load config/costs.yaml as an effective-dated cost-rate schedule."""
    s = settings or Settings()
    return _load_schedule(s.config_dir / "costs.yaml", RateSchedule[CostRates])


def load_tax(settings: Settings | None = None) -> RateSchedule[TaxRates]:
    """Load config/tax.yaml as an effective-dated tax-parameter schedule."""
    s = settings or Settings()
    return _load_schedule(s.config_dir / "tax.yaml", RateSchedule[TaxRates])
