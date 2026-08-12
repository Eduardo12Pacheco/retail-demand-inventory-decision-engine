from __future__ import annotations

from datetime import date

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from real_helpers import daily_rows, frn_table, make_manifest, write_split

from retail_demand_inventory.data import (
    EXPECTED_REAL_SCHEMA,
    MAX_POPULATION_KEYS,
    REQUIRED_HISTORY_DAYS,
    DemandRecord,
    RealLoaderError,
    RowRejection,
    canonical_content_sha256,
    canonical_serialize,
    inspect_parquet_schema,
    load_real_snapshot,
    map_real_row,
    select_population,
    sha256_file,
    verify_parquet_schema,
)
from retail_demand_inventory.data.real_loader import USED_COLUMNS


def _row(**overrides):
    base = {
        "store_id": 1,
        "product_id": 2,
        "dt": "2024-03-28",
        "sale_amount": 1.5,
        "first_category_id": 5,
        "stock_hour6_22_cnt": 0,
    }
    base.update(overrides)
    return base


def _manifest_and_dataset(
    tmp_path, *, keys=((1, 1), (1, 2)), train_days=70, eval_days=7
):
    raw = tmp_path / "raw"
    raw.mkdir()
    write_split(raw, "train", daily_rows(keys, "2024-01-01", train_days))
    write_split(raw, "eval", daily_rows(keys, "2024-03-11", eval_days))
    manifest = make_manifest(raw, train_name="train.parquet", eval_name="eval.parquet")
    return manifest, raw


def test_inspect_parquet_schema_matches_expected(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    path = write_split(raw, "train", daily_rows(((1, 1),), "2024-01-01", 5))
    actual = inspect_parquet_schema(path)
    assert set(actual) == set(EXPECTED_REAL_SCHEMA)
    for column, expected_type in EXPECTED_REAL_SCHEMA.items():
        assert actual[column] == expected_type
    assert actual["sale_amount"] == "double"
    assert actual["stock_hour6_22_cnt"] == "int32"
    assert actual["hours_stock_status"] == "list<element: int64>"


def test_verify_parquet_schema_ok(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    path = write_split(raw, "train", daily_rows(((1, 1),), "2024-01-01", 5))
    assert verify_parquet_schema(path, EXPECTED_REAL_SCHEMA, where="train.parquet") == (
        inspect_parquet_schema(path)
    )


def test_verify_parquet_schema_missing_column_fails(tmp_path) -> None:
    table = frn_table(daily_rows(((1, 1),), "2024-01-01", 2))
    table = table.drop(["stock_hour6_22_cnt"])
    path = tmp_path / "train.parquet"
    pq.write_table(table, path)
    with pytest.raises(RealLoaderError, match="missing expected columns"):
        verify_parquet_schema(path, EXPECTED_REAL_SCHEMA, where="train.parquet")


def test_verify_parquet_schema_wrong_type_fails(tmp_path) -> None:
    from real_helpers import FULL_SCHEMA

    schema = pa.schema(
        [
            (name, pa.int32() if name == "sale_amount" else arrow_type)
            for name, arrow_type in zip(FULL_SCHEMA.names, FULL_SCHEMA.types)
        ]
    )

    def _array(name: str, arrow_type) -> pa.Array:
        if pa.types.is_list(arrow_type):
            return pa.array([[]], type=arrow_type)
        if pa.types.is_string(arrow_type):
            return pa.array(["2024-01-01"], type=arrow_type)
        return pa.array([1], type=arrow_type)

    table = pa.table(
        [
            _array(name, arrow_type)
            for name, arrow_type in zip(schema.names, schema.types)
        ],
        schema=schema,
    )
    path = tmp_path / "train.parquet"
    pq.write_table(table, path)
    with pytest.raises(RealLoaderError, match="sale_amount"):
        verify_parquet_schema(path, EXPECTED_REAL_SCHEMA, where="train.parquet")


def test_map_row_continuous_demand_and_direct_stockout() -> None:
    assert map_real_row(_row(sale_amount=0.77, stock_hour6_22_cnt=3)) == DemandRecord(
        sku="1|2",
        date=date(2024, 3, 28),
        demand_units=0.77,
        category="5",
        stockout_flag=True,
    )
    record = map_real_row(_row(stock_hour6_22_cnt=0))
    assert record.stockout_flag is False


def test_map_row_zero_sales_never_imply_stockout() -> None:
    unknown = map_real_row(_row(sale_amount=0.0, stock_hour6_22_cnt=None))
    assert unknown.stockout_flag is None
    assert unknown.demand_units == 0.0
    no_stockout = map_real_row(_row(sale_amount=0.0, stock_hour6_22_cnt=0))
    assert no_stockout.stockout_flag is False


def test_map_row_unknown_remains_unknown() -> None:
    record = map_real_row(_row(stock_hour6_22_cnt=None))
    assert record.stockout_flag is None


def test_map_row_invalid_stockout_values_rejected() -> None:
    for bad in (18, -1, 3.5, "abc"):
        result = map_real_row(_row(stock_hour6_22_cnt=bad))
        assert isinstance(result, RowRejection)
        assert result.reason == "invalid_stockout_value"


def test_map_row_invalid_timestamp_rejected() -> None:
    result = map_real_row(_row(dt="not-a-date"))
    assert isinstance(result, RowRejection)
    assert result.reason == "invalid_date"


def test_map_row_negative_and_nonfinite_demand_rejected() -> None:
    result = map_real_row(_row(sale_amount=-1.0))
    assert isinstance(result, RowRejection)
    assert result.reason == "negative_demand"
    result = map_real_row(_row(sale_amount=float("nan")))
    assert isinstance(result, RowRejection)
    assert result.reason == "nonfinite_demand"


def test_map_row_missing_required_fields_rejected() -> None:
    assert map_real_row(_row(sale_amount=None)).reason == "missing_demand"
    assert map_real_row(_row(dt=None)).reason == "missing_date"
    assert map_real_row(_row(store_id=None)).reason == "missing_sku"


def test_canonical_and_raw_checksums_are_distinct(tmp_path) -> None:
    manifest, raw = _manifest_and_dataset(tmp_path)
    result = load_real_snapshot(
        manifest,
        raw,
        required_history_days=REQUIRED_HISTORY_DAYS,
        max_keys=MAX_POPULATION_KEYS,
    )
    raw_digest = sha256_file(raw / "train.parquet")
    assert result.canonical_sha256 != raw_digest
    assert result.canonical_sha256 == canonical_content_sha256(result.table)
    assert len(result.canonical_sha256) == 64


def test_canonical_serialize_is_deterministic(tmp_path) -> None:
    manifest, raw = _manifest_and_dataset(tmp_path)
    a = load_real_snapshot(
        manifest,
        raw,
        required_history_days=REQUIRED_HISTORY_DAYS,
        max_keys=MAX_POPULATION_KEYS,
    )
    b = load_real_snapshot(
        manifest,
        raw,
        required_history_days=REQUIRED_HISTORY_DAYS,
        max_keys=MAX_POPULATION_KEYS,
    )
    assert canonical_serialize(a.table) == canonical_serialize(b.table)
    assert a.canonical_sha256 == b.canonical_sha256


def test_population_selects_first_sorted_keys(tmp_path) -> None:
    keys = ((0, 20), (0, 5), (1, 9), (0, 104), (2, 3))
    raw = tmp_path / "raw"
    raw.mkdir()
    write_split(raw, "train", daily_rows(keys, "2024-01-01", 90))
    write_split(raw, "eval", daily_rows(keys, "2024-03-31", 7))
    selection = select_population(
        raw / "train.parquet",
        raw / "eval.parquet",
        required_history_days=63,
        max_keys=3,
    )
    assert selection.selected_keys == ("0|5", "0|20", "0|104")
    assert selection.selected_key_count == 3
    assert selection.excluded_key_count == 2
    assert selection.selected_row_count == 3 * 97
    assert selection.source_row_count == 5 * 97
    assert selection.date_range == (date(2024, 1, 1), date(2024, 4, 6))
    assert "No random sampling" in selection.rule


def test_population_requires_history_and_shared_span(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    write_split(raw, "train", daily_rows(((1, 1), (1, 2)), "2024-01-01", 20))
    write_split(raw, "eval", daily_rows(((1, 1), (1, 2)), "2024-01-21", 7))
    selection = select_population(
        raw / "train.parquet",
        raw / "eval.parquet",
        required_history_days=63,
        max_keys=2,
    )
    assert selection.selected_keys == ()


def test_load_real_snapshot_ok_and_summary(tmp_path) -> None:
    manifest, raw = _manifest_and_dataset(tmp_path)
    result = load_real_snapshot(
        manifest,
        raw,
        required_history_days=REQUIRED_HISTORY_DAYS,
        max_keys=MAX_POPULATION_KEYS,
    )
    assert result.table.skus == ("1|1", "1|2")
    assert result.rejected_by_reason == {}
    assert result.gap_fill_records == 0
    assert result.duplicate_count == 0
    assert result.demand_summary["nonnegative"] is True
    assert result.stockout_summary["unknown"] == 0
    assert result.selection.selected_key_count == 2


def test_loader_rejects_and_counts_deterministically(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    from datetime import timedelta

    d0 = date(2024, 1, 1)
    end = date(2024, 3, 10)
    valid = [
        {
            "store_id": 1,
            "product_id": 1,
            "dt": (d0 + timedelta(days=i)).isoformat(),
            "sale_amount": 1.0,
            "first_category_id": 1,
            "stock_hour6_22_cnt": 0,
        }
        for i in range((end - d0).days + 1)
        if d0 + timedelta(days=i) != date(2024, 1, 31)
    ]
    valid.append(
        {
            "store_id": 1,
            "product_id": 1,
            "dt": "2024-01-31",
            "sale_amount": -5.0,
            "first_category_id": 1,
            "stock_hour6_22_cnt": 0,
        }
    )
    rows = valid + daily_rows(((1, 2),), "2024-01-01", 70)
    write_split(raw, "train", rows)
    write_split(raw, "eval", daily_rows(((1, 1), (1, 2)), "2024-03-11", 7))
    manifest = make_manifest(raw, train_name="train.parquet", eval_name="eval.parquet")
    result_a = load_real_snapshot(
        manifest,
        raw,
        required_history_days=REQUIRED_HISTORY_DAYS,
        max_keys=MAX_POPULATION_KEYS,
    )
    result_b = load_real_snapshot(
        manifest,
        raw,
        required_history_days=REQUIRED_HISTORY_DAYS,
        max_keys=MAX_POPULATION_KEYS,
    )
    assert result_a.rejected_by_reason == {"negative_demand": 1}
    assert result_a.duplicate_count == 0
    assert result_a.gap_fill_records == 1
    assert result_a.canonical_sha256 == result_b.canonical_sha256


def test_loader_rejects_duplicate_rows(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    rows = daily_rows(((1, 1), (1, 2)), "2024-01-01", 70)
    rows.append(
        {
            "store_id": 1,
            "product_id": 1,
            "dt": "2024-01-02",
            "sale_amount": 2.0,
            "first_category_id": 1,
            "stock_hour6_22_cnt": 0,
        }
    )
    write_split(raw, "train", rows)
    write_split(raw, "eval", daily_rows(((1, 1), (1, 2)), "2024-03-11", 7))
    manifest = make_manifest(raw, train_name="train.parquet", eval_name="eval.parquet")
    result = load_real_snapshot(
        manifest,
        raw,
        required_history_days=REQUIRED_HISTORY_DAYS,
        max_keys=MAX_POPULATION_KEYS,
    )
    assert result.rejected_by_reason == {"duplicate_key": 1}
    assert result.duplicate_count == 1


def test_loader_reads_only_used_columns() -> None:
    assert set(USED_COLUMNS) == {
        "store_id",
        "product_id",
        "dt",
        "sale_amount",
        "first_category_id",
        "stock_hour6_22_cnt",
    }


def test_loader_requires_documented_stockout_derivation(tmp_path) -> None:
    manifest, raw = _manifest_and_dataset(tmp_path)
    from dataclasses import replace

    bad = replace(manifest, stockout_derivation_version="2")
    with pytest.raises(RealLoaderError, match="stockout_derivation_version"):
        load_real_snapshot(
            bad,
            raw,
            required_history_days=REQUIRED_HISTORY_DAYS,
            max_keys=MAX_POPULATION_KEYS,
        )


def test_loader_unsupported_schema_version_raises(tmp_path) -> None:
    manifest, raw = _manifest_and_dataset(tmp_path)
    from dataclasses import replace

    bad = replace(manifest, canonicalization_version="999")
    with pytest.raises(RealLoaderError, match="canonicalization_version"):
        load_real_snapshot(
            bad,
            raw,
            required_history_days=REQUIRED_HISTORY_DAYS,
            max_keys=MAX_POPULATION_KEYS,
        )


def test_loader_requires_observed_checksums(tmp_path) -> None:
    from retail_demand_inventory.data import ManifestError

    manifest, raw = _manifest_and_dataset(tmp_path)
    from dataclasses import replace

    unobserved = replace(
        manifest,
        raw_files=tuple(
            replace(entry, observed_size=None, observed_sha256=None)
            for entry in manifest.raw_files
        ),
    )
    with pytest.raises(ManifestError, match="observed"):
        load_real_snapshot(
            unobserved,
            raw,
            required_history_days=REQUIRED_HISTORY_DAYS,
            max_keys=MAX_POPULATION_KEYS,
        )
