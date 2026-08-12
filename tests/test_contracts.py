from __future__ import annotations

from datetime import date

import pytest

from retail_demand_inventory.data.contracts import (
    DailyCadenceIssue,
    DataValidationError,
    DemandRecord,
    DemandTable,
    DuplicateKeyIssue,
    InvalidDateIssue,
    InvalidSkuIssue,
    MissingValueIssue,
    NegativeDemandIssue,
    NonFiniteDemandIssue,
    TimestampOrderingIssue,
    validate_records,
)


def test_from_records_sorts_by_sku_and_date() -> None:
    records = [
        DemandRecord("sku-b", date(2024, 1, 2), 2.0),
        DemandRecord("sku-a", date(2024, 1, 2), 1.0),
        DemandRecord("sku-a", date(2024, 1, 1), 0.5),
    ]
    table = DemandTable.from_records(records)
    assert [(r.sku, r.date.isoformat()) for r in table.records] == [
        ("sku-a", "2024-01-01"),
        ("sku-a", "2024-01-02"),
        ("sku-b", "2024-01-02"),
    ]


def test_duplicate_key_detected() -> None:
    records = [
        DemandRecord("sku-a", date(2024, 1, 1), 1.0),
        DemandRecord("sku-a", date(2024, 1, 1), 2.0),
    ]
    issues = validate_records(records)
    assert any(isinstance(i, DuplicateKeyIssue) for i in issues)
    with pytest.raises(DataValidationError):
        DemandTable.from_records(records)


def test_negative_demand_detected() -> None:
    issues = validate_records([DemandRecord("sku-a", date(2024, 1, 1), -1.0)])
    assert any(isinstance(i, NegativeDemandIssue) for i in issues)


def test_nan_and_inf_demand_detected() -> None:
    for bad in (float("nan"), float("inf"), float("-inf")):
        issues = validate_records([DemandRecord("sku-a", date(2024, 1, 1), bad)])
        assert any(isinstance(i, NonFiniteDemandIssue) for i in issues)


def test_missing_demand_detected() -> None:
    records = [
        DemandRecord("sku-a", date(2024, 1, 1), 0.0),
        DemandRecord("sku-a", date(2024, 1, 2), None),
    ]  # type: ignore[arg-type]
    issues = validate_records(records)
    assert any(isinstance(i, MissingValueIssue) for i in issues)


def test_invalid_sku_detected() -> None:
    issues = validate_records([DemandRecord("", date(2024, 1, 1), 1.0)])
    assert any(isinstance(i, InvalidSkuIssue) for i in issues)


def test_invalid_date_detected() -> None:
    issues = validate_records([DemandRecord("sku-a", "2024-01-01", 1.0)])  # type: ignore[arg-type]
    assert any(isinstance(i, InvalidDateIssue) for i in issues)


def test_timestamp_ordering_detected() -> None:
    records = [
        DemandRecord("sku-a", date(2024, 1, 2), 1.0),
        DemandRecord("sku-a", date(2024, 1, 1), 1.0),
    ]
    issues = validate_records(records)
    assert any(isinstance(i, TimestampOrderingIssue) for i in issues)


def test_daily_cadence_gap_detected() -> None:
    records = [
        DemandRecord("sku-a", date(2024, 1, 1), 1.0),
        DemandRecord("sku-a", date(2024, 1, 3), 1.0),
    ]
    issues = validate_records(records)
    assert any(isinstance(i, DailyCadenceIssue) for i in issues)
    table = DemandTable.from_records(records, require_daily_cadence=False)
    assert len(table.records) == 2


def test_from_records_raises_aggregate_on_any_issue() -> None:
    with pytest.raises(DataValidationError):
        DemandTable.from_records([DemandRecord("sku-a", date(2024, 1, 1), -5.0)])


def test_continuous_non_integer_demand_is_valid() -> None:
    table = DemandTable.from_records(
        [
            DemandRecord("sku-a", date(2024, 1, 1), 0.77),
            DemandRecord("sku-a", date(2024, 1, 2), 1.09),
        ]
    )
    assert table.records[0].demand_units == 0.77


def test_optional_fields_are_none_by_default() -> None:
    record = DemandRecord("sku-a", date(2024, 1, 1), 1.0)
    assert record.category is None
    assert record.stockout_flag is None


def test_series_for_and_category_for() -> None:
    table = DemandTable.from_records(
        [
            DemandRecord("sku-b", date(2024, 1, 1), 2.0, category="x"),
            DemandRecord("sku-a", date(2024, 1, 1), 1.0, category="y"),
            DemandRecord("sku-a", date(2024, 1, 2), 1.5, category="y"),
        ]
    )
    assert table.series_for("sku-a")[1].demand_units == 1.5
    assert table.category_for("sku-a") == "y"
    assert table.skus == ("sku-a", "sku-b")
