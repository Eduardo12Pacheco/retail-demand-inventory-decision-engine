"""Dataset manifests: validation, checksums, round-trips."""

from __future__ import annotations

import json

import pytest

from retail_demand_inventory.data import (
    DatasetManifest,
    ManifestError,
    load_manifest,
    save_manifest,
    sha256_file,
)


def _manifest(**overrides) -> DatasetManifest:
    base = {
        "name": "fixture",
        "source_url": "https://example.invalid/source",
        "publisher": "test-publisher",
        "retrieval_date": "2026-08-11",
        "dataset_version": "1.0",
        "license_name": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/legalcode",
        "fields": ("sku", "date", "demand_units"),
        "canonical_mapping": {"demand_units": "sale_amount"},
        "missingness_policy": "fill gaps with zero demand",
    }
    base.update(overrides)
    return DatasetManifest(**base)


def test_sha256_file_is_deterministic(tmp_path) -> None:
    path = tmp_path / "payload.bin"
    path.write_bytes(b"deterministic payload" * 100)
    assert sha256_file(path) == sha256_file(path)
    assert len(sha256_file(path)) == 64


def test_valid_manifest_passes() -> None:
    assert _manifest().validate() == ()


def test_missing_fields_flagged() -> None:
    problems = _manifest(name="").validate()
    assert any("name" in p for p in problems)
    problems = _manifest(retrieval_date="not-a-date").validate()
    assert any("retrieval_date" in p for p in problems)


def test_bad_checksum_flagged() -> None:
    problems = _manifest(checksum="deadbeef").validate()
    assert any("checksum" in p for p in problems)


def test_verify_checksum_ok_and_mismatch(tmp_path) -> None:
    path = tmp_path / "file.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    good = _manifest(checksum=sha256_file(path))
    assert good.verify_checksum(path)
    path.write_text("a,b\n1,3\n", encoding="utf-8")
    assert not good.verify_checksum(path)


def test_save_load_roundtrip(tmp_path) -> None:
    manifest = _manifest(checksum="a" * 64, accepted=True, notes="synthetic")
    save_manifest(tmp_path / "m.json", manifest)
    loaded = load_manifest(tmp_path / "m.json")
    assert loaded == manifest


def test_load_malformed_raises(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"name": "x"}), encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(path)


def test_committed_fixture_manifest_verifies(repo_root) -> None:
    manifest = load_manifest(
        repo_root / "data" / "manifests" / "fixture_synthetic.json"
    )
    assert manifest.validate() == ()
    assert manifest.verify_checksum(
        repo_root / "data" / "fixtures" / "freshretailnet_style_synthetic.csv"
    )
    assert manifest.accepted is True
    assert "synthetic" in manifest.notes.lower()
