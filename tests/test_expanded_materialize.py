"""Expanded (v2) real materialization and v1 baseline regression.

Offline by default (tiny fixtures). Two tests use the locally acquired raw
snapshot and are skipped when `data/raw/` is absent; they are the only tests
that touch real bytes.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from real_helpers import make_manifest, write_expanded_raw

from retail_demand_inventory.data import (
    ManifestError,
    RealLoaderError,
)
from retail_demand_inventory.data.population_manifest import (
    POPULATION_V2_ID,
    build_population_manifest,
)
from retail_demand_inventory.evaluation.materialize import (
    REAL_EXPANDED_LABEL,
    REAL_EXPANDED_REPORT_NAME,
    REAL_REPORT_NAME,
    materialize_real,
    materialize_real_expanded,
)
from retail_demand_inventory.evaluation.reports import load_json

V1_REPORT_SHA256 = "552aa5edbefcf45ff7416b237c0f16f60b38408f5fe921cffe610076bdad007a"


def _setup_expanded(tmp_path, *, stores=3, products=3, per_store_cap=1, target_keys=3):
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
    return raw, manifest_path, pop_path


# --- v1 baseline regression ------------------------------------------------


def test_committed_v1_real_report_hash_pinned(repo_root) -> None:
    report = repo_root / "data/evaluations" / "freshretailnet-real-report.json"
    assert report.exists()
    digest = hashlib.sha256(report.read_bytes()).hexdigest()
    assert digest == V1_REPORT_SHA256


def test_v1_real_report_unchanged_when_materialized_to_temp(
    repo_root, tmp_path
) -> None:
    raw = repo_root / "data" / "raw"
    if not (
        raw / "freshretailnet-08c1fab7f9257bc73679d415d65d644165d351d4-train.parquet"
    ).exists():
        pytest.skip("raw snapshot not available locally")
    committed_path = repo_root / "data/evaluations" / "freshretailnet-real-report.json"
    outdir = tmp_path / "out"
    report_path = materialize_real(
        manifest_path=repo_root / "data/manifests" / "freshretailnet-real.json",
        raw_dir=raw,
        outdir=outdir,
    )
    committed = load_json(committed_path)
    regenerated = load_json(report_path)
    # The only field that varies across runs is the documented informational
    # git HEAD recorded at generation time ("not the eventual commit SHA");
    # every other field must be byte-identical.
    for data in (committed, regenerated):
        data["real"]["repository_commit_sha"] = "<normalized>"
    assert json.dumps(regenerated, sort_keys=True) == json.dumps(
        committed, sort_keys=True
    )


# --- expanded (v2) materialization -----------------------------------------


def test_expanded_materialize_writes_distinct_report(tmp_path) -> None:
    raw, manifest_path, pop_path = _setup_expanded(tmp_path)
    outdir = tmp_path / "out"
    report_path = materialize_real_expanded(
        manifest_path=manifest_path,
        population_path=pop_path,
        raw_dir=raw,
        outdir=outdir,
    )
    assert report_path.name == REAL_EXPANDED_REPORT_NAME
    assert not (outdir / REAL_REPORT_NAME).exists()
    assert not (outdir / "experiment_report.json").exists()


def test_expanded_materialize_uses_population(tmp_path) -> None:
    raw, manifest_path, pop_path = _setup_expanded(tmp_path)
    report = load_json(
        materialize_real_expanded(
            manifest_path=manifest_path,
            population_path=pop_path,
            raw_dir=raw,
            outdir=tmp_path / "out",
        )
    )
    assert report["meta"]["source_mode"] == "real-freshretailnet-expanded"
    assert report["meta"]["evaluation_label"] == REAL_EXPANDED_LABEL
    assert report["dataset"]["source_label"] == "real-freshretailnet-expanded"
    expanded = report["expanded"]
    assert expanded["population_id"] == POPULATION_V2_ID
    assert expanded["population"]["selected_key_count"] == 3
    assert len(report["overall"]["skus"]) == 3
    assert expanded["dimensions"]["key_count"] == 3
    assert expanded["dimensions"]["store_count"] == 3
    assert expanded["dimensions"]["train_row_count"] == 3 * 90
    assert expanded["dimensions"]["eval_row_count"] == 3 * 7
    assert expanded["canonical_content_sha256"]
    assert expanded["pinned_revision"]
    assert expanded["stockout_derivation_version"] == "1"
    assert expanded["implementation_code_revision"]
    assert expanded["report_generation_revision"]
    assert expanded["train_eval_separation"]["date_overlap"] is False


def test_expanded_materialize_required_aggregate_fields(tmp_path) -> None:
    raw, manifest_path, pop_path = _setup_expanded(tmp_path)
    report = load_json(
        materialize_real_expanded(
            manifest_path=manifest_path,
            population_path=pop_path,
            raw_dir=raw,
            outdir=tmp_path / "out",
        )
    )
    agg = report["expanded"]["aggregates"]
    assert agg["key_count"] == 3

    final = agg["final_test_forecast"]
    for metric in ("mae", "rmse", "wmape", "mase"):
        assert metric in final["micro_pooled"]
        assert metric in final["macro_mean"]
        per_key = final["per_key"][metric]
        for key in ("mean", "median", "p25", "p75", "p95", "count", "undefined"):
            assert key in per_key

    for model in ("naive", "moving_average", "ses", "hist_gradient_boosting"):
        assert model in agg["backtest"]

    assert agg["per_fold"] and agg["per_fold"][0]["fold_index"] == 0
    for fold in agg["per_fold"]:
        assert fold["models"]

    policy = agg["policy"]
    for name in (
        "service_level",
        "fill_rate",
        "stockout_units",
        "stockout_events",
        "total_cost",
        "avg_inventory",
    ):
        assert name in policy["selected_metrics"]
        assert policy["selected_metrics"][name]["median"] is not None
    assert "keys_meeting_target" in policy["constraint_satisfaction"]
    assert "infeasible_keys" in policy["fallback"]
    assert "fallback_reason_counts" in policy["fallback"]
    assert "total_cost_sum" in policy["micro"]

    failed = agg["failed_undefined"]
    assert failed["final_test_defined_metric_values"] >= 0
    assert failed["final_test_undefined_metric_values"] >= 0

    profile = report["expanded"]["resource_profile"]
    assert profile["source"] == "documented-constant"
    assert profile["materialization_estimated_runtime_seconds"] > 0
    assert profile["estimated_peak_memory_bytes"] > 0
    assert profile["estimated_report_bytes"] > 0

    assert any("bounded" in limitation for limitation in report["limitations"])


def test_expanded_materialize_stockout_and_revision_preserved(tmp_path) -> None:
    raw, manifest_path, pop_path = _setup_expanded(tmp_path)
    manifest = make_manifest(raw, train_name="train.parquet", eval_name="eval.parquet")
    report = load_json(
        materialize_real_expanded(
            manifest_path=manifest_path,
            population_path=pop_path,
            raw_dir=raw,
            outdir=tmp_path / "out",
        )
    )
    semantics = report["expanded"]["stockout_semantics"]
    assert semantics["derivation_version"] == manifest.stockout_derivation_version
    assert semantics["rule"] == manifest.stockout_derivation_rule
    assert report["expanded"]["pinned_revision"] == manifest.pinned_revision


def test_expanded_materialize_deterministic(tmp_path) -> None:
    raw, manifest_path, pop_path = _setup_expanded(tmp_path)
    out_a = materialize_real_expanded(
        manifest_path=manifest_path,
        population_path=pop_path,
        raw_dir=raw,
        outdir=tmp_path / "a",
    )
    out_b = materialize_real_expanded(
        manifest_path=manifest_path,
        population_path=pop_path,
        raw_dir=raw,
        outdir=tmp_path / "b",
    )
    assert out_a.read_bytes() == out_b.read_bytes()


def test_expanded_materialize_rejects_canonical_mismatch(tmp_path) -> None:
    raw, manifest_path, pop_path = _setup_expanded(tmp_path)
    from dataclasses import replace

    from retail_demand_inventory.data.population_manifest import (
        load_population_manifest,
    )

    population = load_population_manifest(pop_path)
    tampered = replace(population, canonical_content_sha256="b" * 64)
    bad_path = tmp_path / "population-bad.json"
    tampered.save(bad_path)
    with pytest.raises(RuntimeError, match="canonical checksum mismatch"):
        materialize_real_expanded(
            manifest_path=manifest_path,
            population_path=bad_path,
            raw_dir=raw,
            outdir=tmp_path / "out",
        )


def test_expanded_materialize_missing_raw_no_fallback(tmp_path) -> None:
    _raw, manifest_path, pop_path = _setup_expanded(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ManifestError, match="not found"):
        materialize_real_expanded(
            manifest_path=manifest_path,
            population_path=pop_path,
            raw_dir=empty,
            outdir=tmp_path / "out",
        )


def test_expanded_materialize_rejects_divergent_population(tmp_path) -> None:
    raw, manifest_path, pop_path = _setup_expanded(tmp_path)
    from dataclasses import replace

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
        materialize_real_expanded(
            manifest_path=manifest_path,
            population_path=tampered_path,
            raw_dir=raw,
            outdir=tmp_path / "out",
        )
