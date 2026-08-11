"""Real snapshot manifest: metadata, gates, checksum rules, revisions."""

from __future__ import annotations

import json

import pytest
from real_helpers import REVISION, make_manifest

from retail_demand_inventory.data import (
    REAL_GATES,
    ManifestError,
    load_real_manifest,
    sha256_file,
)
from retail_demand_inventory.data.real_manifest import (
    RawFileEntry,
    RealSnapshotManifest,
)


def test_committed_real_manifest_metadata(repo_root) -> None:
    manifest = load_real_manifest(
        repo_root / "data" / "manifests" / "freshretailnet-real.json"
    )
    assert manifest.dataset_id == "Dingdong-Inc/FreshRetailNet-50K"
    assert manifest.pinned_revision == REVISION
    assert manifest.publisher == "Dingdong Limited (Hugging Face org Dingdong-Inc)"
    assert manifest.access_method.startswith("huggingface.co")
    assert manifest.source_urls["page"].startswith("https://huggingface.co/")
    assert manifest.license_url.startswith("https://creativecommons.org/")
    assert manifest.attribution and manifest.citation
    assert set(manifest.gates) == set(REAL_GATES)
    assert all(manifest.gates.values())
    names = {entry.name for entry in manifest.raw_files}
    assert names == {"train", "eval"}
    for entry in manifest.raw_files:
        assert entry.expected_size == entry.observed_size
        assert entry.expected_sha256 == entry.observed_sha256
        assert len(entry.expected_sha256) == 64
    assert (
        manifest.canonical_content_sha256
        and len(manifest.canonical_content_sha256) == 64
    )


def test_gate_names_are_exactly_the_documented_five() -> None:
    assert REAL_GATES == (
        "source_verified",
        "license_verified",
        "snapshot_verified",
        "schema_verified",
        "stockout_semantics_verified",
    )


def test_missing_required_field_fails(tmp_path) -> None:
    manifest = make_manifest(tmp_path, train_name="t.parquet", eval_name="e.parquet")
    payload = manifest.to_dict()
    del payload["dataset_id"]
    with pytest.raises(ManifestError):
        RealSnapshotManifest.from_dict(payload).require_valid()


def test_wrong_revision_fails_validation(tmp_path) -> None:
    manifest = make_manifest(tmp_path, train_name="t.parquet", eval_name="e.parquet")
    from dataclasses import replace

    wrong = replace(manifest, pinned_revision="a" * 40)
    problems = wrong.validate()
    assert any("revision" in problem for problem in problems)
    with pytest.raises(ManifestError):
        wrong.require_valid()


def test_unsupported_canonicalization_version_fails(tmp_path) -> None:
    manifest = make_manifest(
        tmp_path,
        train_name="t.parquet",
        eval_name="e.parquet",
        canonicalization_version="999",
    )
    assert any("canonicalization_version" in p for p in manifest.validate())
    with pytest.raises(ManifestError):
        manifest.require_valid()


def test_raw_checksum_ok(tmp_path) -> None:
    path = tmp_path / "payload.bin"
    path.write_bytes(b"payload")
    manifest = make_manifest(tmp_path, train_name="t.parquet", eval_name="e.parquet")
    entry = RawFileEntry(
        name="x",
        local_name="x.bin",
        url=f"https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/resolve/{REVISION}/data/x.bin",
        expected_size=path.stat().st_size,
        expected_sha256=sha256_file(path),
        expected_checksum_source="test",
        observed_size=path.stat().st_size,
        observed_sha256=sha256_file(path),
    )
    assert entry.to_dict()["name"] == "x"
    assert manifest.verify_raw(tmp_path) == ()


def test_raw_checksum_mismatch_reported(tmp_path) -> None:
    path = tmp_path / "payload.bin"
    path.write_bytes(b"payload")
    manifest = make_manifest(tmp_path, train_name="t.parquet", eval_name="e.parquet")
    from dataclasses import replace

    bad = replace(
        manifest,
        raw_files=(
            RawFileEntry(
                name="x",
                local_name="payload.bin",
                url=f"https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/resolve/{REVISION}/data/x.bin",
                expected_size=path.stat().st_size,
                expected_sha256="0" * 64,
                expected_checksum_source="test",
                observed_size=path.stat().st_size,
                observed_sha256="0" * 64,
            ),
            *manifest.raw_files,
        ),
    )
    problems = bad.verify_raw(tmp_path)
    assert any("sha256" in p and "x" in p for p in problems)


def test_missing_observed_checksum_fails_verification(tmp_path) -> None:
    path = tmp_path / "payload.bin"
    path.write_bytes(b"payload")
    manifest = make_manifest(tmp_path, train_name="t.parquet", eval_name="e.parquet")
    from dataclasses import replace

    no_observed = replace(
        manifest,
        raw_files=(
            RawFileEntry(
                name="x",
                local_name="payload.bin",
                url=f"https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/resolve/{REVISION}/data/x.bin",
                expected_size=path.stat().st_size,
                expected_sha256=sha256_file(path),
                expected_checksum_source="test",
                observed_size=None,
                observed_sha256=None,
            ),
            *manifest.raw_files,
        ),
    )
    problems = no_observed.verify_raw(tmp_path)
    assert any("observed" in p for p in problems)


def test_missing_raw_file_reported(tmp_path) -> None:
    manifest = make_manifest(tmp_path, train_name="t.parquet", eval_name="e.parquet")
    from dataclasses import replace

    missing = replace(
        manifest,
        raw_files=(
            RawFileEntry(
                name="x",
                local_name="does-not-exist.parquet",
                url=f"https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/resolve/{REVISION}/data/x.parquet",
                expected_size=1,
                expected_sha256="a" * 64,
                expected_checksum_source="test",
                observed_size=1,
                observed_sha256="a" * 64,
            ),
            *manifest.raw_files,
        ),
    )
    assert any("not found" in p for p in missing.verify_raw(tmp_path))


def test_require_gates_blocks_unverified(tmp_path) -> None:
    manifest = make_manifest(
        tmp_path,
        train_name="t.parquet",
        eval_name="e.parquet",
        gates={"schema_verified": False},
    )
    with pytest.raises(ManifestError, match="schema_verified"):
        manifest.require_gates()


def test_save_load_roundtrip(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "t.parquet").write_bytes(b"t")
    (raw / "e.parquet").write_bytes(b"e")
    manifest = make_manifest(
        raw,
        train_name="t.parquet",
        eval_name="e.parquet",
        canonical_sha="b" * 64,
        schema_report_path="data/reports/x.json",
    )
    saved = tmp_path / "m.json"
    manifest.save(saved)
    loaded = load_real_manifest(saved)
    assert loaded == manifest
    assert json.loads(saved.read_text())["gates"]["schema_verified"] is True
