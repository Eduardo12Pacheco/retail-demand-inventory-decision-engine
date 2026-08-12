from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from .events import EventLog

if TYPE_CHECKING:
    from .engine import DailyState, DemandSource, SimulationConfig


@dataclass(frozen=True)
class SimulationOutcome:
    run_id: str
    sku: str
    policy_id: str
    policy_version: str
    policy_params: Mapping[str, float | int]
    config: SimulationConfig
    demand_source: DemandSource
    seed: int
    dates: tuple[date, ...]
    daily: tuple[DailyState, ...]
    events: EventLog
    total_demand: float
    served_units: float
    lost_units: float
    stockout_events: int
    fill_rate: float | None
    service_level: float | None
    avg_inventory: float
    max_inventory: float
    total_ordering_cost: float
    total_holding_cost: float
    total_stockout_cost: float
    total_cost: float
    first_order_quantity: float

    def summary_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "sku": self.sku,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_params": dict(self.policy_params),
            "config": self.config.to_dict(),
            "demand_source": self.demand_source.to_dict(),
            "seed": self.seed,
            "start_date": self.dates[0].isoformat(),
            "end_date": self.dates[-1].isoformat(),
            "total_demand": self.total_demand,
            "served_units": self.served_units,
            "lost_units": self.lost_units,
            "stockout_events": self.stockout_events,
            "fill_rate": self.fill_rate,
            "service_level": self.service_level,
            "avg_inventory": self.avg_inventory,
            "max_inventory": self.max_inventory,
            "total_ordering_cost": self.total_ordering_cost,
            "total_holding_cost": self.total_holding_cost,
            "total_stockout_cost": self.total_stockout_cost,
            "total_cost": self.total_cost,
            "first_order_quantity": self.first_order_quantity,
        }

    def daily_states_dicts(self) -> tuple[dict[str, object], ...]:
        return tuple(state.to_dict() for state in self.daily)

    def events_dict(self) -> dict[str, object]:
        return {
            "orders": [
                {
                    "date": e.date.isoformat(),
                    "quantity": e.quantity,
                    "arrival_date": e.arrival_date.isoformat(),
                }
                for e in self.events.orders
            ],
            "arrivals": [
                {"date": e.date.isoformat(), "quantity": e.quantity}
                for e in self.events.arrivals
            ],
        }
