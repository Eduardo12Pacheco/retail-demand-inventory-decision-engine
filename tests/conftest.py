from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from retail_demand_inventory.data import (
    DemandRecord,
    DemandTable,
    load_canonical_csv,
    load_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo_root() -> Path:
    return ROOT


@pytest.fixture
def fixture_table() -> DemandTable:
    return load_canonical_csv(
        ROOT / "data/fixtures" / "freshretailnet_style_synthetic.csv"
    )


@pytest.fixture
def fixture_manifest():
    return load_manifest(ROOT / "data/manifests" / "fixture_synthetic.json")


def make_table(
    demands: list[float],
    *,
    sku: str = "sku-1",
    start: date = date(2024, 1, 1),
    category: str | None = "cat-1",
) -> DemandTable:
    records = [
        DemandRecord(
            sku=sku,
            date=start + timedelta(days=i),
            demand_units=value,
            category=category,
        )
        for i, value in enumerate(demands)
    ]
    return DemandTable.from_records(records)


@pytest.fixture
def table_factory():
    return make_table
