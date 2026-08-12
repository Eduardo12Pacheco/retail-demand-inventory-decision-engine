"""Typed robustness scenario manifest for the decision layer.

The scenario manifest freezes the bounded sensitivity matrix BEFORE any
robustness metric is materialized. It records, for a FROZEN deterministic
scenario set over the existing v2 population:

- identity and provenance: `source_manifest_id`, `source_manifest_revision`,
  `population_manifest_id`, `population_manifest_path`,
- protocol invariants: seed, horizon, selection objective, tie-break, and the
  explicit invariant-parameter list (source facts, v2 population, forecast
  models/versions, candidate policy families/versions, folds, observed
  selection-window semantics),
- forecast and policy versions the report must use (validated against code),
- the ordered scenario IDs and the per-scenario definitions: service target,
  lead/review assumptions, cost multipliers, demand-stress settings, changed
  parameters, labels, descriptions and rationale,
- a stable `content_sha256` over the canonical serialization (independent of
  file formatting), so the frozen matrix is verifiable byte-for-byte.

The manifest is always GENERATED from code (`build_scenarios_manifest`); it is
never hand-typed. Validation rejects duplicate IDs, missing parameters,
negative/nonfinite costs, nonpositive lead/review, service targets outside
[0, 1], unknown policy/model versions, unknown source/population IDs, broken
deterministic ordering, and a checksum mismatch.

Scenario demand stress is explicitly modeled as a *scenario-simulation-only*
assumption: the scale applies to the deployment/simulation stress window and
never to source demand, forecast training, or the primary v2 evaluation.

Command:

    python -m retail_demand_inventory.decisions.scenarios \\
        --out data/manifests/robustness-scenarios-v1.0.0.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..data.manifests import ManifestError, sha256_bytes
from ..forecasting import (
    HistGradientBoostingForecaster,
    MovingAverageForecaster,
    NaiveForecaster,
    SESForecaster,
)
from ..simulation import OrderUpToSafetyStockPolicy, ReorderPointOrderQuantityPolicy
from ..versions import PROTOCOL_VERSION

SCENARIOS_MANIFEST_VERSION = "v1.0.0"
SCENARIOS_MANIFEST_NAME = "robustness-scenarios"
SCENARIOS_MANIFEST_FILE_NAME = "robustness-scenarios-v1.0.0.json"

# The frozen scenario matrix, in deterministic order: the exact current
# reference first, then one-factor-at-a-time cost/lead/review/service changes,
# one joint stress case, and the demand-stress case last.
SCENARIO_ORDER = (
    "baseline-v1",
    "holding-high",
    "stockout-high",
    "ordering-high",
    "costs-low",
    "lead-short",
    "lead-long",
    "review-weekly",
    "lead-review-long",
    "service-085",
    "service-095",
    "demand-stress-high",
)

DEMAND_STRESS_SCOPE = "scenario-simulation-only"

# Parameter names a scenario may declare as changed (relative to baseline-v1).
KNOWN_PARAMETER_NAMES = (
    "service_level_target",
    "lead_time_days",
    "review_period_days",
    "cost_multipliers.holding",
    "cost_multipliers.stockout",
    "cost_multipliers.ordering",
    "demand_stress.scale",
)

SELECTION_OBJECTIVE = (
    "minimize total cost subject to simulated service level >= scenario target"
)
TIE_BREAK = (
    "feasible: lower total cost, then lower stockout units, then lower avg "
    "inventory, then lexicographically smaller run_id; infeasible fallback: "
    "highest simulated service level, then lower total cost, then "
    "lexicographically smaller run_id (transparent, never labeled optimal)"
)

INVARIANT_PARAMETERS = (
    "source facts (pinned revision, raw bytes, raw SHA-256, canonical content)",
    "v2 population selection (freshretailnet-real-population-v2)",
    (
        "forecast models and model versions (naive, moving_average, ses, "
        "hist_gradient_boosting)"
    ),
    "candidate policy families and policy versions",
    "horizon (7 days)",
    "temporal folds (expanding origins; final test untouched)",
    "seed 20260811",
    (
        "observed selection-window semantics (last validation fold demand, "
        "observed sales; censored demand during stockouts is documented, not "
        "recovered)"
    ),
)

SELECTION_WINDOW_DEMAND_SCALE = (
    "selection-window demand is never scaled: policy candidate selection always "
    "uses the observed last-validation-fold demand; a scenario demand scale "
    "applies ONLY to deployment/simulation stress and is documented per scenario"
)

# The exact source/population IDs the committed manifest references. They are
# validated at executor time against the actual manifests (unknown IDs fail).
SOURCE_MANIFEST_ID = "freshretailnet-real.json"
SOURCE_MANIFEST_PATH = "data/manifests/freshretailnet-real.json"
POPULATION_MANIFEST_ID = "freshretailnet-real-population-v2"
POPULATION_MANIFEST_PATH = "data/manifests/freshretailnet-real-population-v2.json"

# Default service/lead/review from the current reference (docs/evaluation-protocol.md).
REFERENCE_SERVICE_TARGET = 0.90
REFERENCE_LEAD_TIME_DAYS = 3
REFERENCE_REVIEW_PERIOD_DAYS = 1

# Default demand stress is no stress (scale 1.0, scenario-simulation-only).
DEFAULT_DEMAND_STRESS: Mapping[str, object] = {
    "scale": 1.0,
    "scope": DEMAND_STRESS_SCOPE,
}

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _sha256_ok(value: str | None) -> bool:
    return isinstance(value, str) and bool(_HEX_64.match(value))


def _revision_ok(value: str | None) -> bool:
    return isinstance(value, str) and bool(_HEX_40.match(value))


def _finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _code_forecast_versions() -> dict[str, str]:
    models = (
        NaiveForecaster(),
        MovingAverageForecaster(window=7),
        SESForecaster(alpha=0.3),
        HistGradientBoostingForecaster(),
    )
    return {model.model_id: model.model_version for model in models}


def _code_policy_versions() -> dict[str, str]:
    return {
        ReorderPointOrderQuantityPolicy.policy_id: (
            ReorderPointOrderQuantityPolicy.policy_version
        ),
        OrderUpToSafetyStockPolicy.policy_id: OrderUpToSafetyStockPolicy.policy_version,
    }


def _deterministic_timestamp() -> tuple[str, str]:
    raw = os.environ.get("SOURCE_DATE_EPOCH")
    if raw:
        try:
            ts = datetime.fromtimestamp(int(raw), tz=UTC)
            return ts.isoformat(), "SOURCE_DATE_EPOCH"
        except ValueError:
            pass
    return "2026-08-11T00:00:00+00:00", "documented-fixed-value"


def _repo_head() -> tuple[str | None, str]:
    """HEAD at generation time; never fabricates the eventual commit SHA."""
    root = Path(__file__).resolve().parents[3]
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return (
                out.stdout.strip(),
                (
                    "git HEAD at generation time (manifest generated before "
                    "commit; not the eventual commit SHA)"
                ),
            )
    except (OSError, subprocess.SubprocessError):
        pass
    return None, "unavailable"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ScenarioDefinition:
    """One frozen robustness scenario: all decision assumptions for the run."""

    scenario_id: str
    label: str
    description: str
    rationale: str
    service_level_target: float
    lead_time_days: int
    review_period_days: int
    cost_multipliers: Mapping[str, float]
    demand_stress: Mapping[str, object]
    changed_parameters: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "label": self.label,
            "description": self.description,
            "rationale": self.rationale,
            "service_level_target": self.service_level_target,
            "lead_time_days": self.lead_time_days,
            "review_period_days": self.review_period_days,
            "cost_multipliers": dict(self.cost_multipliers),
            "demand_stress": dict(self.demand_stress),
            "changed_parameters": list(self.changed_parameters),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ScenarioDefinition:
        try:
            demand_stress = dict(data["demand_stress"])
            return cls(
                scenario_id=str(data["scenario_id"]),
                label=str(data["label"]),
                description=str(data["description"]),
                rationale=str(data["rationale"]),
                service_level_target=float(data["service_level_target"]),
                lead_time_days=int(data["lead_time_days"]),
                review_period_days=int(data["review_period_days"]),
                cost_multipliers={
                    str(k): float(v) for k, v in dict(data["cost_multipliers"]).items()
                },
                demand_stress=demand_stress,
                changed_parameters=tuple(
                    str(p) for p in data.get("changed_parameters", ())
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(
                f"scenario definition is missing or malformed: {exc}"
            ) from exc

    def validate(self) -> tuple[str, ...]:
        problems: list[str] = []
        prefix = f"scenario {self.scenario_id!r}: "
        if not str(self.scenario_id).strip():
            return (prefix + "scenario_id must be non-empty",)
        if not _ID_RE.match(self.scenario_id):
            problems.append(f"{prefix}scenario_id must be lowercase [a-z0-9-]")
        for field in ("label", "description", "rationale"):
            if not str(getattr(self, field)).strip():
                problems.append(f"{prefix}{field} must be non-empty")
        if not _finite(self.service_level_target):
            problems.append(f"{prefix}service_level_target must be finite")
        elif not (0.0 <= self.service_level_target <= 1.0):
            problems.append(
                f"{prefix}service_level_target must be within [0, 1], got "
                f"{self.service_level_target}"
            )
        if not isinstance(self.lead_time_days, int) or self.lead_time_days <= 0:
            problems.append(
                f"{prefix}lead_time_days must be a positive integer, got "
                f"{self.lead_time_days!r}"
            )
        if not isinstance(self.review_period_days, int) or self.review_period_days <= 0:
            problems.append(
                f"{prefix}review_period_days must be a positive integer, got "
                f"{self.review_period_days!r}"
            )
        for name in ("holding", "stockout", "ordering"):
            value = self.cost_multipliers.get(name)
            if value is None:
                problems.append(f"{prefix}cost_multipliers.{name} is missing")
                continue
            if not _finite(value):
                problems.append(
                    f"{prefix}cost_multipliers.{name} must be finite, got {value!r}"
                )
            elif value < 0:
                problems.append(
                    f"{prefix}cost_multipliers.{name} must be >= 0, got {value!r}"
                )
        scale = self.demand_stress.get("scale")
        if not _finite(scale):
            problems.append(f"{prefix}demand_stress.scale must be finite")
        elif scale <= 0:
            problems.append(f"{prefix}demand_stress.scale must be > 0, got {scale!r}")
        if self.demand_stress.get("scope") != DEMAND_STRESS_SCOPE:
            problems.append(
                f"{prefix}demand_stress.scope must be "
                f"{DEMAND_STRESS_SCOPE!r}, got {self.demand_stress.get('scope')!r}"
            )
        for parameter in self.changed_parameters:
            if parameter not in KNOWN_PARAMETER_NAMES:
                problems.append(f"{prefix}unknown changed parameter {parameter!r}")
        return tuple(problems)

    def require_valid(self) -> None:
        problems = self.validate()
        if problems:
            raise ManifestError("; ".join(problems))


@dataclass(frozen=True)
class RobustnessScenariosManifest:
    """The frozen scenario matrix plus all protocol invariants it runs under."""

    manifest_version: str
    manifest_name: str
    protocol_version: str
    source_manifest_id: str
    source_manifest_revision: str
    population_manifest_id: str
    population_manifest_path: str
    forecast_versions: Mapping[str, str]
    policy_versions: Mapping[str, str]
    seed: int
    horizon: int
    selection_objective: str
    tie_break: str
    invariant_parameters: tuple[str, ...]
    selection_window_demand_scale: str
    scenario_ids: tuple[str, ...]
    scenarios: Mapping[str, ScenarioDefinition]
    creation_timestamp: str = ""
    timestamp_source: str = ""
    code_revision: str | None = None
    code_revision_note: str = ""
    content_sha256: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> RobustnessScenariosManifest:
        try:
            scenario_ids = tuple(str(s) for s in data["scenario_ids"])
            scenarios = {
                str(sid): ScenarioDefinition.from_dict(dict(entry))
                for sid, entry in dict(data["scenarios"]).items()
            }
            return cls(
                manifest_version=str(data["manifest_version"]),
                manifest_name=str(data["manifest_name"]),
                protocol_version=str(data["protocol_version"]),
                source_manifest_id=str(data["source_manifest_id"]),
                source_manifest_revision=str(data["source_manifest_revision"]),
                population_manifest_id=str(data["population_manifest_id"]),
                population_manifest_path=str(data["population_manifest_path"]),
                forecast_versions={
                    str(k): str(v) for k, v in dict(data["forecast_versions"]).items()
                },
                policy_versions={
                    str(k): str(v) for k, v in dict(data["policy_versions"]).items()
                },
                seed=int(data["seed"]),
                horizon=int(data["horizon"]),
                selection_objective=str(data["selection_objective"]),
                tie_break=str(data["tie_break"]),
                invariant_parameters=tuple(
                    str(p) for p in data["invariant_parameters"]
                ),
                selection_window_demand_scale=str(
                    data["selection_window_demand_scale"]
                ),
                scenario_ids=scenario_ids,
                scenarios=scenarios,
                creation_timestamp=str(data.get("creation_timestamp", "")),
                timestamp_source=str(data.get("timestamp_source", "")),
                code_revision=(
                    str(data["code_revision"]) if data.get("code_revision") else None
                ),
                code_revision_note=str(data.get("code_revision_note", "")),
                content_sha256=(
                    str(data["content_sha256"]) if data.get("content_sha256") else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(
                f"robustness scenario manifest is missing or malformed: {exc}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "manifest_name": self.manifest_name,
            "protocol_version": self.protocol_version,
            "source_manifest_id": self.source_manifest_id,
            "source_manifest_revision": self.source_manifest_revision,
            "population_manifest_id": self.population_manifest_id,
            "population_manifest_path": self.population_manifest_path,
            "forecast_versions": dict(self.forecast_versions),
            "policy_versions": dict(self.policy_versions),
            "seed": self.seed,
            "horizon": self.horizon,
            "selection_objective": self.selection_objective,
            "tie_break": self.tie_break,
            "invariant_parameters": list(self.invariant_parameters),
            "selection_window_demand_scale": self.selection_window_demand_scale,
            "scenario_ids": list(self.scenario_ids),
            "scenarios": {
                sid: scenario.to_dict() for sid, scenario in self.scenarios.items()
            },
            "creation_timestamp": self.creation_timestamp,
            "timestamp_source": self.timestamp_source,
            "code_revision": self.code_revision,
            "code_revision_note": self.code_revision_note,
            "content_sha256": self.content_sha256,
        }

    def content_checksum(self) -> str:
        """Stable SHA-256 over the canonical payload (excludes the checksum)."""
        payload = dict(self.to_dict())
        payload.pop("content_sha256", None)
        body = (
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            + "\n"
        )
        return sha256_bytes(body.encode("utf-8"))

    def validate(self) -> tuple[str, ...]:
        problems: list[str] = []
        if not self.manifest_version.strip():
            problems.append("manifest_version must be non-empty")
        if not self.manifest_name.strip():
            problems.append("manifest_name must be non-empty")
        if not self.protocol_version.strip():
            problems.append("protocol_version must be non-empty")
        if not self.source_manifest_id.strip():
            problems.append("source_manifest_id must be non-empty")
        if not _revision_ok(self.source_manifest_revision):
            problems.append(
                "source_manifest_revision must be a 40-char lowercase hex sha1"
            )
        if not self.population_manifest_id.strip():
            problems.append("population_manifest_id must be non-empty")
        if not self.population_manifest_path.strip():
            problems.append("population_manifest_path must be non-empty")

        expected_forecast = _code_forecast_versions()
        if not self.forecast_versions:
            problems.append("forecast_versions must not be empty")
        elif self.forecast_versions != expected_forecast:
            problems.append(
                "forecast_versions must match the code versions exactly "
                f"({expected_forecast}), got ({dict(self.forecast_versions)})"
            )
        expected_policy = _code_policy_versions()
        if not self.policy_versions:
            problems.append("policy_versions must not be empty")
        elif self.policy_versions != expected_policy:
            problems.append(
                "policy_versions must match the code versions exactly "
                f"({expected_policy}), got ({dict(self.policy_versions)})"
            )

        if not isinstance(self.seed, int) or self.seed <= 0:
            problems.append("seed must be a positive integer")
        if not isinstance(self.horizon, int) or self.horizon <= 0:
            problems.append("horizon must be a positive integer")
        if not self.selection_objective.strip():
            problems.append("selection_objective must be non-empty")
        if not self.tie_break.strip():
            problems.append("tie_break must be non-empty")
        if not self.invariant_parameters:
            problems.append("invariant_parameters must not be empty")
        for parameter in self.invariant_parameters:
            if not str(parameter).strip():
                problems.append("invariant_parameters entries must be non-empty")
        if not self.selection_window_demand_scale.strip():
            problems.append("selection_window_demand_scale must be non-empty")

        ids = self.scenario_ids
        if not ids:
            problems.append("scenario_ids must not be empty")
        else:
            if len(set(ids)) != len(ids):
                problems.append("scenario_ids contains duplicate IDs")
            ordered = tuple(sid for sid in SCENARIO_ORDER if sid in set(ids))
            if list(ids) != list(ordered):
                problems.append(
                    "scenario_ids must follow the frozen SCENARIO_ORDER "
                    "deterministically"
                )
            for sid in ids:
                if not _ID_RE.match(sid):
                    problems.append(f"scenario_id {sid!r} must be lowercase [a-z0-9-]")
        if set(self.scenarios) != set(ids):
            problems.append(
                "scenarios keys must exactly match scenario_ids (no missing or "
                "extra scenarios)"
            )
        for sid in ids:
            scenario = self.scenarios.get(sid)
            if scenario is None:
                problems.append(f"missing scenario definition for {sid!r}")
                continue
            if scenario.scenario_id != sid:
                problems.append(
                    f"scenario definition id {scenario.scenario_id!r} does not "
                    f"match key {sid!r}"
                )
            problems.extend(scenario.validate())
        if not self.creation_timestamp:
            problems.append("creation_timestamp is required")
        if not self.timestamp_source.strip():
            problems.append("timestamp_source must be non-empty")
        if self.code_revision is not None and not _revision_ok(self.code_revision):
            problems.append("code_revision must be a 40-char lowercase hex sha1")
        if not _sha256_ok(self.content_sha256):
            problems.append("content_sha256 must be a 64-char lowercase hex sha256")
        else:
            actual = self.content_checksum()
            if actual != self.content_sha256:
                problems.append(
                    "content_sha256 mismatch: recomputed "
                    f"{actual} != recorded {self.content_sha256}"
                )
        return tuple(problems)

    def require_valid(self) -> None:
        problems = self.validate()
        if problems:
            raise ManifestError("; ".join(problems))

    def save(self, path: Path) -> None:
        self.require_valid()
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")


def load_scenarios_manifest(path: Path) -> RobustnessScenariosManifest:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    manifest = RobustnessScenariosManifest.from_dict(data)
    manifest.require_valid()
    return manifest


def _default_scenarios() -> tuple[ScenarioDefinition, ...]:
    """The frozen 12-scenario matrix (see docs/robustness-protocol.md)."""
    demand_stress = dict(DEFAULT_DEMAND_STRESS)
    stress_high = {"scale": 1.30, "scope": DEMAND_STRESS_SCOPE}
    return (
        ScenarioDefinition(
            scenario_id="baseline-v1",
            label="Exact current reference",
            description=(
                "Reproduces the current v2 decisions exactly: service target "
                "0.90, lead 3, review 1, cost multipliers 1.0, demand scale 1.0."
            ),
            rationale=(
                "The baseline must reproduce the current v2 decisions "
                "byte-for-byte and serves as the comparison reference for every "
                "other scenario."
            ),
            service_level_target=REFERENCE_SERVICE_TARGET,
            lead_time_days=REFERENCE_LEAD_TIME_DAYS,
            review_period_days=REFERENCE_REVIEW_PERIOD_DAYS,
            cost_multipliers={"holding": 1.0, "stockout": 1.0, "ordering": 1.0},
            demand_stress=demand_stress,
            changed_parameters=(),
        ),
        ScenarioDefinition(
            scenario_id="holding-high",
            label="Holding cost doubled",
            description="Holding multiplier 2.0; everything else identical to baseline.",
            rationale=(
                "One-factor-at-a-time: a higher holding cost should push "
                "selection toward lower inventory coverage."
            ),
            service_level_target=REFERENCE_SERVICE_TARGET,
            lead_time_days=REFERENCE_LEAD_TIME_DAYS,
            review_period_days=REFERENCE_REVIEW_PERIOD_DAYS,
            cost_multipliers={"holding": 2.0, "stockout": 1.0, "ordering": 1.0},
            demand_stress=demand_stress,
            changed_parameters=("cost_multipliers.holding",),
        ),
        ScenarioDefinition(
            scenario_id="stockout-high",
            label="Stockout cost doubled",
            description="Stockout multiplier 2.0; everything else identical to baseline.",
            rationale=(
                "One-factor-at-a-time: a higher stockout cost should push "
                "selection toward higher service coverage."
            ),
            service_level_target=REFERENCE_SERVICE_TARGET,
            lead_time_days=REFERENCE_LEAD_TIME_DAYS,
            review_period_days=REFERENCE_REVIEW_PERIOD_DAYS,
            cost_multipliers={"holding": 1.0, "stockout": 2.0, "ordering": 1.0},
            demand_stress=demand_stress,
            changed_parameters=("cost_multipliers.stockout",),
        ),
        ScenarioDefinition(
            scenario_id="ordering-high",
            label="Ordering cost doubled",
            description="Ordering multiplier 2.0; everything else identical to baseline.",
            rationale=(
                "One-factor-at-a-time: a higher fixed order cost should push "
                "selection toward larger, less frequent orders."
            ),
            service_level_target=REFERENCE_SERVICE_TARGET,
            lead_time_days=REFERENCE_LEAD_TIME_DAYS,
            review_period_days=REFERENCE_REVIEW_PERIOD_DAYS,
            cost_multipliers={"holding": 1.0, "stockout": 1.0, "ordering": 2.0},
            demand_stress=demand_stress,
            changed_parameters=("cost_multipliers.ordering",),
        ),
        ScenarioDefinition(
            scenario_id="costs-low",
            label="All costs halved",
            description=(
                "Holding, stockout, and ordering multipliers all 0.5; "
                "everything else identical to baseline."
            ),
            rationale=(
                "A uniform cost deflation keeps relative cost ordering but "
                "changes absolute magnitudes; checks that selection is not "
                "scale-driven."
            ),
            service_level_target=REFERENCE_SERVICE_TARGET,
            lead_time_days=REFERENCE_LEAD_TIME_DAYS,
            review_period_days=REFERENCE_REVIEW_PERIOD_DAYS,
            cost_multipliers={"holding": 0.5, "stockout": 0.5, "ordering": 0.5},
            demand_stress=demand_stress,
            changed_parameters=(
                "cost_multipliers.holding",
                "cost_multipliers.stockout",
                "cost_multipliers.ordering",
            ),
        ),
        ScenarioDefinition(
            scenario_id="lead-short",
            label="Lead time 2 days",
            description="Lead time shortened from 3 to 2 days.",
            rationale=(
                "One-factor-at-a-time on the supply assumption: a shorter lead "
                "time reduces the coverage base and the initial inventory."
            ),
            service_level_target=REFERENCE_SERVICE_TARGET,
            lead_time_days=2,
            review_period_days=REFERENCE_REVIEW_PERIOD_DAYS,
            cost_multipliers={"holding": 1.0, "stockout": 1.0, "ordering": 1.0},
            demand_stress=demand_stress,
            changed_parameters=("lead_time_days",),
        ),
        ScenarioDefinition(
            scenario_id="lead-long",
            label="Lead time 5 days",
            description="Lead time lengthened from 3 to 5 days.",
            rationale=(
                "One-factor-at-a-time on the supply assumption: a longer lead "
                "time increases the coverage base and required inventory."
            ),
            service_level_target=REFERENCE_SERVICE_TARGET,
            lead_time_days=5,
            review_period_days=REFERENCE_REVIEW_PERIOD_DAYS,
            cost_multipliers={"holding": 1.0, "stockout": 1.0, "ordering": 1.0},
            demand_stress=demand_stress,
            changed_parameters=("lead_time_days",),
        ),
        ScenarioDefinition(
            scenario_id="review-weekly",
            label="Review period 7 days",
            description="Review period lengthened from 1 to 7 days.",
            rationale=(
                "One-factor-at-a-time on the review cadence: a weekly review "
                "changes order timing and coverage."
            ),
            service_level_target=REFERENCE_SERVICE_TARGET,
            lead_time_days=REFERENCE_LEAD_TIME_DAYS,
            review_period_days=7,
            cost_multipliers={"holding": 1.0, "stockout": 1.0, "ordering": 1.0},
            demand_stress=demand_stress,
            changed_parameters=("review_period_days",),
        ),
        ScenarioDefinition(
            scenario_id="lead-review-long",
            label="Lead 5 and review 7",
            description="Joint stress: lead time 5 days and review period 7 days.",
            rationale=(
                "Joint stress case: longer lead plus a weekly review compounds "
                "the coverage increase and order-timing change."
            ),
            service_level_target=REFERENCE_SERVICE_TARGET,
            lead_time_days=5,
            review_period_days=7,
            cost_multipliers={"holding": 1.0, "stockout": 1.0, "ordering": 1.0},
            demand_stress=demand_stress,
            changed_parameters=("lead_time_days", "review_period_days"),
        ),
        ScenarioDefinition(
            scenario_id="service-085",
            label="Service target 0.85",
            description="Service level target lowered from 0.90 to 0.85.",
            rationale=(
                "One-factor-at-a-time on the decision target: a lower target "
                "relaxes the constraint and may lower cost."
            ),
            service_level_target=0.85,
            lead_time_days=REFERENCE_LEAD_TIME_DAYS,
            review_period_days=REFERENCE_REVIEW_PERIOD_DAYS,
            cost_multipliers={"holding": 1.0, "stockout": 1.0, "ordering": 1.0},
            demand_stress=demand_stress,
            changed_parameters=("service_level_target",),
        ),
        ScenarioDefinition(
            scenario_id="service-095",
            label="Service target 0.95",
            description="Service level target raised from 0.90 to 0.95.",
            rationale=(
                "One-factor-at-a-time on the decision target: a higher target "
                "tightens the constraint and may raise cost or force fallback."
            ),
            service_level_target=0.95,
            lead_time_days=REFERENCE_LEAD_TIME_DAYS,
            review_period_days=REFERENCE_REVIEW_PERIOD_DAYS,
            cost_multipliers={"holding": 1.0, "stockout": 1.0, "ordering": 1.0},
            demand_stress=demand_stress,
            changed_parameters=("service_level_target",),
        ),
        ScenarioDefinition(
            scenario_id="demand-stress-high",
            label="Demand stress 1.30 (scenario simulation only)",
            description=(
                "Controlled demand scale 1.30 applied to the deployment/"
                "simulation stress window ONLY; source demand, forecast "
                "training, and the primary v2 evaluation are untouched."
            ),
            rationale=(
                "An explicitly modeled forecast-stress assumption: a 30% higher "
                "deployment-window demand tests order sizing under demand "
                "surprise without touching source facts or training."
            ),
            service_level_target=REFERENCE_SERVICE_TARGET,
            lead_time_days=REFERENCE_LEAD_TIME_DAYS,
            review_period_days=REFERENCE_REVIEW_PERIOD_DAYS,
            cost_multipliers={"holding": 1.0, "stockout": 1.0, "ordering": 1.0},
            demand_stress=stress_high,
            changed_parameters=("demand_stress.scale",),
        ),
    )


def build_scenarios_manifest(
    *,
    source_manifest_id: str | None = None,
    source_manifest_revision: str | None = None,
    population_manifest_id: str | None = None,
    population_manifest_path: str | None = None,
    scenarios: Sequence[ScenarioDefinition] | None = None,
    creation_timestamp: str | None = None,
    timestamp_source: str | None = None,
    code_revision: str | None = None,
) -> RobustnessScenariosManifest:
    """Generate the frozen robustness scenario manifest.

    IDs/revision default to the committed real source and population manifests;
    versions default to the actual code versions. Never hand-typed: the manifest
    is always derived from code and (by default) the committed manifests.
    """
    if (
        source_manifest_id is None
        or source_manifest_revision is None
        or population_manifest_id is None
        or population_manifest_path is None
    ):
        from ..data.population_manifest import (
            SOURCE_MANIFEST_ID as POP_SOURCE_MANIFEST_ID,
        )
        from ..data.population_manifest import load_population_manifest
        from ..data.real_manifest import load_real_manifest

        root = _repo_root()
        source = load_real_manifest(root / SOURCE_MANIFEST_PATH)
        population = load_population_manifest(root / POPULATION_MANIFEST_PATH)
        if source_manifest_id is None:
            source_manifest_id = POP_SOURCE_MANIFEST_ID
        if source_manifest_revision is None:
            source_manifest_revision = source.pinned_revision
        if population_manifest_id is None:
            population_manifest_id = population.population_id
        if population_manifest_path is None:
            population_manifest_path = POPULATION_MANIFEST_PATH

    if scenarios is None:
        scenarios = _default_scenarios()

    ts, ts_source = (
        (creation_timestamp, timestamp_source)
        if creation_timestamp is not None
        else _deterministic_timestamp()
    )
    revision_note = "provided"
    if code_revision is None:
        code_revision, revision_note = _repo_head()

    definitions = {scenario.scenario_id: scenario for scenario in scenarios}
    ids = tuple(scenario.scenario_id for scenario in scenarios)

    manifest = RobustnessScenariosManifest(
        manifest_version=SCENARIOS_MANIFEST_VERSION,
        manifest_name=SCENARIOS_MANIFEST_NAME,
        protocol_version=PROTOCOL_VERSION,
        source_manifest_id=str(source_manifest_id),
        source_manifest_revision=str(source_manifest_revision),
        population_manifest_id=str(population_manifest_id),
        population_manifest_path=str(population_manifest_path),
        forecast_versions=_code_forecast_versions(),
        policy_versions=_code_policy_versions(),
        seed=20260811,
        horizon=7,
        selection_objective=SELECTION_OBJECTIVE,
        tie_break=TIE_BREAK,
        invariant_parameters=INVARIANT_PARAMETERS,
        selection_window_demand_scale=SELECTION_WINDOW_DEMAND_SCALE,
        scenario_ids=ids,
        scenarios=definitions,
        creation_timestamp=ts,
        timestamp_source=ts_source,
        code_revision=code_revision,
        code_revision_note=revision_note,
        content_sha256=None,
    )
    manifest = replace(manifest, content_sha256=manifest.content_checksum())
    manifest.require_valid()
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the frozen robustness scenario manifest for the "
            "decision-layer sensitivity analysis over the v2 population."
        )
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        manifest = build_scenarios_manifest()
        manifest.save(args.out)
    except (ManifestError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {args.out}")
    print(
        f"scenarios manifest {manifest.manifest_version}: "
        f"{len(manifest.scenario_ids)} scenarios, content sha256 "
        f"{manifest.content_sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
