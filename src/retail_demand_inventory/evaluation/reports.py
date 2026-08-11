"""JSON serialization for evaluation reports.

All report payloads are plain JSON-compatible structures (dict/list/str/float/
int/bool/None). `sanitize` converts numpy scalar types so the report survives
`json.dumps` unchanged, and `save_json` produces deterministic bytes for fixed
inputs (sorted keys, fixed indent).

Determinism contract: the same report content always serializes to the same
bytes, which is what makes materializer runs byte-identical.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def round6(value: float | None) -> float | None:
    """Round a metric/value to 6 decimals; None stays None."""
    if value is None:
        return None
    return round(float(value), 6)


def sanitize(obj: Any) -> Any:
    """Convert numpy scalars/arrays to plain Python values, recursively."""
    import numpy as np

    if isinstance(obj, np.ndarray):
        return [sanitize(v) for v in obj.tolist()]
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, dict):
        return {str(k): sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    return obj


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(sanitize(obj), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    path.write_text(payload, encoding="utf-8")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@dataclass(frozen=True)
class ExperimentReport:
    """Top-level evaluation report produced by the materializer."""

    meta: Mapping[str, object]
    dataset: Mapping[str, object]
    protocol: Mapping[str, object]
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    overall: Mapping[str, object]
    per_sku: Mapping[str, Mapping[str, object]]

    def to_dict(self) -> dict[str, object]:
        return {
            "meta": dict(self.meta),
            "dataset": dict(self.dataset),
            "protocol": dict(self.protocol),
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "overall": dict(self.overall),
            "per_sku": {sku: dict(section) for sku, section in self.per_sku.items()},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ExperimentReport:
        return cls(
            meta=dict(data["meta"]),
            dataset=dict(data["dataset"]),
            protocol=dict(data["protocol"]),
            assumptions=tuple(str(a) for a in data["assumptions"]),
            limitations=tuple(str(l) for l in data["limitations"]),
            overall=dict(data["overall"]),
            per_sku={str(k): dict(v) for k, v in data["per_sku"].items()},
        )

    def save(self, path: Path) -> None:
        save_json(path, self.to_dict())

    @classmethod
    def load(cls, path: Path) -> ExperimentReport:
        return cls.from_dict(load_json(path))
