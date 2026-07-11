"""P0-01 placeholder: prove the installed package and CLI wiring end-to-end."""

import json

from typer.testing import CliRunner

import quant
from quant.cli import app


def test_status_reports_ok_and_version() -> None:
    result = CliRunner().invoke(app, ["status"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == {"ok": True, "version": quant.__version__}
