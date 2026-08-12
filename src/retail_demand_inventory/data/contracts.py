from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta


class DataValidationError(ValueError):
    pass


class ValidationIssue(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{type(self).__name__}({self.message!r})"


class MissingValueIssue(ValidationIssue):
    pass


class InvalidSkuIssue(ValidationIssue):
    pass


class InvalidDateIssue(ValidationIssue):
    pass


class NegativeDemandIssue(ValidationIssue):
    pass


class NonFiniteDemandIssue(ValidationIssue):
    pass


class NumericRangeIssue(ValidationIssue):
    pass


class DuplicateKeyIssue(ValidationIssue):
    pass


class TimestampOrderingIssue(ValidationIssue):
    pass


class DailyCadenceIssue(ValidationIssue):
    pass


@dataclass(frozen=True)
class DemandRecord:
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
        prev: date | None = None
        for record in by_sku[sku]:
            if prev is not None and record.date <= prev:
                issues.append(
                    TimestampOrderingIssue(
                        f"sku={sku!r}: dates not strictly increasing at {record.date.isoformat()}"
                    )
                )
            prev = record.date
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
    records: tuple[DemandRecord, ...]

    @classmethod
    def from_records(
        cls, records: Iterable[DemandRecord], *, require_daily_cadence: bool = True
    ) -> DemandTable:
        raw = tuple(records)
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
        return DemandTable.from_records(
            r for r in self.series_for(sku) if start <= r.date <= end
        )

    def filter_dates(self, sku: str, dates: Iterable[date]) -> DemandTable:
        wanted = set(dates)
        return DemandTable.from_records(
            r for r in self.series_for(sku) if r.date in wanted
        )


def all_dates(records: Iterable[DemandRecord]) -> tuple[date, ...]:
    return tuple(sorted({r.date for r in records}))


def date_range_days(start: date, end: date) -> tuple[date, ...]:
    if end < start:
        raise ValueError("end before start")
    return tuple(start + timedelta(days=i) for i in range((end - start).days + 1))
