"""P0-10 integration: committed-fixture CA pipeline (JSON → parse → classify → validated table).

No network: the fixture is 24 real feed rows trimmed from the live 5y pull, one per classifier
branch. Asserts the whole pipeline end-to-end plus the RawStore-backed build entry point.
"""

from datetime import date
from pathlib import Path

import pytest

from quant.config import Settings
from quant.curate.corp_actions import build_corp_actions, build_corp_actions_frames
from quant.curate.parsers.corp_actions import parse_corp_actions
from quant.errors import ContractViolation
from quant.ingest import RawStore
from quant.schemas import CorporateActions

FIXTURE = Path(__file__).parent.parent / "fixtures" / "corp_actions" / "corp_actions-trimmed.json"


def _build():
    return build_corp_actions_frames(parse_corp_actions(FIXTURE.read_bytes()))


class TestFixturePipeline:
    def test_counts_match_hand_classification(self) -> None:
        s = _build().stats
        assert s["parsed_rows"] == 24
        assert s["non_equity_dropped"] == 3  # GS + IV + RR
        assert s["meetings_dropped"] == 2  # AGM + EGM
        assert s["kept"] == 19
        assert s["auto"] == 11 and s["needs_review"] == 8
        assert s["kind_split"] == 2 and s["kind_bonus"] == 4 and s["kind_dividend"] == 5
        assert s["kind_rights"] == 3 and s["kind_buyback"] == 2
        assert s["kind_demerger"] == 1 and s["kind_other"] == 2

    def test_table_revalidates_against_the_contract(self) -> None:
        ca = _build().corporate_actions
        CorporateActions.validate(ca, lazy=True)  # money-bearing arrow-typed contract

    def test_demergers_rights_and_other_are_all_needs_review(self) -> None:
        ca = _build().corporate_actions
        review = ca[ca["kind"].isin(["demerger", "rights", "other"])]
        assert len(review) == 6  # 1 demerger + 3 rights + 2 other
        assert bool((review["status"] == "needs_review").all())

    def test_compound_dividend_is_summed(self) -> None:
        from decimal import Decimal

        ca = _build().corporate_actions
        row = ca[ca["source_ref"].str.contains("Special Dividend - Rs 2.50")].iloc[0]
        assert row["kind"] == "dividend" and row["cash_amount"] == Decimal("7.50")

    def test_available_at_is_ex_date_midnight(self) -> None:
        ca = _build().corporate_actions
        row = ca.iloc[0]
        assert row["available_at"].date() == row["ex_date"]
        assert row["available_at"].hour == 0 and row["available_at"].minute == 0


class TestRawStoreEntryPoint:
    def test_build_reads_from_raw_store(self, tmp_path: Path) -> None:
        settings = Settings(data_dir=tmp_path / "data")
        RawStore(settings).put(
            "corp_actions", date(2026, 7, 15), FIXTURE.read_bytes(), suffix=".json"
        )
        res = build_corp_actions(settings)
        assert res.stats["kept"] == 19

    def test_no_raw_files_is_a_contract_violation(self, tmp_path: Path) -> None:
        with pytest.raises(ContractViolation, match="no corp_actions raw files"):
            build_corp_actions(Settings(data_dir=tmp_path / "data"))
