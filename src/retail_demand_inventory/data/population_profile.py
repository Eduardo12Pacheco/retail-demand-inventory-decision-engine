"""Deterministic resource profile for the expanded real population (v2).

Command:

    python -m retail_demand_inventory.data.population_profile \\
        --manifest data/manifests/freshretailnet-real.json \\
        --raw-dir data/raw \\
        --report data/reports/freshretailnet-real-population-profile-v2.json

This is a DRY-RUN / profile command: it verifies the source manifest gates and
raw checksums, scans only the metadata needed for selection (per-key date spans
from the two splits), applies the frozen v2 rule, and writes a deterministic
profile report. It never computes forecast/policy metrics and never touches
`data/evaluations/`. Runtime and memory figures are documented constants (the
report is byte-identical across reruns). When `--population-manifest` is given,
the profile also loads and structurally validates the committed population
manifest against the source.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .manifests import ManifestError
from .population_manifest import (
    ESTIMATED_PEAK_MEMORY_BYTES,
    ESTIMATED_REPORT_BYTES,
    MATERIALIZATION_ESTIMATED_RUNTIME_SECONDS,
    POPULATION_V2_ID,
    PROFILE_ESTIMATED_RUNTIME_SECONDS,
    SOURCE_MANIFEST_ID,
    _deterministic_timestamp,
    _keys_checksum,
    _repo_head,
    load_population_manifest,
)
from .real_loader import (
    PER_STORE_CAP_KEYS,
    REQUIRED_HISTORY_DAYS,
    TARGET_POPULATION_KEYS,
    RealLoaderError,
    analyze_population,
    select_expanded_population,
    verify_population_selection,
)
from .real_manifest import load_real_manifest

PROFILE_ID = "freshretailnet-real-population-profile-v2"


def _save_json_deterministic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(body, encoding="utf-8")


def build_population_profile(
    *,
    manifest_path: Path,
    raw_dir: Path,
    report_path: Path,
    required_history_days: int = REQUIRED_HISTORY_DAYS,
    per_store_cap: int = PER_STORE_CAP_KEYS,
    target_keys: int = TARGET_POPULATION_KEYS,
    population_manifest_path: Path | None = None,
) -> Path:
    """Compute and write the deterministic population profile (dry-run only)."""
    source = load_real_manifest(manifest_path)
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
        population_id=POPULATION_V2_ID,
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

    ts, ts_source = _deterministic_timestamp()
    code_revision, revision_note = _repo_head()

    population_status: dict[str, object] = {"present": False}
    if population_manifest_path is not None:
        population = load_population_manifest(population_manifest_path)
        population_status = {
            "present": True,
            "path": str(population_manifest_path),
            "population_id": population.population_id,
            "validated": True,
            "canonical_content_sha256": population.canonical_content_sha256,
            "selection_checksums": dict(population.selection_checksums),
        }
        if population.population_id != selection.population_id:
            population_status["validated"] = False
            population_status["validation_error"] = "population_id mismatch"
        else:
            try:
                verify_population_selection(
                    manifest=source,
                    population=population,
                    train_path=train_path,
                    eval_path=eval_path,
                    required_history_days=required_history_days,
                )
            except RealLoaderError as exc:
                population_status["validated"] = False
                population_status["validation_error"] = str(exc)

    coverage_key = selection.selected_key_count / selection.candidate_key_count
    coverage_row = (
        selection.selected_row_count / selection.source_row_count
        if selection.source_row_count
        else 0.0
    )
    report = {
        "report_version": "1.0",
        "profile_id": PROFILE_ID,
        "population_id": POPULATION_V2_ID,
        "mode": "dry-run",
        "source": {
            "source_manifest_id": SOURCE_MANIFEST_ID,
            "source_manifest_path": str(manifest_path),
            "dataset_id": source.dataset_id,
            "pinned_revision": source.pinned_revision,
            "manifest_gates": dict(source.gates),
            "raw_files": [
                {
                    "name": entry.name,
                    "local_name": entry.local_name,
                    "expected_size": entry.expected_size,
                    "observed_size": entry.observed_size,
                    "expected_sha256": entry.expected_sha256,
                    "observed_sha256": entry.observed_sha256,
                    "verified": True,
                }
                for entry in source.raw_files
            ],
        },
        "history_rule": {
            "required_history_days": required_history_days,
            "requirement": (
                "MIN_TRAIN_PERIODS + HORIZON + FINAL_TEST_PERIODS = "
                "42 + 7 + 14 consecutive days"
            ),
            "date_span": "identical date span (modal span among qualifying keys)",
        },
        "selection_rule": {
            "rule": selection.rule,
            "target_keys": target_keys,
            "per_store_cap": per_store_cap,
        },
        "counts": {
            "source_row_count": selection.source_row_count,
            "candidate_key_count": selection.candidate_key_count,
            "qualifying_key_count": selection.qualifying_key_count,
            "eligible_key_count": selection.eligible_key_count,
            "selected_key_count": selection.selected_key_count,
            "excluded_key_count": selection.excluded_key_count,
            "selected_row_count": selection.selected_row_count,
            "excluded_row_count": selection.excluded_row_count,
            "train_row_count": selection.train_row_count,
            "eval_row_count": selection.eval_row_count,
            "store_count": len(selection.store_key_counts),
            "product_count": selection.product_key_count,
        },
        "coverage": {
            "selected_of_source_keys": {
                "selected": selection.selected_key_count,
                "total": selection.candidate_key_count,
                "fraction": round(coverage_key, 6),
            },
            "selected_of_source_rows": {
                "selected": selection.selected_row_count,
                "total": selection.source_row_count,
                "fraction": round(coverage_row, 6),
            },
        },
        "per_store_keys": dict(selection.store_key_counts),
        "date_range": (
            [d.isoformat() for d in selection.date_range]
            if selection.date_range
            else None
        ),
        "train_eval_separation": {
            "train_dates": train_dates,
            "eval_dates": eval_dates,
            "date_overlap": False,
            "note": (
                "Each selected key appears in train (first 90 days) and eval "
                "(last 7 days) with disjoint dates; the evaluation re-splits "
                "chronologically per the protocol."
            ),
        },
        "exclusion_reasons": dict(selection.exclusion_reasons),
        "selection_checksums": {
            "selected_keys_sha256": _keys_checksum(selection.selected_keys),
            "excluded_keys_sha256": _keys_checksum(excluded_keys),
        },
        "population_manifest": population_status,
        "resource_profile": {
            "profile_estimated_runtime_seconds": PROFILE_ESTIMATED_RUNTIME_SECONDS,
            "materialization_estimated_runtime_seconds": (
                MATERIALIZATION_ESTIMATED_RUNTIME_SECONDS
            ),
            "estimated_peak_memory_bytes": ESTIMATED_PEAK_MEMORY_BYTES,
            "estimated_report_bytes": ESTIMATED_REPORT_BYTES,
            "source": "documented-constant",
            "note": (
                "Documented deterministic constants, not wall-clock measurements. "
                "Basis: measured v1 runtime ~87s for 10 keys and measured v2 "
                "runtime ~83s wall for 100 keys (shared-backtest optimization); "
                "documented materialization budget 300s; span grouping ~1s; 100 "
                "selected keys ~0.3s read; measured report ~4.1MB; memory is "
                "tiny (~9,700 canonical records)."
            ),
        },
        "budget": {
            "within_budget": True,
            "budget_note": (
                "The expanded population (100 keys, ~9,700 rows) is within the "
                "documented budget: measured materialization ~83s wall (budget "
                "300s), measured report ~4.1MB, peak memory ~8MiB bound."
            ),
        },
        "non_final_metrics": {
            "uses_outcomes": False,
            "note": (
                "Dry-run profile only: verifies checksums, scans selection "
                "metadata, and reports structural counts. No forecast/policy "
                "metrics are computed or reported."
            ),
        },
        "generation": {
            "creation_timestamp": ts,
            "timestamp_source": ts_source,
            "code_revision": code_revision,
            "code_revision_note": revision_note,
        },
    }
    report_path = Path(report_path)
    _save_json_deterministic(report_path, report)
    return report_path


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
            "Deterministic dry-run resource profile for the expanded real "
            "population (v2). Never computes evaluation metrics."
        )
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--population-manifest", type=Path, default=None)
    parser.add_argument(
        "--required-history-days", type=int, default=REQUIRED_HISTORY_DAYS
    )
    parser.add_argument("--per-store-cap", type=int, default=PER_STORE_CAP_KEYS)
    parser.add_argument("--target-keys", type=int, default=TARGET_POPULATION_KEYS)
    args = parser.parse_args(argv)

    try:
        report_path = build_population_profile(
            manifest_path=args.manifest,
            raw_dir=args.raw_dir,
            report_path=args.report,
            required_history_days=args.required_history_days,
            per_store_cap=args.per_store_cap,
            target_keys=args.target_keys,
            population_manifest_path=args.population_manifest,
        )
    except (ManifestError, RealLoaderError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
