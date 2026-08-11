"""Evidence bundle attaching a recommendation to its reproducible inputs.

Every recommendation must be traceable to: the dataset manifest, the forecast
model and its version, the backtest/final-test report paths, the simulation
run IDs that scored every candidate and the sensitivity runs, and the
package/schema/protocol versions that produced it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceBundle:
    dataset_manifest: Mapping[str, object]
    source_label: str  # "synthetic-fixture" | "audited-source"
    forecast_models: tuple[Mapping[str, str], ...]  # {model_id, model_version}
    selected_model_id: str
    selected_model_version: str
    backtest_report_path: str
    final_test_report_path: str | None
    selection_run_ids: Mapping[str, str]  # policy_id -> run_id (selection window)
    recommendation_run_id: str
    sensitivity_run_ids: Mapping[str, str]  # scale -> run_id
    package_version: str
    schema_version: str
    protocol_version: str

    def to_dict(self) -> dict[str, object]:
        return {
            "dataset_manifest": dict(self.dataset_manifest),
            "source_label": self.source_label,
            "forecast_models": [dict(m) for m in self.forecast_models],
            "selected_model_id": self.selected_model_id,
            "selected_model_version": self.selected_model_version,
            "backtest_report_path": self.backtest_report_path,
            "final_test_report_path": self.final_test_report_path,
            "selection_run_ids": dict(self.selection_run_ids),
            "recommendation_run_id": self.recommendation_run_id,
            "sensitivity_run_ids": dict(self.sensitivity_run_ids),
            "package_version": self.package_version,
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
        }
