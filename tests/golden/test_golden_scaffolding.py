"""P0-01 placeholder; the sacred 3-stock/8-quarter golden scenario (doc 16) lands with P0-11.

Golden tests reproduce hand-computed results to the paisa; expected values are never
updated to make a run pass without a written justification.
"""

from pathlib import Path


def test_fixture_directory_exists() -> None:
    assert (Path(__file__).parent.parent / "fixtures").is_dir()
