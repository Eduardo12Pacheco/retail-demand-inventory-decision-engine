"""Deterministic loaders for canonical demand data.

Two entry points:

- `load_canonical_csv`: reads the committed synthetic fixture (and any CSV in
  the same canonical schema). Pure Python `csv`, no third-party dependency,
  fully deterministic.
- FreshRetailNet path: `FreshRetailNetRowMapper` maps a raw source row
  (as read from the audited dataset, which is never downloaded by this repo)
  into a `DemandRecord`, and `load_fresh_retail_net` streams a source-shaped
  CSV through the mapper, fills internal missing days with explicit zeros, and
  builds a validated `DemandTable`. No network access is ever performed.

Missing-day policy (documented in docs/source-contract.md): an internal gap
within a SKU's span is filled with `demand_units = 0.0` and
`stockout_flag = None`, because a missing record is not evidence of a stockout.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from pathlib import Path

_ONE_DAY = timedelta(days=1)

from .contracts import (
    DataValidationError,
    DemandRecord,
    DemandTable,
    date_range_days,
)

CANONICAL_COLUMNS = ("sku", "date", "demand_units", "category", "stockout_flag")

# FreshRetailNet source fields actually consumed by the canonical mapping.
FRESH_RETAIL_NET_USED_FIELDS = (
    "dt",
    "store_id",
    "product_id",
    "sale_amount",
    "first_category_id",
    "stock_hour6_22_cnt",
    "hours_stock_status",
)


class LoaderError(ValueError):
    """Raised when a source row cannot be mapped into the canonical schema."""


def _parse_date(value: str, where: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise LoaderError(f"{where}: invalid date {value!r}") from exc


def _parse_demand(value: str, where: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise LoaderError(f"{where}: invalid demand_units {value!r}") from exc
    if math.isnan(parsed) or math.isinf(parsed):
        raise LoaderError(f"{where}: demand_units must be finite")
    if parsed < 0:
        raise LoaderError(f"{where}: demand_units must be >= 0")
    return parsed


def _parse_stockout_flag(value: str | None) -> bool | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if cleaned in {"", "na", "nan", "none", "null"}:
        return None
    if cleaned in {"1", "true", "yes", "stockout"}:
        return True
    if cleaned in {"0", "false", "no"}:
        return False
    raise LoaderError(f"invalid stockout_flag {value!r}")


def parse_canonical_row(row: Mapping[str, object], where: str) -> DemandRecord:
    """Build a `DemandRecord` from a canonical-schema row mapping."""
    sku = str(row.get("sku") or "").strip()
    if not sku:
        raise LoaderError(f"{where}: sku must be a non-empty string")

    raw_date = row.get("date")
    if raw_date is None or str(raw_date).strip() == "":
        raise LoaderError(f"{where}: missing date")
    when = _parse_date(str(raw_date).strip(), where)

    raw_demand = row.get("demand_units")
    if raw_demand is None or str(raw_demand).strip() == "":
        raise LoaderError(f"{where}: missing demand_units")
    demand = _parse_demand(str(raw_demand).strip(), where)

    category = str(row.get("category") or "").strip() or None
    stockout = _parse_stockout_flag(
        str(row.get("stockout_flag")).strip()
        if row.get("stockout_flag") is not None
        else None
    )

    return DemandRecord(
        sku=sku,
        date=when,
        demand_units=demand,
        category=category,
        stockout_flag=stockout,
    )


def load_canonical_csv(
    path: Path, *, require_daily_cadence: bool = True
) -> DemandTable:
    """Load a canonical-schema CSV into a validated `DemandTable`.

    Expected columns: `sku,date,demand_units[,category,stockout_flag]`.
    Column order does not matter; missing optional columns default to None.
    """
    records: list[DemandRecord] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise LoaderError(f"{path.name}: empty CSV, no header row")
        for lineno, raw in enumerate(reader, start=2):
            records.append(parse_canonical_row(raw, f"{path.name}:{lineno}"))
    if not records:
        raise LoaderError(f"{path.name}: no data rows")
    try:
        return DemandTable.from_records(
            records, require_daily_cadence=require_daily_cadence
        )
    except DataValidationError as exc:
        raise LoaderError(f"{path.name}: {exc}") from exc


class FreshRetailNetRowMapper:
    """Maps a FreshRetailNet source row into a canonical `DemandRecord`.

    Canonical mapping (docs/source-contract.md):
        sku          <- f"{store_id}|{product_id}"
        date         <- dt
        demand_units <- sale_amount (globally normalized float, non-negative)
        category     <- first_category_id
        stockout_flag<- derived from hours_stock_status / stock_hour6_22_cnt

    The stockout-day rule is intentionally conservative and documented: a day
    is flagged as a stockout day when the source reports at least one
    out-of-stock hour in the trading window. The exact rule will be re-audited
    against the real bytes at ingestion time; the mapper accepts an explicit
    `stockout_threshold` so the rule is a parameter, not a hidden constant.
    """

    def __init__(self, *, stockout_threshold_hours: int = 1) -> None:
        self.stockout_threshold_hours = stockout_threshold_hours

    def map_row(self, row: Mapping[str, object], where: str = "<row>") -> DemandRecord:
        store = row.get("store_id")
        product = row.get("product_id")
        if (
            store is None
            or product is None
            or str(store).strip() == ""
            or str(product).strip() == ""
        ):
            raise LoaderError(f"{where}: store_id and product_id are required")
        sku = f"{store}|{product}"

        raw_dt = row.get("dt")
        if raw_dt is None or str(raw_dt).strip() == "":
            raise LoaderError(f"{where}: missing dt")
        when = _parse_date(str(raw_dt).strip(), where)

        raw_sale = row.get("sale_amount")
        if raw_sale is None or str(raw_sale).strip() == "":
            raise LoaderError(f"{where}: missing sale_amount")
        demand = _parse_demand(str(raw_sale).strip(), where)

        category = str(row.get("first_category_id") or "").strip() or None

        stockout: bool | None = None
        raw_cnt = row.get("stock_hour6_22_cnt")
        if raw_cnt is not None and str(raw_cnt).strip() not in {"", "nan"}:
            hours = int(float(str(raw_cnt).strip()))
            stockout = hours >= self.stockout_threshold_hours

        return DemandRecord(
            sku=sku,
            date=when,
            demand_units=demand,
            category=category,
            stockout_flag=stockout,
        )


def _fill_daily_gaps(records: Iterable[DemandRecord]) -> tuple[DemandRecord, ...]:
    from itertools import pairwise

    by_sku: dict[str, list[DemandRecord]] = {}
    for record in records:
        by_sku.setdefault(record.sku, []).append(record)

    filled: list[DemandRecord] = []
    for sku in sorted(by_sku):
        ordered = sorted(by_sku[sku], key=lambda r: r.date)
        filled.extend(ordered)
        for left, right in pairwise(ordered):
            gap = (right.date - left.date).days
            if gap <= 1:
                continue
            filled.extend(
                DemandRecord(
                    sku=sku,
                    date=missing,
                    demand_units=0.0,
                    category=ordered[0].category,
                    stockout_flag=None,
                )
                for missing in date_range_days(
                    left.date + _ONE_DAY, right.date - _ONE_DAY
                )
            )
    return tuple(sorted(filled, key=lambda r: (r.sku, r.date)))


def load_fresh_retail_net(
    path: Path,
    *,
    stockout_threshold_hours: int = 1,
    require_daily_cadence: bool = True,
) -> DemandTable:
    """Load a FreshRetailNet-shaped CSV into a validated canonical table.

    `path` must be a local file in the source row schema (comma-separated with
    a header containing at least the used fields). No network access.
    Internal missing days are filled with explicit zero-demand records.
    """
    mapper = FreshRetailNetRowMapper(stockout_threshold_hours=stockout_threshold_hours)
    records: list[DemandRecord] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise LoaderError(f"{path.name}: empty CSV, no header row")
        for lineno, raw in enumerate(reader, start=2):
            records.append(mapper.map_row(raw, f"{path.name}:{lineno}"))
    if not records:
        raise LoaderError(f"{path.name}: no data rows")
    filled = _fill_daily_gaps(records)
    try:
        return DemandTable.from_records(
            filled, require_daily_cadence=require_daily_cadence
        )
    except DataValidationError as exc:
        raise LoaderError(f"{path.name}: {exc}") from exc
