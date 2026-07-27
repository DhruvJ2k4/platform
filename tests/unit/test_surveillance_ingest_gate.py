"""P0-14 ingest-layer content gate: the columns-only stub is rejected, real content passes
through untouched (a narrow, documented exception to "byte-sniff only, never parse" -- see
ingest/surveillance.py's module docstring for why a full json.loads is unavoidable here).
"""

import json

import pytest

from conftest import asm_snapshot_bytes, gsm_snapshot_bytes
from quant.errors import SourceError
from quant.ingest.surveillance import _reject_columns_only_stub

# The exact bytes captured live 2026-07-27 (both asm.json and gsm.json return this without a
# full Akamai bot-challenge session -- see ops/journal.md).
_REAL_STUB = json.dumps(
    {
        "columns": [
            {"name": "srno", "heading": "Sr. No"},
            {"name": "symbol", "heading": "SYMBOL"},
            {"name": "companyName", "heading": "COMPANY NAME"},
            {"name": "isin", "heading": "ISIN"},
            {"name": "survCode", "heading": "ASM STAGE"},
        ]
    }
).encode()


def test_stub_is_rejected() -> None:
    with pytest.raises(SourceError, match="columns-only stub"):
        _reject_columns_only_stub(_REAL_STUB, "asm")


def test_bare_columns_key_is_rejected() -> None:
    with pytest.raises(SourceError, match="columns-only stub"):
        _reject_columns_only_stub(json.dumps({"columns": []}).encode(), "gsm")


def test_real_asm_shaped_payload_passes_through_untouched() -> None:
    b = asm_snapshot_bytes([("INE0000000A0", "AAA", "A Co", "Stage I")])
    _reject_columns_only_stub(b, "asm")  # must not raise


def test_real_gsm_shaped_payload_passes_through_untouched() -> None:
    b = gsm_snapshot_bytes([("INE0000000A0", "AAA", "A Co", "desc", "code")])
    _reject_columns_only_stub(b, "gsm")  # must not raise


def test_real_gsm_bare_array_payload_passes_through_untouched() -> None:
    b = gsm_snapshot_bytes([("INE0000000A0", "AAA", "A Co", "desc", "code")], wrapper_key=None)
    _reject_columns_only_stub(b, "gsm")  # must not raise


def test_empty_response_is_rejected() -> None:
    with pytest.raises(SourceError, match="empty response body"):
        _reject_columns_only_stub(b"", "asm")


def test_malformed_json_is_rejected() -> None:
    with pytest.raises(SourceError, match="not valid JSON"):
        _reject_columns_only_stub(b"not json at all", "gsm")


def test_unrecognized_but_real_shape_is_not_second_guessed() -> None:
    # The gate detects ONLY the specific known stub -- any other shape (even one this parser
    # doesn't yet understand) must pass through to curation, never be rejected here.
    b = json.dumps({"columns": [], "someFutureKey": {"rows": []}}).encode()
    _reject_columns_only_stub(b, "asm")  # must not raise
