from __future__ import annotations

from datetime import date, timedelta

import pytest

from retail_demand_inventory.decisions import (
    DemandStats,
    EvidenceBundle,
    PolicyCandidate,
    Recommendation,
    build_recommendation,
    generate_candidates,
    select_policy,
    simulate_candidates,
)
from retail_demand_inventory.simulation import (
    DemandSource,
    ReorderPointOrderQuantityPolicy,
    SimulationConfig,
)


def _candidate(
    policy_id, service_level, total_cost, run_id, **extra
) -> PolicyCandidate:
    defaults = {
        "policy_version": "1.0",
        "policy_params": {"p": 1.0},
        "service_level": service_level,
        "fill_rate": 0.9,
        "total_cost": total_cost,
        "stockout_units": 1.0,
        "stockout_events": 1,
        "avg_inventory": 5.0,
        "first_order_quantity": 10.0,
    }
    defaults.update(extra)
    return PolicyCandidate(policy_id=policy_id, run_id=run_id, **defaults)


def test_select_min_cost_among_feasible() -> None:
    candidates = [
        _candidate("a", service_level=0.95, total_cost=100.0, run_id="r1"),
        _candidate("b", service_level=0.92, total_cost=80.0, run_id="r2"),
        _candidate("c", service_level=0.89, total_cost=10.0, run_id="r3"),
    ]
    result = select_policy(candidates, target_service_level=0.90)
    assert result.constraint_satisfied is True
    assert result.selected.policy_id == "b"
    assert result.fallback_reason is None
    assert "not an optimality claim" in result.reason


def test_infeasible_falls_back_to_highest_service() -> None:
    candidates = [
        _candidate("a", service_level=0.80, total_cost=5.0, run_id="r1"),
        _candidate("b", service_level=0.70, total_cost=1.0, run_id="r2"),
    ]
    result = select_policy(candidates, target_service_level=0.90)
    assert result.constraint_satisfied is False
    assert result.selected.policy_id == "a"
    assert result.fallback_reason is not None


def test_tie_break_is_deterministic() -> None:
    candidates = [
        _candidate("a", service_level=0.95, total_cost=80.0, run_id="run_aaa"),
        _candidate("b", service_level=0.95, total_cost=80.0, run_id="run_bbb"),
    ]
    first = select_policy(candidates, 0.90)
    second = select_policy(candidates, 0.90)
    assert first == second
    assert first.selected.run_id == "run_aaa"


def test_empty_candidates_raise() -> None:
    with pytest.raises(ValueError):
        select_policy([], 0.90)


def test_generate_candidates_is_deterministic_and_both_families() -> None:
    stats = DemandStats(mean_daily=2.0, std_daily=0.5, n_days=100)
    a = generate_candidates(stats, lead_time_days=3, review_period_days=1)
    b = generate_candidates(stats, lead_time_days=3, review_period_days=1)
    assert a == b
    ids = {p.policy_id for p in a}
    assert ids == {"reorder_point_order_quantity", "order_up_to_safety_stock"}
    assert len(a) == 12


def _config() -> SimulationConfig:
    return SimulationConfig(
        sku="sku-1",
        initial_inventory=8.0,
        lead_time_days=2,
        review_period_days=1,
        holding_cost_per_unit_per_day=0.1,
        stockout_cost_per_unit=2.0,
        ordering_cost_per_order=5.0,
    )


def _dates(days: int) -> tuple[date, ...]:
    start = date(2024, 3, 1)
    return tuple(start + timedelta(days=i) for i in range(days))


def test_simulate_candidates_produces_scored_candidates() -> None:
    policies = (
        ReorderPointOrderQuantityPolicy(reorder_point=3.0, order_quantity=8.0),
        ReorderPointOrderQuantityPolicy(reorder_point=10.0, order_quantity=8.0),
    )
    candidates = simulate_candidates(
        policies,
        sku="sku-1",
        dates=_dates(7),
        demand=[2.0, 3.0, 1.0, 4.0, 2.0, 0.5, 1.5],
        config=_config(),
        seed=7,
        demand_source=DemandSource(kind="observed", reference="test"),
    )
    assert len(candidates) == 2
    assert all(c.total_cost > 0 for c in candidates)


def test_build_recommendation_traceability() -> None:
    policies = tuple(
        generate_candidates(
            DemandStats(mean_daily=2.0, std_daily=0.5, n_days=100),
            lead_time_days=2,
            review_period_days=1,
        )
    )
    candidates = simulate_candidates(
        policies,
        sku="sku-1",
        dates=_dates(7),
        demand=[2.0, 3.0, 1.0, 4.0, 2.0, 0.5, 1.5],
        config=_config(),
        seed=7,
        demand_source=DemandSource(kind="observed", reference="selection"),
    )
    selection = select_policy(candidates, 0.90)
    evidence = EvidenceBundle(
        dataset_manifest={"name": "fixture"},
        source_label="synthetic-fixture",
        forecast_models=({"model_id": "naive", "model_version": "1.0"},),
        selected_model_id="naive",
        selected_model_version="1.0",
        backtest_report_path="data/evaluations/x.json",
        final_test_report_path=None,
        selection_run_ids={c.policy_id: c.run_id for c in candidates},
        recommendation_run_id="",
        sensitivity_run_ids={},
        package_version="0.1.0",
        schema_version="1.0",
        protocol_version="1.0",
    )
    rec = build_recommendation(
        sku="sku-1",
        category="cat-1",
        stats=DemandStats(mean_daily=2.0, std_daily=0.5, n_days=100),
        selection_candidates=candidates,
        selection_result=selection,
        forecast_model_id="naive",
        forecast_model_version="1.0",
        forecast_horizon=7,
        deployment_forecast_dates=_dates(7),
        deployment_forecast=[2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0],
        config=_config(),
        seed=7,
        service_level_target=0.90,
        evidence=evidence,
        assumptions=("a1",),
        limitations=("l1",),
        generated_at="2026-08-11T00:00:00+00:00",
    )
    assert isinstance(rec, Recommendation)
    assert rec.order_quantity >= 0
    assert rec.simulated_service_level is not None
    assert set(rec.sensitivity) == {"scale_0.9", "scale_1.0", "scale_1.1"}
    assert rec.evidence.recommendation_run_id.startswith("run_")
    assert len(rec.evidence.sensitivity_run_ids) == 3
    for text in (rec.reason, rec.objective, str(rec.policy_params)):
        assert "is optimal" not in text
    assert "constraint" in rec.objective


def test_sensitivity_varys_with_demand_scale() -> None:
    policies = (
        ReorderPointOrderQuantityPolicy(reorder_point=3.0, order_quantity=8.0),
        ReorderPointOrderQuantityPolicy(reorder_point=10.0, order_quantity=8.0),
    )
    candidates = simulate_candidates(
        policies,
        sku="sku-1",
        dates=_dates(7),
        demand=[2.0, 3.0, 1.0, 4.0, 2.0, 0.5, 1.5],
        config=_config(),
        seed=7,
        demand_source=DemandSource(kind="observed", reference="selection"),
    )
    selection = select_policy(candidates, 0.90)
    evidence = EvidenceBundle(
        dataset_manifest={"name": "fixture"},
        source_label="synthetic-fixture",
        forecast_models=({"model_id": "naive", "model_version": "1.0"},),
        selected_model_id="naive",
        selected_model_version="1.0",
        backtest_report_path="data/evaluations/x.json",
        final_test_report_path=None,
        selection_run_ids={c.policy_id: c.run_id for c in candidates},
        recommendation_run_id="",
        sensitivity_run_ids={},
        package_version="0.1.0",
        schema_version="1.0",
        protocol_version="1.0",
    )
    rec = build_recommendation(
        sku="sku-1",
        category="cat-1",
        stats=DemandStats(mean_daily=2.0, std_daily=0.5, n_days=100),
        selection_candidates=candidates,
        selection_result=selection,
        forecast_model_id="naive",
        forecast_model_version="1.0",
        forecast_horizon=7,
        deployment_forecast_dates=_dates(7),
        deployment_forecast=[5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
        config=_config(),
        seed=7,
        service_level_target=0.90,
        evidence=evidence,
        assumptions=(),
        limitations=(),
        generated_at="2026-08-11T00:00:00+00:00",
    )
    costs = [
        rec.sensitivity[s]["total_cost"]
        for s in ("scale_0.9", "scale_1.0", "scale_1.1")
    ]
    assert costs[0] >= 0 and costs[2] >= 0
    assert costs[0] != costs[2]
