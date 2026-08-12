from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from ..simulation import (
    DemandSource,
    OrderUpToSafetyStockPolicy,
    Policy,
    ReorderPointOrderQuantityPolicy,
    SimulationConfig,
    SimulationInput,
    simulate,
)
from .evidence import EvidenceBundle
from .ranking import PolicyCandidate, SelectionResult


@dataclass(frozen=True)
class DemandStats:
    mean_daily: float
    std_daily: float
    n_days: int

    def to_dict(self) -> dict[str, object]:
        return {
            "mean_daily": self.mean_daily,
            "std_daily": self.std_daily,
            "n_days": self.n_days,
        }


@dataclass(frozen=True)
class Recommendation:
    sku: str
    category: str | None
    forecast_model_id: str
    forecast_model_version: str
    forecast_horizon: int
    deployment_forecast: tuple[float, ...]
    policy_id: str
    policy_version: str
    policy_params: Mapping[str, float | int]
    order_quantity: float
    service_level_target: float
    simulated_period: str
    simulated_service_level: float | None
    simulated_fill_rate: float | None
    simulated_total_cost: float
    simulated_stockout_units: float
    simulated_stockout_events: int
    simulated_avg_inventory: float
    objective: str
    constraint_satisfied: bool
    fallback_reason: str | None
    reason: str
    sensitivity: Mapping[str, Mapping[str, float | None]]
    evidence: EvidenceBundle
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    generated_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "sku": self.sku,
            "category": self.category,
            "forecast_model_id": self.forecast_model_id,
            "forecast_model_version": self.forecast_model_version,
            "forecast_horizon": self.forecast_horizon,
            "deployment_forecast": list(self.deployment_forecast),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_params": dict(self.policy_params),
            "order_quantity": self.order_quantity,
            "service_level_target": self.service_level_target,
            "simulated_period": self.simulated_period,
            "simulated_service_level": self.simulated_service_level,
            "simulated_fill_rate": self.simulated_fill_rate,
            "simulated_total_cost": self.simulated_total_cost,
            "simulated_stockout_units": self.simulated_stockout_units,
            "simulated_stockout_events": self.simulated_stockout_events,
            "simulated_avg_inventory": self.simulated_avg_inventory,
            "objective": self.objective,
            "constraint_satisfied": self.constraint_satisfied,
            "fallback_reason": self.fallback_reason,
            "reason": self.reason,
            "sensitivity": {
                str(scale): dict(row) for scale, row in sorted(self.sensitivity.items())
            },
            "evidence": self.evidence.to_dict(),
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "generated_at": self.generated_at,
        }


def _round2(value: float) -> float:
    return round(float(value), 2)


def generate_candidates(
    stats: DemandStats,
    *,
    lead_time_days: int,
    review_period_days: int,
) -> tuple[Policy, ...]:
    base = stats.mean_daily * (lead_time_days + review_period_days)
    order_qty = max(
        1.0, _round2(stats.mean_daily * (lead_time_days + review_period_days))
    )

    candidates: list[Policy] = []
    for k in (0.8, 1.0, 1.2, 1.4):
        candidates.append(
            ReorderPointOrderQuantityPolicy(
                reorder_point=_round2(base * k),
                order_quantity=order_qty,
            )
        )
    safety_sigma = stats.std_daily * math.sqrt(lead_time_days + review_period_days)
    for k in (0.9, 1.0, 1.1, 1.2):
        for z in (0.5, 1.0):
            candidates.append(
                OrderUpToSafetyStockPolicy(
                    order_up_to_level=_round2(base * k + z * safety_sigma)
                )
            )
    return tuple(candidates)


def simulate_candidates(
    policies: Sequence[Policy],
    *,
    sku: str,
    dates: Sequence[date],
    demand: Sequence[float],
    config: SimulationConfig,
    seed: int,
    demand_source: DemandSource,
) -> tuple[PolicyCandidate, ...]:
    candidates: list[PolicyCandidate] = []
    for policy in policies:
        outcome = simulate(
            SimulationInput(
                dates=tuple(dates),
                demand=tuple(float(v) for v in demand),
                config=config,
                policy=policy,
                seed=seed,
                demand_source=demand_source,
            )
        )
        candidates.append(PolicyCandidate.from_outcome(outcome))
    return tuple(candidates)


def _scale_demand(demand: Sequence[float], scale: float) -> tuple[float, ...]:
    return tuple(round(float(v) * scale, 6) for v in demand)


def build_recommendation(
    *,
    sku: str,
    category: str | None,
    stats: DemandStats,
    selection_candidates: Sequence[PolicyCandidate],
    selection_result: SelectionResult,
    forecast_model_id: str,
    forecast_model_version: str,
    forecast_horizon: int,
    deployment_forecast_dates: Sequence[date],
    deployment_forecast: Sequence[float],
    config: SimulationConfig,
    seed: int,
    service_level_target: float,
    evidence: EvidenceBundle,
    assumptions: Sequence[str],
    limitations: Sequence[str],
    generated_at: str,
) -> Recommendation:
    selected = selection_result.selected
    selected_policy = _policy_from_params(selected.policy_id, selected.policy_params)

    rec_source = DemandSource(
        kind="forecast",
        model_id=forecast_model_id,
        model_version=forecast_model_version,
        reference="deployment_forecast",
    )
    rec_input = SimulationInput(
        dates=tuple(deployment_forecast_dates),
        demand=tuple(float(v) for v in deployment_forecast),
        config=config,
        policy=selected_policy,
        seed=seed,
        demand_source=rec_source,
    )
    rec_outcome = simulate(rec_input)

    sensitivity: dict[str, Mapping[str, float | None]] = {}
    sensitivity_run_ids: dict[str, str] = {}
    for scale in (0.9, 1.0, 1.1):
        scaled_input = SimulationInput(
            dates=tuple(deployment_forecast_dates),
            demand=_scale_demand(deployment_forecast, scale),
            config=config,
            policy=selected_policy,
            seed=seed,
            demand_source=DemandSource(
                kind="forecast",
                model_id=forecast_model_id,
                model_version=forecast_model_version,
                reference=f"deployment_forecast_scaled_{scale}",
            ),
        )
        outcome = simulate(scaled_input)
        key = f"scale_{scale}"
        sensitivity[key] = {
            "service_level": outcome.service_level,
            "fill_rate": outcome.fill_rate,
            "total_cost": outcome.total_cost,
        }
        sensitivity_run_ids[key] = outcome.run_id

    evidence_with_runs = _with_runs(
        evidence,
        recommendation_run_id=rec_outcome.run_id,
        sensitivity_run_ids=sensitivity_run_ids,
    )

    return Recommendation(
        sku=sku,
        category=category,
        forecast_model_id=forecast_model_id,
        forecast_model_version=forecast_model_version,
        forecast_horizon=forecast_horizon,
        deployment_forecast=tuple(float(v) for v in deployment_forecast),
        policy_id=selected.policy_id,
        policy_version=selected.policy_version,
        policy_params=dict(selected.policy_params),
        order_quantity=rec_outcome.first_order_quantity,
        service_level_target=service_level_target,
        simulated_period="deployment forecast window",
        simulated_service_level=rec_outcome.service_level,
        simulated_fill_rate=rec_outcome.fill_rate,
        simulated_total_cost=rec_outcome.total_cost,
        simulated_stockout_units=rec_outcome.lost_units,
        simulated_stockout_events=rec_outcome.stockout_events,
        simulated_avg_inventory=rec_outcome.avg_inventory,
        objective=selection_result.objective,
        constraint_satisfied=selection_result.constraint_satisfied,
        fallback_reason=selection_result.fallback_reason,
        reason=selection_result.reason,
        sensitivity=sensitivity,
        evidence=evidence_with_runs,
        assumptions=tuple(assumptions),
        limitations=tuple(limitations),
        generated_at=generated_at,
    )


def _policy_from_params(policy_id: str, params: Mapping[str, float | int]) -> Policy:
    if policy_id == ReorderPointOrderQuantityPolicy.policy_id:
        return ReorderPointOrderQuantityPolicy(
            reorder_point=float(params["reorder_point"]),
            order_quantity=float(params["order_quantity"]),
        )
    if policy_id == OrderUpToSafetyStockPolicy.policy_id:
        return OrderUpToSafetyStockPolicy(
            order_up_to_level=float(params["order_up_to_level"])
        )
    raise ValueError(f"unknown policy id: {policy_id}")


def _with_runs(
    evidence: EvidenceBundle,
    *,
    recommendation_run_id: str,
    sensitivity_run_ids: Mapping[str, str],
) -> EvidenceBundle:
    from dataclasses import replace

    return replace(
        evidence,
        recommendation_run_id=recommendation_run_id,
        sensitivity_run_ids=dict(sensitivity_run_ids),
    )
