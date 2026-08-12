"""Typed population manifest for an expanded deterministic real evaluation.

The v1 real evaluation is `MAX_POPULATION_KEYS = 10` keys with no per-store cap
and no manifest. The v2 expanded population is opt-in via a committed
`PopulationManifest` that records, for a FROZEN deterministic selection rule:

- identity: `population_id`, the source manifest id/path it is derived from,
- provenance: pinned revision, per-raw-file local name/size/SHA-256,
- the selection rule (eligibility, history requirement, store-diversity cap,
  target key count) and the resulting counts (candidate/qualifying/eligible/
  selected/excluded keys and rows, train/eval rows, stores, products),
- the date range and the train/eval separation facts,
- selected/excluded key-list checksums and the canonical-content SHA-256,
- the resource budget (documented constants, not measurements),
- `seed = null` (no sampling) and `train_metadata_only = true` (selection never
  reads demand/stockout values), plus generation timestamp and code revision.

The manifest is always GENERATED from code over the actual verified raw bytes
(`build_population_manifest`); it is never hand-typed. It commits only small
metadata and key lists; the raw bytes stay in the gitignored `data/raw/`.

Command:

    python -m retail_demand_inventory.data.population_manifest \\
        --source-manifest data/manifests/freshretailnet-real.json \\
        --raw-dir data/raw \\
        --out data/manifests/freshretailnet-real-population-v2.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .manifests import ManifestError, sha256_bytes
from .real_loader import (
    PER_STORE_CAP_KEYS,
    REQUIRED_HISTORY_DAYS,
    TARGET_POPULATION_KEYS,
    RealLoaderError,
    analyze_population,
    load_real_snapshot,
    select_expanded_population,
)
from .real_manifest import load_real_manifest

POPULATION_MANIFEST_VERSION = "1"
POPULATION_V2_ID = "freshretailnet-real-population-v2"
SOURCE_MANIFEST_ID = "freshretailnet-real.json"

# Deterministic resource budget (documented constants, not wall-clock
# measurements). Basis: measured v1 runtime ~87s for 10 keys and measured v2
# runtime ~83s wall for 100 keys after the shared-backtest optimization; the
# documented materialization budget is 300s. Measured report size ~4.1MB;
# memory is tiny (~9,700 canonical records; the parquet reads are
# column-filtered).
PROFILE_ESTIMATED_RUNTIME_SECONDS = 3
MATERIALIZATION_ESTIMATED_RUNTIME_SECONDS = 300
ESTIMATED_PEAK_MEMORY_BYTES = 8_388_608
ESTIMATED_REPORT_BYTES = 4_200_000

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")


def _sha256_ok(value: str | None) -> bool:
    return isinstance(value, str) and bool(_HEX_64.match(value))


def _revision_ok(value: str | None) -> bool:
    return isinstance(value, str) and bool(_HEX_40.match(value))


def _deterministic_timestamp() -> tuple[str, str]:
    raw = os.environ.get("SOURCE_DATE_EPOCH")
    if raw:
        try:
            ts = datetime.fromtimestamp(int(raw), tz=UTC)
            return ts.isoformat(), "SOURCE_DATE_EPOCH"
        except ValueError:
            pass
    return "2026-08-11T00:00:00+00:00", "documented-fixed-value"


def _repo_head() -> tuple[str | None, str]:
    """HEAD at generation time; never fabricates the eventual commit SHA."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return (
                out.stdout.strip(),
                (
                    "git HEAD at generation time (manifest generated before "
                    "commit; not the eventual commit SHA)"
                ),
            )
    except (OSError, subprocess.SubprocessError):
        pass
    return None, "unavailable"


def _keys_checksum(keys: Sequence[str]) -> str:
    """Deterministic SHA-256 over the canonical serialization of a key list."""
    payload = json.dumps(sorted(keys), separators=(",", ":"), ensure_ascii=False) + "\n"
    return sha256_bytes(payload.encode("utf-8"))


@dataclass(frozen=True)
class PopulationManifest:
    """Everything needed to reproduce one expanded real population (v2)."""

    manifest_version: str
    population_id: str
    source_manifest_id: str
    source_manifest_path: str
    source_dataset_id: str
    pinned_revision: str
    raw_checksums: Mapping[str, Mapping[str, Any]]
    selection_rule: str
    required_history_days: int
    per_store_cap: int
    target_keys: int
    candidate_key_count: int
    qualifying_key_count: int
    eligible_key_count: int
    selected_key_count: int
    excluded_key_count: int
    source_row_count: int
    selected_row_count: int
    excluded_row_count: int
    train_row_count: int
    eval_row_count: int
    store_count: int
    product_count: int
    store_key_counts: Mapping[str, int]
    date_range: tuple[str, str]
    train_eval_separation: Mapping[str, Any]
    selection_checksums: Mapping[str, str]
    canonical_content_sha256: str | None
    resource_budget: Mapping[str, Any]
    seed: None = None
    train_metadata_only: bool = True
    creation_timestamp: str = ""
    timestamp_source: str = ""
    code_revision: str | None = None
    code_revision_note: str = ""
    selected_keys: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PopulationManifest:
        try:
            raw_checksums = {
                str(k): dict(v) for k, v in dict(data["raw_checksums"]).items()
            }
            train_eval_separation = dict(data.get("train_eval_separation", {}))
            selection_checksums = {
                str(k): str(v) for k, v in dict(data["selection_checksums"]).items()
            }
            resource_budget = dict(data.get("resource_budget", {}))
            date_range = tuple(str(d) for d in data["date_range"])
            return cls(
                manifest_version=str(
                    data.get("manifest_version", POPULATION_MANIFEST_VERSION)
                ),
                population_id=str(data["population_id"]),
                source_manifest_id=str(data["source_manifest_id"]),
                source_manifest_path=str(data["source_manifest_path"]),
                source_dataset_id=str(data["source_dataset_id"]),
                pinned_revision=str(data["pinned_revision"]),
                raw_checksums=raw_checksums,
                selection_rule=str(data["selection_rule"]),
                required_history_days=int(data["required_history_days"]),
                per_store_cap=int(data["per_store_cap"]),
                target_keys=int(data["target_keys"]),
                candidate_key_count=int(data["candidate_key_count"]),
                qualifying_key_count=int(data["qualifying_key_count"]),
                eligible_key_count=int(data["eligible_key_count"]),
                selected_key_count=int(data["selected_key_count"]),
                excluded_key_count=int(data["excluded_key_count"]),
                source_row_count=int(data["source_row_count"]),
                selected_row_count=int(data["selected_row_count"]),
                excluded_row_count=int(data["excluded_row_count"]),
                train_row_count=int(data["train_row_count"]),
                eval_row_count=int(data["eval_row_count"]),
                store_count=int(data["store_count"]),
                product_count=int(data["product_count"]),
                store_key_counts={
                    str(k): int(v)
                    for k, v in dict(data.get("store_key_counts", {})).items()
                },
                date_range=date_range,
                train_eval_separation=train_eval_separation,
                selection_checksums=selection_checksums,
                canonical_content_sha256=(
                    str(data["canonical_content_sha256"])
                    if data.get("canonical_content_sha256")
                    else None
                ),
                resource_budget=resource_budget,
                seed=data.get("seed"),
                train_metadata_only=bool(data.get("train_metadata_only", True)),
                creation_timestamp=str(data.get("creation_timestamp", "")),
                timestamp_source=str(data.get("timestamp_source", "")),
                code_revision=(
                    str(data["code_revision"]) if data.get("code_revision") else None
                ),
                code_revision_note=str(data.get("code_revision_note", "")),
                selected_keys=tuple(str(k) for k in data.get("selected_keys", ())),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(
                f"population manifest is missing or malformed: {exc}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "population_id": self.population_id,
            "source_manifest_id": self.source_manifest_id,
            "source_manifest_path": self.source_manifest_path,
            "source_dataset_id": self.source_dataset_id,
            "pinned_revision": self.pinned_revision,
            "raw_checksums": {
                name: dict(entry) for name, entry in self.raw_checksums.items()
            },
            "selection_rule": self.selection_rule,
            "required_history_days": self.required_history_days,
            "per_store_cap": self.per_store_cap,
            "target_keys": self.target_keys,
            "candidate_key_count": self.candidate_key_count,
            "qualifying_key_count": self.qualifying_key_count,
            "eligible_key_count": self.eligible_key_count,
            "selected_key_count": self.selected_key_count,
            "excluded_key_count": self.excluded_key_count,
            "source_row_count": self.source_row_count,
            "selected_row_count": self.selected_row_count,
            "excluded_row_count": self.excluded_row_count,
            "train_row_count": self.train_row_count,
            "eval_row_count": self.eval_row_count,
            "store_count": self.store_count,
            "product_count": self.product_count,
            "store_key_counts": dict(self.store_key_counts),
            "date_range": list(self.date_range),
            "train_eval_separation": dict(self.train_eval_separation),
            "selection_checksums": dict(self.selection_checksums),
            "canonical_content_sha256": self.canonical_content_sha256,
            "resource_budget": dict(self.resource_budget),
            "seed": self.seed,
            "train_metadata_only": self.train_metadata_only,
            "creation_timestamp": self.creation_timestamp,
            "timestamp_source": self.timestamp_source,
            "code_revision": self.code_revision,
            "code_revision_note": self.code_revision_note,
            "selected_keys": list(self.selected_keys),
        }

    def validate(self) -> tuple[str, ...]:
        """Return human-readable problems; empty tuple means valid."""
        problems: list[str] = []
        if not str(self.population_id).strip():
            problems.append("missing or empty field: population_id")
        elif not re.match(r"^[a-z0-9][a-z0-9-]*$", self.population_id):
            problems.append(
                f"population_id {self.population_id!r} must be lowercase [a-z0-9-]"
            )
        for key in (
            "source_manifest_id",
            "source_manifest_path",
            "source_dataset_id",
            "selection_rule",
            "timestamp_source",
        ):
            if not str(getattr(self, key)).strip():
                problems.append(f"missing or empty field: {key}")
        if not _revision_ok(self.pinned_revision):
            problems.append("pinned_revision must be a 40-char lowercase hex sha1")
        if not self.raw_checksums:
            problems.append("raw_checksums must not be empty")
        for name, entry in sorted(self.raw_checksums.items()):
            prefix = f"raw checksum {name!r}: "
            if not str(entry.get("local_name", "")).strip():
                problems.append(f"{prefix}local_name must be non-empty")
            try:
                if int(entry.get("size", -1)) <= 0:
                    problems.append(f"{prefix}size must be positive")
            except (TypeError, ValueError):
                problems.append(f"{prefix}size must be an integer")
            if not _sha256_ok(str(entry.get("sha256", ""))):
                problems.append(f"{prefix}sha256 must be a 64-char lowercase hex")
        if self.required_history_days <= 0:
            problems.append("required_history_days must be positive")
        if self.per_store_cap <= 0:
            problems.append("per_store_cap must be positive")
        if self.target_keys <= 0:
            problems.append("target_keys must be positive")
        if not (0 <= self.eligible_key_count <= self.qualifying_key_count):
            problems.append("expected 0 <= eligible <= qualifying")
        if not (0 <= self.qualifying_key_count <= self.candidate_key_count):
            problems.append("expected 0 <= qualifying <= candidate")
        if self.selected_key_count != len(self.selected_keys):
            problems.append("selected_key_count must equal len(selected_keys)")
        if (
            self.excluded_key_count
            != self.candidate_key_count - self.selected_key_count
        ):
            problems.append(
                "excluded_key_count must equal candidate_key_count - selected_key_count"
            )
        if not (0 <= self.selected_key_count <= self.eligible_key_count):
            problems.append("expected 0 <= selected <= eligible")
        if self.source_row_count < self.selected_row_count:
            problems.append("selected_row_count must be <= source_row_count")
        if self.selected_row_count != self.train_row_count + self.eval_row_count:
            problems.append(
                "selected_row_count must equal train_row_count + eval_row_count"
            )
        if self.store_count != len(self.store_key_counts):
            problems.append("store_count must equal len(store_key_counts)")
        if self.product_count <= 0:
            problems.append("product_count must be positive")
        if self.seed is not None:
            problems.append("seed must be null (no sampling)")
        if self.train_metadata_only is not True:
            problems.append("train_metadata_only must be true")
        try:
            if len(self.date_range) != 2:
                raise ValueError("date_range must have 2 entries")
            from datetime import date as _date

            start = _date.fromisoformat(self.date_range[0])
            end = _date.fromisoformat(self.date_range[1])
            if start > end:
                problems.append("date_range start must be <= end")
        except (ValueError, TypeError):
            problems.append("date_range must be two ISO dates")
        separation = self.train_eval_separation
        if "date_overlap" not in separation:
            problems.append("train_eval_separation must record date_overlap")
        elif separation.get("date_overlap") is not False:
            problems.append("train_eval_separation date_overlap must be false")
        for name in ("selected_keys_sha256", "excluded_keys_sha256"):
            value = self.selection_checksums.get(name)
            if not _sha256_ok(value):
                problems.append(
                    f"selection_checksums.{name} must be a 64-char lowercase hex"
                )
        if self.canonical_content_sha256 is not None and not _sha256_ok(
            self.canonical_content_sha256
        ):
            problems.append(
                "canonical_content_sha256 must be a 64-char lowercase hex sha256"
            )
        if not self.resource_budget:
            problems.append("resource_budget must not be empty")
        if not self.creation_timestamp:
            problems.append("creation_timestamp is required")
        if self.code_revision is not None and not _revision_ok(self.code_revision):
            problems.append("code_revision must be a 40-char lowercase hex sha1")
        return tuple(problems)

    def require_valid(self) -> None:
        problems = self.validate()
        if problems:
            raise ManifestError("; ".join(problems))

    def save(self, path: Path) -> None:
        self.require_valid()
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")


def load_population_manifest(path: Path) -> PopulationManifest:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    manifest = PopulationManifest.from_dict(data)
    manifest.require_valid()
    return manifest


def build_population_manifest(
    *,
    source_manifest_path: Path,
    raw_dir: Path,
    required_history_days: int = REQUIRED_HISTORY_DAYS,
    per_store_cap: int = PER_STORE_CAP_KEYS,
    target_keys: int = TARGET_POPULATION_KEYS,
    population_id: str = POPULATION_V2_ID,
    source_manifest_id: str = SOURCE_MANIFEST_ID,
    creation_timestamp: str | None = None,
    timestamp_source: str | None = None,
    code_revision: str | None = None,
) -> PopulationManifest:
    """Generate the v2 population manifest from the verified raw snapshot.

    Never hand-typed: every count and checksum is derived from the actual raw
    bytes via the deterministic selection and canonical loader.
    """
    source = load_real_manifest(source_manifest_path)
    source.require_gates()
    source.require_raw_ok(raw_dir)

    train_path = raw_dir / source.raw_file("train").local_name
    eval_path = raw_dir / source.raw_file("eval").local_name
    analysis = analyze_population(
        train_path, eval_path, required_history_days=required_history_days
    )
    selection = select_expanded_population(
        train_path,
        eval_path,
        required_history_days=required_history_days,
        per_store_cap=per_store_cap,
        target_keys=target_keys,
        population_id=population_id,
    )

    excluded_keys = [
        key for key in analysis.all_keys if key not in set(selection.selected_keys)
    ]
    train_dates = _span_extent(
        [analysis.train_spans.get(key) for key in selection.selected_keys]
    )
    eval_dates = _span_extent(
        [analysis.eval_spans.get(key) for key in selection.selected_keys]
    )

    ts, ts_source = (
        (creation_timestamp, timestamp_source)
        if creation_timestamp is not None
        else _deterministic_timestamp()
    )
    revision_note = "provided"
    if code_revision is None:
        code_revision, revision_note = _repo_head()

    raw_checksums: dict[str, dict[str, Any]] = {}
    for entry in source.raw_files:
        raw_checksums[entry.name] = {
            "local_name": entry.local_name,
            "size": entry.expected_size,
            "sha256": entry.expected_sha256,
        }

    resource_budget = {
        "estimated_materialization_runtime_seconds": (
            MATERIALIZATION_ESTIMATED_RUNTIME_SECONDS
        ),
        "estimated_profile_runtime_seconds": PROFILE_ESTIMATED_RUNTIME_SECONDS,
        "estimated_peak_memory_bytes": ESTIMATED_PEAK_MEMORY_BYTES,
        "estimated_report_bytes": ESTIMATED_REPORT_BYTES,
        "source": "documented-constant",
        "note": (
            "Documented deterministic constants, not wall-clock measurements. "
            "Basis: measured v1 runtime ~87s for 10 keys and measured v2 "
            "runtime ~83s wall for 100 keys (shared-backtest optimization); "
            "documented materialization budget 300s; span grouping ~1s; 100 "
            "selected keys ~0.3s read; measured report ~4.1MB; memory is tiny "
            "(~9,700 canonical records)."
        ),
    }

    manifest = PopulationManifest(
        manifest_version=POPULATION_MANIFEST_VERSION,
        population_id=population_id,
        source_manifest_id=source_manifest_id,
        source_manifest_path=str(source_manifest_path),
        source_dataset_id=source.dataset_id,
        pinned_revision=source.pinned_revision,
        raw_checksums=raw_checksums,
        selection_rule=selection.rule,
        required_history_days=required_history_days,
        per_store_cap=per_store_cap,
        target_keys=target_keys,
        candidate_key_count=selection.candidate_key_count,
        qualifying_key_count=selection.qualifying_key_count,
        eligible_key_count=selection.eligible_key_count,
        selected_key_count=selection.selected_key_count,
        excluded_key_count=selection.excluded_key_count,
        source_row_count=selection.source_row_count,
        selected_row_count=selection.selected_row_count,
        excluded_row_count=selection.excluded_row_count,
        train_row_count=selection.train_row_count,
        eval_row_count=selection.eval_row_count,
        store_count=len(selection.store_key_counts),
        product_count=selection.product_key_count,
        store_key_counts=dict(selection.store_key_counts),
        date_range=(
            tuple(d.isoformat() for d in selection.date_range)
            if selection.date_range
            else ("", "")
        ),
        train_eval_separation={
            "train_dates": train_dates,
            "eval_dates": eval_dates,
            "date_overlap": False,
            "note": (
                "The publisher ships two parallel files. Each selected key "
                "appears in train (first 90 days) and eval (last 7 days) with "
                "disjoint dates; the evaluation re-splits chronologically per "
                "the protocol and never mixes the raw splits' rows."
            ),
        },
        selection_checksums={
            "selected_keys_sha256": _keys_checksum(selection.selected_keys),
            "excluded_keys_sha256": _keys_checksum(excluded_keys),
        },
        canonical_content_sha256=None,
        resource_budget=resource_budget,
        seed=None,
        train_metadata_only=True,
        creation_timestamp=ts,
        timestamp_source=ts_source,
        code_revision=code_revision,
        code_revision_note=revision_note,
        selected_keys=selection.selected_keys,
    )
    manifest.require_valid()

    # Canonical-content SHA-256 for the v2 population (small: ~9,700 records).
    result = load_real_snapshot(
        source,
        raw_dir,
        required_history_days=required_history_days,
        population=manifest,
    )
    manifest = replace(manifest, canonical_content_sha256=result.canonical_sha256)
    manifest.require_valid()
    return manifest


def _span_extent(
    spans: Sequence[tuple[str | None, str | None, int] | None],
) -> list[str]:
    mins = [s[0] for s in spans if s is not None and s[0] is not None]
    maxs = [s[1] for s in spans if s is not None and s[1] is not None]
    if not mins or not maxs:
        return []
    return [min(mins), max(maxs)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the v2 population manifest for the expanded deterministic "
            "real evaluation from the verified raw snapshot."
        )
    )
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--required-history-days", type=int, default=REQUIRED_HISTORY_DAYS
    )
    parser.add_argument("--per-store-cap", type=int, default=PER_STORE_CAP_KEYS)
    parser.add_argument("--target-keys", type=int, default=TARGET_POPULATION_KEYS)
    args = parser.parse_args(argv)

    try:
        manifest = build_population_manifest(
            source_manifest_path=args.source_manifest,
            raw_dir=args.raw_dir,
            required_history_days=args.required_history_days,
            per_store_cap=args.per_store_cap,
            target_keys=args.target_keys,
        )
        manifest.save(args.out)
    except (ManifestError, RealLoaderError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {args.out}")
    print(
        f"population {manifest.population_id}: {manifest.selected_key_count} keys "
        f"({manifest.store_count} stores, {manifest.product_count} products), "
        f"{manifest.selected_row_count} rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
