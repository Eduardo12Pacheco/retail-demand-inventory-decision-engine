from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SYNTHETIC_NOTICE = "Synthetic fixture — not a real business result"

ROBUSTNESS_NOTICE = (
    "Sensitivity analysis over modeled business assumptions — not observed "
    "retailer costs"
)
ROBUSTNESS_GENERALIZATION = (
    "Results are bounded to the deterministic v2 population and do not "
    "generalize to all retailers."
)
ROBUSTNESS_REPORT_NAME = "freshretailnet-robustness-report-v1.0.0.json"


def _load_report() -> dict:
    from retail_demand_inventory.evaluation.reports import load_json

    report_path = ROOT / "data/evaluations" / "experiment_report.json"
    if not report_path.exists():
        raise FileNotFoundError(
            f"report not found at {report_path}. Generate it with:\n"
            "    uv run python -m retail_demand_inventory.evaluation.materialize"
        )
    return load_json(report_path)


def _real_status_text() -> str:
    report_path = ROOT / "data/evaluations" / "freshretailnet-real-report.json"
    manifest_path = ROOT / "data/manifests" / "freshretailnet-real.json"
    if not report_path.exists():
        recovery = (
            "**Real-snapshot mode is unavailable** (report not found). "
            "To enable it, run once with network:\n\n"
            "    uv run python -m retail_demand_inventory.data.acquisition \\\n"
            "        --manifest data/manifests/freshretailnet-real.json --output-dir data/raw\n"
            "    uv run python -m retail_demand_inventory.data.schema_report \\\n"
            "        --manifest data/manifests/freshretailnet-real.json \\\n"
            "        --report data/reports/freshretailnet-real-schema.json\n"
            "    uv run python -m retail_demand_inventory.evaluation.materialize \\\n"
            "        --source real --manifest data/manifests/freshretailnet-real.json"
        )
        if not manifest_path.exists():
            recovery = (
                "**Real-snapshot mode is unavailable** (manifest and report not "
                "found). Acquire and evaluate the pinned snapshot with the "
                "commands documented in `docs/demo-script.md`."
            )
        return recovery

    from retail_demand_inventory.evaluation.reports import load_json

    report = load_json(report_path)
    dataset = report["dataset"]
    real = report.get("real", {})
    stockout = report["protocol"].get("stockout_semantics", {})
    lines = [
        (
            f"- **Label**: `{real.get('evaluation_label', dataset.get('evaluation_label'))}` — "
            "a bounded evaluation, NOT a full-dataset result; does not generalize."
        ),
        (
            f"- **Dataset**: {dataset.get('dataset_id')} · pinned revision "
            f"`{real.get('pinned_revision')}`"
        ),
        (
            f"- **Manifest**: `{dataset.get('manifest_path')}` · version "
            f"`{dataset.get('manifest_version')}` · gates verified"
        ),
        (
            f"- **Population**: {dataset['population']['selected_key_count']} of "
            f"{dataset['population']['qualifying_key_count']} qualifying keys, "
            f"{dataset['population']['selected_row_count']} of "
            f"{dataset['population']['source_row_count']} source rows "
            f"({dataset['population']['excluded_key_count']} keys excluded)"
        ),
        f"- **Canonical checksum**: `{real.get('canonical_content_sha256', '')[:16]}`…",
        f"- **Stockout semantics**: {stockout.get('rule')}",
        (
            "- **Observed sales vs unconstrained demand**: metrics and forecasts "
            "target observed sales; censored demand during stockouts is documented, "
            "not recovered."
        ),
    ]
    if real.get("repository_commit_sha"):
        lines.append(
            f"- **Code revision at generation**: `{real['repository_commit_sha'][:12]}` "
            f"({real.get('repository_commit_sha_note', '')})"
        )
    limitations = report.get("limitations", [])
    for limitation in limitations[:3]:
        lines.append(f"- **Limitation**: {limitation}")
    expanded = _expanded_status_text()
    if expanded:
        lines.append("")
        lines.append("**Expanded (v2) population status**")
        lines.append(expanded)
    return "\n".join(lines)


def _expanded_status_text() -> str:
    report_path = ROOT / "data/evaluations" / "freshretailnet-real-expanded-report.json"
    if not report_path.exists():
        return ""
    from retail_demand_inventory.evaluation.reports import load_json

    report = load_json(report_path)
    expanded = report.get("expanded", {})
    dataset = report["dataset"]
    agg = expanded.get("aggregates", {})
    stockout = expanded.get("stockout_semantics", {})
    lines = [
        (
            f"- **Label**: `{expanded.get('evaluation_label', dataset.get('evaluation_label'))}` — "
            "a bounded expanded evaluation, NOT a full-dataset result; does not generalize."
        ),
        (
            f"- **Population**: `{expanded.get('population_id')}` — "
            f"{expanded['population']['selected_key_count']} of "
            f"{expanded['population']['candidate_key_count']} keys across "
            f"{expanded['dimensions']['store_count']} stores / "
            f"{expanded['dimensions']['product_count']} products, "
            f"{expanded['dimensions']['train_row_count']} + "
            f"{expanded['dimensions']['eval_row_count']} train/eval rows"
        ),
        (f"- **Stockout semantics**: {stockout.get('rule')}"),
    ]
    final = agg.get("final_test_forecast", {})
    per_key = final.get("per_key", {})
    if per_key:
        mae = per_key.get("mae", {})
        lines.append(
            "- **Final-test MAE across keys** "
            f"(median {_fmt(mae.get('median'))}, p25 {_fmt(mae.get('p25'))}, "
            f"p75 {_fmt(mae.get('p75'))}, p95 {_fmt(mae.get('p95'))}) — "
            "describes the selected 100-key population only."
        )
    policy = agg.get("policy", {})
    constraint = policy.get("constraint_satisfaction", {})
    fallback = policy.get("fallback", {})
    if constraint:
        lines.append(
            f"- **Service constraint**: {constraint.get('keys_meeting_target')} keys "
            f"meeting the target, {constraint.get('keys_below_target')} below; "
            f"{fallback.get('infeasible_keys')} infeasible (documented fallback)."
        )
    limitations = report.get("limitations", [])
    for limitation in limitations[:2]:
        lines.append(f"- **Limitation**: {limitation}")
    return "\n".join(lines)


def _robustness_report():
    from retail_demand_inventory.evaluation.reports import load_json

    report_path = ROOT / "data/evaluations" / ROBUSTNESS_REPORT_NAME
    if not report_path.exists():
        return None
    return load_json(report_path)


def _robustness_status_text() -> str:
    report = _robustness_report()
    if report is None:
        return (
            "**Robustness report is not available** (no committed "
            "`freshretailnet-robustness-report-v1.0.0.json`)."
        )
    robustness = report["robustness"]
    facts = report["source_facts"]
    analysis = robustness["analysis"]
    overall = analysis["aggregate"]["overall"]
    population = facts.get("population", {})
    store_key_counts = population.get("store_key_counts")
    if isinstance(store_key_counts, dict):
        store_count = len(store_key_counts)
    else:
        store_count = population.get("store_count")
    product_count = population.get("product_key_count")
    if product_count is None:
        product_count = population.get("product_count")
    lines = [
        f"- **{ROBUSTNESS_NOTICE}**",
        f"- **{ROBUSTNESS_GENERALIZATION}**",
        (
            f"- **Population**: `{facts.get('population_id')}` — "
            f"{population.get('selected_key_count')} keys across "
            f"{store_count} stores / {product_count} products"
        ),
        (
            f"- **Scenarios**: {robustness['scenario_count']} frozen scenarios "
            f"(manifest `{robustness['scenario_manifest']['manifest_version']}`, "
            f"content sha256 `{robustness['scenario_manifest']['content_sha256'][:16]}`…)"
        ),
        (
            f"- **Policy retention across non-baseline scenarios**: "
            f"{overall.get('policy_retained_pct')}% retained, "
            f"{overall.get('policy_changed_pct')}% changed; "
            f"{overall.get('infeasible_pct')}% infeasible (documented fallback)."
        ),
        (
            "- **Modeled costs, lead times, and service targets are NOT "
            "observed retailer facts**; they are documented assumptions varied "
            "for sensitivity analysis."
        ),
    ]
    return "\n".join(lines)


def _robustness_comparison_table(sku: str, scenario_id: str) -> dict:
    report = _robustness_report()
    robustness = report["robustness"]
    scenarios = robustness["scenarios"]
    if scenario_id == "baseline-v1":
        return {}
    baseline_keys = scenarios["baseline-v1"]["keys"]
    if sku not in baseline_keys or sku not in scenarios[scenario_id]["keys"]:
        return _robustness_scenario_summary_table(sku, scenario_id, robustness)
    base = baseline_keys[sku]
    scenario = scenarios[scenario_id]["keys"][sku]

    def num(value) -> str:
        return "undefined" if value is None else f"{value:.4f}"

    base_rec = base["recommendation"]
    scen_rec = scenario["recommendation"]
    return {
        "metric": [
            "selected policy",
            "order quantity",
            "reorder point / order-up-to level",
            "simulated service level",
            "simulated fill rate",
            "simulated total cost",
            "simulated stockout units",
            "simulated avg inventory",
            "constraint satisfied (selection)",
        ],
        "baseline-v1": [
            base_rec["policy_id"],
            num(base_rec["order_quantity"]),
            num(base_rec["trigger_level"]),
            num(base_rec["simulated_service_level"]),
            num(base_rec["simulated_fill_rate"]),
            num(base_rec["simulated_total_cost"]),
            num(base_rec["simulated_stockout_units"]),
            num(base_rec["simulated_avg_inventory"]),
            str(base["selection"]["constraint_satisfied"]),
        ],
        scenario_id: [
            scen_rec["policy_id"],
            num(scen_rec["order_quantity"]),
            num(scen_rec["trigger_level"]),
            num(scen_rec["simulated_service_level"]),
            num(scen_rec["simulated_fill_rate"]),
            num(scen_rec["simulated_total_cost"]),
            num(scen_rec["simulated_stockout_units"]),
            num(scen_rec["simulated_avg_inventory"]),
            str(scenario["selection"]["constraint_satisfied"]),
        ],
    }


def _robustness_scenario_summary_table(
    sku: str, scenario_id: str, robustness: dict
) -> dict:
    summary = robustness["analysis"]["aggregate"]["per_scenario"][scenario_id]
    return {
        "metric": [
            f"SKU `{sku}` in the bounded real v2 report",
            "keys evaluated (bounded v2 real population)",
            "policy retained across real keys (scenario-level)",
            "policy changed across real keys (scenario-level)",
            "infeasible (documented fallback)",
            "constraint satisfied across real keys (scenario-level)",
        ],
        "value": [
            "no — fixture SKU has no real counterpart; per-key comparison unavailable",
            str(summary["key_count"]),
            f"{summary['policy_retained_pct']}%",
            f"{summary['policy_changed_pct']}%",
            f"{summary['infeasible_pct']}%",
            f"{summary['constraint_satisfied_pct']}%",
        ],
    }


def _load_fixture_table():
    from retail_demand_inventory.data import load_canonical_csv

    fixture_path = ROOT / "data/fixtures" / "freshretailnet_style_synthetic.csv"
    return load_canonical_csv(fixture_path)


def main() -> None:
    try:
        import streamlit as st
    except ImportError as exc:  # pragma: no cover - only reached at runtime
        raise SystemExit(
            "Streamlit is not installed. Install the demo extra:\n"
            "    uv sync --dev --extra demo"
        ) from exc

    st.set_page_config(
        page_title="Retail Demand Inventory Decision Engine", layout="wide"
    )
    st.title("Retail Demand — Inventory Decision Engine")
    st.markdown(
        f'<p style="color:white;background:#7f1d1d;padding:0.6em;border-radius:6px;font-weight:700;">{SYNTHETIC_NOTICE}</p>',
        unsafe_allow_html=True,
    )

    report = _load_report()
    table = _load_fixture_table()

    meta = report["meta"]
    dataset = report["dataset"]

    with st.expander("Experiment status", expanded=True):
        st.markdown(
            f"- **Data source**: `{dataset['source_label']}` — {dataset['name']}\n"
            f"- **Dataset license (fixture)**: {dataset['license_name']}\n"
            f"- **Checksum (sha256)**: `{dataset['checksum'][:16]}…` verified against `{dataset['file_path']}`\n"
            f"- **Seed**: `{meta['seed']}` · **generated_at**: `{meta['generated_at']}` (`{meta['timestamp_source']}`)\n"
            f"- **Versions**: package `{meta['package_version']}` · protocol `{meta['protocol_version']}` · schema `{meta['schema_version']}`"
        )
        st.markdown(
            "**Source contract vs fixture**: `docs/source-contract.md` documents the audited "
            "**FreshRetailNet-50K** dataset (Dingdong Limited, CC BY 4.0, pinned revision "
            "`08c1fab7f9257bc73679d415d65d644165d351d4`). The charts and numbers below "
            "come from the **synthetic development fixture**; a verified real-snapshot "
            "report, when present, is shown separately."
        )

    with st.expander("Real snapshot status (bounded evaluation)", expanded=False):
        st.markdown(_real_status_text())

    skus = report["overall"]["skus"]
    selected_sku = st.selectbox(
        "SKU",
        options=skus,
        format_func=lambda s: f"{s} — category {table.category_for(s)}",
    )
    section = report["per_sku"][selected_sku]

    robustness = _robustness_report()
    if robustness is not None:
        with st.expander(
            "Robustness (sensitivity over modeled business assumptions)",
            expanded=False,
        ):
            st.markdown(_robustness_status_text())
            scenario_ids = robustness["robustness"]["scenario_ids"]
            selected_scenario = st.selectbox(
                "Scenario",
                options=scenario_ids,
                index=1,
                format_func=lambda s: (
                    f"{s} — {robustness['robustness']['scenarios'][s]['definition']['label']}"
                ),
            )
            if selected_scenario != "baseline-v1":
                comparison = _robustness_comparison_table(
                    selected_sku, selected_scenario
                )
                if comparison:
                    if "value" in comparison:
                        st.markdown(
                            f"**`{selected_sku}` is a fixture SKU with no "
                            "counterpart in the real v2 report** — showing "
                            f"scenario-level stability across the bounded real "
                            f"report for `{selected_scenario}` vs `baseline-v1`:"
                        )
                    else:
                        st.markdown(
                            f"**Baseline-v1 vs `{selected_scenario}` for SKU "
                            f"`{selected_sku}`** (deployment-window outcome):"
                        )
                    st.table(comparison)
                summary = robustness["robustness"]["analysis"]["aggregate"][
                    "per_scenario"
                ][selected_scenario]
                st.markdown(
                    f"**Across all {summary['key_count']} keys**: "
                    f"policy retained {summary['policy_retained_pct']}%, changed "
                    f"{summary['policy_changed_pct']}%, infeasible "
                    f"{summary['infeasible_pct']}% (documented fallback)."
                )
                st.caption(
                    "Per-key deltas and the transition matrix are in the "
                    "committed robustness report."
                )
            st.caption(f"{ROBUSTNESS_NOTICE} · {ROBUSTNESS_GENERALIZATION}")

    history_dates = [d.isoformat() for d, _ in table.daily_series(selected_sku)]
    history_values = [v for _, v in table.daily_series(selected_sku)]
    ft = section["final_test"]
    dep = section["deployment_forecast"]

    st.subheader("Demand history and forecasts")
    st.line_chart(
        {
            "date": history_dates,
            "observed_history": history_values,
            "final_test_actual": _series(history_dates, ft["dates"], ft["actual"]),
            "final_test_forecast": _series(history_dates, ft["dates"], ft["predicted"]),
            "deployment_forecast": _series(history_dates, dep["dates"], dep["values"]),
        },
        x="date",
        y=[
            "observed_history",
            "final_test_actual",
            "final_test_forecast",
            "deployment_forecast",
        ],
    )

    st.subheader("Error metrics (final test, out of sample)")
    st.markdown(f"Model: **{ft['model_id']}** v{ft['model_version']}")
    st.table(_metrics_table(ft["metrics"]))

    st.subheader("Backtest — model comparison (validation folds only)")
    rows = []
    for m in section["backtest"]["models"]:
        rows.append(
            {
                "model_id": m["model_id"],
                "version": m["model_version"],
                "pooled_mae": _fmt(m["pooled_metrics"].get("mae")),
                "pooled_rmse": _fmt(m["pooled_metrics"].get("rmse")),
                "pooled_wmape": _fmt(m["pooled_metrics"].get("wmape")),
                "mean_fold_mase": _fmt(m["mean_of_fold_metrics"].get("mase")),
            }
        )
    st.table(rows)
    st.caption(
        "Selection rule: min pooled validation MAE, tie-break WMAPE then model_id. Final test is never used for selection."
    )

    st.subheader("Policy comparison (simulated on the last validation fold)")
    sel = section["policy_selection"]
    policy_rows = []
    for c in sel["candidates"]:
        policy_rows.append(
            {
                "policy_id": c["policy_id"],
                "params": str(c["policy_params"]),
                "service_level": _fmt(c["service_level"]),
                "fill_rate": _fmt(c["fill_rate"]),
                "stockout_units": _fmt(c["stockout_units"]),
                "stockout_events": c["stockout_events"],
                "total_cost": _fmt(c["total_cost"]),
                "selected": "yes" if c["run_id"] == sel["selected"]["run_id"] else "",
            }
        )
    st.table(policy_rows)
    st.caption(
        f"Target service level ≥ {sel['target_service_level']}. Constraint satisfied: "
        f"{sel['constraint_satisfied']}."
        + (f" Fallback: {sel['fallback_reason']}." if sel["fallback_reason"] else "")
    )

    st.subheader("Recommendation")
    rec = section["recommendation"]
    st.markdown(
        f"- **Policy**: `{rec['policy_id']}` v{rec['policy_version']} with params "
        f"`{rec['policy_params']}`\n"
        f"- **Order quantity (first order)**: `{_fmt(rec['order_quantity'])}` units\n"
        f"- **Simulated on the {rec['simulated_period']}** (deployment forecast): "
        f"service level `{_fmt(rec['simulated_service_level'])}` (target ≥ "
        f"{rec['service_level_target']}), fill rate `{_fmt(rec['simulated_fill_rate'])}`, "
        f"stockouts `{_fmt(rec['simulated_stockout_units'])}` units / "
        f"{rec['simulated_stockout_events']} events, avg inventory "
        f"`{_fmt(rec['simulated_avg_inventory'])}`, **total cost `{_fmt(rec['simulated_total_cost'])}`**\n"
        f"- **Objective**: {rec['objective']} · constraint satisfied: {rec['constraint_satisfied']}\n"
        f"- **Reason**: {rec['reason']}"
    )
    st.markdown(f"- **Evidence run ID**: `{rec['evidence']['recommendation_run_id']}`")

    st.subheader("Sensitivity (deployment forecast demand scaled)")
    sens_rows = [
        {
            "scale": scale,
            "service_level": _fmt(row["service_level"]),
            "fill_rate": _fmt(row["fill_rate"]),
            "total_cost": _fmt(row["total_cost"]),
            "run_id": rec["evidence"]["sensitivity_run_ids"][scale],
        }
        for scale, row in rec["sensitivity"].items()
    ]
    st.table(sens_rows)

    st.subheader("Assumptions and limitations")
    st.markdown("\n".join(f"- {a}" for a in report["assumptions"]))
    st.markdown("\n".join(f"- {l}" for l in report["limitations"]))

    st.caption(
        f"Evidence: backtest/final-test report `{rec['evidence']['backtest_report_path']}` · "
        f"dataset manifest `{dataset['file_path']}` · {SYNTHETIC_NOTICE}"
    )


def _series(
    all_dates: list[str], series_dates: list[str], values: list[float]
) -> list[float | None]:
    wanted = dict(zip(series_dates, values))
    return [wanted.get(d) for d in all_dates]


def _metrics_table(metrics: dict) -> dict:
    return {
        "metric": list(metrics),
        "value": [_fmt(v) for v in metrics.values()],
    }


def _fmt(value) -> str:
    if value is None:
        return "undefined"
    return f"{value:.4f}"


if __name__ == "__main__":
    main()
