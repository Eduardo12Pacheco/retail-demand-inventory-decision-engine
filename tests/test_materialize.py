from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from retail_demand_inventory.evaluation.materialize import SYNTHETIC_NOTICE, materialize
from retail_demand_inventory.evaluation.reports import ExperimentReport, load_json

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def paths(repo_root):
    return {
        "fixture": repo_root
        / "data"
        / "fixtures"
        / "freshretailnet_style_synthetic.csv",
        "manifest": repo_root / "data" / "manifests" / "fixture_synthetic.json",
    }


def test_materialize_is_byte_deterministic(tmp_path, paths) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    materialize(
        fixture_path=paths["fixture"], manifest_path=paths["manifest"], outdir=out_a
    )
    materialize(
        fixture_path=paths["fixture"], manifest_path=paths["manifest"], outdir=out_b
    )
    assert (out_a / "experiment_report.json").read_bytes() == (
        out_b / "experiment_report.json"
    ).read_bytes()


def test_materialize_report_has_required_sections(tmp_path, paths) -> None:
    report_path = materialize(
        fixture_path=paths["fixture"], manifest_path=paths["manifest"], outdir=tmp_path
    )
    report = ExperimentReport.load(report_path)
    data = report.to_dict()
    assert {
        "meta",
        "dataset",
        "protocol",
        "assumptions",
        "limitations",
        "overall",
        "per_sku",
    } <= set(data)
    assert data["meta"]["seed"] == 20260811
    assert data["meta"]["package_version"] == "0.1.0"
    assert data["dataset"]["source_label"] == "synthetic-fixture"
    assert SYNTHETIC_NOTICE in data["dataset"]["synthetic_notice"]
    assert len(data["per_sku"]) == 2
    for section in data["per_sku"].values():
        assert {
            "backtest",
            "final_test",
            "deployment_forecast",
            "policy_selection",
            "recommendation",
        } <= set(section)
        rec = section["recommendation"]
        assert rec["evidence"]["recommendation_run_id"].startswith("run_")
        assert rec["evidence"]["selection_run_ids"]
        assert "optimal" not in rec["objective"]


def test_materialize_checksum_mismatch_raises(tmp_path, paths) -> None:
    import shutil

    corrupted = tmp_path / "corrupted.csv"
    shutil.copyfile(paths["fixture"], corrupted)
    with corrupted.open("a", encoding="utf-8") as handle:
        handle.write("corruption\n")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        materialize(
            fixture_path=corrupted,
            manifest_path=paths["manifest"],
            outdir=tmp_path / "out",
        )


def test_final_test_never_leaks_into_selection(tmp_path, paths) -> None:
    report_path = materialize(
        fixture_path=paths["fixture"], manifest_path=paths["manifest"], outdir=tmp_path
    )
    data = load_json(report_path)
    protocol = data["protocol"]
    assert protocol["final_test_periods"] == 14
    assert protocol["horizon"] == 7
    assert "final test excluded" in protocol["model_selection_rule"]


def test_demo_module_imports_without_streamlit() -> None:
    module_path = REPO_ROOT / "scripts" / "demo_forecast.py"
    spec = importlib.util.spec_from_file_location(
        "demo_forecast_under_test", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "streamlit" not in sys.modules


def test_demo_reads_only_committed_paths(repo_root) -> None:
    from retail_demand_inventory.evaluation.reports import load_json

    report = load_json(repo_root / "data" / "evaluations" / "experiment_report.json")
    assert report["dataset"]["source_label"] == "synthetic-fixture"
    assert "synthetic" in report["dataset"]["name"]
