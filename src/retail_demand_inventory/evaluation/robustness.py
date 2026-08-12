from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

import numpy as np

from ..decisions.scenarios import SCENARIO_ORDER
from .population_aggregates import distribution_stats
from .reports import round6

BASELINE_SCENARIO_ID = "baseline-v1"
QUANTILE_LEVELS = (25, 50, 75, 95)


def _ensure_complete_keys(scenarios: Mapping[str, Mapping[str, object]]) -> None:
    ids = list(scenarios)
    if BASELINE_SCENARIO_ID not in ids:
        raise ValueError(
            f"robustness analysis requires the {BASELINE_SCENARIO_ID!r} scenario"
        )
    baseline_keys = set(scenarios[BASELINE_SCENARIO_ID])
    if not baseline_keys:
        raise ValueError("baseline scenario has no keys")
    for scenario_id, sections in scenarios.items():
        if scenario_id == BASELINE_SCENARIO_ID:
            continue
        keys = set(sections)
        if keys != baseline_keys:
            missing = sorted(baseline_keys - keys)
            extra = sorted(keys - baseline_keys)
            raise ValueError(
                f"scenario {scenario_id!r} key set diverges from baseline: "
                f"{len(missing)} missing, {len(extra)} extra — hidden filtering "
                "would invalidate the analysis"
            )


def _delta(
    base: float | None, value: float | None, *, relative: bool = False
) -> float | None:
    if base is None or value is None:
        return None
    if relative:
        if base == 0:
            return None
        return round6((value - base) / base)
    return round6(value - base)


def _quantiles(values: Sequence[float | None]) -> dict[str, float | None]:
    present = [v for v in values if v is not None]
    if not present:
        return {f"p{p}": None for p in QUANTILE_LEVELS}
    a = np.asarray(present, dtype=float)
    return {f"p{p}": round6(float(np.percentile(a, p))) for p in QUANTILE_LEVELS}


def _section_metrics(section: Mapping[str, object]) -> dict[str, object]:
    rec = dict(section["recommendation"])
    selection = dict(section["selection"])
    return {
        "policy_id": str(rec["policy_id"]),
        "policy_params": dict(rec["policy_params"]),
        "order_quantity": rec.get("order_quantity"),
        "trigger_level": rec.get("trigger_level"),
        "service_level": rec.get("simulated_service_level"),
        "fill_rate": rec.get("simulated_fill_rate"),
        "total_cost": rec.get("simulated_total_cost"),
        "stockout_units": rec.get("simulated_stockout_units"),
        "stockout_events": rec.get("simulated_stockout_events"),
        "avg_inventory": rec.get("simulated_avg_inventory"),
        "constraint_satisfied": bool(selection["constraint_satisfied"]),
        "fallback_reason": selection.get("fallback_reason"),
    }


def per_key_baseline_comparison(
    scenarios: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    baseline = {
        key: _section_metrics(section)
        for key, section in scenarios[BASELINE_SCENARIO_ID].items()
    }
    out: dict[str, object] = {}
    for scenario_id in SCENARIO_ORDER:
        if scenario_id == BASELINE_SCENARIO_ID or scenario_id not in scenarios:
            continue
        per_key: dict[str, object] = {}
        for key in sorted(scenarios[scenario_id]):
            b = baseline[key]
            s = _section_metrics(scenarios[scenario_id][key])
            retained = b["policy_id"] == s["policy_id"]
            feasibility_regression = (
                b["constraint_satisfied"] and not s["constraint_satisfied"]
            )
            per_key[key] = {
                "baseline_policy_id": b["policy_id"],
                "scenario_policy_id": s["policy_id"],
                "policy_retained": retained,
                "policy_changed": not retained,
                "order_quantity": {
                    "baseline": b["order_quantity"],
                    "scenario": s["order_quantity"],
                    "absolute_delta": _delta(b["order_quantity"], s["order_quantity"]),
                    "relative_delta": _delta(
                        b["order_quantity"],
                        s["order_quantity"],
                        relative=True,
                    ),
                },
                "trigger_level": {
                    "baseline": b["trigger_level"],
                    "scenario": s["trigger_level"],
                    "absolute_delta": _delta(b["trigger_level"], s["trigger_level"]),
                    "relative_delta": _delta(
                        b["trigger_level"], s["trigger_level"], relative=True
                    ),
                },
                "service_level": {
                    "baseline": b["service_level"],
                    "scenario": s["service_level"],
                    "delta": _delta(b["service_level"], s["service_level"]),
                },
                "fill_rate": {
                    "baseline": b["fill_rate"],
                    "scenario": s["fill_rate"],
                    "delta": _delta(b["fill_rate"], s["fill_rate"]),
                },
                "total_cost": {
                    "baseline": b["total_cost"],
                    "scenario": s["total_cost"],
                    "absolute_delta": _delta(b["total_cost"], s["total_cost"]),
                    "relative_delta": _delta(
                        b["total_cost"], s["total_cost"], relative=True
                    ),
                },
                "stockout_units": {
                    "baseline": b["stockout_units"],
                    "scenario": s["stockout_units"],
                    "delta": _delta(b["stockout_units"], s["stockout_units"]),
                },
                "stockout_events": {
                    "baseline": b["stockout_events"],
                    "scenario": s["stockout_events"],
                    "delta": _delta(b["stockout_events"], s["stockout_events"]),
                },
                "avg_inventory": {
                    "baseline": b["avg_inventory"],
                    "scenario": s["avg_inventory"],
                    "delta": _delta(b["avg_inventory"], s["avg_inventory"]),
                },
                "constraint_satisfied_baseline": b["constraint_satisfied"],
                "constraint_satisfied_scenario": s["constraint_satisfied"],
                "feasibility_regression": feasibility_regression,
                "fallback_reason_scenario": s["fallback_reason"],
            }
        out[scenario_id] = per_key
    return out


def _summary_stats(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {
        "quantiles": {
            "order_quantity_relative_delta": _quantiles(
                [r["order_quantity"]["relative_delta"] for r in rows]
            ),
            "trigger_level_relative_delta": _quantiles(
                [r["trigger_level"]["relative_delta"] for r in rows]
            ),
            "total_cost_relative_delta": _quantiles(
                [r["total_cost"]["relative_delta"] for r in rows]
            ),
            "service_level_delta": _quantiles(
                [r["service_level"]["delta"] for r in rows]
            ),
            "stockout_units_delta": _quantiles(
                [r["stockout_units"]["delta"] for r in rows]
            ),
        },
        "distributions": {
            "order_quantity_relative_delta": distribution_stats(
                [r["order_quantity"]["relative_delta"] for r in rows]
            ),
            "trigger_level_relative_delta": distribution_stats(
                [r["trigger_level"]["relative_delta"] for r in rows]
            ),
            "total_cost_relative_delta": distribution_stats(
                [r["total_cost"]["relative_delta"] for r in rows]
            ),
            "service_level_delta": distribution_stats(
                [r["service_level"]["delta"] for r in rows]
            ),
            "stockout_units_delta": distribution_stats(
                [r["stockout_units"]["delta"] for r in rows]
            ),
            "stockout_events_delta": distribution_stats(
                [r["stockout_events"]["delta"] for r in rows]
            ),
        },
    }


def aggregate_summary(comparison: Mapping[str, object]) -> dict[str, object]:
    overall_retained = 0
    overall_pairs = 0
    overall_satisfied = 0
    overall_infeasible = 0
    overall_fallback = 0
    overall_regression = 0
    per_scenario: dict[str, object] = {}
    for scenario_id in SCENARIO_ORDER:
        if scenario_id == BASELINE_SCENARIO_ID or scenario_id not in comparison:
            continue
        rows = list(comparison[scenario_id].values())
        retained = sum(1 for r in rows if r["policy_retained"])
        satisfied = sum(1 for r in rows if r["constraint_satisfied_scenario"])
        infeasible = len(rows) - satisfied
        fallback = sum(1 for r in rows if r["fallback_reason_scenario"] is not None)
        regression = sum(1 for r in rows if r["feasibility_regression"])
        fallback_reason_counts = dict(
            Counter(
                r["fallback_reason_scenario"]
                for r in rows
                if r["fallback_reason_scenario"] is not None
            )
        )
        overall_retained += retained
        overall_pairs += len(rows)
        overall_satisfied += satisfied
        overall_infeasible += infeasible
        overall_fallback += fallback
        overall_regression += regression
        per_scenario[scenario_id] = {
            "key_count": len(rows),
            "policy_retained_count": retained,
            "policy_retained_pct": round6(retained / len(rows) * 100),
            "policy_changed_count": len(rows) - retained,
            "policy_changed_pct": round6((len(rows) - retained) / len(rows) * 100),
            "constraint_satisfied_count": satisfied,
            "constraint_satisfied_pct": round6(satisfied / len(rows) * 100),
            "infeasible_count": infeasible,
            "infeasible_pct": round6(infeasible / len(rows) * 100),
            "fallback_count": fallback,
            "fallback_pct": round6(fallback / len(rows) * 100),
            "fallback_reason_counts": fallback_reason_counts,
            "feasibility_regression_count": regression,
            "feasibility_regression_pct": round6(regression / len(rows) * 100),
            "summary_stats": _summary_stats(rows),
        }
    overall = {
        "scenario_key_pairs": overall_pairs,
        "policy_retained_count": overall_retained,
        "policy_retained_pct": (
            round6(overall_retained / overall_pairs * 100) if overall_pairs else None
        ),
        "policy_changed_count": overall_pairs - overall_retained,
        "policy_changed_pct": (
            round6((overall_pairs - overall_retained) / overall_pairs * 100)
            if overall_pairs
            else None
        ),
        "constraint_satisfied_count": overall_satisfied,
        "constraint_satisfied_pct": (
            round6(overall_satisfied / overall_pairs * 100) if overall_pairs else None
        ),
        "infeasible_count": overall_infeasible,
        "infeasible_pct": (
            round6(overall_infeasible / overall_pairs * 100) if overall_pairs else None
        ),
        "fallback_count": overall_fallback,
        "fallback_pct": (
            round6(overall_fallback / overall_pairs * 100) if overall_pairs else None
        ),
        "feasibility_regression_count": overall_regression,
        "feasibility_regression_pct": (
            round6(overall_regression / overall_pairs * 100) if overall_pairs else None
        ),
    }
    return {"overall": overall, "per_scenario": per_scenario}


def transition_matrix(comparison: Mapping[str, object]) -> dict[str, object]:
    out: dict[str, object] = {}
    aggregate: dict[str, Counter] = {}
    for scenario_id in SCENARIO_ORDER:
        if scenario_id == BASELINE_SCENARIO_ID or scenario_id not in comparison:
            continue
        matrix: dict[str, Counter] = {}
        for row in comparison[scenario_id].values():
            matrix.setdefault(row["baseline_policy_id"], Counter())[
                row["scenario_policy_id"]
            ] += 1
            aggregate.setdefault(row["baseline_policy_id"], Counter())[
                row["scenario_policy_id"]
            ] += 1
        out[scenario_id] = {
            baseline_policy: {
                scenario_policy: matrix[baseline_policy][scenario_policy]
                for scenario_policy in sorted(matrix[baseline_policy])
            }
            for baseline_policy in sorted(matrix)
        }
    out["aggregate_non_baseline"] = {
        baseline_policy: {
            scenario_policy: aggregate[baseline_policy][scenario_policy]
            for scenario_policy in sorted(aggregate[baseline_policy])
        }
        for baseline_policy in sorted(aggregate)
    }
    return out


def observed_tradeoffs(
    scenarios: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    per_scenario: dict[str, object] = {}
    cross: dict[str, dict[str, object]] = {}
    for scenario_id in SCENARIO_ORDER:
        if scenario_id not in scenarios:
            continue
        sections = list(scenarios[scenario_id].values())
        metrics = [_section_metrics(s) for s in sections]
        means: dict[str, float] = {}
        medians: dict[str, float] = {}
        for name in (
            "total_cost",
            "service_level",
            "fill_rate",
            "avg_inventory",
            "stockout_units",
        ):
            values = [m[name] for m in metrics if m[name] is not None]
            means[name] = round6(sum(values) / len(values)) if values else None
            medians[name] = (
                round6(float(np.median(np.asarray(values, dtype=float))))
                if values
                else None
            )
        holding = [
            s["recommendation"]["cost_components"]["total_holding_cost"]
            for s in sections
        ]
        stockout_cost = [
            s["recommendation"]["cost_components"]["total_stockout_cost"]
            for s in sections
        ]
        ordering = [
            s["recommendation"]["cost_components"]["total_ordering_cost"]
            for s in sections
        ]
        per_scenario[scenario_id] = {
            "key_count": len(sections),
            "cost_vs_service": {
                "mean_total_cost": means["total_cost"],
                "median_total_cost": medians["total_cost"],
                "mean_service_level": means["service_level"],
                "median_service_level": medians["service_level"],
            },
            "inventory_vs_fill": {
                "mean_avg_inventory": means["avg_inventory"],
                "median_avg_inventory": medians["avg_inventory"],
                "mean_fill_rate": means["fill_rate"],
                "median_fill_rate": medians["fill_rate"],
            },
            "stockouts_vs_holding": {
                "mean_stockout_cost": round6(sum(stockout_cost) / len(stockout_cost)),
                "mean_holding_cost": round6(sum(holding) / len(holding)),
                "mean_ordering_cost": round6(sum(ordering) / len(ordering)),
                "mean_stockout_units": means["stockout_units"],
                "median_stockout_units": medians["stockout_units"],
            },
        }
        for name, value in means.items():
            cross.setdefault(name, {})[scenario_id] = value
    return {
        "note": (
            "Neutral descriptive trade-off summaries over the deterministic v2 "
            "population under the frozen scenario matrix; they are observations, "
            "NOT Pareto-optimality or optimality claims."
        ),
        "per_scenario": per_scenario,
        "cross_scenario": {
            name: {
                sid: values[sid]
                for sid in SCENARIO_ORDER
                if sid in values and values[sid] is not None
            }
            for name, values in cross.items()
        },
    }


def robustness_analysis(
    scenarios: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    _ensure_complete_keys(scenarios)
    comparison = per_key_baseline_comparison(scenarios)
    return {
        "baseline_scenario_id": BASELINE_SCENARIO_ID,
        "scenario_ids": [sid for sid in SCENARIO_ORDER if sid in scenarios],
        "per_key_baseline_comparison": comparison,
        "aggregate": aggregate_summary(comparison),
        "transition_matrix": transition_matrix(comparison),
        "observed_tradeoffs": observed_tradeoffs(scenarios),
        "note": (
            "All deltas are scenario minus baseline-v1 per key over the "
            "deployment-window recommendation outcome; feasibility and fallback "
            "come from the policy-selection result. Relative deltas are "
            "undefined when the baseline value is zero. Nothing here is an "
            "optimality or Pareto claim."
        ),
    }
