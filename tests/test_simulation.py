"""Inventory simulator: conservation, lead time, stockouts, determinism."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from retail_demand_inventory.simulation import (
    DemandSource,
    OrderUpToSafetyStockPolicy,
    ReorderPointOrderQuantityPolicy,
    SimulationConfig,
    SimulationInput,
    simulate,
)


def _dates(days: int, start: date = date(2024, 1, 1)) -> tuple[date, ...]:
    return tuple(start + timedelta(days=i) for i in range(days))


def _config(**overrides) -> SimulationConfig:
    base = {
        "sku": "sku-1",
        "initial_inventory": 5.0,
        "lead_time_days": 2,
        "review_period_days": 1,
        "holding_cost_per_unit_per_day": 0.1,
        "stockout_cost_per_unit": 2.0,
        "ordering_cost_per_order": 5.0,
    }
    base.update(overrides)
    return SimulationConfig(**base)


def _run(demand, policy, config=None, seed=7) -> object:
    config = config or _config()
    return simulate(
        SimulationInput(
            dates=_dates(len(demand)),
            demand=tuple(float(v) for v in demand),
            config=config,
            policy=policy,
            seed=seed,
            demand_source=DemandSource(kind="synthetic", reference="test"),
        )
    )


def test_inventory_conservation_every_day() -> None:
    demand = [2.0, 3.0, 1.0, 4.0, 2.0, 0.5, 1.5, 3.0, 2.0, 1.0]
    policy = ReorderPointOrderQuantityPolicy(reorder_point=3.0, order_quantity=8.0)
    outcome = _run(demand, policy)
    for state in outcome.daily:
        served = state.demand - state.lost_sales
        assert state.ending_inventory == pytest.approx(
            state.starting_inventory + state.received - served
        )


def test_lost_sales_not_backlogged() -> None:
    demand = [3.0, 5.0]  # day 2 demand exceeds inventory even after nothing arrives
    policy = ReorderPointOrderQuantityPolicy(reorder_point=1.0, order_quantity=100.0)
    config = _config(initial_inventory=3.0, lead_time_days=10)
    outcome = _run(demand, policy, config)
    assert outcome.lost_units == pytest.approx(5.0)
    assert outcome.daily[1].lost_sales == pytest.approx(5.0)
    # nothing arrives within the window; ending inventory stays 0
    assert outcome.daily[1].ending_inventory == pytest.approx(0.0)


def test_lead_time_order_arrival() -> None:
    demand = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    policy = ReorderPointOrderQuantityPolicy(reorder_point=10.0, order_quantity=6.0)
    config = _config(initial_inventory=1.0, lead_time_days=2)
    outcome = _run(demand, policy, config)
    # Day 0: position 1 <= 10 -> order 6, arriving day 0+2 = day 2.
    assert outcome.daily[0].order_placed == 6.0
    assert outcome.daily[0].received == 0.0
    assert outcome.daily[1].received == 0.0
    assert outcome.daily[2].received == pytest.approx(6.0)
    assert outcome.events.orders[0].arrival_date == outcome.dates[2]


def test_service_level_and_fill_rate_hand_calculated() -> None:
    demand = [2.0, 1.0, 3.0]  # init 2 -> day1 loses 1, day2 loses 3
    policy = OrderUpToSafetyStockPolicy(order_up_to_level=0.0)  # never order
    config = _config(initial_inventory=2.0)
    outcome = _run(demand, policy, config)
    # served: 2 + 0 + 0 = 2 of 6 demand; lost 4; fill = 2/6
    assert outcome.total_demand == pytest.approx(6.0)
    assert outcome.lost_units == pytest.approx(4.0)
    assert outcome.fill_rate == pytest.approx(2 / 6)
    # only day 0 fully met out of 3 demanded days
    assert outcome.service_level == pytest.approx(1 / 3)
    assert outcome.stockout_events == 2


def test_deterministic_with_fixed_seed() -> None:
    policy = ReorderPointOrderQuantityPolicy(reorder_point=3.0, order_quantity=8.0)
    demand = [2.0, 3.0, 1.0, 4.0, 2.0, 0.5, 1.5]
    a = _run(demand, policy)
    b = _run(demand, policy)
    assert a.run_id == b.run_id
    assert a.total_cost == b.total_cost
    assert a.daily == b.daily


def test_run_id_changes_with_parameters() -> None:
    demand = [2.0, 3.0, 1.0, 4.0, 2.0]
    a = _run(
        demand, ReorderPointOrderQuantityPolicy(reorder_point=3.0, order_quantity=8.0)
    )
    b = _run(
        demand, ReorderPointOrderQuantityPolicy(reorder_point=4.0, order_quantity=8.0)
    )
    assert a.run_id != b.run_id


def test_higher_reorder_point_improves_service() -> None:
    demand = [
        2.0,
        3.0,
        1.0,
        4.0,
        2.0,
        0.5,
        1.5,
        3.0,
        2.0,
        1.0,
        2.5,
        2.0,
        3.5,
        1.0,
        2.0,
        4.0,
        1.0,
        2.0,
        3.0,
        2.5,
    ]
    low = _run(
        demand, ReorderPointOrderQuantityPolicy(reorder_point=0.5, order_quantity=4.0)
    )
    high = _run(
        demand, ReorderPointOrderQuantityPolicy(reorder_point=10.0, order_quantity=20.0)
    )
    assert high.service_level >= low.service_level
    assert high.lost_units <= low.lost_units


def test_costs_breakdown() -> None:
    demand = [2.0, 2.0, 2.0]
    policy = ReorderPointOrderQuantityPolicy(reorder_point=10.0, order_quantity=5.0)
    config = _config(initial_inventory=2.0, lead_time_days=1)
    outcome = _run(demand, policy, config)
    # Day0: order 5 (cost 5), end inv 0 (holding 0)
    # Day1: arrival 5, demand 2 -> end 3 (holding 0.3); position 3 <= 10 -> order 5 (cost 5)
    # Day2: arrival 5, demand 2 -> end 6 (holding 0.6); position 6 <= 10 -> order 5 (cost 5)
    assert outcome.total_ordering_cost == pytest.approx(15.0)
    assert outcome.total_holding_cost == pytest.approx(0.9)
    assert outcome.total_stockout_cost == pytest.approx(0.0)
    assert outcome.total_cost == pytest.approx(15.9)


def test_first_order_quantity() -> None:
    demand = [2.0, 2.0]
    policy = ReorderPointOrderQuantityPolicy(reorder_point=10.0, order_quantity=5.0)
    outcome = _run(demand, policy)
    assert outcome.first_order_quantity == pytest.approx(5.0)


def test_order_up_to_policy() -> None:
    demand = [1.0, 1.0, 1.0]
    policy = OrderUpToSafetyStockPolicy(order_up_to_level=6.0)
    config = _config(initial_inventory=2.0, lead_time_days=1)
    outcome = _run(demand, policy, config)
    # Day0: start 2, demand 1 -> end 1; position 1 < 6 -> order 5 (arrives day 1)
    # Day1: received 5 -> start 6, demand 1 -> end 5; position 5 < 6 -> order 1
    assert outcome.daily[0].order_placed == pytest.approx(5.0)
    assert outcome.daily[1].received == pytest.approx(5.0)
    assert outcome.daily[1].order_placed == pytest.approx(1.0)


def test_empty_period_raises() -> None:
    from retail_demand_inventory.simulation import SimulationError

    with pytest.raises(SimulationError):
        simulate(
            SimulationInput(
                dates=(),
                demand=(),
                config=_config(),
                policy=ReorderPointOrderQuantityPolicy(1.0, 5.0),
                seed=1,
                demand_source=DemandSource(kind="synthetic"),
            )
        )
