from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta
from typing import ClassVar

from ..data import DemandTable


class InsufficientHistoryError(ValueError):
    pass


@dataclass(frozen=True)
class FutureContext:
    dates: tuple[date, ...]

    def __len__(self) -> int:
        return len(self.dates)


def future_context_from(start: date, horizon: int) -> FutureContext:
    if horizon < 0:
        raise ValueError("horizon must be non-negative")
    dates = tuple(start + timedelta(days=i) for i in range(horizon))
    return FutureContext(dates)


@dataclass(frozen=True)
class ForecastPoint:
    date: date
    value: float


@dataclass(frozen=True)
class Forecast:
    sku: str
    model_id: str
    model_version: str
    points: tuple[ForecastPoint, ...]
    insufficient_history: bool = False
    fallback_reason: str | None = None

    @property
    def horizon(self) -> int:
        return len(self.points)

    @property
    def values(self) -> tuple[float, ...]:
        return tuple(p.value for p in self.points)

    @property
    def dates(self) -> tuple[date, ...]:
        return tuple(p.date for p in self.points)

    def to_dict(self) -> dict[str, object]:
        return {
            "sku": self.sku,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "points": [
                {"date": p.date.isoformat(), "value": p.value} for p in self.points
            ],
            "insufficient_history": self.insufficient_history,
            "fallback_reason": self.fallback_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Forecast:
        return cls(
            sku=str(data["sku"]),
            model_id=str(data["model_id"]),
            model_version=str(data["model_version"]),
            points=tuple(
                ForecastPoint(
                    date=ForecastPoint._parse_date(p["date"]), value=float(p["value"])
                )
                for p in data["points"]
            ),
            insufficient_history=bool(data.get("insufficient_history", False)),
            fallback_reason=data.get("fallback_reason"),
        )

    @staticmethod
    def _parse_date(value: object) -> date:
        return date.fromisoformat(str(value))


class Forecaster(ABC):
    model_id: ClassVar[str]
    model_version: ClassVar[str]
    min_history: ClassVar[int]

    @abstractmethod
    def fit(self, train_data: DemandTable) -> Forecaster:
        raise NotImplementedError

    @abstractmethod
    def predict(self, context: FutureContext, horizon: int) -> Forecast:
        raise NotImplementedError


def require_single_sku(train_data: DemandTable) -> str:
    skus = train_data.skus
    if len(skus) > 1:
        raise ValueError(f"forecasters fit one SKU at a time; got {len(skus)}: {skus}")
    return skus[0] if skus else ""
