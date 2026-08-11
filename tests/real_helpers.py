"""Shared helpers for real-snapshot tests (offline, tiny temporary parquet).

Temp parquet files are built in the full pinned-snapshot schema (all expected
columns and types) so schema verification exercises the same code path as the
real 4.85M-row files.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from retail_demand_inventory.data.manifests import sha256_file
from retail_demand_inventory.data.real_manifest import (
    RawFileEntry,
    RealSnapshotManifest,
)

REVISION = "08c1fab7f9257bc73679d415d65d644165d351d4"
BASE_URL = f"https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/resolve/{REVISION}/data"

FULL_SCHEMA = pa.schema(
    [
        ("city_id", pa.int64()),
        ("store_id", pa.int64()),
        ("management_group_id", pa.int64()),
        ("first_category_id", pa.int64()),
        ("second_category_id", pa.int64()),
        ("third_category_id", pa.int64()),
        ("product_id", pa.int64()),
        ("dt", pa.string()),
        ("sale_amount", pa.float64()),
        ("hours_sale", pa.list_(pa.float64())),
        ("stock_hour6_22_cnt", pa.int32()),
        ("hours_stock_status", pa.list_(pa.int64())),
        ("discount", pa.float64()),
        ("holiday_flag", pa.int32()),
        ("activity_flag", pa.int32()),
        ("precpt", pa.float64()),
        ("avg_temperature", pa.float64()),
        ("avg_humidity", pa.float64()),
        ("avg_wind_level", pa.float64()),
    ]
)

_DEFAULTS = {
    "city_id": None,
    "store_id": None,
    "product_id": None,
    "first_category_id": None,
    "dt": None,
    "sale_amount": None,
    "stock_hour6_22_cnt": None,
    "hours_sale": [],
    "hours_stock_status": [],
    "discount": None,
    "holiday_flag": None,
    "activity_flag": None,
    "precpt": None,
    "avg_temperature": None,
    "avg_humidity": None,
    "avg_wind_level": None,
}


def frn_table(rows) -> pa.Table:
    """pyarrow table in the full pinned-snapshot schema from list-of-dict rows."""
    arrays = [
        pa.array([row.get(name, _DEFAULTS.get(name)) for row in rows], type=arrow_type)
        for name, arrow_type in zip(FULL_SCHEMA.names, FULL_SCHEMA.types)
    ]
    return pa.table(arrays, schema=FULL_SCHEMA)


def write_split(directory: Path, name: str, rows) -> Path:
    """Write rows to `directory/{name}.parquet`; returns the path."""
    path = directory / f"{name}.parquet"
    pq.write_table(frn_table(rows), path)
    return path


def daily_rows(
    keys, start: str, n: int, *, sale=1.0, category=1, stock=0
) -> list[dict]:
    """Consecutive daily rows for each (store_id, product_id) key over `n` days."""
    rows: list[dict] = []
    d0 = date.fromisoformat(start)
    for store, product in keys:
        for i in range(n):
            rows.append(
                {
                    "store_id": store,
                    "product_id": product,
                    "dt": (d0 + timedelta(days=i)).isoformat(),
                    "sale_amount": sale,
                    "first_category_id": category,
                    "stock_hour6_22_cnt": stock,
                }
            )
    return rows


def make_manifest(
    raw_dir: Path,
    *,
    train_name: str,
    eval_name: str,
    canonical_sha: str | None = None,
    schema_report_path: str | None = None,
    gates: dict | None = None,
    canonicalization_version: str = "1",
    stockout_derivation_version: str = "1",
    observed: bool = True,
) -> RealSnapshotManifest:
    """Build a valid RealSnapshotManifest over the two temp parquet files."""
    train = raw_dir / train_name
    eval_file = raw_dir / eval_name
    raw_dir.mkdir(parents=True, exist_ok=True)
    if not train.exists():
        pq.write_table(frn_table(daily_rows(((0, 0),), "2024-01-01", 3)), train)
    if not eval_file.exists():
        pq.write_table(frn_table(daily_rows(((0, 0),), "2024-01-04", 3)), eval_file)

    def entry(name: str, local: Path) -> RawFileEntry:
        size = local.stat().st_size
        sha = sha256_file(local)
        return RawFileEntry(
            name=name,
            local_name=local.name,
            url=f"{BASE_URL}/{name}.parquet",
            expected_size=size,
            expected_sha256=sha,
            expected_checksum_source="test fixture",
            observed_size=size if observed else None,
            observed_sha256=sha if observed else None,
        )

    all_gates = {
        "source_verified": True,
        "license_verified": True,
        "snapshot_verified": True,
        "schema_verified": True,
        "stockout_semantics_verified": True,
    }
    if gates is not None:
        all_gates.update(gates)
    return RealSnapshotManifest(
        manifest_version="1",
        dataset_id="Dingdong-Inc/FreshRetailNet-50K",
        name="test real snapshot",
        publisher="test-publisher",
        pinned_revision=REVISION,
        source_urls={"page": "https://example.invalid/page"},
        retrieval_date="2026-08-11",
        dataset_version="1.0",
        license_name="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/legalcode",
        attribution="test attribution",
        citation="test citation",
        access_method="test",
        raw_files=(entry("train", train), entry("eval", eval_file)),
        canonicalization_version=canonicalization_version,
        canonicalization_rule="test canonicalization rule",
        canonical_content_sha256=canonical_sha,
        schema_report_path=schema_report_path,
        stockout_derivation_version=stockout_derivation_version,
        stockout_derivation_rule="test stockout rule",
        gates=all_gates,
    )
