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
from typing import Annotated, Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
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
    # Cookie-prime GET before the real request (P0-10): the NSE www API is cookie-gated, so the
    # adapter fetches prime_url first (its 403 still sets the Akamai cookie) to unlock the API.
    prime_url: str | None = None
    # POST sources (P0-15, index TRI): niftyindices' TRI endpoint is an ASP.NET page-method taking
    # a JSON `cinfo` body naming the index + date window. `index_label` is the exact niftyindices
    # index name the adapter puts in that body; `chunk_days` caps each request's window (the TRI
    # endpoint rejects spans > ~1y), so a multi-year backfill fetches in <=chunk_days slices.
    method: str = "GET"
    index_label: str | None = None
    chunk_days: int | None = Field(default=None, gt=0)

    @field_validator("method")
    @classmethod
    def _known_method(cls, v: str) -> str:
        if v not in ("GET", "POST"):
            raise ValueError(f"method must be GET or POST, got {v!r}")
        return v


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


_CA_KINDS = frozenset({"split", "bonus", "dividend", "demerger", "rights", "buyback", "other"})


class CAResolution(BaseModel):
    """One operator-entered corporate-action resolution (RB-4; ADR-024/025).

    Keyed to exactly one needs_review corporate_actions row by (isin, ex_date, kind).
    Ratio kinds keep the row kind's semantics (doc 21 §1): split/rights/demerger/other →
    factor = ratio_den/ratio_num; bonus (X:Y terms) → ratio_den/(ratio_num+ratio_den);
    they carry ratio terms and never cash. kind='dividend' carries cash_amount — THIS
    ROW's per-share amount from the circular (compound components summed, ADR-023), NOT
    the ex-date group total: other payable dividend rows on the same (isin, ex_date)
    credit separately and sum downstream — and never ratio terms (dividends have no price
    factor, ADR-025). source_ref cites the circular.
    Resolutions live in config because curated is a function of (raw, code, config) — an
    operational-DB row would be silently wiped by every rebuild (doc 08).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    isin: str = Field(min_length=12, max_length=12)
    ex_date: date
    kind: str  # one of _CA_KINDS (validated below); matched against the needs_review row
    ratio_num: int | None = Field(default=None, gt=0)
    ratio_den: int | None = Field(default=None, gt=0)
    cash_amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    source_ref: str = Field(min_length=1)  # exchange circular reference — never optional

    @field_validator("cash_amount", mode="before")
    @classmethod
    def _no_binary_floats(cls, v: object) -> object:
        # The YAML loader never yields floats; this closes the programmatic path (doc 23).
        if isinstance(v, float):
            raise ValueError("cash_amount must be a Decimal/str/int, never a binary float")
        return v

    @model_validator(mode="after")
    def _shape_matches_kind(self) -> Self:
        if self.kind not in _CA_KINDS:
            raise ValueError(f"unknown kind {self.kind!r}; known kinds: {sorted(_CA_KINDS)}")
        if self.kind == "dividend":
            if self.cash_amount is None or not (self.ratio_num is None and self.ratio_den is None):
                raise ValueError(
                    "a dividend resolution carries cash_amount (this row's per-share amount,"
                    " paisa-quantized) and no ratio terms — dividends never price-adjust"
                    " (ADR-025)"
                )
        elif self.ratio_num is None or self.ratio_den is None or self.cash_amount is not None:
            raise ValueError(
                f"a {self.kind} resolution carries ratio_num/ratio_den and no cash_amount "
                "(ratio semantics per kind — doc 21 §1)"
            )
        return self


def load_ca_resolutions(settings: Settings | None = None) -> list[CAResolution]:
    """Load config/ca-resolutions.yaml; empty list allowed; malformed entries fail loudly."""
    s = settings or Settings()
    path = s.config_dir / "ca-resolutions.yaml"
    data = load_yaml(path)
    if not isinstance(data, dict) or "resolutions" not in data:
        raise ConfigError(f"invalid config {path}: expected a 'resolutions' list (may be empty)")
    entries = data["resolutions"]
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise ConfigError(f"invalid config {path}: 'resolutions' must be a list")
    try:
        resolutions = [CAResolution.model_validate(e) for e in entries]
    except ValidationError as exc:
        raise ConfigError(f"invalid config {path}: {exc}") from exc
    keys = [(r.isin, r.ex_date, r.kind) for r in resolutions]
    if len(keys) != len(set(keys)):
        raise ConfigError(f"invalid config {path}: duplicate (isin, ex_date, kind) resolution")
    return resolutions


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


class LiquidityConfig(BaseModel):
    """Liquidity + PIT-universe thresholds (doc 21 §3-4, P0-13); consumed by curate/universe.py.

    Every bound is strictly positive so a parseable-but-wrong ``mdtv_floor_rupees: 0`` cannot
    silently disable a hard filter and admit an uninvestable name (risk-manager guard). Not
    effective-dated: universe hygiene is a single current policy, and the file's config-hash
    joins the curated manifest identity so tuning a threshold mints a new immutable version.
    ``mdtv_floor_rupees`` is the interim ff-mcap PROXY (doc 21 §4 "rank by MDTV" superseded by an
    absolute floor for PIT-safety, ADR-026); ``p_max`` sizes the query-time capacity = p_max·MDTV
    (the investable(book) overlay itself is deferred to P1/P2).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    window_trading_days: int = Field(gt=0)
    price_floor_rupees: Decimal = Field(gt=0)
    min_age_trading_days: int = Field(gt=0)
    max_zero_days_pct: Decimal = Field(gt=0, le=1)
    mdtv_floor_rupees: Decimal = Field(gt=0)
    p_max: Decimal = Field(gt=0, le=1)


def load_liquidity(settings: Settings | None = None) -> LiquidityConfig:
    """Load config/liquidity.yaml; missing / malformed / out-of-range fails loudly (ConfigError)."""
    s = settings or Settings()
    path = s.config_dir / "liquidity.yaml"
    data = load_yaml(path)
    if not isinstance(data, dict):
        raise ConfigError(f"invalid config {path}: expected a mapping of thresholds")
    try:
        return LiquidityConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid config {path}: {exc}") from exc


def load_costs(settings: Settings | None = None) -> RateSchedule[CostRates]:
    """Load config/costs.yaml as an effective-dated cost-rate schedule."""
    s = settings or Settings()
    return _load_schedule(s.config_dir / "costs.yaml", RateSchedule[CostRates])


def load_tax(settings: Settings | None = None) -> RateSchedule[TaxRates]:
    """Load config/tax.yaml as an effective-dated tax-parameter schedule."""
    s = settings or Settings()
    return _load_schedule(s.config_dir / "tax.yaml", RateSchedule[TaxRates])
