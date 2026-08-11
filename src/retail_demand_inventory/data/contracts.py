"""Canonical validated demand data model.

`DemandRecord` is the smallest demand observation: one SKU on one day with an
observed (continuous, non-negative) demand value in canonical units. Optional
fields are only present when the source provides them; absence is encoded as
`None`, never as a fabricated value.

`DemandTable` is an immutable, validated collection of records, sorted by
`(sku, date)`, with strict daily cadence per SKU by default.

Validation covers: missing required values, invalid/absent SKU, impossible
dates, non-finite or negative demand, duplicate `(sku, date)` keys,
timestamp ordering, and daily-frequency consistency. `validate_records`
returns every issue it finds; `DemandTable.from_records` raises on any issue.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta


class DataValidationError(ValueError):
    """Raised when demand records fail canonical validation."""


class ValidationIssue(Exception):
    """Base class for a single canonical validation problem."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{type(self).__name__}({self.message!r})"


class MissingValueIssue(ValidationIssue):
    """A required field is missing."""


class InvalidSkuIssue(ValidationIssue):
    """The SKU is absent or blank."""


class InvalidDateIssue(ValidationIssue):
    """The date is not a valid calendar date."""


class NegativeDemandIssue(ValidationIssue):
    """Demand is negative."""


class NonFiniteDemandIssue(ValidationIssue):
    """Demand is NaN or infinite."""


class NumericRangeIssue(ValidationIssue):
    """A numeric value is outside its documented range."""


class DuplicateKeyIssue(ValidationIssue):
    """The (sku, date) key appears more than once."""


class TimestampOrderingIssue(ValidationIssue):
    """Dates are not strictly increasing within a SKU."""


class DailyCadenceIssue(ValidationIssue):
    """Consecutive dates within a SKU are not exactly one day apart."""


@dataclass(frozen=True)
class DemandRecord:
    """One canonical demand observation for a SKU on a day.

    Attributes:
        sku: Canonical store-product identifier, non-empty string.
        date: Calendar date of the observation.
        demand_units: Observed sales/demand in canonical units. Continuous
            non-negative float; FreshRetailNet's `sale_amount` is globally
            normalized and is NOT an integer count.
        category: Optional coarse grouping key (e.g. first-level category).
        stockout_flag: Optional source annotation that the day contained a
            stockout. Absent (`None`) means the source did not annotate it.
    """

    sku: str
    date: date
    demand_units: float
    category: str | None = None
    stockout_flag: bool | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "sku": self.sku,
            "date": self.date.isoformat(),
            "demand_units": self.demand_units,
            "category": self.category,
            "stockout_flag": self.stockout_flag,
        }


def _validate_record(record: DemandRecord, index: int) -> Iterator[ValidationIssue]:
    if not isinstance(record.sku, str) or not record.sku.strip():
        yield InvalidSkuIssue(f"record {index}: sku must be a non-empty string")
    if not isinstance(record.date, date):
        yield InvalidDateIssue(f"record {index}: date must be a datetime.date")
    if record.demand_units is None:
        yield MissingValueIssue(
            f"record {index} ({record.sku} {record.date}): demand_units is missing"
        )
        return
    if not isinstance(record.demand_units, (int, float)):
        yield NumericRangeIssue(
            f"record {index} ({record.sku} {record.date}): demand_units must be numeric"
        )
        return
    if math.isnan(record.demand_units) or math.isinf(record.demand_units):
        yield NonFiniteDemandIssue(
            f"record {index} ({record.sku} {record.date}): demand_units must be finite"
        )
    if record.demand_units < 0:
        yield NegativeDemandIssue(
            f"record {index} ({record.sku} {record.date}): demand_units must be >= 0"
        )


def validate_records(
    records: Sequence[DemandRecord], *, require_daily_cadence: bool = True
) -> tuple[ValidationIssue, ...]:
    """Return every validation issue in `records`, in deterministic order."""
    issues: list[ValidationIssue] = []
    for index, record in enumerate(records):
        issues.extend(_validate_record(record, index))

    counts = Counter((r.sku, r.date) for r in records)
    for (sku, when), n in sorted(
        counts.items(), key=lambda item: (item[0][0], item[0][1])
    ):
        if n > 1:
            issues.append(
                DuplicateKeyIssue(
                    f"duplicate key sku={sku!r} date={when.isoformat()} appears {n} times"
                )
            )

    by_sku: dict[str, list[DemandRecord]] = {}
    for record in records:
        by_sku.setdefault(record.sku, []).append(record)

    for sku in sorted(by_sku):
        # Timestamp ordering is checked against INPUT order: a canonical table
        # must arrive sorted, so out-of-order input is a real error.
        prev: date | None = None
        for record in by_sku[sku]:
            if prev is not None and record.date <= prev:
                issues.append(
                    TimestampOrderingIssue(
                        f"sku={sku!r}: dates not strictly increasing at {record.date.isoformat()}"
                    )
                )
            prev = record.date
        # Daily cadence is checked on the sorted series.
        ordered = sorted(by_sku[sku], key=lambda r: r.date)
        prev = None
        for record in ordered:
            if (
                prev is not None
                and require_daily_cadence
                and (record.date - prev).days != 1
            ):
                issues.append(
                    DailyCadenceIssue(
                        f"sku={sku!r}: gap of {(record.date - prev).days} days between "
                        f"{prev.isoformat()} and {record.date.isoformat()}"
                    )
                )
            prev = record.date

    return tuple(issues)


@dataclass(frozen=True)
class DemandTable:
    """Immutable validated demand observations for one or more SKUs."""

    records: tuple[DemandRecord, ...]

    @classmethod
    def from_records(
        cls, records: Iterable[DemandRecord], *, require_daily_cadence: bool = True
    ) -> DemandTable:
        raw = tuple(records)
        # Sort first (tolerant normalization); validation then runs on the
        # canonical order. `validate_records` remains strict on input order
        # for callers that need to reject out-of-order sources.
        ordered = tuple(sorted(raw, key=lambda r: (r.sku, r.date)))
        issues = validate_records(ordered, require_daily_cadence=require_daily_cadence)
        if issues:
            raise DataValidationError(
                f"{len(issues)} validation issue(s); first: {issues[0].message}"
            )
        return cls(ordered)

    @property
    def skus(self) -> tuple[str, ...]:
        return tuple(sorted({r.sku for r in self.records}))

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(
            sorted({r.category for r in self.records if r.category is not None})
        )

    def has_sku(self, sku: str) -> bool:
        return any(r.sku == sku for r in self.records)

    def series_for(self, sku: str) -> tuple[DemandRecord, ...]:
        """All records for `sku`, sorted by date."""
        return tuple(r for r in self.records if r.sku == sku)

    def category_for(self, sku: str) -> str | None:
        for r in self.records:
            if r.sku == sku:
                return r.category
        return None

    def date_range(self) -> tuple[date, date]:
        if not self.records:
            raise ValueError("empty table has no date range")
        dates = [r.date for r in self.records]
        return min(dates), max(dates)

    def daily_series(self, sku: str) -> tuple[tuple[date, float], ...]:
        """Consecutive `(date, demand_units)` pairs for `sku`."""
        return tuple((r.date, r.demand_units) for r in self.series_for(sku))

    @property
    def num_records(self) -> int:
        return len(self.records)

    def to_records_dicts(self) -> tuple[dict[str, object], ...]:
        return tuple(r.to_dict() for r in self.records)

    @classmethod
    def concat(cls, tables: Sequence[DemandTable]) -> DemandTable:
        combined: list[DemandRecord] = []
        for table in tables:
            combined.extend(table.records)
        return cls.from_records(combined)

    def slice_between(self, sku: str, start: date, end: date) -> DemandTable:
        """Records for `sku` with `start <= date <= end`."""
        return DemandTable.from_records(
            r for r in self.series_for(sku) if start <= r.date <= end
        )

    def filter_dates(self, sku: str, dates: Iterable[date]) -> DemandTable:
        wanted = set(dates)
        return DemandTable.from_records(
            r for r in self.series_for(sku) if r.date in wanted
        )


def all_dates(records: Iterable[DemandRecord]) -> tuple[date, ...]:
    """Sorted unique dates across records."""
    return tuple(sorted({r.date for r in records}))


def date_range_days(start: date, end: date) -> tuple[date, ...]:
    """Every calendar day from `start` to `end` inclusive."""
    if end < start:
        raise ValueError("end before start")
    return tuple(start + timedelta(days=i) for i in range((end - start).days + 1))
