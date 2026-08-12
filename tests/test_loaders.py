from __future__ import annotations

import csv
from datetime import date

import pytest

from retail_demand_inventory.data import (
    FreshRetailNetRowMapper,
    LoaderError,
    load_canonical_csv,
    load_fresh_retail_net,
)
from retail_demand_inventory.data.contracts import DemandRecord


def _write_csv(path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def test_load_canonical_csv_roundtrip(tmp_path, repo_root) -> None:
    src = repo_root / "data" / "fixtures" / "freshretailnet_style_synthetic.csv"
    table = load_canonical_csv(src)
    assert len(table.skus) == 2
    assert all(len(table.series_for(sku)) == 120 for sku in table.skus)
    assert all(r.demand_units >= 0 for r in table.records)


def test_load_canonical_csv_optional_columns(tmp_path) -> None:
    path = _write_csv(
        tmp_path / "canonical.csv",
        ["sku", "date", "demand_units"],
        [["s1", "2024-01-01", "1.5"], ["s1", "2024-01-02", "0.0"]],
    )
    table = load_canonical_csv(path)
    assert table.records[0].category is None
    assert table.records[0].stockout_flag is None


def test_load_canonical_csv_bad_row_raises(tmp_path) -> None:
    path = _write_csv(
        tmp_path / "bad.csv",
        ["sku", "date", "demand_units"],
        [["s1", "not-a-date", "1.0"]],
    )
    with pytest.raises(LoaderError):
        load_canonical_csv(path)


def test_load_canonical_csv_negative_raises(tmp_path) -> None:
    path = _write_csv(
        tmp_path / "neg.csv",
        ["sku", "date", "demand_units"],
        [["s1", "2024-01-01", "-1.0"]],
    )
    with pytest.raises(LoaderError):
        load_canonical_csv(path)


def test_load_canonical_csv_empty_raises(tmp_path) -> None:
    path = _write_csv(tmp_path / "empty.csv", ["sku", "date", "demand_units"], [])
    with pytest.raises(LoaderError):
        load_canonical_csv(path)


def test_fresh_retail_net_mapper() -> None:
    mapper = FreshRetailNetRowMapper()
    record = mapper.map_row(
        {
            "dt": "2024-03-28",
            "store_id": "7",
            "product_id": "38",
            "sale_amount": "0.1",
            "first_category_id": "5",
            "stock_hour6_22_cnt": "3",
        }
    )
    assert record == DemandRecord(
        sku="7|38",
        date=date(2024, 3, 28),
        demand_units=0.1,
        category="5",
        stockout_flag=True,
    )


def test_fresh_retail_net_mapper_continuous_demand_and_no_stockout() -> None:
    mapper = FreshRetailNetRowMapper()
    record = mapper.map_row(
        {
            "dt": "2024-03-28",
            "store_id": "7",
            "product_id": "38",
            "sale_amount": "0.77",
            "first_category_id": "5",
            "stock_hour6_22_cnt": "0",
        }
    )
    assert record.demand_units == 0.77
    assert record.stockout_flag is False


def test_fresh_retail_net_mapper_missing_fields_raise(tmp_path) -> None:
    mapper = FreshRetailNetRowMapper()
    with pytest.raises(LoaderError):
        mapper.map_row({"dt": "2024-03-28", "product_id": "38", "sale_amount": "0.1"})
    with pytest.raises(LoaderError):
        mapper.map_row({"dt": "2024-03-28", "store_id": "7", "product_id": "38"})


def test_load_fresh_retail_net_fills_gaps(tmp_path) -> None:
    path = _write_csv(
        tmp_path / "frn.csv",
        [
            "dt",
            "store_id",
            "product_id",
            "sale_amount",
            "first_category_id",
            "stock_hour6_22_cnt",
        ],
        [
            ["2024-01-01", "7", "38", "0.1", "5", "0"],
            ["2024-01-03", "7", "38", "0.2", "5", "0"],
        ],
    )
    table = load_fresh_retail_net(path)
    series = table.daily_series("7|38")
    assert [d.isoformat() for d, _ in series] == [
        "2024-01-01",
        "2024-01-02",
        "2024-01-03",
    ]
    assert series[1][1] == 0.0
    assert table.series_for("7|38")[1].stockout_flag is None


def test_fresh_retail_net_loader_is_offline(tmp_path) -> None:
    path = _write_csv(
        tmp_path / "frn.csv",
        [
            "dt",
            "store_id",
            "product_id",
            "sale_amount",
            "first_category_id",
            "stock_hour6_22_cnt",
        ],
        [["2024-01-01", "7", "38", "0.1", "5", "0"]],
    )
    table = load_fresh_retail_net(path)
    assert table.skus == ("7|38",)
