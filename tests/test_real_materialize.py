"""Real-mode materializer: gates, no-fallback, provenance, determinism."""

from __future__ import annotations

import json

import pytest
from real_helpers import daily_rows, make_manifest, write_split

from retail_demand_inventory.data import (
    REAL_GATES,
    ManifestError,
)
from retail_demand_inventory.evaluation.materialize import (
    REAL_LABEL,
    REAL_REPORT_NAME,
    materialize,
    materialize_real,
)
from retail_demand_inventory.evaluation.reports import ExperimentReport, load_json


def _setup(tmp_path, *, train_days=70, eval_days=7, keys=((1, 1), (1, 2)), gates=None):
    raw = tmp_path / "raw"
    raw.mkdir()
    write_split(raw, "train", daily_rows(keys, "2024-01-01", train_days))
    write_split(raw, "eval", daily_rows(keys, "2024-03-11", eval_days))
    manifest = make_manifest(
        raw, train_name="train.parquet", eval_name="eval.parquet", gates=gates
    )
    manifest_path = tmp_path / "manifest.json"
    manifest.save(manifest_path)
    return manifest, manifest_path, raw


def _set_canonical(manifest, manifest_path, raw):
    from dataclasses import replace

    from retail_demand_inventory.data.real_loader import (
        MAX_POPULATION_KEYS,
        REQUIRED_HISTORY_DAYS,
        load_real_snapshot,
    )

    result = load_real_snapshot(
        manifest,
        raw,
        required_history_days=REQUIRED_HISTORY_DAYS,
        max_keys=MAX_POPULATION_KEYS,
    )
    updated = replace(manifest, canonical_content_sha256=result.canonical_sha256)
    updated.save(manifest_path)
    return updated


def test_fixture_mode_offline_and_clearly_labeled(tmp_path, repo_root) -> None:
    fixture = repo_root / "data" / "fixtures" / "freshretailnet_style_synthetic.csv"
    manifest = repo_root / "data" / "manifests" / "fixture_synthetic.json"
    outdir = tmp_path / "out"
    report_path = materialize(
        fixture_path=fixture, manifest_path=manifest, outdir=outdir
    )
    data = load_json(report_path)
    assert data["dataset"]["source_label"] == "synthetic-fixture"
    assert "synthetic" in data["dataset"]["name"]


def test_real_mode_missing_raw_no_fallback(tmp_path) -> None:
    manifest, manifest_path, raw = _setup(tmp_path)
    manifest = _set_canonical(manifest, manifest_path, raw)
    empty_raw = tmp_path / "empty-raw"
    empty_raw.mkdir()
    outdir = tmp_path / "out"
    with pytest.raises(ManifestError, match="not found"):
        materialize_real(manifest_path=manifest_path, raw_dir=empty_raw, outdir=outdir)
    assert not (outdir / REAL_REPORT_NAME).exists()
    assert not (outdir / "experiment_report.json").exists()


def test_real_mode_manifest_checked_first(tmp_path) -> None:
    _manifest, manifest_path, raw = _setup(tmp_path, gates={"schema_verified": False})
    outdir = tmp_path / "out"
    with pytest.raises(ManifestError, match="schema_verified"):
        materialize_real(manifest_path=manifest_path, raw_dir=raw, outdir=outdir)
    assert not (outdir / REAL_REPORT_NAME).exists()


def test_real_mode_raw_checksum_mismatch(tmp_path) -> None:
    manifest, manifest_path, raw = _setup(tmp_path)
    manifest = _set_canonical(manifest, manifest_path, raw)
    with (raw / "train.parquet").open("ab") as handle:
        handle.write(b"corruption")
    outdir = tmp_path / "out"
    with pytest.raises(ManifestError, match="sha256"):
        materialize_real(manifest_path=manifest_path, raw_dir=raw, outdir=outdir)


def test_real_mode_canonical_checksum_mismatch(tmp_path) -> None:
    manifest, manifest_path, raw = _setup(tmp_path)
    from dataclasses import replace

    wrong = replace(manifest, canonical_content_sha256="b" * 64)
    wrong.save(manifest_path)
    outdir = tmp_path / "out"
    with pytest.raises(RuntimeError, match="canonical checksum mismatch"):
        materialize_real(manifest_path=manifest_path, raw_dir=raw, outdir=outdir)


def test_real_mode_report_data_source_and_provenance(tmp_path) -> None:
    manifest, manifest_path, raw = _setup(tmp_path)
    manifest = _set_canonical(manifest, manifest_path, raw)
    outdir = tmp_path / "out"
    report_path = materialize_real(
        manifest_path=manifest_path, raw_dir=raw, outdir=outdir
    )
    assert report_path.name == REAL_REPORT_NAME
    report = ExperimentReport.load(report_path)
    data = report.to_dict()
    assert data["meta"]["source_mode"] == "real-freshretailnet-bounded"
    assert data["meta"]["evaluation_label"] == REAL_LABEL
    assert data["dataset"]["source_label"] == "real-freshretailnet-bounded"
    assert data["dataset"]["evaluation_label"] == REAL_LABEL
    assert data["dataset"]["population"]["selected_key_count"] == 2
    assert set(REAL_GATES) <= set(data["dataset"]["gates"])
    assert all(data["dataset"]["gates"].values())
    real = data["real"]
    assert real["pinned_revision"] == manifest.pinned_revision
    assert real["canonical_content_sha256"] == manifest.canonical_content_sha256
    assert set(real["raw_checksums"]) == {"train", "eval"}
    assert real["population"]["selected_keys"]
    assert real["protocol_version"]
    assert real["split_config"]["horizon"] == 7
    assert real["stockout_semantics"]["derivation_version"] == "1"
    assert real["repository_commit_sha"]
    assert "not the eventual commit" in real["repository_commit_sha_note"]
    assert "Deterministic bounded evaluation" in real["scope_note"]
    for section in data["per_sku"].values():
        evidence = section["recommendation"]["evidence"]
        assert evidence["source_label"] == "real-freshretailnet-bounded"
        assert (
            evidence["dataset_manifest"]["source_label"]
            == "real-freshretailnet-bounded"
        )


def test_real_mode_never_silently_relabels(tmp_path) -> None:
    manifest, manifest_path, raw = _setup(tmp_path)
    _set_canonical(manifest, manifest_path, raw)
    report_path = materialize_real(
        manifest_path=manifest_path, raw_dir=raw, outdir=tmp_path / "o"
    )
    data = json.loads(report_path.read_text())
    assert "synthetic" not in data["dataset"]["source_label"]
    assert data["dataset"]["source_label"] == "real-freshretailnet-bounded"


def test_real_mode_deterministic_reports(tmp_path) -> None:
    manifest, manifest_path, raw = _setup(tmp_path)
    _set_canonical(manifest, manifest_path, raw)
    out_a = materialize_real(
        manifest_path=manifest_path, raw_dir=raw, outdir=tmp_path / "a"
    )
    out_b = materialize_real(
        manifest_path=manifest_path, raw_dir=raw, outdir=tmp_path / "b"
    )
    assert out_a.read_bytes() == out_b.read_bytes()


def test_real_population_never_full_snapshot(tmp_path) -> None:
    keys = [(0, i) for i in range(12)]
    manifest, manifest_path, raw = _setup(tmp_path, keys=keys)
    _set_canonical(manifest, manifest_path, raw)
    report_path = materialize_real(
        manifest_path=manifest_path, raw_dir=raw, outdir=tmp_path / "o"
    )
    data = load_json(report_path)
    population = data["dataset"]["population"]
    assert "Deterministic bounded evaluation" in population["rule"]
    assert population["selected_key_count"] < population["candidate_key_count"]
    assert population["excluded_key_count"] > 0
    assert "full snapshot" not in data["meta"]["evaluation_label"]
