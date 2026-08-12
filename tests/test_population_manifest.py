from __future__ import annotations

import json

import pytest
from real_helpers import make_manifest, write_expanded_raw

from retail_demand_inventory.data import (
    PER_STORE_CAP_KEYS,
    REQUIRED_HISTORY_DAYS,
    TARGET_POPULATION_KEYS,
    ManifestError,
)
from retail_demand_inventory.data.population_manifest import (
    POPULATION_V2_ID,
    PopulationManifest,
    _keys_checksum,
    build_population_manifest,
    load_population_manifest,
)
from retail_demand_inventory.data.real_loader import (
    canonical_serialize,
    select_expanded_population,
)


def _setup(tmp_path, *, stores=3, products=3, per_store_cap=2, target_keys=4):
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
    return raw, manifest_path, population


def test_build_population_manifest_roundtrip(tmp_path) -> None:
    _raw, _manifest_path, population = _setup(tmp_path)
    assert population.population_id == POPULATION_V2_ID
    assert population.manifest_version == "1"
    assert population.source_manifest_id == "freshretailnet-real.json"
    assert population.per_store_cap == 2
    assert population.target_keys == 4
    assert population.selected_key_count == len(population.selected_keys) == 4
    assert population.selected_keys == ("0|0", "0|1", "1|0", "1|1")
    assert population.pinned_revision
    assert population.raw_checksums["train"]["sha256"]
    assert (
        population.canonical_content_sha256
        and len(population.canonical_content_sha256) == 64
    )
    assert population.seed is None
    assert population.train_metadata_only is True
    assert population.train_eval_separation["date_overlap"] is False
    population.require_valid()

    out = tmp_path / "pop.json"
    population.save(out)
    loaded = load_population_manifest(out)
    assert loaded == population
    assert loaded.to_dict() == population.to_dict()


def test_build_population_manifest_matches_selection(tmp_path) -> None:
    raw, _manifest_path, population = _setup(
        tmp_path, stores=12, products=12, per_store_cap=10, target_keys=100
    )
    selection = select_expanded_population(
        raw / "train.parquet",
        raw / "eval.parquet",
        required_history_days=REQUIRED_HISTORY_DAYS,
        per_store_cap=PER_STORE_CAP_KEYS,
        target_keys=TARGET_POPULATION_KEYS,
        population_id=POPULATION_V2_ID,
    )
    assert population.selected_keys == selection.selected_keys
    assert population.selected_key_count == selection.selected_key_count
    assert population.excluded_key_count == selection.excluded_key_count
    assert population.eligible_key_count == selection.eligible_key_count
    assert population.store_count == len(selection.store_key_counts)
    assert population.product_count == selection.product_key_count
    assert population.train_row_count == selection.train_row_count
    assert population.eval_row_count == selection.eval_row_count
    assert population.source_row_count == selection.source_row_count


def test_population_manifest_key_checksums(tmp_path) -> None:
    raw, _manifest_path, population = _setup(tmp_path)
    from retail_demand_inventory.data.real_loader import analyze_population

    analysis = analyze_population(
        raw / "train.parquet",
        raw / "eval.parquet",
        required_history_days=REQUIRED_HISTORY_DAYS,
    )
    excluded = [k for k in analysis.all_keys if k not in set(population.selected_keys)]
    assert population.selection_checksums["selected_keys_sha256"] == _keys_checksum(
        population.selected_keys
    )
    assert population.selection_checksums["excluded_keys_sha256"] == _keys_checksum(
        excluded
    )


def test_population_manifest_canonical_checksum_is_canonical(tmp_path) -> None:
    raw, manifest_path, population = _setup(tmp_path)
    from retail_demand_inventory.data.real_manifest import load_real_manifest

    source = load_real_manifest(manifest_path)
    from retail_demand_inventory.data.real_loader import load_real_snapshot

    result = load_real_snapshot(
        source,
        raw,
        required_history_days=REQUIRED_HISTORY_DAYS,
        population=population,
    )
    assert result.canonical_sha256 == population.canonical_content_sha256
    payload = canonical_serialize(result.table)
    assert payload.startswith(b'[{"')
    assert b'"sku"' in payload and b'"demand_units"' in payload
    assert b'"stockout_flag"' in payload


def test_population_manifest_validation_rejects_tampering(tmp_path) -> None:
    _raw, _manifest_path, population = _setup(tmp_path)
    payload = population.to_dict()
    payload["selected_key_count"] = 99
    problems = PopulationManifest.from_dict(payload).validate()
    assert any("selected_key_count" in p for p in problems)

    payload = population.to_dict()
    payload["seed"] = 1
    problems = PopulationManifest.from_dict(payload).validate()
    assert any("seed" in p for p in problems)

    payload = population.to_dict()
    payload["train_metadata_only"] = False
    problems = PopulationManifest.from_dict(payload).validate()
    assert any("train_metadata_only" in p for p in problems)


def test_population_manifest_rejects_missing_source(tmp_path) -> None:
    with pytest.raises((ManifestError, OSError)):
        build_population_manifest(
            source_manifest_path=tmp_path / "missing.json",
            raw_dir=tmp_path,
        )


def test_load_population_manifest_requires_valid(tmp_path) -> None:
    _raw, _manifest_path, population = _setup(tmp_path)
    out = tmp_path / "pop.json"
    population.save(out)
    payload = json.loads(out.read_text())
    payload["per_store_cap"] = 0
    out.write_text(json.dumps(payload))
    with pytest.raises(ManifestError):
        load_population_manifest(out)
