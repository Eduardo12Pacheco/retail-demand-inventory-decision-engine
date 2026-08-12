"""Focused offline tests for demo robustness helpers vs the committed report.

The demo is fixture-default: its two fixture SKUs (`1001|38`, `1002|65`) have
no counterpart in the real v2 robustness report, so per-key comparisons must
degrade to a bounded scenario-level summary instead of crashing.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

ROBUSTNESS_REPORT_NAME = "freshretailnet-robustness-report-v1.0.0.json"

FIXTURE_SKUS = ("1001|38", "1002|65")


def _load_demo_module():
    module_path = ROOT / "scripts" / "demo_forecast.py"
    spec = importlib.util.spec_from_file_location(
        "demo_robustness_under_test", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _committed_report():
    return json.loads(
        (ROOT / "data" / "evaluations" / ROBUSTNESS_REPORT_NAME).read_text()
    )


def test_robustness_status_text_renders_real_population_counts(repo_root) -> None:
    if not (repo_root / "data" / "evaluations" / ROBUSTNESS_REPORT_NAME).exists():
        pytest.skip("committed robustness report not generated yet")
    module = _load_demo_module()
    text = module._robustness_status_text()
    population = _committed_report()["source_facts"]["population"]

    store_count = len(population["store_key_counts"])
    product_count = population["product_key_count"]
    assert f"{population['selected_key_count']} keys across" in text
    assert f"{store_count} stores / {product_count} products" in text
    assert "None stores" not in text and "None products" not in text
    assert module.ROBUSTNESS_NOTICE in text
    assert module.ROBUSTNESS_GENERALIZATION in text


def test_robustness_status_text_defensive_shape_without_key_counts(
    repo_root, monkeypatch
) -> None:
    if not (repo_root / "data" / "evaluations" / ROBUSTNESS_REPORT_NAME).exists():
        pytest.skip("committed robustness report not generated yet")
    module = _load_demo_module()
    report = _committed_report()
    del report["source_facts"]["population"]["store_key_counts"]
    del report["source_facts"]["population"]["product_key_count"]
    report["source_facts"]["population"]["store_count"] = 7
    report["source_facts"]["population"]["product_count"] = 3
    monkeypatch.setattr(module, "_robustness_report", lambda: report)

    text = module._robustness_status_text()
    assert "7 stores / 3 products" in text


@pytest.mark.parametrize("sku", FIXTURE_SKUS)
def test_robustness_comparison_fixture_sku_returns_bounded_summary(
    repo_root, sku
) -> None:
    if not (repo_root / "data" / "evaluations" / ROBUSTNESS_REPORT_NAME).exists():
        pytest.skip("committed robustness report not generated yet")
    module = _load_demo_module()
    summary = module._robustness_comparison_table(sku, "holding-high")

    assert "value" in summary
    assert f"SKU `{sku}` in the bounded real v2 report" in summary["metric"]
    assert (
        "no — fixture SKU has no real counterpart"
        in summary["value"][
            summary["metric"].index(f"SKU `{sku}` in the bounded real v2 report")
        ]
    )
    committed = _committed_report()["robustness"]["analysis"]["aggregate"][
        "per_scenario"
    ]["holding-high"]
    assert f"{committed['key_count']}" in summary["value"]
    assert f"{committed['policy_retained_pct']}%" in summary["value"]


def test_robustness_comparison_real_key_keeps_per_key_shape(repo_root) -> None:
    if not (repo_root / "data" / "evaluations" / ROBUSTNESS_REPORT_NAME).exists():
        pytest.skip("committed robustness report not generated yet")
    module = _load_demo_module()
    real_key = "0|4"
    comparison = module._robustness_comparison_table(real_key, "holding-high")

    assert "value" not in comparison
    assert set(comparison) == {"metric", "baseline-v1", "holding-high"}
    assert comparison["metric"][0] == "selected policy"
    assert len(comparison["metric"]) == 9
    assert len(comparison["baseline-v1"]) == 9
    assert len(comparison["holding-high"]) == 9
    assert comparison["baseline-v1"][0] in {
        "reorder_point_order_quantity",
        "order_up_to",
    }


def test_robustness_comparison_baseline_scenario_is_empty(repo_root) -> None:
    if not (repo_root / "data" / "evaluations" / ROBUSTNESS_REPORT_NAME).exists():
        pytest.skip("committed robustness report not generated yet")
    module = _load_demo_module()
    assert module._robustness_comparison_table("1001|38", "baseline-v1") == {}
