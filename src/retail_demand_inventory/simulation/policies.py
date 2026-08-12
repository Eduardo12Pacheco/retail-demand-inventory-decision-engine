from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar


class Policy(ABC):
    policy_id: ClassVar[str]
    policy_version: ClassVar[str]

    @abstractmethod
    def order_decision(self, inventory_position: float, *, review_day: bool) -> float:
        pass

    @abstractmethod
    def params(self) -> Mapping[str, float | int]:
        pass


@dataclass(frozen=True)
class ReorderPointOrderQuantityPolicy(Policy):
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
