"""Event records produced by the inventory simulator.

Orders and arrivals are recorded so a simulation run is fully auditable:
every order placed on a review day and every arrival (the order's lead-time
delivery) is an explicit event.
"""

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
