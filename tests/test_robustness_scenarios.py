"""Robustness scenario manifest: generation, validation, checksum, ordering."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from retail_demand_inventory.data.manifests import ManifestError
from retail_demand_inventory.decisions.scenarios import (
    DEMAND_STRESS_SCOPE,
    KNOWN_PARAMETER_NAMES,
    REFERENCE_LEAD_TIME_DAYS,
    REFERENCE_REVIEW_PERIOD_DAYS,
    REFERENCE_SERVICE_TARGET,
    SCENARIO_ORDER,
    ScenarioDefinition,
    build_scenarios_manifest,
    load_scenarios_manifest,
)
from retail_demand_inventory.evaluation.materialize import (
    LEAD_TIME_DAYS,
    REVIEW_PERIOD_DAYS,
    SEED,
    SERVICE_LEVEL_TARGET,
)


def _value_for(definition: ScenarioDefinition, parameter: str):
    if parameter == "service_level_target":
        return definition.service_level_target
    if parameter == "lead_time_days":
        return definition.lead_time_days
    if parameter == "review_period_days":
        return definition.review_period_days
    if parameter.startswith("cost_multipliers."):
        return definition.cost_multipliers[parameter.split(".")[1]]
    if parameter == "demand_stress.scale":
        return definition.demand_stress["scale"]
    raise AssertionError(f"unknown parameter {parameter!r}")


@pytest.fixture
def scenarios(tmp_path):
    manifest = build_scenarios_manifest()
    path = tmp_path / "scenarios.json"
    manifest.save(path)
    return manifest, path


def test_build_roundtrip(tmp_path) -> None:
    manifest = build_scenarios_manifest()
    path = tmp_path / "scenarios.json"
    manifest.save(path)
    loaded = load_scenarios_manifest(path)
    assert loaded == manifest
    assert loaded.to_dict() == manifest.to_dict()
    assert manifest.manifest_version == "v1.0.0"
    assert manifest.protocol_version == "1.0"
    assert manifest.seed == SEED
    assert manifest.forecast_versions["naive"] == "1.0"
    assert manifest.policy_versions["reorder_point_order_quantity"] == "1.0"
    assert manifest.content_sha256 and len(manifest.content_sha256) == 64


def test_exactly_12_scenarios_in_frozen_order(scenarios) -> None:
    manifest, _path = scenarios
    assert len(manifest.scenario_ids) == 12
    assert manifest.scenario_ids == tuple(
        sid for sid in SCENARIO_ORDER if sid in set(manifest.scenario_ids)
    )
    assert set(manifest.scenarios) == set(manifest.scenario_ids)
    assert manifest.scenario_ids[0] == "baseline-v1"
    assert manifest.scenario_ids[-1] == "demand-stress-high"


def test_baseline_config_reproduces_current_reference(scenarios) -> None:
    manifest, _path = scenarios
    baseline = manifest.scenarios["baseline-v1"]
    assert baseline.service_level_target == SERVICE_LEVEL_TARGET
    assert baseline.lead_time_days == LEAD_TIME_DAYS
    assert baseline.review_period_days == REVIEW_PERIOD_DAYS
    assert baseline.cost_multipliers == {
        "holding": 1.0,
        "stockout": 1.0,
        "ordering": 1.0,
    }
    assert baseline.demand_stress["scale"] == 1.0
    assert baseline.demand_stress["scope"] == DEMAND_STRESS_SCOPE
    assert baseline.changed_parameters == ()
    # exact reference values match the committed protocol constants
    assert REFERENCE_SERVICE_TARGET == 0.90
    assert REFERENCE_LEAD_TIME_DAYS == 3
    assert REFERENCE_REVIEW_PERIOD_DAYS == 1


def test_changed_parameters_declared_only(scenarios) -> None:
    manifest, _path = scenarios
    baseline = manifest.scenarios["baseline-v1"]
    for scenario_id in manifest.scenario_ids[1:]:
        scenario = manifest.scenarios[scenario_id]
        actual_changes = {
            parameter
            for parameter in KNOWN_PARAMETER_NAMES
            if _value_for(scenario, parameter) != _value_for(baseline, parameter)
        }
        assert set(scenario.changed_parameters) == actual_changes, scenario_id
        assert set(scenario.changed_parameters) <= set(KNOWN_PARAMETER_NAMES)
        assert scenario.demand_stress["scope"] == DEMAND_STRESS_SCOPE


def test_scenario_values_match_matrix(scenarios) -> None:
    manifest, _path = scenarios
    s = manifest.scenarios
    assert s["holding-high"].cost_multipliers["holding"] == 2.0
    assert s["stockout-high"].cost_multipliers["stockout"] == 2.0
    assert s["ordering-high"].cost_multipliers["ordering"] == 2.0
    assert s["costs-low"].cost_multipliers == {
        "holding": 0.5,
        "stockout": 0.5,
        "ordering": 0.5,
    }
    assert s["lead-short"].lead_time_days == 2
    assert s["lead-long"].lead_time_days == 5
    assert s["review-weekly"].review_period_days == 7
    assert s["lead-review-long"].lead_time_days == 5
    assert s["lead-review-long"].review_period_days == 7
    assert s["service-085"].service_level_target == 0.85
    assert s["service-095"].service_level_target == 0.95
    assert s["demand-stress-high"].demand_stress["scale"] == 1.30
    assert s["demand-stress-high"].demand_stress["scope"] == DEMAND_STRESS_SCOPE


def test_duplicate_scenario_ids_rejected(scenarios) -> None:
    manifest, _path = scenarios
    payload = manifest.to_dict()
    payload["scenario_ids"] = [
        "baseline-v1",
        "baseline-v1",
        *payload["scenario_ids"][1:],
    ]
    problems = (
        __import__(
            "retail_demand_inventory.decisions.scenarios",
            fromlist=["RobustnessScenariosManifest"],
        )
        .RobustnessScenariosManifest.from_dict(payload)
        .validate()
    )
    assert any("duplicate" in problem for problem in problems)


def test_missing_and_extra_scenario_rejected(scenarios) -> None:
    manifest, _path = scenarios
    cls = __import__(
        "retail_demand_inventory.decisions.scenarios",
        fromlist=["RobustnessScenariosManifest"],
    ).RobustnessScenariosManifest
    payload = manifest.to_dict()
    payload["scenarios"].pop("holding-high")
    payload["scenario_ids"] = [
        sid for sid in payload["scenario_ids"] if sid != "holding-high"
    ]
    pruned = cls.from_dict(payload)
    pruned = replace(pruned, content_sha256=pruned.content_checksum())
    assert pruned.validate() == ()

    payload = manifest.to_dict()
    payload["scenario_ids"] = list(payload["scenario_ids"]) + ["extra"]
    extra = cls.from_dict(payload)
    extra = replace(extra, content_sha256=extra.content_checksum())
    problems = extra.validate()
    assert any("scenarios keys must exactly match" in p for p in problems)


def test_missing_params_rejected(scenarios) -> None:
    manifest, _path = scenarios
    payload = manifest.to_dict()
    del payload["scenarios"]["baseline-v1"]["cost_multipliers"]
    cls = __import__(
        "retail_demand_inventory.decisions.scenarios",
        fromlist=["RobustnessScenariosManifest"],
    ).RobustnessScenariosManifest
    with pytest.raises(ManifestError):
        cls.from_dict(payload)


def test_invalid_service_targets_rejected(scenarios) -> None:
    manifest, _path = scenarios
    cls = __import__(
        "retail_demand_inventory.decisions.scenarios",
        fromlist=["RobustnessScenariosManifest"],
    ).RobustnessScenariosManifest
    for bad in (1.5, -0.1, 2.0):
        payload = manifest.to_dict()
        definition = dict(payload["scenarios"]["service-095"])
        definition["service_level_target"] = bad
        payload["scenarios"]["service-095"] = definition
        problems = cls.from_dict(payload).validate()
        assert any("service_level_target" in p for p in problems)


def test_negative_and_nonfinite_costs_rejected(scenarios) -> None:
    manifest, _path = scenarios
    cls = __import__(
        "retail_demand_inventory.decisions.scenarios",
        fromlist=["RobustnessScenariosManifest"],
    ).RobustnessScenariosManifest
    for bad in (-0.5, float("nan"), float("inf")):
        payload = manifest.to_dict()
        definition = dict(payload["scenarios"]["holding-high"])
        multipliers = dict(definition["cost_multipliers"])
        multipliers["holding"] = bad
        definition["cost_multipliers"] = multipliers
        payload["scenarios"]["holding-high"] = definition
        problems = cls.from_dict(payload).validate()
        assert any("cost_multipliers.holding" in p for p in problems)


def test_nonpositive_lead_and_review_rejected(scenarios) -> None:
    manifest, _path = scenarios
    cls = __import__(
        "retail_demand_inventory.decisions.scenarios",
        fromlist=["RobustnessScenariosManifest"],
    ).RobustnessScenariosManifest
    for bad in (0, -1):
        payload = manifest.to_dict()
        definition = dict(payload["scenarios"]["lead-short"])
        definition["lead_time_days"] = bad
        payload["scenarios"]["lead-short"] = definition
        problems = cls.from_dict(payload).validate()
        assert any("lead_time_days" in p for p in problems)

        payload = manifest.to_dict()
        definition = dict(payload["scenarios"]["review-weekly"])
        definition["review_period_days"] = bad
        payload["scenarios"]["review-weekly"] = definition
        problems = cls.from_dict(payload).validate()
        assert any("review_period_days" in p for p in problems)


def test_unknown_model_and_policy_versions_rejected(scenarios) -> None:
    manifest, _path = scenarios
    cls = __import__(
        "retail_demand_inventory.decisions.scenarios",
        fromlist=["RobustnessScenariosManifest"],
    ).RobustnessScenariosManifest
    payload = manifest.to_dict()
    versions = dict(payload["forecast_versions"])
    versions["naive"] = "9.9"
    payload["forecast_versions"] = versions
    problems = cls.from_dict(payload).validate()
    assert any("forecast_versions" in p for p in problems)

    payload = manifest.to_dict()
    versions = dict(payload["policy_versions"])
    versions["reorder_point_order_quantity"] = "9.9"
    payload["policy_versions"] = versions
    problems = cls.from_dict(payload).validate()
    assert any("policy_versions" in p for p in problems)

    payload = manifest.to_dict()
    versions = dict(payload["forecast_versions"])
    versions["made_up_model"] = "1.0"
    payload["forecast_versions"] = versions
    problems = cls.from_dict(payload).validate()
    assert any("forecast_versions" in p for p in problems)


def test_broken_scenario_ordering_rejected(scenarios) -> None:
    manifest, _path = scenarios
    payload = manifest.to_dict()
    payload["scenario_ids"] = [
        "holding-high",
        "baseline-v1",
        *[
            sid
            for sid in payload["scenario_ids"]
            if sid not in ("baseline-v1", "holding-high")
        ],
    ]
    cls = __import__(
        "retail_demand_inventory.decisions.scenarios",
        fromlist=["RobustnessScenariosManifest"],
    ).RobustnessScenariosManifest
    problems = cls.from_dict(payload).validate()
    assert any("SCENARIO_ORDER" in p or "deterministically" in p for p in problems)


def test_checksum_stable_and_tamper_rejected(scenarios) -> None:
    manifest, _path = scenarios
    assert manifest.content_sha256 == manifest.content_checksum()
    rebuilt = build_scenarios_manifest()
    assert rebuilt.content_sha256 == manifest.content_sha256

    payload = manifest.to_dict()
    payload["scenarios"]["service-095"]["service_level_target"] = 0.96
    cls = __import__(
        "retail_demand_inventory.decisions.scenarios",
        fromlist=["RobustnessScenariosManifest"],
    ).RobustnessScenariosManifest
    tampered = cls.from_dict(payload)
    problems = tampered.validate()
    assert any("content_sha256 mismatch" in p for p in problems)
    with pytest.raises(ManifestError, match="content_sha256 mismatch"):
        tampered.require_valid()


def test_load_requires_valid_checksum(tmp_path) -> None:
    manifest = build_scenarios_manifest()
    path = tmp_path / "scenarios.json"
    manifest.save(path)
    payload = json.loads(path.read_text())
    payload["seed"] = 0
    path.write_text(json.dumps(payload))
    with pytest.raises(ManifestError):
        load_scenarios_manifest(path)


def test_scenario_definition_validation_direct() -> None:
    from retail_demand_inventory.decisions.scenarios import ScenarioDefinition

    good = ScenarioDefinition(
        scenario_id="x-ok",
        label="l",
        description="d",
        rationale="r",
        service_level_target=0.9,
        lead_time_days=3,
        review_period_days=1,
        cost_multipliers={"holding": 1.0, "stockout": 1.0, "ordering": 1.0},
        demand_stress={"scale": 1.0, "scope": DEMAND_STRESS_SCOPE},
        changed_parameters=(),
    )
    assert good.validate() == ()
    bad = replace(
        good,
        scenario_id="Bad-ID",
        service_level_target=1.2,
        lead_time_days=-1,
        demand_stress={"scale": 0.0, "scope": DEMAND_STRESS_SCOPE},
        changed_parameters=("made_up",),
    )
    problems = bad.validate()
    assert any("scenario_id" in p for p in problems)
    assert any("service_level_target" in p for p in problems)
    assert any("lead_time_days" in p for p in problems)
    assert any("demand_stress.scale" in p for p in problems)
    assert any("unknown changed parameter" in p for p in problems)
