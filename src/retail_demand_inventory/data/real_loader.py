"""Parquet schema inspection and deterministic canonical loading for a pinned
real-data snapshot (FreshRetailNet-50K).

This module reads ONLY the columns needed for the canonical demand record plus
the stockout derivation, maps them deterministically into the canonical
`DemandRecord` schema, and never fabricates a stockout flag:

- `sku`        <- `"{store_id}|{product_id}"`
- `date`       <- `dt`
- `demand_units` <- `sale_amount` (non-negative finite float; observed sales)
- `category`   <- `first_category_id`
- `stockout_flag` <- `stock_hour6_22_cnt > 0` (documented count of out-of-stock
  hours 06:00-22:00); missing value stays unknown (`None`); the value must be
  an integer in 0..17. Zero sales NEVER imply a stockout.

Invalid rows are never silently dropped: every rejected row is counted with a
deterministic reason. Internal missing days within a SKU's observed span are
filled with `demand_units = 0.0` and `stockout_flag = None` (documented policy:
a missing record is not evidence of a stockout).

Population rule (documented BEFORE any metric; no random sampling):
"Deterministic bounded evaluation over pinned snapshot": keys observed in
train whose combined train+eval records cover at least `required_history_days`
consecutive days AND share the identical date span with the modal span among
qualifying keys; select the first `max_keys` in ascending (store_id,
product_id) order. The shared-span requirement guarantees every selected key
spans the same calendar, which the evaluation protocol requires.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from .contracts import DataValidationError, DemandRecord, DemandTable
from .loaders import _fill_daily_gaps
from .manifests import sha256_bytes
from .real_manifest import (
    SUPPORTED_CANONICALIZATION_VERSION,
    SUPPORTED_STOCKOUT_DERIVATION_VERSION,
    RealSnapshotManifest,
)

# Canonical schema expected in the pinned snapshot's parquet files. Recorded
# from the verified bytes (fields/types match the pinned README; the parquet
# bytes use list<element: int64> for hours_stock_status, see source-contract).
EXPECTED_REAL_SCHEMA: dict[str, str] = {
    "city_id": "int64",
    "store_id": "int64",
    "management_group_id": "int64",
    "first_category_id": "int64",
    "second_category_id": "int64",
    "third_category_id": "int64",
    "product_id": "int64",
    "dt": "string",
    "sale_amount": "double",
    "hours_sale": "list<element: double>",
    "stock_hour6_22_cnt": "int32",
    "hours_stock_status": "list<element: int64>",
    "discount": "double",
    "holiday_flag": "int32",
    "activity_flag": "int32",
    "precpt": "double",
    "avg_temperature": "double",
    "avg_humidity": "double",
    "avg_wind_level": "double",
}

# Columns the real loader actually consumes. Everything else is preserved in
# the raw bytes under data/raw for audit but is not read into memory.
USED_COLUMNS = (
    "store_id",
    "product_id",
    "dt",
    "sale_amount",
    "first_category_id",
    "stock_hour6_22_cnt",
)
SELECTION_COLUMNS = ("store_id", "product_id", "dt")

# Population bounds: the expanding-window protocol needs
# MIN_TRAIN_PERIODS + HORIZON + FINAL_TEST_PERIODS = 42 + 7 + 14 consecutive
# days per SKU, and the evaluation is deliberately bounded.
REQUIRED_HISTORY_DAYS = 63
MAX_POPULATION_KEYS = 10

# Documented stockout derivation rule (docs/source-contract.md).
STOCKOUT_DERIVATION_RULE = (
    "stock_hour6_22_cnt > 0 (documented number of out-of-stock hours in "
    "06:00-22:00) => stockout_flag True; 0 => False; missing => unknown (None); "
    "value validated as integer in 0..17; never derived from sale_amount."
)

CANONICALIZATION_RULE = (
    "Read only used columns from the pinned parquet files; map "
    "store_id|product_id -> sku, dt -> date, sale_amount -> demand_units, "
    "first_category_id -> category, stock_hour6_22_cnt > 0 -> stockout_flag; "
    "reject invalid rows with deterministic reasons; fill internal missing "
    "days within each SKU's observed span with demand_units=0.0 and "
    "stockout_flag=None; canonical content = JSON of the sorted canonical "
    "records over the bounded population."
)


class RealLoaderError(ValueError):
    """Raised when a real snapshot cannot be loaded or verified."""


@dataclass(frozen=True)
class RowRejection:
    """A deterministic reason a source row was not accepted."""

    reason: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"reason": self.reason, "detail": self.detail}


def _scalar_type_str(arrow_type: pa.DataType) -> str:
    """Canonical, pyarrow-version-stable type string (normalizes list naming)."""
    if pa.types.is_list(arrow_type):
        return f"list<element: {_scalar_type_str(arrow_type.value_type)}>"
    return str(arrow_type)


def inspect_parquet_schema(path: Path) -> dict[str, str]:
    """Return {column: canonical type string} from the parquet file's schema."""
    schema = pq.read_schema(path)
    return {field.name: _scalar_type_str(field.type) for field in schema}


def verify_parquet_schema(
    path: Path, expected: Mapping[str, str], *, where: str
) -> dict[str, str]:
    """Validate the parquet schema against the expected columns/types."""
    actual = inspect_parquet_schema(path)
    missing = sorted(set(expected) - set(actual))
    if missing:
        raise RealLoaderError(
            f"{where}: schema missing expected columns: {', '.join(missing)}"
        )
    unexpected = sorted(set(actual) - set(expected))
    if unexpected:
        raise RealLoaderError(
            f"{where}: schema has unexpected columns: {', '.join(unexpected)}"
        )
    for column, expected_type in expected.items():
        if actual[column] != expected_type:
            raise RealLoaderError(
                f"{where}: column {column!r} type {actual[column]!r} "
                f"!= expected {expected_type!r}"
            )
    return actual


def map_real_row(
    row: Mapping[str, object], *, where: str = "<row>"
) -> DemandRecord | RowRejection:
    """Map one raw source row to a canonical `DemandRecord` or a rejection."""
    store = row.get("store_id")
    product = row.get("product_id")
    if store is None or product is None or str(store).strip() == "":
        return RowRejection(
            "missing_sku", f"{where}: store_id and product_id are required"
        )
    sku = f"{store}|{product}"

    raw_dt = row.get("dt")
    if raw_dt is None or str(raw_dt).strip() == "":
        return RowRejection("missing_date", f"{where}: dt is required")
    try:
        when = date.fromisoformat(str(raw_dt).strip())
    except ValueError:
        return RowRejection("invalid_date", f"{where}: invalid dt {raw_dt!r}")

    raw_sale = row.get("sale_amount")
    if raw_sale is None or str(raw_sale).strip() == "":
        return RowRejection("missing_demand", f"{where}: sale_amount is required")
    try:
        demand = float(raw_sale)
    except (TypeError, ValueError):
        return RowRejection(
            "nonfinite_demand", f"{where}: sale_amount {raw_sale!r} is not numeric"
        )
    if math.isnan(demand) or math.isinf(demand):
        return RowRejection("nonfinite_demand", f"{where}: sale_amount must be finite")
    if demand < 0:
        return RowRejection(
            "negative_demand", f"{where}: sale_amount must be >= 0, got {raw_sale!r}"
        )

    category: str | None = None
    raw_category = row.get("first_category_id")
    if raw_category is not None and str(raw_category).strip() != "":
        category = str(raw_category).strip()

    stockout: bool | None = None
    raw_cnt = row.get("stock_hour6_22_cnt")
    if raw_cnt is not None and str(raw_cnt).strip() not in {"", "nan", "null", "None"}:
        try:
            hours = float(str(raw_cnt).strip())
        except (TypeError, ValueError):
            return RowRejection(
                "invalid_stockout_value",
                f"{where}: stock_hour6_22_cnt {raw_cnt!r} is not numeric",
            )
        if not hours.is_integer() or not (0 <= hours <= 17):
            return RowRejection(
                "invalid_stockout_value",
                f"{where}: stock_hour6_22_cnt must be an integer in 0..17, "
                f"got {raw_cnt!r}",
            )
        stockout = int(hours) > 0

    return DemandRecord(
        sku=sku,
        date=when,
        demand_units=demand,
        category=category,
        stockout_flag=stockout,
    )


def canonical_serialize(table: DemandTable) -> bytes:
    """Deterministic byte serialization of the canonical table (sorted records)."""
    rows = [
        {
            "sku": record.sku,
            "date": record.date.isoformat(),
            "demand_units": record.demand_units,
            "category": record.category,
            "stockout_flag": record.stockout_flag,
        }
        for record in table.records
    ]
    payload = (
        json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    )
    return payload.encode("utf-8")


def canonical_content_sha256(table: DemandTable) -> str:
    """SHA-256 over the canonical serialization (distinct from raw file bytes)."""
    return sha256_bytes(canonical_serialize(table))


@dataclass(frozen=True)
class PopulationSelection:
    """Deterministic bounded population over the pinned snapshot."""

    rule: str
    required_history_days: int
    max_keys: int
    source_row_count: int
    selected_row_count: int
    excluded_row_count: int
    selected_key_count: int
    excluded_key_count: int
    candidate_key_count: int
    qualifying_key_count: int
    selected_keys: tuple[str, ...]
    date_range: tuple[date, date] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "rule": self.rule,
            "required_history_days": self.required_history_days,
            "max_keys": self.max_keys,
            "source_row_count": self.source_row_count,
            "selected_row_count": self.selected_row_count,
            "excluded_row_count": self.excluded_row_count,
            "selected_key_count": self.selected_key_count,
            "excluded_key_count": self.excluded_key_count,
            "candidate_key_count": self.candidate_key_count,
            "qualifying_key_count": self.qualifying_key_count,
            "selected_keys": list(self.selected_keys),
            "date_range": (
                [d.isoformat() for d in self.date_range] if self.date_range else None
            ),
        }


def _key_sort_key(key: str) -> tuple[int, int]:
    store, product = key.split("|", 1)
    return (int(store), int(product))


def _group_spans(path: Path) -> dict[str, tuple[str | None, str | None, int]]:
    """Per-key (min_dt, max_dt, count) from one parquet file."""
    table = pq.read_table(path, columns=list(SELECTION_COLUMNS))
    grouped = table.group_by(["store_id", "product_id"]).aggregate(
        [("dt", "min"), ("dt", "max"), ("dt", "count")]
    )
    spans: dict[str, tuple[str | None, str | None, int]] = {}
    for record in grouped.to_pylist():
        key = f"{record['store_id']}|{record['product_id']}"
        spans[key] = (record["dt_min"], record["dt_max"], int(record["dt_count"]))
    return spans


def _merge_spans(
    train: tuple[str | None, str | None, int] | None,
    eval_: tuple[str | None, str | None, int] | None,
) -> tuple[str | None, str | None, int]:
    counts = [c for span in (train, eval_) if span is not None for c in [span[2]]]
    total = sum(counts)
    mins = [
        span[0] for span in (train, eval_) if span is not None and span[0] is not None
    ]
    maxs = [
        span[1] for span in (train, eval_) if span is not None and span[1] is not None
    ]
    return (min(mins) if mins else None, max(maxs) if maxs else None, total)


def select_population(
    train_path: Path,
    eval_path: Path,
    *,
    required_history_days: int,
    max_keys: int,
) -> PopulationSelection:
    """Select the deterministic bounded population (documented rule above)."""
    if required_history_days <= 0:
        raise RealLoaderError("required_history_days must be positive")
    if max_keys <= 0:
        raise RealLoaderError("max_keys must be positive")

    train_spans = _group_spans(train_path)
    eval_spans = _group_spans(eval_path)
    all_keys = sorted(set(train_spans) | set(eval_spans))

    combined: dict[str, tuple[str | None, str | None, int]] = {}
    for key in all_keys:
        combined[key] = _merge_spans(train_spans.get(key), eval_spans.get(key))

    source_row_count = sum(span[2] for span in combined.values())

    candidates: list[tuple[str, date, date, int]] = []
    for key in all_keys:
        if key not in train_spans:
            continue  # "observed in train" only
        min_dt, max_dt, _count = combined[key]
        try:
            start = date.fromisoformat(str(min_dt))
            end = date.fromisoformat(str(max_dt))
        except (TypeError, ValueError):
            continue  # span cannot be determined; not a candidate
        span_days = (end - start).days + 1
        # Gaps and duplicate dates are handled deterministically by the row
        # loader (gap fill / duplicate rejection); the population rule here is
        # purely the required chronological history over the shared span.
        candidates.append((key, start, end, span_days))

    qualifying = [c for c in candidates if c[3] >= required_history_days]
    modal_counts = Counter((c[1], c[2]) for c in qualifying)
    if not modal_counts:
        return PopulationSelection(
            rule=_population_rule(required_history_days, max_keys),
            required_history_days=required_history_days,
            max_keys=max_keys,
            source_row_count=source_row_count,
            selected_row_count=0,
            excluded_row_count=source_row_count,
            selected_key_count=0,
            excluded_key_count=len(all_keys),
            candidate_key_count=len(candidates),
            qualifying_key_count=0,
            selected_keys=(),
            date_range=None,
        )
    reference_span = modal_counts.most_common(1)[0][0]
    selected = [
        c[0]
        for c in sorted(qualifying, key=lambda c: _key_sort_key(c[0]))
        if (c[1], c[2]) == reference_span
    ][:max_keys]

    selected_keys = tuple(selected)
    selected_row_count = sum(combined[key][2] for key in selected_keys)
    date_range = None
    if selected_keys:
        starts = [c[1] for c in qualifying if c[0] in set(selected_keys)]
        ends = [c[2] for c in qualifying if c[0] in set(selected_keys)]
        date_range = (min(starts), max(ends))

    return PopulationSelection(
        rule=_population_rule(required_history_days, max_keys),
        required_history_days=required_history_days,
        max_keys=max_keys,
        source_row_count=source_row_count,
        selected_row_count=selected_row_count,
        excluded_row_count=source_row_count - selected_row_count,
        selected_key_count=len(selected_keys),
        excluded_key_count=len(all_keys) - len(selected_keys),
        candidate_key_count=len(candidates),
        qualifying_key_count=len(qualifying),
        selected_keys=selected_keys,
        date_range=date_range,
    )


def _population_rule(required_history_days: int, max_keys: int) -> str:
    return (
        "Deterministic bounded evaluation over pinned snapshot: keys observed in "
        "train whose combined train+eval records span at least "
        f"{required_history_days} consecutive days AND share the identical date "
        "span (modal span among qualifying keys); select the "
        f"first {max_keys} keys in ascending (store_id, product_id) numeric order. "
        "No random sampling; no protocol change after results are seen."
    )


def _read_rows_for_keys(path: Path, keys: Sequence[str]) -> list[dict[str, object]]:
    """Read only the used columns, filtering to the selected keys."""
    if not keys:
        return []
    wanted = set(keys)
    store_ids = sorted({int(key.split("|", 1)[0]) for key in wanted})
    product_ids = sorted({int(key.split("|", 1)[1]) for key in wanted})
    dataset = ds.dataset(str(path))
    table = dataset.to_table(
        columns=list(USED_COLUMNS),
        filter=(ds.field("store_id").isin(store_ids))
        & (ds.field("product_id").isin(product_ids)),
    )
    selected: list[dict[str, object]] = []
    for record in table.to_pylist():
        key = f"{record['store_id']}|{record['product_id']}"
        if key in wanted:
            selected.append(record)
    return selected


@dataclass(frozen=True)
class RealSnapshotLoadResult:
    """Canonical table plus deterministic loading summary for the population."""

    table: DemandTable
    selection: PopulationSelection
    canonical_sha256: str
    rejected_by_reason: Mapping[str, int]
    gap_fill_records: int
    duplicate_count: int
    missing_value_counts: Mapping[str, int]
    unknown_stockout_records: int
    demand_summary: Mapping[str, object]
    stockout_summary: Mapping[str, object]

    def schema_report(
        self, manifest: RealSnapshotManifest, raw_dir: Path
    ) -> dict[str, Any]:
        """Deterministic, compact schema report over the loaded population."""
        return {
            "report_version": "1.0",
            "source": {
                "dataset_id": manifest.dataset_id,
                "pinned_revision": manifest.pinned_revision,
                "raw_files": [
                    {
                        "name": entry.name,
                        "local_name": entry.local_name,
                        "expected_size": entry.expected_size,
                        "observed_size": entry.observed_size,
                        "expected_sha256": entry.expected_sha256,
                        "observed_sha256": entry.observed_sha256,
                    }
                    for entry in manifest.raw_files
                ],
            },
            "population": self.selection.to_dict(),
            "inspection": {
                split_name: inspect_parquet_schema(raw_dir / entry.local_name)
                for split_name, entry in (
                    ("train", manifest.raw_file("train")),
                    ("eval", manifest.raw_file("eval")),
                )
            },
            "loading": {
                "frequency": "daily (validated per SKU; gaps filled only inside an observed span)",
                "raw_rows_read": self.selection.selected_row_count,
                "accepted_rows": len(self.table.records),
                "rejected_rows": sum(self.rejected_by_reason.values()),
                "rejected_by_reason": dict(self.rejected_by_reason),
                "duplicate_rows": self.duplicate_count,
                "gap_fill_records": self.gap_fill_records,
                "missing_value_counts": dict(self.missing_value_counts),
                "sku_count": len(self.table.skus),
                "date_range": (
                    [d.isoformat() for d in self.table.date_range()]
                    if self.table.records
                    else None
                ),
                "demand_summary": dict(self.demand_summary),
                "stockout_summary": dict(self.stockout_summary),
                "unknown_stockout_records": self.unknown_stockout_records,
            },
            "canonical": {
                "canonicalization_version": manifest.canonicalization_version,
                "canonicalization_rule": manifest.canonicalization_rule,
                "stockout_derivation_version": manifest.stockout_derivation_version,
                "stockout_derivation_rule": manifest.stockout_derivation_rule,
                "canonical_content_sha256": self.canonical_sha256,
            },
        }


def load_real_snapshot(
    manifest: RealSnapshotManifest,
    raw_dir: Path,
    *,
    required_history_days: int,
    max_keys: int,
) -> RealSnapshotLoadResult:
    """Load the deterministic bounded population from verified raw parquet files."""
    manifest.require_raw_ok(raw_dir)
    if manifest.stockout_derivation_version != SUPPORTED_STOCKOUT_DERIVATION_VERSION:
        raise RealLoaderError(
            "unsupported stockout_derivation_version: "
            f"{manifest.stockout_derivation_version!r}"
        )
    if manifest.canonicalization_version != SUPPORTED_CANONICALIZATION_VERSION:
        raise RealLoaderError(
            "unsupported canonicalization_version: "
            f"{manifest.canonicalization_version!r}"
        )

    train_entry = manifest.raw_file("train")
    eval_entry = manifest.raw_file("eval")
    train_path = raw_dir / train_entry.local_name
    eval_path = raw_dir / eval_entry.local_name
    verify_parquet_schema(
        train_path,
        manifest.expected_schema or EXPECTED_REAL_SCHEMA,
        where="train.parquet",
    )
    verify_parquet_schema(
        eval_path,
        manifest.expected_schema or EXPECTED_REAL_SCHEMA,
        where="eval.parquet",
    )

    selection = select_population(
        train_path,
        eval_path,
        required_history_days=required_history_days,
        max_keys=max_keys,
    )
    if not selection.selected_keys:
        raise RealLoaderError("population selection produced no selected keys")

    raw_rows: list[dict[str, object]] = [
        *_read_rows_for_keys(train_path, selection.selected_keys),
        *_read_rows_for_keys(eval_path, selection.selected_keys),
    ]

    accepted: list[DemandRecord] = []
    rejections: Counter[str] = Counter()
    missing_counts: Counter[str] = Counter()
    seen_keys: set[tuple[str, date]] = set()
    duplicate_count = 0
    for record in raw_rows:
        if record.get("store_id") is None or record.get("product_id") is None:
            missing_counts["store_id|product_id"] += 1
        if record.get("dt") is None:
            missing_counts["dt"] += 1
        if record.get("sale_amount") is None:
            missing_counts["sale_amount"] += 1
        if record.get("stock_hour6_22_cnt") is None:
            missing_counts["stock_hour6_22_cnt"] += 1
        mapped = map_real_row(record, where="<row>")
        if isinstance(mapped, RowRejection):
            rejections[mapped.reason] += 1
            continue
        key = (mapped.sku, mapped.date)
        if key in seen_keys:
            duplicate_count += 1
            rejections["duplicate_key"] += 1
            continue
        seen_keys.add(key)
        accepted.append(mapped)

    filled = _fill_daily_gaps(accepted)
    gap_fill_records = sum(
        1 for record in filled if (record.sku, record.date) not in seen_keys
    )
    try:
        table = DemandTable.from_records(filled, require_daily_cadence=True)
    except DataValidationError as exc:
        raise RealLoaderError(f"canonical validation failed: {exc}") from exc

    unknown_stockout = sum(1 for r in table.records if r.stockout_flag is None)
    stockout_true = sum(1 for r in table.records if r.stockout_flag is True)
    stockout_false = len(table.records) - stockout_true - unknown_stockout

    demand_values = [r.demand_units for r in table.records]
    demand_summary = {
        "count": len(demand_values),
        "mean": round(sum(demand_values) / len(demand_values), 6),
        "min": round(min(demand_values), 6),
        "max": round(max(demand_values), 6),
        "zero_demand_records": sum(1 for v in demand_values if v == 0.0),
        "nonnegative": all(v >= 0 for v in demand_values),
    }
    stockout_summary = {
        "true": stockout_true,
        "false": stockout_false,
        "unknown": unknown_stockout,
        "stockout_ratio": round(
            stockout_true / len(table.records) if table.records else None, 6
        ),
    }

    return RealSnapshotLoadResult(
        table=table,
        selection=selection,
        canonical_sha256=canonical_content_sha256(table),
        rejected_by_reason=dict(rejections),
        gap_fill_records=gap_fill_records,
        duplicate_count=duplicate_count,
        missing_value_counts=dict(missing_counts),
        unknown_stockout_records=unknown_stockout,
        demand_summary=demand_summary,
        stockout_summary=stockout_summary,
    )
