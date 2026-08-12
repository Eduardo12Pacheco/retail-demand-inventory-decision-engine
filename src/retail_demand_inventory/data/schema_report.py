from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .manifests import ManifestError
from .real_loader import (
    MAX_POPULATION_KEYS,
    REQUIRED_HISTORY_DAYS,
    RealLoaderError,
    load_real_snapshot,
)
from .real_manifest import load_real_manifest


def _save_json_deterministic(path: Path, payload: dict) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(body, encoding="utf-8")


def build_schema_report(
    manifest_path: Path,
    report_path: Path,
    *,
    raw_dir: Path,
    required_history_days: int = REQUIRED_HISTORY_DAYS,
    max_keys: int = MAX_POPULATION_KEYS,
) -> Path:
    manifest = load_real_manifest(manifest_path)
    if not manifest.gates.get("snapshot_verified", False):
        raise RealLoaderError(
            "snapshot_verified gate is false; run acquisition before schema inspection"
        )
    result = load_real_snapshot(
        manifest,
        raw_dir,
        required_history_days=required_history_days,
        max_keys=max_keys,
    )
    report = result.schema_report(manifest, raw_dir)
    report_path = Path(report_path)
    _save_json_deterministic(report_path, report)

    updated = manifest.with_schema_record(
        canonical_content_sha256=result.canonical_sha256,
        schema_report_path=str(report_path),
        canonicalization_rule=report["canonical"]["canonicalization_rule"],
        stockout_derivation_rule=report["canonical"]["stockout_derivation_rule"],
    )
    updated.save(manifest_path)
    return report_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the deterministic schema report for the pinned real snapshot."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    args = parser.parse_args(argv)

    try:
        report_path = build_schema_report(
            args.manifest,
            args.report,
            raw_dir=args.raw_dir,
        )
    except (ManifestError, RealLoaderError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
