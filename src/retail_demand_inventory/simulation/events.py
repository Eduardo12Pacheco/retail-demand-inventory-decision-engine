from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class OrderEvent:
    date: date
    quantity: float
    arrival_date: date


@dataclass(frozen=True)
class ArrivalEvent:
    date: date
    quantity: float


@dataclass(frozen=True)
class EventLog:
    orders: tuple[OrderEvent, ...] = ()
    arrivals: tuple[ArrivalEvent, ...] = ()
