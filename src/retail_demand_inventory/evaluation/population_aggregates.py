from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

import numpy as np

from ..data.real_loader import ExpandedPopulationSelection
from .reports import round6

FINAL_TEST_METRICS = ("mae", "rmse", "wmape", "mase")
BACKTEST_METRICS = ("mae", "rmse", "wmape", "mase")
POLICY_METRICS = (
    "service_level",
    "fill_rate",
    "stockout_units",
    "stockout_events",
    "total_cost",
    "avg_inventory",
)


def _pct(values: np.ndarray, p: float) -> float:
    return round6(float(np.percentile(values, p)))


def distribution_stats(values: Sequence[float | None]) -> dict[str, object]:
    present = [v for v in values if v is not None]
    n = len(values)
    undefined = n - len(present)
    if not present:
        return {
            "count": n,
            "undefined": undefined,
            "mean": None,
            "sum": None,
            "median": None,
            "p25": None,
            "p75": None,
            "p95": None,
            "min": None,
            "max": None,
        }
    a = np.asarray(present, dtype=float)
    return {
        "count": n,
        "undefined": undefined,
        "mean": round6(float(a.mean())),
        "sum": round6(float(a.sum())),
        "median": _pct(a, 50),
        "p25": _pct(a, 25),
        "p75": _pct(a, 75),
        "p95": _pct(a, 95),
        "min": round6(float(a.min())),
        "max": round6(float(a.max())),
    }


def _pooled(actuals: Sequence[float], predicted: Sequence[float]) -> dict[str, object]:
    a = np.asarray(actuals, dtype=float)
    p = np.asarray(predicted, dtype=float)
    if a.size == 0:
        return {
            "count": 0,
            "mae": None,
            "rmse": None,
            "wmape": None,
            "mase": None,
        }
    errors = a - p
    mae = round6(float(np.mean(np.abs(errors))))
    rmse = round6(float(np.sqrt(np.mean(errors**2))))
    sum_abs = float(np.sum(np.abs(errors)))
    sum_a = float(np.sum(a))
    wmape = round6(sum_abs / sum_a) if sum_a > 0 else None
    return {
        "count": int(a.size),
        "mae": mae,
        "rmse": rmse,
        "wmape": wmape,
        "mase": None,
    }


def final_test_aggregates(
    per_sku: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    keys = sorted(per_sku)
    actuals: list[float] = []
    predicted: list[float] = []
    for key in keys:
        final_test = per_sku[key]["final_test"]
        actuals.extend(final_test["actual"])
        predicted.extend(final_test["predicted"])
    per_key = {
        metric: distribution_stats(
            [per_sku[key]["final_test"]["metrics"].get(metric) for key in keys]
        )
        for metric in FINAL_TEST_METRICS
    }
    return {
        "key_count": len(keys),
        "micro_pooled": _pooled(actuals, predicted),
        "macro_mean": {
            metric: per_key[metric]["mean"] for metric in FINAL_TEST_METRICS
        },
        "per_key": per_key,
        "note": (
            "micro_pooled is pooled over all keys' final-test actual/predicted "
            "values; MASE is per-key (in-sample naive scale) so its pooled value "
            "is undefined and it is reported at macro/per-key level only."
        ),
    }


def backtest_aggregates(
    per_sku: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    by_model: dict[str, dict[str, object]] = {}
    for key in sorted(per_sku):
        for summary in per_sku[key]["backtest"]["models"]:
            model_id = summary["model_id"]
            entry = by_model.setdefault(
                model_id,
                {
                    "model_version": summary["model_version"],
                    "pooled": {m: [] for m in BACKTEST_METRICS},
                    "mean_of_fold": {m: [] for m in BACKTEST_METRICS},
                    "count_insufficient_history": 0,
                    "count": 0,
                },
            )
            entry["count"] += int(summary.get("count", 0))
            entry["count_insufficient_history"] += int(
                summary.get("count_insufficient_history", 0)
            )
            for metric in BACKTEST_METRICS:
                entry["pooled"][metric].append(summary["pooled_metrics"].get(metric))
                entry["mean_of_fold"][metric].append(
                    summary["mean_of_fold_metrics"].get(metric)
                )
    out: dict[str, object] = {}
    for model_id in sorted(by_model):
        entry = by_model[model_id]
        out[model_id] = {
            "model_version": entry["model_version"],
            "count": entry["count"],
            "count_insufficient_history": entry["count_insufficient_history"],
            "pooled_metrics": {
                metric: distribution_stats(entry["pooled"][metric])
                for metric in BACKTEST_METRICS
            },
            "mean_of_fold_metrics": {
                metric: distribution_stats(entry["mean_of_fold"][metric])
                for metric in BACKTEST_METRICS
            },
        }
    return out


def per_fold_aggregates(
    per_sku: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    by_fold: dict[int, dict[str, dict[str, list[float | None]]]] = {}
    for key in sorted(per_sku):
        for row in per_sku[key]["backtest"]["per_fold"]:
            fold = by_fold.setdefault(row["fold_index"], {})
            entry = fold.setdefault(row["model_id"], {})
            for metric, value in row["metrics"].items():
                entry.setdefault(metric, []).append(value)
    out: list[dict[str, object]] = []
    for fold_index in sorted(by_fold):
        models = {
            model_id: {
                metric: distribution_stats(values)
                for metric, values in by_fold[fold_index][model_id].items()
            }
            for model_id in sorted(by_fold[fold_index])
        }
        out.append({"fold_index": fold_index, "models": models})
    return out


def policy_aggregates(per_sku: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    keys = sorted(per_sku)
    selected = [per_sku[key]["policy_selection"]["selected"] for key in keys]
    metrics = {
        name: distribution_stats([s.get(name) for s in selected])
        for name in POLICY_METRICS
    }
    satisfied = [
        bool(per_sku[key]["policy_selection"]["constraint_satisfied"]) for key in keys
    ]
    fallback_reasons = [
        per_sku[key]["policy_selection"].get("fallback_reason") for key in keys
    ]
    return {
        "key_count": len(keys),
        "selected_metrics": metrics,
        "micro": {
            "total_cost_sum": distribution_stats(
                [s.get("total_cost") for s in selected]
            )["sum"],
            "stockout_units_sum": distribution_stats(
                [s.get("stockout_units") for s in selected]
            )["sum"],
            "stockout_events_sum": distribution_stats(
                [s.get("stockout_events") for s in selected]
            )["sum"],
            "mean_service_level": distribution_stats(
                [s.get("service_level") for s in selected]
            )["mean"],
            "mean_fill_rate": distribution_stats(
                [s.get("fill_rate") for s in selected]
            )["mean"],
        },
        "constraint_satisfaction": {
            "keys_meeting_target": sum(satisfied),
            "keys_below_target": len(satisfied) - sum(satisfied),
        },
        "fallback": {
            "infeasible_keys": sum(1 for r in fallback_reasons if r is not None),
            "fallback_reason_counts": dict(
                Counter(r for r in fallback_reasons if r is not None)
            ),
        },
    }


def failed_undefined_counts(
    per_sku: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    final_undefined = 0
    final_defined = 0
    backtest_insufficient = 0
    policy_service_undefined = 0
    for key in sorted(per_sku):
        for value in per_sku[key]["final_test"]["metrics"].values():
            if value is None:
                final_undefined += 1
            else:
                final_defined += 1
        for row in per_sku[key]["backtest"]["per_fold"]:
            if row.get("insufficient_history"):
                backtest_insufficient += 1
        if per_sku[key]["policy_selection"]["selected"].get("service_level") is None:
            policy_service_undefined += 1
    return {
        "final_test_defined_metric_values": final_defined,
        "final_test_undefined_metric_values": final_undefined,
        "backtest_insufficient_history_rows": backtest_insufficient,
        "policy_selected_service_level_undefined_keys": policy_service_undefined,
    }


def build_expanded_section(
    *,
    per_sku: Mapping[str, Mapping[str, object]],
    selection: ExpandedPopulationSelection,
) -> dict[str, object]:
    return {
        "key_count": len(per_sku),
        "selection": selection.to_dict(),
        "final_test_forecast": final_test_aggregates(per_sku),
        "backtest": backtest_aggregates(per_sku),
        "per_fold": per_fold_aggregates(per_sku),
        "policy": policy_aggregates(per_sku),
        "failed_undefined": failed_undefined_counts(per_sku),
        "note": (
            "Aggregates are descriptive summaries over the 100-key population; "
            "they are NOT full-dataset results and do not generalize."
        ),
    }
