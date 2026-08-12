from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..simulation import SimulationOutcome

OBJECTIVE = "minimize total cost subject to the service-level constraint (>= target)"


@dataclass(frozen=True)
class PolicyCandidate:
    policy_id: str
    policy_version: str
    policy_params: Mapping[str, float | int]
    run_id: str
    service_level: float | None
    fill_rate: float | None
    total_cost: float
    stockout_units: float
    stockout_events: int
    avg_inventory: float
    first_order_quantity: float

    @classmethod
    def from_outcome(cls, outcome: SimulationOutcome) -> PolicyCandidate:
        return cls(
            policy_id=outcome.policy_id,
            policy_version=outcome.policy_version,
            policy_params=dict(outcome.policy_params),
            run_id=outcome.run_id,
            service_level=outcome.service_level,
            fill_rate=outcome.fill_rate,
            total_cost=outcome.total_cost,
            stockout_units=outcome.lost_units,
            stockout_events=outcome.stockout_events,
            avg_inventory=outcome.avg_inventory,
            first_order_quantity=outcome.first_order_quantity,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_params": dict(self.policy_params),
            "run_id": self.run_id,
            "service_level": self.service_level,
            "fill_rate": self.fill_rate,
            "total_cost": self.total_cost,
            "stockout_units": self.stockout_units,
            "stockout_events": self.stockout_events,
            "avg_inventory": self.avg_inventory,
            "first_order_quantity": self.first_order_quantity,
        }


@dataclass(frozen=True)
class SelectionResult:
    candidates: tuple[PolicyCandidate, ...]
    selected: PolicyCandidate
    target_service_level: float
    objective: str
    constraint_satisfied: bool
    fallback_reason: str | None
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "selected": self.selected.to_dict(),
            "target_service_level": self.target_service_level,
            "objective": self.objective,
            "constraint_satisfied": self.constraint_satisfied,
            "fallback_reason": self.fallback_reason,
            "reason": self.reason,
        }


def select_policy(
    candidates: Sequence[PolicyCandidate], target_service_level: float
) -> SelectionResult:
    if not candidates:
        raise ValueError("cannot select from an empty candidate set")

    feasible = [
        c
        for c in candidates
        if c.service_level is not None and c.service_level >= target_service_level
    ]

    if feasible:
        selected = min(
            feasible,
            key=lambda c: (c.total_cost, c.stockout_units, c.avg_inventory, c.run_id),
        )
        reason = (
            f"{selected.policy_id} selected: lowest total cost ({selected.total_cost:.4f}) "
            f"among candidates meeting service level >= {target_service_level} "
            f"(simulated service level {selected.service_level:.4f}). "
            "Selection is among generated candidates under the protocol rule; it is not an optimality claim."
        )
        return SelectionResult(
            candidates=tuple(candidates),
            selected=selected,
            target_service_level=target_service_level,
            objective=OBJECTIVE,
            constraint_satisfied=True,
            fallback_reason=None,
            reason=reason,
        )

    selected = min(
        candidates,
        key=lambda c: (
            -(c.service_level if c.service_level is not None else -1.0),
            c.total_cost,
            c.run_id,
        ),
    )
    fallback = (
        f"no candidate reached service level >= {target_service_level}; "
        f"selected the highest-service candidate as a transparent fallback"
    )
    reason = (
        f"{selected.policy_id} selected under fallback: highest simulated service level "
        f"({selected.service_level} < target {target_service_level}). "
        "This is a documented infeasible-case fallback, not an optimality claim."
    )
    return SelectionResult(
        candidates=tuple(candidates),
        selected=selected,
        target_service_level=target_service_level,
        objective=OBJECTIVE,
        constraint_satisfied=False,
        fallback_reason=fallback,
        reason=reason,
    )
