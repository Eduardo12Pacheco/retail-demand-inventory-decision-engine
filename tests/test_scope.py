"""Workspace scaffold sanity checks.

These tests verify the prepared workspace contract only. They do not
pretend forecasting, simulation, or decision features exist.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_expected_directories_exist() -> None:
    for name in ("src", "tests", "docs", "data/fixtures", "data/manifests", "deploy"):
        assert (ROOT / name).is_dir(), f"missing expected directory: {name}"


def test_package_imports() -> None:
    import retail_demand_inventory

    assert retail_demand_inventory.__version__ == "0.1.0"
