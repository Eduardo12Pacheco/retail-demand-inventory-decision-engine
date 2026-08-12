"""Population profile: deterministic reproducibility, coverage counts, dry-run
behavior, and population-manifest validation reporting."""

from __future__ import annotations

import json

from real_helpers import make_manifest, write_expanded_raw

from retail_demand_inventory.data.population_manifest import (
    POPULATION_V2_ID,
    build_population_manifest,
)
from retail_demand_inventory.data.population_profile import build_population_profile


def _setup(tmp_path, *, stores=12, products=12):
    raw = tmp_path / "raw"
    raw.mkdir()
    write_expanded_raw(raw, stores=stores, products=products)
    manifest = make_manifest(raw, train_name="train.parquet", eval_name="eval.parquet")
    manifest_path = tmp_path / "manifest.json"
    manifest.save(manifest_path)
    return raw, manifest_path


def test_profile_reproducible_byte_identical(tmp_path) -> None:
    raw, manifest_path = _setup(tmp_path)
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"
    build_population_profile(
        manifest_path=manifest_path,
        raw_dir=raw,
        report_path=out_a,
        population_manifest_path=None,
    )
    build_population_profile(
        manifest_path=manifest_path,
        raw_dir=raw,
        report_path=out_b,
        population_manifest_path=None,
    )
    assert out_a.read_bytes() == out_b.read_bytes()


def test_profile_counts_and_coverage(tmp_path) -> None:
    raw, manifest_path = _setup(tmp_path, stores=12, products=12)
    out = tmp_path / "profile.json"
    build_population_profile(manifest_path=manifest_path, raw_dir=raw, report_path=out)
    data = json.loads(out.read_text())
    assert data["population_id"] == POPULATION_V2_ID
    assert data["mode"] == "dry-run"
    assert data["counts"]["selected_key_count"] == 100
    assert data["counts"]["candidate_key_count"] == 144
    assert data["counts"]["store_count"] == 10
    assert data["counts"]["product_count"] == 10
    assert data["counts"]["train_row_count"] == 100 * 90
    assert data["counts"]["eval_row_count"] == 100 * 7
    assert data["coverage"]["selected_of_source_keys"]["fraction"] == round(
        100 / 144, 6
    )
    assert set(data["per_store_keys"]) == {
        "0",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
    }
    assert all(v == 10 for v in data["per_store_keys"].values())
    assert data["train_eval_separation"]["date_overlap"] is False
    assert data["selection_rule"]["target_keys"] == 100
    assert data["selection_rule"]["per_store_cap"] == 10
    assert data["history_rule"]["required_history_days"] == 63
    assert data["selection_checksums"]["selected_keys_sha256"]
    assert data["resource_profile"]["source"] == "documented-constant"
    assert data["budget"]["within_budget"] is True


def test_profile_is_dry_run_no_metrics(tmp_path) -> None:
    raw, manifest_path = _setup(tmp_path)
    out = tmp_path / "profile.json"
    build_population_profile(manifest_path=manifest_path, raw_dir=raw, report_path=out)
    data = json.loads(out.read_text())
    assert data["non_final_metrics"]["uses_outcomes"] is False
    for forbidden in ("per_sku", "metrics", "forecast", "policy_selection"):
        assert forbidden not in data, f"profile must not contain {forbidden!r}"


def test_profile_validates_population_manifest(tmp_path) -> None:
    raw, manifest_path = _setup(tmp_path)
    population = build_population_manifest(
        source_manifest_path=manifest_path, raw_dir=raw, per_store_cap=2, target_keys=4
    )
    pop_path = tmp_path / "population.json"
    population.save(pop_path)
    out = tmp_path / "profile.json"
    build_population_profile(
        manifest_path=manifest_path,
        raw_dir=raw,
        report_path=out,
        population_manifest_path=pop_path,
    )
    data = json.loads(out.read_text())
    assert data["population_manifest"]["present"] is True
    assert data["population_manifest"]["validated"] is True
    assert (
        data["population_manifest"]["canonical_content_sha256"]
        == population.canonical_content_sha256
    )
    assert (
        data["population_manifest"]["selection_checksums"]
        == population.selection_checksums
    )


def test_profile_reports_invalid_population_manifest(tmp_path) -> None:
    raw, manifest_path = _setup(tmp_path)
    population = build_population_manifest(
        source_manifest_path=manifest_path, raw_dir=raw, per_store_cap=2, target_keys=4
    )
    from dataclasses import replace

    tampered = replace(population, selected_keys=("0|0", "0|1", "0|2", "9|999"))
    pop_path = tmp_path / "population.json"
    tampered.save(pop_path)
    out = tmp_path / "profile.json"
    build_population_profile(
        manifest_path=manifest_path,
        raw_dir=raw,
        report_path=out,
        population_manifest_path=pop_path,
    )
    data = json.loads(out.read_text())
    assert data["population_manifest"]["validated"] is False
    assert "diverge" in data["population_manifest"]["validation_error"]
