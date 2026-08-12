from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from real_helpers import daily_rows, make_manifest, write_expanded_raw, write_split

from retail_demand_inventory.data import (
    PER_STORE_CAP_KEYS,
    REQUIRED_HISTORY_DAYS,
    TARGET_POPULATION_KEYS,
    RealLoaderError,
    analyze_population,
    select_expanded_population,
    verify_population_selection,
)
from retail_demand_inventory.data.population_manifest import (
    POPULATION_V2_ID,
    build_population_manifest,
)


def _expanded(raw: Path, *, per_store_cap=10, target_keys=100):
    return select_expanded_population(
        raw / "train.parquet",
        raw / "eval.parquet",
        required_history_days=REQUIRED_HISTORY_DAYS,
        per_store_cap=per_store_cap,
        target_keys=target_keys,
        population_id=POPULATION_V2_ID,
    )


def test_expanded_selection_cap_and_target(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    write_expanded_raw(raw, stores=12, products=12)
    selection = _expanded(raw)
    assert selection.selected_key_count == 100
    assert selection.selected_key_count == TARGET_POPULATION_KEYS
    assert selection.per_store_cap == PER_STORE_CAP_KEYS
    assert selection.candidate_key_count == 144
    assert selection.qualifying_key_count == 144
    assert selection.eligible_key_count == 144
    assert selection.excluded_key_count == 44
    assert len(selection.store_key_counts) == 10
    assert selection.store_key_counts == {str(s): 10 for s in range(10)}
    assert set(selection.store_key_counts) == {
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
    assert selection.product_key_count == 10
    assert selection.selected_row_count == 100 * 97
    assert selection.train_row_count == 100 * 90
    assert selection.eval_row_count == 100 * 7
    assert selection.exclusion_reasons == {
        "beyond_store_cap": 24,
        "beyond_target": 20,
    }
    assert selection.date_range == (date(2024, 1, 1), date(2024, 4, 6))
    assert "store-diversity cap of at most 10 keys per store" in selection.rule
    assert "No random sampling" in selection.rule
    assert "no final metrics" in selection.rule


def test_expanded_selection_preserves_v1_keys(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    write_expanded_raw(raw, stores=3, products=12)
    selection = _expanded(raw, per_store_cap=10, target_keys=20)
    v1 = ("0|0", "0|1", "0|2", "0|3", "0|4", "0|5", "0|6", "0|7", "0|8", "0|9")
    assert all(key in selection.selected_keys for key in v1)
    assert selection.selected_keys[:10] == v1
    assert selection.selected_keys[10:20] == (
        "1|0",
        "1|1",
        "1|2",
        "1|3",
        "1|4",
        "1|5",
        "1|6",
        "1|7",
        "1|8",
        "1|9",
    )


def test_expanded_exclusion_reasons(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    write_expanded_raw(raw, stores=12, products=12)
    eval_only = [(10, 500)]
    write_split(
        raw,
        "eval",
        daily_rows(eval_only, "2024-04-01", 7),
    )
    short = daily_rows([(10, 600)], "2024-01-01", 40)
    full_train = daily_rows(
        [(s, p) for s in range(12) for p in range(12)], "2024-01-01", 90
    )
    write_split(raw, "train", full_train + short)
    selection = _expanded(raw)
    assert selection.exclusion_reasons["not_observed_in_train"] == 1
    assert selection.exclusion_reasons["below_required_history"] == 1
    assert selection.exclusion_reasons["beyond_store_cap"] == 24
    assert selection.exclusion_reasons["beyond_target"] == 20
    assert sum(selection.exclusion_reasons.values()) == selection.excluded_key_count
    assert selection.selected_key_count == 100


def test_expanded_selection_never_uses_outcomes(tmp_path) -> None:
    raw_a = tmp_path / "a"
    raw_b = tmp_path / "b"
    raw_a.mkdir()
    raw_b.mkdir()
    write_expanded_raw(raw_a, stores=3, products=4, sale=1.0)
    write_expanded_raw(raw_b, stores=3, products=4, sale=99.0)
    sel_a = _expanded(raw_a, per_store_cap=2, target_keys=4)
    sel_b = _expanded(raw_b, per_store_cap=2, target_keys=4)
    assert sel_a.selected_keys == sel_b.selected_keys
    assert sel_a.exclusion_reasons == sel_b.exclusion_reasons
    assert sel_a.date_range == sel_b.date_range


def test_expanded_selection_not_observed_in_train_ineligible(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    keys = [(s, p) for s in range(2) for p in range(3)]
    write_split(raw, "train", daily_rows(keys, "2024-01-01", 90))
    eval_only = [(7, 900)]
    write_split(raw, "eval", daily_rows(keys + eval_only, "2024-04-01", 7))
    selection = _expanded(raw, per_store_cap=1, target_keys=2)
    assert (7, 900) not in selection.selected_keys
    assert "7|900" not in selection.selected_keys
    assert selection.exclusion_reasons["not_observed_in_train"] == 1


def test_expanded_analysis_shared_with_v1(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    write_expanded_raw(raw, stores=2, products=3)
    analysis = analyze_population(
        raw / "train.parquet",
        raw / "eval.parquet",
        required_history_days=REQUIRED_HISTORY_DAYS,
    )
    assert len(analysis.all_keys) == 6
    assert analysis.source_row_count == 6 * 97
    assert len(analysis.qualifying) == 6
    assert analysis.modal_span == (date(2024, 1, 1), date(2024, 4, 6))


def test_verify_population_selection_passes_for_generated(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    write_expanded_raw(raw, stores=3, products=3)
    manifest = make_manifest(raw, train_name="train.parquet", eval_name="eval.parquet")
    manifest_path = tmp_path / "manifest.json"
    manifest.save(manifest_path)
    population = build_population_manifest(
        source_manifest_path=manifest_path,
        raw_dir=raw,
        per_store_cap=2,
        target_keys=4,
    )
    selection = verify_population_selection(
        manifest=manifest,
        population=population,
        train_path=raw / "train.parquet",
        eval_path=raw / "eval.parquet",
        required_history_days=REQUIRED_HISTORY_DAYS,
    )
    assert selection.selected_keys == population.selected_keys
    assert selection.selected_key_count == 4
    assert len(selection.store_key_counts) == 2


def test_verify_population_selection_rejects_divergent_keys(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    write_expanded_raw(raw, stores=3, products=3)
    manifest = make_manifest(raw, train_name="train.parquet", eval_name="eval.parquet")
    manifest_path = tmp_path / "manifest.json"
    manifest.save(manifest_path)
    population = build_population_manifest(
        source_manifest_path=manifest_path,
        raw_dir=raw,
        per_store_cap=2,
        target_keys=4,
    )
    from dataclasses import replace

    bad_keys = population.selected_keys[:3] + ("9|999",)
    tampered = replace(population, selected_keys=bad_keys)
    with pytest.raises(RealLoaderError, match="diverge"):
        verify_population_selection(
            manifest=manifest,
            population=tampered,
            train_path=raw / "train.parquet",
            eval_path=raw / "eval.parquet",
            required_history_days=REQUIRED_HISTORY_DAYS,
        )


def test_verify_population_selection_rejects_revision_mismatch(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    write_expanded_raw(raw, stores=3, products=3)
    manifest = make_manifest(raw, train_name="train.parquet", eval_name="eval.parquet")
    manifest_path = tmp_path / "manifest.json"
    manifest.save(manifest_path)
    population = build_population_manifest(
        source_manifest_path=manifest_path,
        raw_dir=raw,
        per_store_cap=2,
        target_keys=4,
    )
    from dataclasses import replace

    tampered = replace(population, pinned_revision="a" * 40)
    with pytest.raises(RealLoaderError, match="revision divergence"):
        verify_population_selection(
            manifest=manifest,
            population=tampered,
            train_path=raw / "train.parquet",
            eval_path=raw / "eval.parquet",
            required_history_days=REQUIRED_HISTORY_DAYS,
        )


def test_verify_population_selection_rejects_checksum_mismatch(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    write_expanded_raw(raw, stores=3, products=3)
    manifest = make_manifest(raw, train_name="train.parquet", eval_name="eval.parquet")
    manifest_path = tmp_path / "manifest.json"
    manifest.save(manifest_path)
    population = build_population_manifest(
        source_manifest_path=manifest_path,
        raw_dir=raw,
        per_store_cap=2,
        target_keys=4,
    )
    from dataclasses import replace

    checksums = dict(population.raw_checksums)
    checksums["train"] = {"local_name": "train.parquet", "size": 1, "sha256": "0" * 64}
    tampered = replace(population, raw_checksums=checksums)
    with pytest.raises(RealLoaderError, match="diverged"):
        verify_population_selection(
            manifest=manifest,
            population=tampered,
            train_path=raw / "train.parquet",
            eval_path=raw / "eval.parquet",
            required_history_days=REQUIRED_HISTORY_DAYS,
        )
