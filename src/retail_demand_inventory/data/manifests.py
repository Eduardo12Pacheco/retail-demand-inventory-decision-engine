"""Dataset manifests and checksums.

Every retained data artifact (fixture, generated report) is declared in a
committed manifest with a SHA256 checksum and its source/license provenance.
Consumers verify the checksum before reading the artifact.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


def sha256_file(path: Path, *, chunk_size: int = 1 << 20) -> str:
    """Hex SHA256 of a file, streamed in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class ManifestError(ValueError):
    """Raised when a manifest is malformed or fails validation."""


@dataclass(frozen=True)
class DatasetManifest:
    """Provenance and checksum metadata for one retained data artifact.

    `accepted` records whether the artifact was accepted by the source
    contract. The synthetic fixture manifest is accepted for *methodology
    development* only and is explicitly not an audited-source result.
    """

    name: str
    source_url: str
    publisher: str
    retrieval_date: str  # ISO date
    dataset_version: str
    license_name: str
    license_url: str
    fields: tuple[str, ...]
    canonical_mapping: Mapping[str, str]
    missingness_policy: str
    checksum_algorithm: str = "sha256"
    checksum: str | None = None
    file_path: str | None = None
    accepted: bool = False
    notes: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DatasetManifest:
        try:
            return cls(
                name=str(data["name"]),
                source_url=str(data["source_url"]),
                publisher=str(data["publisher"]),
                retrieval_date=str(data["retrieval_date"]),
                dataset_version=str(data["dataset_version"]),
                license_name=str(data["license_name"]),
                license_url=str(data["license_url"]),
                fields=tuple(str(f) for f in data["fields"]),
                canonical_mapping=dict(data["canonical_mapping"]),
                missingness_policy=str(data["missingness_policy"]),
                checksum_algorithm=str(data.get("checksum_algorithm", "sha256")),
                checksum=str(data["checksum"]) if data.get("checksum") else None,
                file_path=str(data["file_path"]) if data.get("file_path") else None,
                accepted=bool(data.get("accepted", False)),
                notes=str(data.get("notes", "")),
            )
        except (KeyError, TypeError) as exc:
            raise ManifestError(f"manifest is missing or malformed: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_url": self.source_url,
            "publisher": self.publisher,
            "retrieval_date": self.retrieval_date,
            "dataset_version": self.dataset_version,
            "license_name": self.license_name,
            "license_url": self.license_url,
            "fields": list(self.fields),
            "canonical_mapping": dict(self.canonical_mapping),
            "missingness_policy": self.missingness_policy,
            "checksum_algorithm": self.checksum_algorithm,
            "checksum": self.checksum,
            "file_path": self.file_path,
            "accepted": self.accepted,
            "notes": self.notes,
        }

    def validate(self) -> tuple[str, ...]:
        """Return human-readable problems; empty tuple means valid."""
        problems: list[str] = []
        for key in (
            "name",
            "source_url",
            "publisher",
            "retrieval_date",
            "dataset_version",
            "license_name",
            "license_url",
            "missingness_policy",
        ):
            if not str(getattr(self, key)).strip():
                problems.append(f"missing or empty field: {key}")
        try:
            date.fromisoformat(self.retrieval_date)
        except ValueError:
            problems.append(
                f"retrieval_date is not an ISO date: {self.retrieval_date!r}"
            )
        if not self.fields:
            problems.append("fields must not be empty")
        if self.checksum_algorithm != "sha256":
            problems.append(
                f"unsupported checksum algorithm: {self.checksum_algorithm}"
            )
        if self.checksum is not None and (
            len(self.checksum) != 64
            or any(c not in "0123456789abcdef" for c in self.checksum)
        ):
            problems.append("checksum must be a 64-char lowercase hex sha256")
        return tuple(problems)

    def require_valid(self) -> None:
        problems = self.validate()
        if problems:
            raise ManifestError("; ".join(problems))

    def verify_checksum(self, file_path: Path) -> bool:
        """True if `file_path` matches the recorded checksum (or no checksum recorded)."""
        if self.checksum is None:
            return True
        return sha256_file(file_path) == self.checksum


def save_manifest(path: Path, manifest: DatasetManifest) -> None:
    manifest.require_valid()
    payload = json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")


def load_manifest(path: Path) -> DatasetManifest:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    manifest = DatasetManifest.from_dict(data)
    manifest.require_valid()
    return manifest
