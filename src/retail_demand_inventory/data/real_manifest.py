"""Typed manifest for a pinned real-data snapshot.

This complements the synthetic `DatasetManifest`: it records everything needed
to acquire, verify, and audit a real dataset snapshot without keeping the raw
bytes in the repository:

- identity (dataset id, publisher, pinned revision, source URLs),
- license / attribution / citation,
- raw files with expected (source-declared) and observed (locally computed)
  sizes and SHA-256 checksums, plus optional archive / extracted-file fields,
- the canonicalization version, rule, and canonical-content SHA-256,
- the stockout derivation version and rule,
- explicit gate statuses that must all be true before real-mode evaluation.

A real snapshot is only usable once every gate is true AND every raw file has
an observed checksum. Unlike the synthetic manifest, a missing observed
checksum FAILS verification in real mode: the optional-checksum silent-pass
behavior is reserved for the synthetic fixture only.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from .manifests import ManifestError, sha256_file

REAL_MANIFEST_VERSION = "1"
SUPPORTED_CANONICALIZATION_VERSION = "1"
SUPPORTED_STOCKOUT_DERIVATION_VERSION = "1"

# Exactly-named gate statuses; all five must be true before real evaluation.
REAL_GATES = (
    "source_verified",
    "license_verified",
    "snapshot_verified",
    "schema_verified",
    "stockout_semantics_verified",
)

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")


def _sha256_ok(value: str | None) -> bool:
    return isinstance(value, str) and bool(_HEX_64.match(value))


def _revision_ok(value: str | None) -> bool:
    return isinstance(value, str) and bool(_HEX_40.match(value))


@dataclass(frozen=True)
class RawFileEntry:
    """One raw file of the pinned snapshot (e.g. train.parquet)."""

    name: str
    local_name: str
    url: str
    expected_size: int
    expected_sha256: str
    expected_checksum_source: str
    observed_size: int | None = None
    observed_sha256: str | None = None
    archive_checksum: str | None = None
    extracted_file_checksum: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "local_name": self.local_name,
            "url": self.url,
            "expected_size": self.expected_size,
            "expected_sha256": self.expected_sha256,
            "expected_checksum_source": self.expected_checksum_source,
            "observed_size": self.observed_size,
            "observed_sha256": self.observed_sha256,
            "archive_checksum": self.archive_checksum,
            "extracted_file_checksum": self.extracted_file_checksum,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RawFileEntry:
        try:
            return cls(
                name=str(data["name"]),
                local_name=str(data["local_name"]),
                url=str(data["url"]),
                expected_size=int(data["expected_size"]),
                expected_sha256=str(data["expected_sha256"]),
                expected_checksum_source=str(data["expected_checksum_source"]),
                observed_size=(
                    int(data["observed_size"])
                    if data.get("observed_size") is not None
                    else None
                ),
                observed_sha256=(
                    str(data["observed_sha256"])
                    if data.get("observed_sha256")
                    else None
                ),
                archive_checksum=(
                    str(data["archive_checksum"])
                    if data.get("archive_checksum")
                    else None
                ),
                extracted_file_checksum=(
                    str(data["extracted_file_checksum"])
                    if data.get("extracted_file_checksum")
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(
                f"raw file entry is missing or malformed: {exc}"
            ) from exc


@dataclass(frozen=True)
class RealSnapshotManifest:
    """Provenance, checksums, and gates for one pinned real-data snapshot."""

    manifest_version: str
    dataset_id: str
    name: str
    publisher: str
    pinned_revision: str
    source_urls: Mapping[str, str]
    retrieval_date: str
    dataset_version: str
    license_name: str
    license_url: str
    attribution: str
    citation: str
    access_method: str
    raw_files: tuple[RawFileEntry, ...] = ()
    expected_schema: Mapping[str, str] = field(default_factory=dict)
    canonicalization_version: str = SUPPORTED_CANONICALIZATION_VERSION
    canonicalization_rule: str = ""
    canonical_content_sha256: str | None = None
    schema_report_path: str | None = None
    stockout_derivation_version: str = SUPPORTED_STOCKOUT_DERIVATION_VERSION
    stockout_derivation_rule: str = ""
    gates: Mapping[str, bool] = field(
        default_factory=lambda: {gate: False for gate in REAL_GATES}
    )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RealSnapshotManifest:
        try:
            raw_files = tuple(
                RawFileEntry.from_dict(entry) for entry in data.get("raw_files", ())
            )
            gates = dict(data.get("gates", {}))
            expected_schema = {
                str(k): str(v) for k, v in dict(data.get("expected_schema", {})).items()
            }
            source_urls = {
                str(k): str(v) for k, v in dict(data.get("source_urls", {})).items()
            }
            return cls(
                manifest_version=str(
                    data.get("manifest_version", REAL_MANIFEST_VERSION)
                ),
                dataset_id=str(data["dataset_id"]),
                name=str(data["name"]),
                publisher=str(data["publisher"]),
                pinned_revision=str(data["pinned_revision"]),
                source_urls=source_urls,
                retrieval_date=str(data.get("retrieval_date", "")),
                dataset_version=str(data.get("dataset_version", "")),
                license_name=str(data["license_name"]),
                license_url=str(data["license_url"]),
                attribution=str(data.get("attribution", "")),
                citation=str(data.get("citation", "")),
                access_method=str(data.get("access_method", "")),
                raw_files=raw_files,
                expected_schema=expected_schema,
                canonicalization_version=str(
                    data.get(
                        "canonicalization_version", SUPPORTED_CANONICALIZATION_VERSION
                    )
                ),
                canonicalization_rule=str(data.get("canonicalization_rule", "")),
                canonical_content_sha256=(
                    str(data["canonical_content_sha256"])
                    if data.get("canonical_content_sha256")
                    else None
                ),
                schema_report_path=(
                    str(data["schema_report_path"])
                    if data.get("schema_report_path")
                    else None
                ),
                stockout_derivation_version=str(
                    data.get(
                        "stockout_derivation_version",
                        SUPPORTED_STOCKOUT_DERIVATION_VERSION,
                    )
                ),
                stockout_derivation_rule=str(data.get("stockout_derivation_rule", "")),
                gates={gate: bool(gates.get(gate, False)) for gate in REAL_GATES},
            )
        except (KeyError, TypeError) as exc:
            raise ManifestError(f"manifest is missing or malformed: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "dataset_id": self.dataset_id,
            "name": self.name,
            "publisher": self.publisher,
            "pinned_revision": self.pinned_revision,
            "source_urls": dict(self.source_urls),
            "retrieval_date": self.retrieval_date,
            "dataset_version": self.dataset_version,
            "license_name": self.license_name,
            "license_url": self.license_url,
            "attribution": self.attribution,
            "citation": self.citation,
            "access_method": self.access_method,
            "raw_files": [entry.to_dict() for entry in self.raw_files],
            "expected_schema": dict(self.expected_schema),
            "canonicalization_version": self.canonicalization_version,
            "canonicalization_rule": self.canonicalization_rule,
            "canonical_content_sha256": self.canonical_content_sha256,
            "schema_report_path": self.schema_report_path,
            "stockout_derivation_version": self.stockout_derivation_version,
            "stockout_derivation_rule": self.stockout_derivation_rule,
            "gates": dict(self.gates),
        }

    def validate(self) -> tuple[str, ...]:
        """Return human-readable problems; empty tuple means valid."""
        problems: list[str] = []
        for key in (
            "dataset_id",
            "name",
            "publisher",
            "license_name",
            "license_url",
            "attribution",
            "citation",
            "access_method",
            "canonicalization_rule",
            "stockout_derivation_rule",
        ):
            if not str(getattr(self, key)).strip():
                problems.append(f"missing or empty field: {key}")
        if not self.pinned_revision.strip() or not _revision_ok(self.pinned_revision):
            problems.append("pinned_revision must be a 40-char lowercase hex sha1")
        try:
            date.fromisoformat(self.retrieval_date)
        except ValueError:
            problems.append(
                f"retrieval_date is not an ISO date: {self.retrieval_date!r}"
            )
        if not self.source_urls:
            problems.append("source_urls must not be empty")
        missing_gates = [g for g in REAL_GATES if g not in self.gates]
        if missing_gates:
            problems.append(f"gates missing: {', '.join(missing_gates)}")
        if self.gates and any(not isinstance(v, bool) for v in self.gates.values()):
            problems.append("gate values must be booleans")
        if self.canonicalization_version != SUPPORTED_CANONICALIZATION_VERSION:
            problems.append(
                f"unsupported canonicalization_version: {self.canonicalization_version!r}"
            )
        if self.stockout_derivation_version != SUPPORTED_STOCKOUT_DERIVATION_VERSION:
            problems.append(
                f"unsupported stockout_derivation_version: {self.stockout_derivation_version!r}"
            )
        if self.canonical_content_sha256 is not None and not _sha256_ok(
            self.canonical_content_sha256
        ):
            problems.append(
                "canonical_content_sha256 must be a 64-char lowercase hex sha256"
            )
        if not self.raw_files:
            problems.append("raw_files must not be empty")
        for entry in self.raw_files:
            problems.extend(self._validate_raw_entry(entry))
        return tuple(problems)

    def _validate_raw_entry(self, entry: RawFileEntry) -> list[str]:
        problems: list[str] = []
        prefix = f"raw file {entry.name!r}: "
        if (
            not entry.name.strip()
            or not entry.local_name.strip()
            or not entry.url.strip()
        ):
            problems.append(f"{prefix}name/local_name/url must be non-empty")
        if entry.expected_size <= 0:
            problems.append(f"{prefix}expected_size must be positive")
        if not _sha256_ok(entry.expected_sha256):
            problems.append(
                f"{prefix}expected_sha256 must be a 64-char lowercase hex sha256"
            )
        if not str(entry.expected_checksum_source).strip():
            problems.append(f"{prefix}expected_checksum_source must be non-empty")
        if not str(entry.url).startswith("https://"):
            problems.append(f"{prefix}url must be https")
        if self.pinned_revision not in entry.url:
            problems.append(
                f"{prefix}url does not embed the pinned revision (revision mismatch)"
            )
        for label, value in (
            ("observed_sha256", entry.observed_sha256),
            ("archive_checksum", entry.archive_checksum),
            ("extracted_file_checksum", entry.extracted_file_checksum),
        ):
            if value is not None and not _sha256_ok(value):
                problems.append(
                    f"{prefix}{label} must be a 64-char lowercase hex sha256"
                )
        if entry.observed_size is not None and entry.observed_size <= 0:
            problems.append(f"{prefix}observed_size must be positive")
        return problems

    def require_valid(self) -> None:
        problems = self.validate()
        if problems:
            raise ManifestError("; ".join(problems))

    def require_gates(self) -> None:
        """All five gates must be true; otherwise raise."""
        self.require_valid()
        not_verified = [gate for gate in REAL_GATES if not self.gates.get(gate, False)]
        if not_verified:
            raise ManifestError(
                f"manifest gates not all verified: {', '.join(not_verified)}"
            )

    def raw_file(self, name: str) -> RawFileEntry:
        for entry in self.raw_files:
            if entry.name == name:
                return entry
        raise ManifestError(f"no raw file entry named {name!r}")

    def with_observed(self, name: str, size: int, sha256: str) -> RealSnapshotManifest:
        """Return a copy with the observed size/checksum recorded for `name`."""
        from dataclasses import replace

        updated: list[RawFileEntry] = []
        for entry in self.raw_files:
            if entry.name == name:
                updated.append(
                    replace(entry, observed_size=int(size), observed_sha256=sha256)
                )
            else:
                updated.append(entry)
        return replace(self, raw_files=tuple(updated))

    def with_snapshot_verified(self) -> RealSnapshotManifest:
        from dataclasses import replace

        return replace(self, gates={**self.gates, "snapshot_verified": True})

    def with_schema_record(
        self,
        *,
        canonical_content_sha256: str,
        schema_report_path: str,
        canonicalization_rule: str,
        stockout_derivation_rule: str,
    ) -> RealSnapshotManifest:
        from dataclasses import replace

        return replace(
            self,
            canonical_content_sha256=canonical_content_sha256,
            schema_report_path=schema_report_path,
            canonicalization_rule=canonicalization_rule,
            stockout_derivation_rule=stockout_derivation_rule,
            gates={
                **self.gates,
                "schema_verified": True,
                "stockout_semantics_verified": True,
            },
        )

    def verify_raw(self, directory: Path) -> tuple[str, ...]:
        """Verify every raw file present with exact size and SHA-256.

        In real mode a missing observed checksum is a FAILURE (no silent pass).
        """
        problems: list[str] = []
        for entry in self.raw_files:
            local = directory / entry.local_name
            prefix = f"raw file {entry.name!r} ({local.name}): "
            if not local.exists():
                problems.append(f"{prefix}file not found")
                continue
            if entry.observed_size is None or entry.observed_sha256 is None:
                problems.append(
                    f"{prefix}observed size/sha256 not recorded; run acquisition first"
                )
                continue
            size = local.stat().st_size
            if size != entry.expected_size:
                problems.append(
                    f"{prefix}size {size} != expected {entry.expected_size}"
                )
            if size != entry.observed_size:
                problems.append(
                    f"{prefix}size {size} != observed {entry.observed_size}"
                )
            digest = sha256_file(local)
            if digest != entry.expected_sha256:
                problems.append(
                    f"{prefix}sha256 {digest} != expected {entry.expected_sha256}"
                )
            if digest != entry.observed_sha256:
                problems.append(
                    f"{prefix}sha256 {digest} != observed {entry.observed_sha256}"
                )
        return tuple(problems)

    def require_raw_ok(self, directory: Path) -> None:
        problems = self.verify_raw(directory)
        if problems:
            raise ManifestError("; ".join(problems))

    def save(self, path: Path) -> None:
        self.require_valid()
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")


def load_real_manifest(path: Path) -> RealSnapshotManifest:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    manifest = RealSnapshotManifest.from_dict(data)
    manifest.require_valid()
    return manifest
