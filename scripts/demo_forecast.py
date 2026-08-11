"""Streamlit demo over the committed synthetic fixture and generated report.

Reads ONLY committed files under data/fixtures/, data/manifests/, and
data/evaluations/. No network access. Streamlit is imported lazily inside
`main` so importing this module is safe when the `demo` extra is not installed
(tests rely on that).

Every number shown is produced from the synthetic fixture. The exact phrase
`Synthetic fixture — not a real business result` is rendered prominently, and
the audited source contract is explicitly distinguished from the synthetic
development fixture.

Run:  uv run --extra demo streamlit run scripts/demo_forecast.py
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SYNTHETIC_NOTICE = "Synthetic fixture — not a real business result"


def _load_report() -> dict:
    from retail_demand_inventory.evaluation.reports import load_json

    report_path = ROOT / "data/evaluations" / "experiment_report.json"
    if not report_path.exists():
        raise FileNotFoundError(
            f"report not found at {report_path}. Generate it with:\n"
            "    uv run python -m retail_demand_inventory.evaluation.materialize"
        )
    return load_json(report_path)


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
            "`08c1fab7f9257bc73679d415d65d644165d351d4`). That source is **not retained** and was "
            "**not used** here. This demo runs on the **synthetic development fixture** below."
        )

    skus = report["overall"]["skus"]
    selected_sku = st.selectbox(
        "SKU",
        options=skus,
        format_func=lambda s: f"{s} — category {table.category_for(s)}",
    )
    section = report["per_sku"][selected_sku]

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
    """Align a sparse series onto the full date axis (None where absent)."""
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
