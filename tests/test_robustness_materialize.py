from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from real_helpers import REVISION, make_manifest, write_expanded_raw

from retail_demand_inventory.data import ManifestError, RealLoaderError
from retail_demand_inventory.data.population_manifest import (
    POPULATION_V2_ID,
    build_population_manifest,
)
from retail_demand_inventory.decisions.scenarios import build_scenarios_manifest
from retail_demand_inventory.evaluation.reports import load_json
from retail_demand_inventory.evaluation.robustness import (
    BASELINE_SCENARIO_ID,
    robustness_analysis,
)
from retail_demand_inventory.evaluation.robustness_materialize import (
    FIXTURE_ROBUSTNESS_REPORT_NAME,
    ROBUSTNESS_NOTICE,
    ROBUSTNESS_REPORT_NAME,
    RobustnessError,
    materialize_robustness_fixture,
    materialize_robustness_real,
)

V1_REPORT_SHA256 = "552aa5edbefcf45ff7416b237c0f16f60b38408f5fe921cffe610076bdad007a"
V2_REPORT_SHA256 = "b626a9de2981cdefd1dfda23cff593a7101074a58c6e29cde59b36f53c6b7e84"


def _build_scenarios(
    *,
    source_manifest_id: str = "freshretailnet-real.json",
    source_manifest_revision: str = REVISION,
    population_manifest_id: str = POPULATION_V2_ID,
):
    return build_scenarios_manifest(
        source_manifest_id=source_manifest_id,
        source_manifest_revision=source_manifest_revision,
        population_manifest_id=population_manifest_id,
        population_manifest_path="data/manifests/freshretailnet-real-population-v2.json",
    )


def _setup_real(tmp_path, *, stores=3, products=3, per_store_cap=1, target_keys=3):
    raw = tmp_path / "raw"
    raw.mkdir()
    write_expanded_raw(raw, stores=stores, products=products)
    manifest = make_manifest(raw, train_name="train.parquet", eval_name="eval.parquet")
    manifest_path = tmp_path / "manifest.json"
    manifest.save(manifest_path)
    population = build_population_manifest(
        source_manifest_path=manifest_path,
        raw_dir=raw,
        per_store_cap=per_store_cap,
        target_keys=target_keys,
    )
    pop_path = tmp_path / "population.json"
    population.save(pop_path)
    scenarios = _build_scenarios()
    scen_path = tmp_path / "scenarios.json"
    scenarios.save(scen_path)
    return raw, manifest_path, pop_path, scen_path


def test_v1_and_v2_report_hashes_pinned(repo_root) -> None:
    for name, expected in (
        ("freshretailnet-real-report.json", V1_REPORT_SHA256),
        ("freshretailnet-real-expanded-report.json", V2_REPORT_SHA256),
    ):
        report = repo_root / "data/evaluations" / name
        assert report.exists()
        assert hashlib.sha256(report.read_bytes()).hexdigest() == expected


def _fixture_paths(repo_root):
    return (
        repo_root / "data/fixtures" / "freshretailnet_style_synthetic.csv",
        repo_root / "data/manifests" / "fixture_synthetic.json",
    )


def test_fixture_robustness_report_structure(repo_root, tmp_path) -> None:
    fixture, manifest = _fixture_paths(repo_root)
    report_path = materialize_robustness_fixture(
        fixture_path=fixture,
        manifest_path=manifest,
        scenario_manifest_path=repo_root
        / "data"
        / "manifests"
        / "robustness-scenarios-v1.0.0.json",
        outdir=tmp_path / "out",
    )
    assert report_path.name == FIXTURE_ROBUSTNESS_REPORT_NAME
    assert not (tmp_path / "out" / ROBUSTNESS_REPORT_NAME).exists()
    report = load_json(report_path)
    assert report["meta"]["source_mode"] == "synthetic-fixture-robustness"
    assert report["robustness"]["scenario_count"] == 12
    assert report["robustness"]["scenario_ids"][0] == "baseline-v1"
    assert report["meta"]["report_name"] == FIXTURE_ROBUSTNESS_REPORT_NAME
    for scenario_id in report["robustness"]["scenario_ids"]:
        keys = report["robustness"]["scenarios"][scenario_id]["keys"]
        assert set(keys) == set(report["overall"]["skus"])
    analysis = report["robustness"]["analysis"]
    assert "per_key_baseline_comparison" in analysis
    assert "transition_matrix" in analysis
    assert "aggregate" in analysis
    assert "observed_tradeoffs" in analysis
    assert "Pareto" in analysis["observed_tradeoffs"]["note"]
    assert any("NOT observed" in a for a in report["assumptions"])
    assert report["source_facts"]["source_label"] == "synthetic-fixture"


def test_fixture_baseline_reproduces_current_fixture_decisions(
    repo_root, tmp_path
) -> None:
    fixture, manifest = _fixture_paths(repo_root)
    report_path = materialize_robustness_fixture(
        fixture_path=fixture,
        manifest_path=manifest,
        scenario_manifest_path=repo_root
        / "data"
        / "manifests"
        / "robustness-scenarios-v1.0.0.json",
        outdir=tmp_path / "out",
    )
    robustness = load_json(report_path)["robustness"]
    current = load_json(repo_root / "data/evaluations" / "experiment_report.json")
    baseline = robustness["scenarios"][BASELINE_SCENARIO_ID]["keys"]
    for sku, section in current["per_sku"].items():
        selected = baseline[sku]["selection"]["selected"]
        recommendation = baseline[sku]["recommendation"]
        assert (
            selected["policy_id"]
            == section["policy_selection"]["selected"]["policy_id"]
        )
        assert (
            selected["policy_params"]
            == section["policy_selection"]["selected"]["policy_params"]
        )
        assert selected["run_id"] == section["policy_selection"]["selected"]["run_id"]
        assert (
            recommendation["run_id"]
            == section["recommendation"]["evidence"]["recommendation_run_id"]
        )
        assert (
            recommendation["sensitivity_run_ids"]
            == section["recommendation"]["evidence"]["sensitivity_run_ids"]
        )
        assert recommendation["order_quantity"] == pytest.approx(
            section["recommendation"]["order_quantity"]
        )


def test_fixture_robustness_deterministic(repo_root, tmp_path) -> None:
    fixture, manifest = _fixture_paths(repo_root)
    scenarios = repo_root / "data" / "manifests" / "robustness-scenarios-v1.0.0.json"
    out_a = materialize_robustness_fixture(
        fixture_path=fixture,
        manifest_path=manifest,
        scenario_manifest_path=scenarios,
        outdir=tmp_path / "a",
    )
    out_b = materialize_robustness_fixture(
        fixture_path=fixture,
        manifest_path=manifest,
        scenario_manifest_path=scenarios,
        outdir=tmp_path / "b",
    )
    assert out_a.read_bytes() == out_b.read_bytes()


def test_fixture_rejects_tampered_scenario_manifest(repo_root, tmp_path) -> None:
    _fixture, _manifest = _fixture_paths(repo_root)
    scenarios = build_scenarios_manifest()
    payload = scenarios.to_dict()
    payload["scenarios"]["service-095"]["service_level_target"] = 0.96
    from retail_demand_inventory.decisions.scenarios import (
        RobustnessScenariosManifest,
    )

    tampered = RobustnessScenariosManifest.from_dict(payload)
    bad = tmp_path / "scenarios-bad.json"
    with pytest.raises(ManifestError, match="content_sha256 mismatch"):
        tampered.save(bad)


def test_fixture_mode_does_not_touch_other_reports(repo_root, tmp_path) -> None:
    fixture, manifest = _fixture_paths(repo_root)
    outdir = tmp_path / "out"
    materialize_robustness_fixture(
        fixture_path=fixture,
        manifest_path=manifest,
        scenario_manifest_path=repo_root
        / "data"
        / "manifests"
        / "robustness-scenarios-v1.0.0.json",
        outdir=outdir,
    )
    assert not (outdir / "experiment_report.json").exists()
    assert not (outdir / "freshretailnet-real-report.json").exists()


def test_real_robustness_report_structure(tmp_path) -> None:
    raw, manifest_path, pop_path, scen_path = _setup_real(tmp_path)
    report_path = materialize_robustness_real(
        source_manifest_path=manifest_path,
        population_path=pop_path,
        scenario_manifest_path=scen_path,
        raw_dir=raw,
        outdir=tmp_path / "out",
    )
    assert report_path.name == ROBUSTNESS_REPORT_NAME
    report = load_json(report_path)
    assert report["meta"]["source_mode"] == "real-freshretailnet-expanded-robustness"
    assert report["meta"]["evaluation_label"].startswith(
        "Deterministic robustness evaluation"
    )
    assert (
        report["dataset"]["source_label"] == "real-freshretailnet-expanded-robustness"
    )
    assert report["robustness"]["scenario_count"] == 12
    assert (
        report["robustness"]["scenario_manifest"]["population_manifest_id"]
        == POPULATION_V2_ID
    )
    assert report["source_facts"]["population_id"] == POPULATION_V2_ID
    assert report["source_facts"]["pinned_revision"] == REVISION
    assert report["source_facts"]["raw_checksums"]["train"]["observed_sha256"]
    assert report["source_facts"]["stockout_derivation_version"] == "1"
    assert (
        report["robustness"]["analysis"]["aggregate"]["overall"]["scenario_key_pairs"]
        == 3 * 11
    )
    assert len(report["overall"]["skus"]) == 3


def test_real_robustness_source_and_stockout_preserved(tmp_path) -> None:
    raw, manifest_path, pop_path, scen_path = _setup_real(tmp_path)
    manifest = make_manifest(raw, train_name="train.parquet", eval_name="eval.parquet")
    report = load_json(
        materialize_robustness_real(
            source_manifest_path=manifest_path,
            population_path=pop_path,
            scenario_manifest_path=scen_path,
            raw_dir=raw,
            outdir=tmp_path / "out",
        )
    )
    facts = report["source_facts"]
    for entry in manifest.raw_files:
        recorded = facts["raw_checksums"][entry.name]
        assert recorded["expected_sha256"] == entry.expected_sha256
        assert recorded["observed_sha256"] == entry.observed_sha256
        assert recorded["expected_size"] == entry.expected_size
        assert recorded["observed_size"] == entry.observed_size
    assert facts["stockout_derivation_version"] == manifest.stockout_derivation_version
    assert facts["stockout_derivation_rule"] == manifest.stockout_derivation_rule
    assert facts["canonical_content_sha256"]
    assert facts["observed_sales_semantics"]


def test_real_robustness_deterministic(tmp_path) -> None:
    raw, manifest_path, pop_path, scen_path = _setup_real(tmp_path)
    out_a = materialize_robustness_real(
        source_manifest_path=manifest_path,
        population_path=pop_path,
        scenario_manifest_path=scen_path,
        raw_dir=raw,
        outdir=tmp_path / "a",
    )
    out_b = materialize_robustness_real(
        source_manifest_path=manifest_path,
        population_path=pop_path,
        scenario_manifest_path=scen_path,
        raw_dir=raw,
        outdir=tmp_path / "b",
    )
    assert out_a.read_bytes() == out_b.read_bytes()


def test_real_rejects_unknown_population_id(tmp_path) -> None:
    raw, manifest_path, pop_path, _scen_path = _setup_real(tmp_path)
    scenarios = _build_scenarios(population_manifest_id="unknown-population")
    scen_path = tmp_path / "scenarios-unknown.json"
    scenarios.save(scen_path)
    with pytest.raises(RobustnessError, match="population id divergence"):
        materialize_robustness_real(
            source_manifest_path=manifest_path,
            population_path=pop_path,
            scenario_manifest_path=scen_path,
            raw_dir=raw,
            outdir=tmp_path / "out",
        )


def test_real_rejects_revision_divergence(tmp_path) -> None:
    raw, manifest_path, pop_path, _scen_path = _setup_real(tmp_path)
    scenarios = _build_scenarios(source_manifest_revision="0" * 40)
    scen_path = tmp_path / "scenarios-rev.json"
    scenarios.save(scen_path)
    with pytest.raises(RobustnessError, match="revision divergence"):
        materialize_robustness_real(
            source_manifest_path=manifest_path,
            population_path=pop_path,
            scenario_manifest_path=scen_path,
            raw_dir=raw,
            outdir=tmp_path / "out",
        )


def test_real_rejects_canonical_mismatch(tmp_path) -> None:
    raw, manifest_path, pop_path, scen_path = _setup_real(tmp_path)
    from retail_demand_inventory.data.population_manifest import (
        load_population_manifest,
    )

    population = load_population_manifest(pop_path)
    tampered = replace(population, canonical_content_sha256="b" * 64)
    bad_path = tmp_path / "population-bad.json"
    tampered.save(bad_path)
    with pytest.raises(RobustnessError, match="canonical checksum mismatch"):
        materialize_robustness_real(
            source_manifest_path=manifest_path,
            population_path=bad_path,
            scenario_manifest_path=scen_path,
            raw_dir=raw,
            outdir=tmp_path / "out",
        )


def test_real_missing_raw_no_fallback(tmp_path) -> None:
    _raw, manifest_path, pop_path, scen_path = _setup_real(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises((ManifestError, RealLoaderError)):
        materialize_robustness_real(
            source_manifest_path=manifest_path,
            population_path=pop_path,
            scenario_manifest_path=scen_path,
            raw_dir=empty,
            outdir=tmp_path / "out",
        )


def test_real_rejects_divergent_population(tmp_path) -> None:
    raw, manifest_path, pop_path, scen_path = _setup_real(tmp_path)
    from retail_demand_inventory.data.population_manifest import (
        load_population_manifest,
    )

    population = load_population_manifest(pop_path)
    tampered = replace(
        population, selected_keys=population.selected_keys[:2] + ("9|999",)
    )
    tampered_path = tmp_path / "population-bad.json"
    tampered.save(tampered_path)
    with pytest.raises((RealLoaderError, ManifestError)):
        materialize_robustness_real(
            source_manifest_path=manifest_path,
            population_path=tampered_path,
            scenario_manifest_path=scen_path,
            raw_dir=raw,
            outdir=tmp_path / "out",
        )


def test_committed_robustness_report_consistent_with_v2(repo_root) -> None:
    report_path = repo_root / "data/evaluations" / ROBUSTNESS_REPORT_NAME
    if not report_path.exists():
        pytest.skip("committed robustness report not generated yet")
    robustness = load_json(report_path)["robustness"]
    assert robustness["scenario_count"] == 12
    assert robustness["scenario_ids"][0] == "baseline-v1"
    assert set(robustness["scenarios"][BASELINE_SCENARIO_ID]["keys"]) == set(
        load_json(
            repo_root / "data/evaluations" / "freshretailnet-real-expanded-report.json"
        )["per_sku"]
    )


def test_real_robustness_reproduces_committed_report(repo_root, tmp_path) -> None:
    raw = repo_root / "data" / "raw"
    if not (
        raw / "freshretailnet-08c1fab7f9257bc73679d415d65d644165d351d4-train.parquet"
    ).exists():
        pytest.skip("raw snapshot not available locally")
    committed_path = repo_root / "data/evaluations" / ROBUSTNESS_REPORT_NAME
    if not committed_path.exists():
        pytest.skip("committed robustness report not generated yet")
    outdir = tmp_path / "out"
    report_path = materialize_robustness_real(
        source_manifest_path=repo_root
        / "data"
        / "manifests"
        / "freshretailnet-real.json",
        population_path=repo_root
        / "data"
        / "manifests"
        / "freshretailnet-real-population-v2.json",
        scenario_manifest_path=repo_root
        / "data"
        / "manifests"
        / "robustness-scenarios-v1.0.0.json",
        raw_dir=raw,
        outdir=outdir,
    )
    committed = load_json(committed_path)
    regenerated = load_json(report_path)
    for data in (committed, regenerated):
        data["meta"]["repository_commit_sha"] = "<normalized>"
    assert json.dumps(regenerated, sort_keys=True) == json.dumps(
        committed, sort_keys=True
    )


def _fake_section(scenario_id, key, policy_id="rop_qty", constraint=True):
    return {
        "scenario_id": scenario_id,
        "key": key,
        "selection": {
            "constraint_satisfied": constraint,
            "fallback_reason": None if constraint else "no candidate reached target",
        },
        "recommendation": {
            "policy_id": policy_id,
            "policy_params": {"reorder_point": 10.0, "order_quantity": 20.0},
            "order_quantity": 20.0,
            "trigger_level": 10.0,
            "simulated_service_level": 0.92 if constraint else 0.80,
            "simulated_fill_rate": 0.95,
            "simulated_total_cost": 100.0,
            "simulated_stockout_units": 1.0,
            "simulated_stockout_events": 1,
            "simulated_avg_inventory": 12.0,
            "cost_components": {
                "total_holding_cost": 5.0,
                "total_stockout_cost": 2.0,
                "total_ordering_cost": 3.0,
                "total_cost": 100.0,
            },
        },
    }


def test_analysis_hidden_filtering_rejected() -> None:
    scenarios = {
        BASELINE_SCENARIO_ID: {
            "k1": _fake_section("baseline-v1", "k1"),
            "k2": _fake_section("baseline-v1", "k2"),
        },
        "holding-high": {
            "k1": _fake_section("holding-high", "k1"),
        },
    }
    with pytest.raises(ValueError, match="hidden filtering"):
        robustness_analysis(scenarios)


def test_analysis_missing_baseline_rejected() -> None:
    scenarios = {"holding-high": {"k1": _fake_section("holding-high", "k1")}}
    with pytest.raises(ValueError, match="baseline-v1"):
        robustness_analysis(scenarios)


def test_analysis_transitions_and_deltas() -> None:
    scenarios = {
        BASELINE_SCENARIO_ID: {
            "k1": _fake_section(
                "baseline-v1", "k1", policy_id="rop_qty", constraint=True
            ),
            "k2": _fake_section(
                "baseline-v1", "k2", policy_id="rop_qty", constraint=True
            ),
        },
        "holding-high": {
            "k1": _fake_section(
                "holding-high", "k1", policy_id="order_up_to", constraint=True
            ),
            "k2": _fake_section(
                "holding-high", "k2", policy_id="rop_qty", constraint=False
            ),
        },
    }
    analysis = robustness_analysis(scenarios)
    assert analysis["baseline_scenario_id"] == "baseline-v1"
    comparison = analysis["per_key_baseline_comparison"]["holding-high"]
    assert comparison["k1"]["policy_retained"] is False
    assert comparison["k1"]["policy_changed"] is True
    assert comparison["k1"]["baseline_policy_id"] == "rop_qty"
    assert comparison["k1"]["scenario_policy_id"] == "order_up_to"
    assert comparison["k2"]["policy_retained"] is True
    assert comparison["k2"]["feasibility_regression"] is True
    assert comparison["k2"]["constraint_satisfied_scenario"] is False
    assert comparison["k2"]["fallback_reason_scenario"] is not None
    assert comparison["k1"]["order_quantity"]["relative_delta"] == 0.0
    assert comparison["k1"]["service_level"]["delta"] == pytest.approx(0.92 - 0.92)

    matrix = analysis["transition_matrix"]["holding-high"]
    assert matrix["rop_qty"] == {"order_up_to": 1, "rop_qty": 1}
    agg = analysis["aggregate"]["per_scenario"]["holding-high"]
    assert agg["policy_retained_count"] == 1
    assert agg["policy_changed_count"] == 1
    assert agg["infeasible_count"] == 1
    assert agg["fallback_count"] == 1
    assert agg["feasibility_regression_count"] == 1
    quantiles = analysis["aggregate"]["per_scenario"]["holding-high"]["summary_stats"][
        "quantiles"
    ]
    for key in ("order_quantity_relative_delta", "service_level_delta"):
        assert set(quantiles[key]) == {"p25", "p50", "p75", "p95"}
    tradeoffs = analysis["observed_tradeoffs"]["per_scenario"]["holding-high"]
    assert "cost_vs_service" in tradeoffs
    assert "inventory_vs_fill" in tradeoffs
    assert "stockouts_vs_holding" in tradeoffs
    overall = analysis["aggregate"]["overall"]
    assert overall["scenario_key_pairs"] == 2
    assert overall["policy_retained_count"] == 1
    assert overall["policy_changed_pct"] == 50.0


def test_notice_label_constants() -> None:
    assert "not observed retailer costs" in ROBUSTNESS_NOTICE.lower()
