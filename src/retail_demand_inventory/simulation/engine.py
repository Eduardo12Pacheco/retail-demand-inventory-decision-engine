from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from .events import ArrivalEvent, EventLog, OrderEvent
from .outcomes import SimulationOutcome
from .policies import Policy


def _add_days(day: date, days: int) -> date:
    return day + timedelta(days=days)


class SimulationError(ValueError):
    pass


@dataclass(frozen=True)
class SimulationConfig:
    sku: str
    initial_inventory: float
    lead_time_days: int
    review_period_days: int
    holding_cost_per_unit_per_day: float
    stockout_cost_per_unit: float
    ordering_cost_per_order: float

    def to_dict(self) -> dict[str, object]:
        return {
            "sku": self.sku,
            "initial_inventory": self.initial_inventory,
            "lead_time_days": self.lead_time_days,
            "review_period_days": self.review_period_days,
            "holding_cost_per_unit_per_day": self.holding_cost_per_unit_per_day,
            "stockout_cost_per_unit": self.stockout_cost_per_unit,
            "ordering_cost_per_order": self.ordering_cost_per_order,
        }


@dataclass(frozen=True)
class DemandSource:
    kind: str
    model_id: str | None = None
    model_version: str | None = None
    reference: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "reference": self.reference,
        }


@dataclass(frozen=True)
class SimulationInput:
    dates: tuple[date, ...]
    demand: tuple[float, ...]
    config: SimulationConfig
    policy: Policy
    seed: int
    demand_source: DemandSource

    def __post_init__(self) -> None:
        if len(self.dates) != len(self.demand):
            raise SimulationError("dates and demand must have the same length")
        if not self.dates:
            raise SimulationError("cannot simulate an empty period")
        if self.config.lead_time_days < 0:
            raise SimulationError("lead_time_days must be >= 0")
        if self.config.review_period_days <= 0:
            raise SimulationError("review_period_days must be positive")


@dataclass(frozen=True)
class DailyState:
    date: date
    demand: float
    starting_inventory: float
    on_order_units: float
    received: float
    order_placed: float
    ending_inventory: float
    lost_sales: float
    demand_fully_met: bool
    holding_cost: float
    stockout_cost: float
    ordering_cost: float

    def to_dict(self) -> dict[str, object]:
        return {
            "date": self.date.isoformat(),
            "demand": self.demand,
            "starting_inventory": self.starting_inventory,
            "on_order_units": self.on_order_units,
            "received": self.received,
            "order_placed": self.order_placed,
            "ending_inventory": self.ending_inventory,
            "lost_sales": self.lost_sales,
            "demand_fully_met": self.demand_fully_met,
            "holding_cost": self.holding_cost,
            "stockout_cost": self.stockout_cost,
            "ordering_cost": self.ordering_cost,
        }


def compute_run_id(
    *,
    sku: str,
    config: SimulationConfig,
    policy: Policy,
    seed: int,
    dates: Sequence[date],
    demand: Sequence[float],
    demand_source: DemandSource,
) -> str:
    payload = {
        "sku": sku,
        "config": config.to_dict(),
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "policy_params": dict(policy.params()),
        "seed": seed,
        "demand_source": demand_source.to_dict(),
        "dates": [d.isoformat() for d in dates],
        "demand_sha256": hashlib.sha256(
            repr(tuple(round(float(v), 6) for v in demand)).encode()
        ).hexdigest(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "run_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def simulate(input_: SimulationInput) -> SimulationOutcome:
    config = input_.config
    on_hand = config.initial_inventory
    pipeline: list[tuple[int, float]] = []

    orders: list[OrderEvent] = []
    arrivals: list[ArrivalEvent] = []
    daily_states: list[DailyState] = []

    total_ordering_cost = 0.0
    total_holding_cost = 0.0
    total_stockout_cost = 0.0
    first_order_quantity = 0.0

    for index, (day, demand) in enumerate(zip(input_.dates, input_.demand)):
        on_order = sum(q for _, q in pipeline)

        received = 0.0
        still_in_transit: list[tuple[int, float]] = []
        for arrival_index, quantity in pipeline:
            if arrival_index == index:
                received += quantity
                arrivals.append(ArrivalEvent(date=day, quantity=quantity))
            else:
                still_in_transit.append((arrival_index, quantity))
        pipeline = still_in_transit

        starting_inventory = on_hand
        on_hand += received
        served = min(on_hand, demand)
        lost = demand - served
        on_hand -= served
        demand_fully_met = lost <= 0.0

        review_day = index % config.review_period_days == 0
        position = on_hand + sum(q for _, q in pipeline)
        order_quantity = input_.policy.order_decision(position, review_day=review_day)
        ordering_cost_today = 0.0
        if order_quantity > 0:
            if first_order_quantity == 0.0:
                first_order_quantity = order_quantity
            ordering_cost_today = config.ordering_cost_per_order
            total_ordering_cost += ordering_cost_today
            arrival_day = index + config.lead_time_days
            pipeline.append((arrival_day, order_quantity))
            orders.append(
                OrderEvent(
                    date=day,
                    quantity=order_quantity,
                    arrival_date=_add_days(day, config.lead_time_days),
                )
            )

        holding_cost_today = on_hand * config.holding_cost_per_unit_per_day
        stockout_cost_today = lost * config.stockout_cost_per_unit
        total_holding_cost += holding_cost_today
        total_stockout_cost += stockout_cost_today

        daily_states.append(
            DailyState(
                date=day,
                demand=demand,
                starting_inventory=starting_inventory,
                on_order_units=on_order,
                received=received,
                order_placed=order_quantity,
                ending_inventory=on_hand,
                lost_sales=lost,
                demand_fully_met=demand_fully_met,
                holding_cost=holding_cost_today,
                stockout_cost=stockout_cost_today,
                ordering_cost=ordering_cost_today,
            )
        )

    run_id = compute_run_id(
        sku=config.sku,
        config=config,
        policy=input_.policy,
        seed=input_.seed,
        dates=input_.dates,
        demand=input_.demand,
        demand_source=input_.demand_source,
    )

    total_demand = sum(input_.demand)
    total_lost = sum(state.lost_sales for state in daily_states)
    served_units = total_demand - total_lost
    stockout_events = sum(1 for state in daily_states if state.lost_sales > 0)
    demanded_days = sum(1 for state in daily_states if state.demand > 0)

    inventory_values = [state.ending_inventory for state in daily_states]

    return SimulationOutcome(
        run_id=run_id,
        sku=config.sku,
        policy_id=input_.policy.policy_id,
        policy_version=input_.policy.policy_version,
        policy_params=dict(input_.policy.params()),
        config=config,
        demand_source=input_.demand_source,
        seed=input_.seed,
        dates=tuple(input_.dates),
        daily=tuple(daily_states),
        events=EventLog(orders=tuple(orders), arrivals=tuple(arrivals)),
        total_demand=total_demand,
        served_units=served_units,
        lost_units=total_lost,
        stockout_events=stockout_events,
        fill_rate=(served_units / total_demand) if total_demand > 0 else None,
        service_level=(
            sum(1 for s in daily_states if s.demand_fully_met) / demanded_days
        )
        if demanded_days > 0
        else None,
        avg_inventory=(sum(inventory_values) / len(inventory_values))
        if inventory_values
        else 0.0,
        max_inventory=max(inventory_values) if inventory_values else 0.0,
        total_ordering_cost=total_ordering_cost,
        total_holding_cost=total_holding_cost,
        total_stockout_cost=total_stockout_cost,
        total_cost=total_ordering_cost + total_holding_cost + total_stockout_cost,
        first_order_quantity=first_order_quantity,
    )
