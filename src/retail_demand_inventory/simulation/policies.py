"""Deterministic inventory replenishment policies.

A policy answers one question on a review day: given the current inventory
position (on-hand + in-transit), how many units to order. Both policies are
stateless and deterministic. No policy in this project is ever called
"optimal": policies are generated from documented heuristics and selected by
simulation under the evaluation protocol's objective.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar


class Policy(ABC):
    """Interface for replenishment policies evaluated inside the simulator."""

    policy_id: ClassVar[str]
    policy_version: ClassVar[str]

    @abstractmethod
    def order_decision(self, inventory_position: float, *, review_day: bool) -> float:
        """Return the order quantity to place now (0 = no order).

        `inventory_position` is on-hand inventory plus units in transit.
        Called only on review days by the engine.
        """

    @abstractmethod
    def params(self) -> Mapping[str, float | int]:
        """Documented, serializable parameter snapshot for this instance."""


@dataclass(frozen=True)
class ReorderPointOrderQuantityPolicy(Policy):
    """Fixed reorder point and fixed order quantity (s, Q).

    On a review day, if the inventory position falls to or below the reorder
    point, order exactly `order_quantity` units. Assumptions: demand is lost
    (not backordered) when stock runs out; see engine assumptions.
    """

    policy_id = "reorder_point_order_quantity"
    policy_version = "1.0"

    reorder_point: float
    order_quantity: float

    def __post_init__(self) -> None:
        if self.reorder_point < 0:
            raise ValueError("reorder_point must be >= 0")
        if self.order_quantity <= 0:
            raise ValueError("order_quantity must be > 0")

    def order_decision(self, inventory_position: float, *, review_day: bool) -> float:
        if not review_day:
            return 0.0
        if inventory_position <= self.reorder_point:
            return float(self.order_quantity)
        return 0.0

    def params(self) -> Mapping[str, float | int]:
        return {
            "reorder_point": self.reorder_point,
            "order_quantity": self.order_quantity,
        }


@dataclass(frozen=True)
class OrderUpToSafetyStockPolicy(Policy):
    """Order up to a fixed target level (T, S).

    On a review day, if the inventory position is below `order_up_to_level`,
    order the difference. `order_up_to_level` is expected to be sized as
    (lead-time + review-period) expected demand plus safety stock; the level
    is passed in explicitly and documented per candidate, never tuned inside
    the simulator.
    """

    policy_id = "order_up_to_safety_stock"
    policy_version = "1.0"

    order_up_to_level: float

    def __post_init__(self) -> None:
        if self.order_up_to_level < 0:
            raise ValueError("order_up_to_level must be >= 0")

    def order_decision(self, inventory_position: float, *, review_day: bool) -> float:
        if not review_day:
            return 0.0
        shortfall = self.order_up_to_level - inventory_position
        return max(0.0, shortfall)

    def params(self) -> Mapping[str, float | int]:
        return {"order_up_to_level": self.order_up_to_level}
