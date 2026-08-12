from __future__ import annotations

from pathlib import Path

import pytest
from real_helpers import REVISION, daily_rows, make_manifest, write_split

import retail_demand_inventory.data.acquisition as acquisition_mod
from retail_demand_inventory.data.acquisition import AcquisitionError, acquire


@pytest.fixture
def raw_and_manifest(tmp_path) -> tuple[Path, Path]:
    raw = tmp_path / "raw"
    raw.mkdir()
    write_split(raw, "train", daily_rows(((1, 1), (1, 2)), "2024-01-01", 5))
    write_split(raw, "eval", daily_rows(((1, 1), (1, 2)), "2024-01-06", 5))
    manifest = make_manifest(raw, train_name="train.parquet", eval_name="eval.parquet")
    manifest_path = tmp_path / "manifest.json"
    manifest.save(manifest_path)
    return raw, manifest_path


def _no_network(*_args, **_kwargs):  # pragma: no cover - must never run
    raise AssertionError("network must not be touched in tests")


def test_verify_only_mode_ok_without_network(
    tmp_path, raw_and_manifest, monkeypatch
) -> None:
    raw, manifest_path = raw_and_manifest
    monkeypatch.setattr(acquisition_mod.urllib.request, "urlopen", _no_network)
    before = manifest_path.read_bytes()
    manifest = acquire(manifest_path, raw, download=False, update_manifest=True)
    assert all(manifest.gates.values())
    assert manifest_path.read_bytes() == before


def test_verify_only_missing_observed_checksum_fails(
    tmp_path, raw_and_manifest, monkeypatch
) -> None:
    from dataclasses import replace

    raw, _ = raw_and_manifest
    monkeypatch.setattr(acquisition_mod.urllib.request, "urlopen", _no_network)
    manifest = make_manifest(raw, train_name="train.parquet", eval_name="eval.parquet")
    unobserved = replace(
        manifest,
        raw_files=tuple(
            replace(entry, observed_size=None, observed_sha256=None)
            for entry in manifest.raw_files
        ),
    )
    unobserved_path = tmp_path / "unobserved.json"
    unobserved.save(unobserved_path)
    with pytest.raises(AcquisitionError, match="observed"):
        acquire(unobserved_path, raw, download=False, update_manifest=False)


def test_verify_only_checksum_mismatch_fails(raw_and_manifest, monkeypatch) -> None:
    raw, manifest_path = raw_and_manifest
    monkeypatch.setattr(acquisition_mod.urllib.request, "urlopen", _no_network)
    with (raw / "train.parquet").open("ab") as handle:
        handle.write(b"corruption")
    with pytest.raises(AcquisitionError, match="mismatch"):
        acquire(manifest_path, raw, download=False, update_manifest=False)


def test_verify_only_missing_file_fails(raw_and_manifest, monkeypatch) -> None:
    raw, manifest_path = raw_and_manifest
    monkeypatch.setattr(acquisition_mod.urllib.request, "urlopen", _no_network)
    (raw / "train.parquet").unlink()
    with pytest.raises(AcquisitionError, match="not found"):
        acquire(manifest_path, raw, download=False, update_manifest=False)


def test_download_mode_reuses_existing_verified_files(
    raw_and_manifest, monkeypatch
) -> None:
    raw, manifest_path = raw_and_manifest
    manifest_entry = make_manifest(
        raw, train_name="train.parquet", eval_name="eval.parquet"
    )

    def _stub_peek_headers(url: str) -> tuple[str, str]:
        for entry in manifest_entry.raw_files:
            if entry.url == url:
                return REVISION, str(entry.expected_size)
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(acquisition_mod, "_peek_headers", _stub_peek_headers)
    monkeypatch.setattr(acquisition_mod.urllib.request, "urlopen", _no_network)
    before = manifest_path.read_bytes()
    manifest = acquire(manifest_path, raw, download=True, update_manifest=False)
    assert all(manifest.gates.values())
    assert manifest_path.read_bytes() == before


def test_download_mode_headers_detect_wrong_revision(
    raw_and_manifest, monkeypatch
) -> None:
    raw, manifest_path = raw_and_manifest

    def _wrong_revision_headers(url: str) -> tuple[str, str]:
        return "deadbeef" * 5, str(0)

    monkeypatch.setattr(acquisition_mod, "_peek_headers", _wrong_revision_headers)
    with pytest.raises(AcquisitionError, match="x-repo-commit"):
        acquire(manifest_path, raw, download=True, update_manifest=False)
