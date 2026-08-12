from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..data import (
    DemandTable,
    load_canonical_csv,
    load_manifest,
)
from ..data.population_manifest import load_population_manifest
from ..data.real_loader import REQUIRED_HISTORY_DAYS, load_real_snapshot
from ..data.real_manifest import load_real_manifest
from ..data.splits import expanding_origins
from ..decisions import (
    PolicyCandidate,
    generate_candidates,
    select_policy,
)
from ..decisions.recommendation import _policy_from_params, _scale_demand
from ..decisions.scenarios import (
    DEMAND_STRESS_SCOPE,
    RobustnessScenariosManifest,
    ScenarioDefinition,
    load_scenarios_manifest,
)
from ..forecasting import Forecaster
from ..simulation import DemandSource, SimulationConfig, SimulationInput, simulate
from ..versions import PACKAGE_VERSION, PROTOCOL_VERSION, SCHEMA_VERSION
from .backtesting import (
    BacktestReport,
    evaluate_final_test,
    run_backtest,
    select_best_model,
)
from .materialize import (
    FINAL_TEST_PERIODS,
    HOLDING_COST_PER_UNIT_PER_DAY,
    HORIZON,
    LEAD_TIME_DAYS,
    MIN_TRAIN_PERIODS,
    ORDERING_COST_PER_ORDER,
    REVIEW_PERIOD_DAYS,
    SEED,
    SENSITIVITY_SCALES,
    SERVICE_LEVEL_TARGET,
    STOCKOUT_COST_PER_UNIT,
    SYNTHETIC_NOTICE,
    _demand_values,
    _deployment_forecast,
    _deterministic_timestamp,
    _manifest_summary,
    _real_dataset_summary,
    _relative_or_abs,
    _repo_commit,
    _repo_root,
    _sku_stats,
    _summaries_for,
    build_models,
    model_for_id,
)
from .reports import round6, save_json
from .robustness import robustness_analysis

ROBUSTNESS_REPORT_NAME = "freshretailnet-robustness-report-v1.0.0.json"
FIXTURE_ROBUSTNESS_REPORT_NAME = "fixture-robustness-report-v1.0.0.json"
ROBUSTNESS_REPORT_VERSION = "1.0"

ROBUSTNESS_SOURCE_LABEL = "real-freshretailnet-expanded-robustness"
ROBUSTNESS_EVAL_LABEL = (
    "Deterministic robustness evaluation over the v2 population "
    "(modeled business assumptions)"
)
ROBUSTNESS_NOTICE = (
    "Sensitivity analysis over modeled business assumptions — not observed "
    "retailer costs"
)
ROBUSTNESS_GENERALIZATION = (
    "Results are bounded to the deterministic v2 population and do not "
    "generalize to all retailers."
)

ROBUSTNESS_RUNTIME_BUDGET_SECONDS = 600
ROBUSTNESS_RUNTIME_NOTE = (
    "Documented deterministic constant (not wall-clock): basis v2 "
    "materialization ~83s for 100 keys plus 12 scenarios x 100 keys of "
    "selection/recommendation simulations over short windows."
)

ROBUSTNESS_ASSUMPTIONS = (
    (
        "Modeled costs, lead times, and service targets are NOT observed "
        "retailer facts; they are documented business assumptions varied for "
        "sensitivity analysis."
    ),
    (
        "The v2 population, forecast models/versions, candidate policy "
        "families/versions, seed, horizon, and temporal folds are identical to "
        "the primary v2 evaluation for every scenario."
    ),
    (
        "Policy candidate selection always uses the observed selection-window "
        "demand unscaled; a scenario demand scale applies only to "
        "deployment/simulation stress."
    ),
    (
        "Scenario reruns vary only the declared simulation assumptions and "
        "the demand-stress scale; no forecast is retrained and no policy is "
        "tuned from scenario outcomes."
    ),
    (
        "Sales lost during a stockout are lost, not backlogged; demand is "
        "exogenous to the policy; supply is unlimited; no perishability, "
        "quantity discounts, or capacity limits."
    ),
    (
        "Holding cost is charged on end-of-day on-hand inventory; ordering "
        "cost per order placed; stockout cost per lost unit; effective costs "
        "are the baseline costs times the declared multipliers."
    ),
    "The baseline-v1 scenario reproduces the current v2 decisions.",
)

ROBUSTNESS_LIMITATIONS = (
    (
        "All numbers are sensitivity analyses over the deterministic v2 "
        "population; they are NOT observed retailer costs and do not "
        "generalize to other keys, periods, or retailers."
    ),
    (
        "Modeled costs, lead times, and service targets are assumptions, not "
        "measured business facts."
    ),
    (
        "The demand-stress scenario models a controlled 1.30 forecast-stress "
        "scale on scenario simulation only; source demand, forecast training, "
        "and the primary v2 evaluation are untouched."
    ),
    (
        "No scenario result is an optimality or Pareto claim; summaries are "
        "neutral observed_tradeoffs."
    ),
    (
        "Raw data stays in the gitignored data/raw/; this report records raw "
        "and canonical checksums only."
    ),
    ("No production-readiness claim is made from this bounded robustness evaluation."),
)


class RobustnessError(ValueError):
    pass


def _validate_scenarios_against_source(
    scenarios: RobustnessScenariosManifest,
    source,
    population,
) -> None:
    if scenarios.source_manifest_revision != source.pinned_revision:
        raise RobustnessError(
            "scenario manifest revision divergence: scenarios record "
            f"{scenarios.source_manifest_revision!r}, source manifest records "
            f"{source.pinned_revision!r}"
        )
    if scenarios.source_manifest_id != population.source_manifest_id:
        raise RobustnessError(
            "scenario manifest source id divergence: scenarios record "
            f"{scenarios.source_manifest_id!r}, population manifest records "
            f"{population.source_manifest_id!r}"
        )
    if scenarios.population_manifest_id != population.population_id:
        raise RobustnessError(
            "scenario manifest population id divergence: scenarios record "
            f"{scenarios.population_manifest_id!r}, population manifest records "
            f"{population.population_id!r}"
        )


def _compute_sku_invariants(
    *,
    table: DemandTable,
    sku: str,
    splits,
    models: Sequence[Forecaster],
    backtest: BacktestReport,
    horizon: int,
) -> dict[str, object]:
    stats = _sku_stats(table, sku)
    sku_folds = tuple(ff for ff in backtest.folds if ff.sku == sku)
    sku_summaries = _summaries_for(sku_folds)
    selected = select_best_model(sku_summaries)
    final_test = evaluate_final_test(
        table, sku, model_for_id(selected.model_id), splits
    )
    deployment_dates, deployment_values, dep_model_id, dep_model_version = (
        _deployment_forecast(table, sku, model_for_id(selected.model_id), horizon)
    )
    last_fold = splits.folds[-1]
    selection_dates = last_fold.validation_dates
    selection_demand = _demand_values(table, sku, selection_dates)
    return {
        "sku": sku,
        "category": table.category_for(sku),
        "stats": stats,
        "selected": selected,
        "final_test": final_test,
        "deployment_dates": deployment_dates,
        "deployment_values": deployment_values,
        "dep_model_id": dep_model_id,
        "dep_model_version": dep_model_version,
        "selection_dates": selection_dates,
        "selection_demand": selection_demand,
    }


def _trigger_level(policy_id: str, policy_params: Mapping[str, object]) -> float:
    if policy_id == "reorder_point_order_quantity":
        return float(policy_params["reorder_point"])
    if policy_id == "order_up_to_safety_stock":
        return float(policy_params["order_up_to_level"])
    raise RobustnessError(f"unknown policy id: {policy_id}")


def _build_robustness_sku_section(
    *,
    invariants: Mapping[str, object],
    scenario: ScenarioDefinition,
    models: Sequence[Forecaster],
    seed: int,
    horizon: int,
    report_name: str,
    generated_at: str,
) -> dict[str, object]:
    sku = str(invariants["sku"])
    stats = invariants["stats"]
    lead = scenario.lead_time_days
    review = scenario.review_period_days
    config = SimulationConfig(
        sku=sku,
        initial_inventory=round(stats.mean_daily * (lead + review), 2),
        lead_time_days=lead,
        review_period_days=review,
        holding_cost_per_unit_per_day=round6(
            HOLDING_COST_PER_UNIT_PER_DAY * scenario.cost_multipliers["holding"]
        ),
        stockout_cost_per_unit=round6(
            STOCKOUT_COST_PER_UNIT * scenario.cost_multipliers["stockout"]
        ),
        ordering_cost_per_order=round6(
            ORDERING_COST_PER_ORDER * scenario.cost_multipliers["ordering"]
        ),
    )

    policies = generate_candidates(
        stats, lead_time_days=lead, review_period_days=review
    )
    selection_source = DemandSource(kind="observed", reference="last_validation_fold")
    candidate_rows: list[dict[str, object]] = []
    candidate_outcomes = []
    for policy in policies:
        outcome = simulate(
            SimulationInput(
                dates=tuple(invariants["selection_dates"]),
                demand=tuple(invariants["selection_demand"]),
                config=config,
                policy=policy,
                seed=seed,
                demand_source=selection_source,
            )
        )
        candidate_outcomes.append(outcome)
        candidate_rows.append(
            {
                "policy_id": outcome.policy_id,
                "policy_version": outcome.policy_version,
                "policy_params": dict(outcome.policy_params),
                "run_id": outcome.run_id,
                "service_level": outcome.service_level,
                "fill_rate": outcome.fill_rate,
                "total_cost": round6(outcome.total_cost),
                "stockout_units": round6(outcome.lost_units),
                "stockout_events": outcome.stockout_events,
                "avg_inventory": round6(outcome.avg_inventory),
                "first_order_quantity": round6(outcome.first_order_quantity),
                "cost_components": {
                    "total_ordering_cost": round6(outcome.total_ordering_cost),
                    "total_holding_cost": round6(outcome.total_holding_cost),
                    "total_stockout_cost": round6(outcome.total_stockout_cost),
                },
            }
        )
    candidates = tuple(PolicyCandidate.from_outcome(o) for o in candidate_outcomes)
    selection = select_policy(candidates, scenario.service_level_target)

    selected_policy = _policy_from_params(
        selection.selected.policy_id, selection.selected.policy_params
    )
    stress_scale = float(scenario.demand_stress["scale"])
    if stress_scale == 1.0:
        rec_demand = _scale_demand(tuple(invariants["deployment_values"]), 1.0)
        rec_reference = "deployment_forecast"
    else:
        rec_demand = _scale_demand(tuple(invariants["deployment_values"]), stress_scale)
        rec_reference = f"deployment_forecast_stress_{stress_scale}"
    rec_source = DemandSource(
        kind="forecast",
        model_id=str(invariants["dep_model_id"]),
        model_version=str(invariants["dep_model_version"]),
        reference=rec_reference,
    )
    rec_outcome = simulate(
        SimulationInput(
            dates=tuple(invariants["deployment_dates"]),
            demand=rec_demand,
            config=config,
            policy=selected_policy,
            seed=seed,
            demand_source=rec_source,
        )
    )

    sensitivity: dict[str, Mapping[str, float | None]] = {}
    sensitivity_run_ids: dict[str, str] = {}
    for scale in SENSITIVITY_SCALES:
        effective = round6(stress_scale * float(scale))
        scaled_input = SimulationInput(
            dates=tuple(invariants["deployment_dates"]),
            demand=_scale_demand(tuple(invariants["deployment_values"]), effective),
            config=config,
            policy=selected_policy,
            seed=seed,
            demand_source=DemandSource(
                kind="forecast",
                model_id=str(invariants["dep_model_id"]),
                model_version=str(invariants["dep_model_version"]),
                reference=f"deployment_forecast_scaled_{scale}",
            ),
        )
        outcome = simulate(scaled_input)
        key = f"scale_{scale}"
        sensitivity[key] = {
            "service_level": outcome.service_level,
            "fill_rate": outcome.fill_rate,
            "total_cost": round6(outcome.total_cost),
        }
        sensitivity_run_ids[key] = outcome.run_id

    policy_params = dict(selection.selected.policy_params)
    return {
        "scenario_id": scenario.scenario_id,
        "key": sku,
        "category": invariants["category"],
        "forecast": {
            "models": [
                {"model_id": m.model_id, "model_version": m.model_version}
                for m in models
            ],
            "selected_model_id": str(invariants["selected"].model_id),
            "selected_model_version": str(invariants["selected"].model_version),
            "horizon": horizon,
        },
        "seed": seed,
        "target_service_level": scenario.service_level_target,
        "assumptions": {
            "lead_time_days": lead,
            "review_period_days": review,
            "cost_multipliers": dict(scenario.cost_multipliers),
            "effective_costs": {
                "holding_cost_per_unit_per_day": config.holding_cost_per_unit_per_day,
                "stockout_cost_per_unit": config.stockout_cost_per_unit,
                "ordering_cost_per_order": config.ordering_cost_per_order,
            },
            "demand_stress": dict(scenario.demand_stress),
        },
        "config": config.to_dict(),
        "selection": {
            "candidates": candidate_rows,
            "selected": selection.selected.to_dict(),
            "target_service_level": selection.target_service_level,
            "objective": selection.objective,
            "constraint_satisfied": selection.constraint_satisfied,
            "fallback_reason": selection.fallback_reason,
            "reason": selection.reason,
        },
        "recommendation": {
            "policy_id": selection.selected.policy_id,
            "policy_version": selection.selected.policy_version,
            "policy_params": policy_params,
            "order_quantity": round6(rec_outcome.first_order_quantity),
            "trigger_level": round6(
                _trigger_level(selection.selected.policy_id, policy_params)
            ),
            "trigger_level_note": (
                "reorder_point for reorder_point_order_quantity; "
                "order_up_to_level for order_up_to_safety_stock"
            ),
            "simulated_period": "deployment forecast window (scenario assumptions)",
            "simulated_service_level": rec_outcome.service_level,
            "simulated_fill_rate": rec_outcome.fill_rate,
            "simulated_total_cost": round6(rec_outcome.total_cost),
            "simulated_stockout_units": round6(rec_outcome.lost_units),
            "simulated_stockout_events": rec_outcome.stockout_events,
            "simulated_avg_inventory": round6(rec_outcome.avg_inventory),
            "cost_components": {
                "total_ordering_cost": round6(rec_outcome.total_ordering_cost),
                "total_holding_cost": round6(rec_outcome.total_holding_cost),
                "total_stockout_cost": round6(rec_outcome.total_stockout_cost),
                "total_cost": round6(rec_outcome.total_cost),
            },
            "run_id": rec_outcome.run_id,
            "sensitivity_run_ids": dict(sensitivity_run_ids),
            "sensitivity": {str(k): dict(v) for k, v in sorted(sensitivity.items())},
            "evidence_path": report_name,
        },
        "evidence_path": report_name,
        "generated_at": generated_at,
    }


def _compute_scenario_sections(
    *,
    table: DemandTable,
    models: Sequence[Forecaster],
    backtest: BacktestReport,
    splits,
    scenarios_manifest: RobustnessScenariosManifest,
    report_name: str,
    generated_at: str,
    seed: int,
    horizon: int,
) -> dict[str, Mapping[str, Mapping[str, object]]]:
    invariants = {
        sku: _compute_sku_invariants(
            table=table,
            sku=sku,
            splits=splits,
            models=models,
            backtest=backtest,
            horizon=horizon,
        )
        for sku in table.skus
    }
    sections: dict[str, Mapping[str, Mapping[str, object]]] = {}
    for scenario_id in scenarios_manifest.scenario_ids:
        scenario = scenarios_manifest.scenarios[scenario_id]
        per_key: dict[str, Mapping[str, object]] = {}
        for sku in table.skus:
            per_key[sku] = _build_robustness_sku_section(
                invariants=invariants[sku],
                scenario=scenario,
                models=models,
                seed=seed,
                horizon=horizon,
                report_name=report_name,
                generated_at=generated_at,
            )
        sections[scenario_id] = per_key
    return sections


def _modeled_assumptions_section(
    scenarios_manifest: RobustnessScenariosManifest,
) -> dict[str, object]:
    scenarios = scenarios_manifest.scenarios
    return {
        "note": (
            "Modeled costs, lead times, and service targets are NOT observed "
            "retailer facts; they are documented business assumptions varied "
            "for sensitivity analysis."
        ),
        "service_level_targets": {
            sid: scenarios[sid].service_level_target
            for sid in scenarios_manifest.scenario_ids
        },
        "lead_time_days": {
            sid: scenarios[sid].lead_time_days
            for sid in scenarios_manifest.scenario_ids
        },
        "review_period_days": {
            sid: scenarios[sid].review_period_days
            for sid in scenarios_manifest.scenario_ids
        },
        "cost_multipliers": {
            sid: dict(scenarios[sid].cost_multipliers)
            for sid in scenarios_manifest.scenario_ids
        },
        "demand_stress": {
            sid: dict(scenarios[sid].demand_stress)
            for sid in scenarios_manifest.scenario_ids
        },
        "demand_stress_scope": DEMAND_STRESS_SCOPE,
        "sensitivity_scales": list(SENSITIVITY_SCALES),
        "selection_window_demand_scale": scenarios_manifest.selection_window_demand_scale,
    }


def _assemble_report(
    *,
    meta: Mapping[str, object],
    dataset: Mapping[str, object],
    protocol: Mapping[str, object],
    source_facts: Mapping[str, object],
    modeled_assumptions: Mapping[str, object],
    assumptions: Sequence[str],
    limitations: Sequence[str],
    overall: Mapping[str, object],
    robustness: Mapping[str, object],
) -> dict[str, object]:
    return {
        "meta": dict(meta),
        "dataset": dict(dataset),
        "protocol": dict(protocol),
        "source_facts": dict(source_facts),
        "modeled_assumptions": dict(modeled_assumptions),
        "assumptions": list(assumptions),
        "limitations": list(limitations),
        "overall": dict(overall),
        "robustness": dict(robustness),
    }


def _robustness_section(
    *,
    scenarios_manifest: RobustnessScenariosManifest,
    scenario_manifest_path: Path,
    sections: Mapping[str, Mapping[str, Mapping[str, object]]],
    analysis: Mapping[str, object],
) -> dict[str, object]:
    return {
        "scenario_count": len(scenarios_manifest.scenario_ids),
        "scenario_ids": list(scenarios_manifest.scenario_ids),
        "scenario_manifest_path": _relative_or_abs(scenario_manifest_path),
        "scenario_manifest": scenarios_manifest.to_dict(),
        "scenarios": {
            sid: {
                "definition": scenarios_manifest.scenarios[sid].to_dict(),
                "keys": {key: dict(section) for key, section in per_key.items()},
            }
            for sid, per_key in sections.items()
        },
        "analysis": dict(analysis),
    }


def _run_common(
    *,
    table: DemandTable,
    models: Sequence[Forecaster],
    scenarios_manifest: RobustnessScenariosManifest,
    scenario_manifest_path: Path,
    report_name: str,
    seed: int,
    horizon: int,
    meta: Mapping[str, object],
    dataset: Mapping[str, object],
    protocol: Mapping[str, object],
    source_facts: Mapping[str, object],
    modeled_assumptions: Mapping[str, object],
    assumptions: Sequence[str],
    limitations: Sequence[str],
    overall_extra: Mapping[str, object],
) -> dict[str, object]:
    calendar = tuple(sorted({r.date for r in table.records}))
    splits = expanding_origins(
        calendar,
        min_train_periods=MIN_TRAIN_PERIODS,
        horizon=horizon,
        final_test_periods=FINAL_TEST_PERIODS,
    )
    backtest = run_backtest(table, models, splits.folds, horizon=horizon)

    sections = _compute_scenario_sections(
        table=table,
        models=models,
        backtest=backtest,
        splits=splits,
        scenarios_manifest=scenarios_manifest,
        report_name=report_name,
        generated_at=str(meta["generated_at"]),
        seed=seed,
        horizon=horizon,
    )
    analysis = robustness_analysis(sections)

    overall = {
        "skus": list(table.skus),
        "categories": list(table.categories),
        "num_folds": len(splits.folds),
        "models": [
            {
                "model_id": m.model_id,
                "model_version": m.model_version,
                "min_history": m.min_history,
            }
            for m in models
        ],
        "calendar_start": calendar[0].isoformat(),
        "calendar_end": calendar[-1].isoformat(),
        "final_test_start": splits.final_test_dates[0].isoformat(),
        "final_test_end": splits.final_test_dates[-1].isoformat(),
        "scenario_count": len(scenarios_manifest.scenario_ids),
        "key_count": len(table.skus),
    }
    overall.update(overall_extra)

    robustness = _robustness_section(
        scenarios_manifest=scenarios_manifest,
        scenario_manifest_path=scenario_manifest_path,
        sections=sections,
        analysis=analysis,
    )
    return _assemble_report(
        meta=meta,
        dataset=dataset,
        protocol=protocol,
        source_facts=source_facts,
        modeled_assumptions=modeled_assumptions,
        assumptions=assumptions,
        limitations=limitations,
        overall=overall,
        robustness=robustness,
    )


def materialize_robustness_real(
    *,
    source_manifest_path: Path,
    population_path: Path,
    scenario_manifest_path: Path,
    raw_dir: Path,
    outdir: Path,
) -> Path:
    source = load_real_manifest(source_manifest_path)
    source.require_gates()
    source.require_raw_ok(raw_dir)
    population = load_population_manifest(population_path)
    scenarios_manifest = load_scenarios_manifest(scenario_manifest_path)
    _validate_scenarios_against_source(scenarios_manifest, source, population)

    result = load_real_snapshot(
        source,
        raw_dir,
        required_history_days=REQUIRED_HISTORY_DAYS,
        population=population,
    )
    if result.canonical_sha256 != population.canonical_content_sha256:
        raise RobustnessError(
            "canonical checksum mismatch for expanded population: canonical "
            f"{result.canonical_sha256} != population manifest "
            f"{population.canonical_content_sha256}"
        )

    table = result.table
    models = build_models()
    generated_at, timestamp_source = _deterministic_timestamp()
    dataset = _real_dataset_summary(
        source,
        result,
        raw_dir,
        source_manifest_path,
        source_label=ROBUSTNESS_SOURCE_LABEL,
        evaluation_label=ROBUSTNESS_EVAL_LABEL,
    )
    commit_sha, commit_note = _repo_commit()

    source_facts = {
        "note": (
            "Facts observed from the pinned source snapshot and the v2 "
            "population; they are never changed by a scenario."
        ),
        "dataset_id": source.dataset_id,
        "pinned_revision": source.pinned_revision,
        "manifest_version": source.manifest_version,
        "source_manifest_path": _relative_or_abs(source_manifest_path),
        "raw_checksums": {
            entry.name: {
                "expected_sha256": entry.expected_sha256,
                "observed_sha256": entry.observed_sha256,
                "expected_size": entry.expected_size,
                "observed_size": entry.observed_size,
            }
            for entry in source.raw_files
        },
        "canonical_content_sha256": result.canonical_sha256,
        "canonicalization_version": source.canonicalization_version,
        "stockout_derivation_version": source.stockout_derivation_version,
        "stockout_derivation_rule": source.stockout_derivation_rule,
        "observed_sales_semantics": (
            "metrics and forecasts target observed sales; censored demand "
            "during stockouts is documented, not recovered"
        ),
        "population_id": population.population_id,
        "population_manifest_path": _relative_or_abs(population_path),
        "population": result.selection.to_dict(),
        "loading_summary": {
            "rejected_by_reason": dict(result.rejected_by_reason),
            "gap_fill_records": result.gap_fill_records,
            "duplicate_rows": result.duplicate_count,
            "unknown_stockout_records": result.unknown_stockout_records,
        },
    }

    protocol = {
        "frequency": "daily",
        "horizon": HORIZON,
        "min_train_periods": MIN_TRAIN_PERIODS,
        "final_test_periods": FINAL_TEST_PERIODS,
        "split_policy": (
            "expanding-window rolling origins; step = horizon; final test "
            "untouched; identical for every scenario"
        ),
        "seed": SEED,
        "sensitivity_scales": list(SENSITIVITY_SCALES),
        "baseline_cost_parameters": {
            "service_level_target": SERVICE_LEVEL_TARGET,
            "lead_time_days": LEAD_TIME_DAYS,
            "review_period_days": REVIEW_PERIOD_DAYS,
            "holding_cost_per_unit_per_day": HOLDING_COST_PER_UNIT_PER_DAY,
            "stockout_cost_per_unit": STOCKOUT_COST_PER_UNIT,
            "ordering_cost_per_order": ORDERING_COST_PER_ORDER,
        },
        "selection_objective": scenarios_manifest.selection_objective,
        "tie_break": scenarios_manifest.tie_break,
        "scenario_manifest_version": scenarios_manifest.manifest_version,
        "scenario_manifest_path": _relative_or_abs(scenario_manifest_path),
        "forecast_versions": dict(scenarios_manifest.forecast_versions),
        "policy_versions": dict(scenarios_manifest.policy_versions),
        "invariant_parameters": list(scenarios_manifest.invariant_parameters),
        "selection_window_demand_scale": scenarios_manifest.selection_window_demand_scale,
        "stockout_semantics": {
            "derivation_version": source.stockout_derivation_version,
            "rule": source.stockout_derivation_rule,
            "unknown_remains_unknown": True,
            "zero_sales_never_imply_stockout": True,
        },
        "future_feature_leakage": (
            "none: models use only past lags/rolling stats and calendar "
            "features; scenario reruns never retrain"
        ),
    }

    meta = {
        "report_version": ROBUSTNESS_REPORT_VERSION,
        "report_name": ROBUSTNESS_REPORT_NAME,
        "package_version": PACKAGE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "generated_at": generated_at,
        "timestamp_source": timestamp_source,
        "seed": SEED,
        "source_mode": "real-freshretailnet-expanded-robustness",
        "evaluation_label": ROBUSTNESS_EVAL_LABEL,
        "runtime": {
            "materialization_estimated_runtime_seconds": (
                ROBUSTNESS_RUNTIME_BUDGET_SECONDS
            ),
            "source": "documented-constant",
            "note": ROBUSTNESS_RUNTIME_NOTE,
        },
        "repository_commit_sha": commit_sha,
        "repository_commit_sha_note": commit_note,
    }

    report = _run_common(
        table=table,
        models=models,
        scenarios_manifest=scenarios_manifest,
        scenario_manifest_path=scenario_manifest_path,
        report_name=ROBUSTNESS_REPORT_NAME,
        seed=SEED,
        horizon=HORIZON,
        meta=meta,
        dataset=dataset,
        protocol=protocol,
        source_facts=source_facts,
        modeled_assumptions=_modeled_assumptions_section(scenarios_manifest),
        assumptions=ROBUSTNESS_ASSUMPTIONS,
        limitations=ROBUSTNESS_LIMITATIONS,
        overall_extra={
            "source_mode": "real-freshretailnet-expanded-robustness",
            "population_id": population.population_id,
        },
    )

    outdir.mkdir(parents=True, exist_ok=True)
    report_path = outdir / ROBUSTNESS_REPORT_NAME
    save_json(report_path, report)
    return report_path


def materialize_robustness_fixture(
    *,
    fixture_path: Path,
    manifest_path: Path,
    scenario_manifest_path: Path,
    outdir: Path,
) -> Path:
    manifest = load_manifest(manifest_path)
    from ..data import sha256_file

    if not manifest.verify_checksum(fixture_path):
        raise RobustnessError(
            f"checksum mismatch for {fixture_path}: manifest declares "
            f"{manifest.checksum}, file is {sha256_file(fixture_path)}"
        )
    scenarios_manifest = load_scenarios_manifest(scenario_manifest_path)
    table = load_canonical_csv(fixture_path)
    models = build_models()
    generated_at, timestamp_source = _deterministic_timestamp()

    dataset = _manifest_summary(manifest, fixture_path)
    source_facts = {
        "note": "Synthetic fixture robustness run; no real business result.",
        "source_label": "synthetic-fixture",
        "name": manifest.name,
        "checksum_algorithm": manifest.checksum_algorithm,
        "checksum": manifest.checksum,
        "file_path": _relative_or_abs(fixture_path),
        "synthetic_notice": SYNTHETIC_NOTICE,
    }
    protocol = {
        "frequency": "daily",
        "horizon": HORIZON,
        "min_train_periods": MIN_TRAIN_PERIODS,
        "final_test_periods": FINAL_TEST_PERIODS,
        "split_policy": (
            "expanding-window rolling origins; step = horizon; final test "
            "untouched; identical for every scenario"
        ),
        "seed": SEED,
        "sensitivity_scales": list(SENSITIVITY_SCALES),
        "baseline_cost_parameters": {
            "service_level_target": SERVICE_LEVEL_TARGET,
            "lead_time_days": LEAD_TIME_DAYS,
            "review_period_days": REVIEW_PERIOD_DAYS,
            "holding_cost_per_unit_per_day": HOLDING_COST_PER_UNIT_PER_DAY,
            "stockout_cost_per_unit": STOCKOUT_COST_PER_UNIT,
            "ordering_cost_per_order": ORDERING_COST_PER_ORDER,
        },
        "selection_objective": scenarios_manifest.selection_objective,
        "tie_break": scenarios_manifest.tie_break,
        "scenario_manifest_version": scenarios_manifest.manifest_version,
        "scenario_manifest_path": _relative_or_abs(scenario_manifest_path),
        "forecast_versions": dict(scenarios_manifest.forecast_versions),
        "policy_versions": dict(scenarios_manifest.policy_versions),
        "invariant_parameters": list(scenarios_manifest.invariant_parameters),
        "selection_window_demand_scale": scenarios_manifest.selection_window_demand_scale,
        "fixture_notice": SYNTHETIC_NOTICE,
    }
    meta = {
        "report_version": ROBUSTNESS_REPORT_VERSION,
        "report_name": FIXTURE_ROBUSTNESS_REPORT_NAME,
        "package_version": PACKAGE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "generated_at": generated_at,
        "timestamp_source": timestamp_source,
        "seed": SEED,
        "source_mode": "synthetic-fixture-robustness",
        "evaluation_label": "Synthetic fixture robustness evaluation",
        "runtime": {
            "materialization_estimated_runtime_seconds": (
                ROBUSTNESS_RUNTIME_BUDGET_SECONDS
            ),
            "source": "documented-constant",
            "note": ROBUSTNESS_RUNTIME_NOTE,
        },
    }

    report = _run_common(
        table=table,
        models=models,
        scenarios_manifest=scenarios_manifest,
        scenario_manifest_path=scenario_manifest_path,
        report_name=FIXTURE_ROBUSTNESS_REPORT_NAME,
        seed=SEED,
        horizon=HORIZON,
        meta=meta,
        dataset=dataset,
        protocol=protocol,
        source_facts=source_facts,
        modeled_assumptions=_modeled_assumptions_section(scenarios_manifest),
        assumptions=ASSUMPTIONS_FIXTURE,
        limitations=LIMITATIONS_FIXTURE,
        overall_extra={"source_mode": "synthetic-fixture-robustness"},
    )

    outdir.mkdir(parents=True, exist_ok=True)
    report_path = outdir / FIXTURE_ROBUSTNESS_REPORT_NAME
    save_json(report_path, report)
    return report_path


ASSUMPTIONS_FIXTURE = ROBUSTNESS_ASSUMPTIONS + (
    SYNTHETIC_NOTICE,
    "This fixture robustness run is for offline development and tests only.",
)

LIMITATIONS_FIXTURE = ROBUSTNESS_LIMITATIONS + (
    (
        "The fixture is a small synthetic series (2 SKUs); scenario results "
        "here carry no real-world meaning."
    ),
)


def main(argv: Sequence[str] | None = None) -> int:

    parser = argparse.ArgumentParser(
        description=(
            "Deterministic decision robustness over the frozen scenario matrix: "
            "fixture (offline, default) or the verified v2 real population."
        )
    )
    parser.add_argument(
        "--source",
        choices=("fixture", "real"),
        default="fixture",
        help="fixture (offline synthetic, default) or real (v2 population over data/raw)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="dataset manifest path (defaults per source mode)",
    )
    parser.add_argument(
        "--population",
        type=Path,
        default=None,
        help="v2 population manifest path (required for --source real)",
    )
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=None,
        help="robustness scenario manifest path (default: committed v1.0.0)",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=None,
        help="raw snapshot directory for --source real (default data/raw)",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=None,
        help="output directory for the robustness report",
    )
    args = parser.parse_args(argv)

    root = _repo_root()
    scenarios_path = (
        args.scenarios
        or root / "data" / "manifests" / "robustness-scenarios-v1.0.0.json"
    )
    outdir = args.outdir or root / "data" / "evaluations"

    if args.source == "fixture":
        fixture = root / "data" / "fixtures" / "freshretailnet_style_synthetic.csv"
        manifest_path = (
            args.manifest or root / "data" / "manifests" / "fixture_synthetic.json"
        )
        if not fixture.exists() or not manifest_path.exists():
            print("error: fixture or fixture manifest not found", file=sys.stderr)
            return 2
        try:
            report_path = materialize_robustness_fixture(
                fixture_path=fixture,
                manifest_path=manifest_path,
                scenario_manifest_path=scenarios_path,
                outdir=outdir,
            )
        except Exception as exc:  # noqa: BLE001 - CLI boundary
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {report_path}")
        print(SYNTHETIC_NOTICE)
        return 0

    manifest_path = (
        args.manifest or root / "data" / "manifests" / "freshretailnet-real.json"
    )
    population_path = args.population or (
        root / "data" / "manifests" / "freshretailnet-real-population-v2.json"
    )
    raw_dir = args.raw_dir or root / "data" / "raw"
    if not manifest_path.exists():
        print(f"error: real manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    if not population_path.exists():
        print(
            f"error: population manifest not found: {population_path}",
            file=sys.stderr,
        )
        return 2
    if not scenarios_path.exists():
        print(
            f"error: scenario manifest not found: {scenarios_path}",
            file=sys.stderr,
        )
        return 2
    if not raw_dir.exists():
        print(
            f"error: raw snapshot directory not found: {raw_dir}\n"
            "Acquire it first:\n"
            "  uv run python -m retail_demand_inventory.data.acquisition "
            "--manifest data/manifests/freshretailnet-real.json --output-dir data/raw",
            file=sys.stderr,
        )
        return 2
    try:
        report_path = materialize_robustness_real(
            source_manifest_path=manifest_path,
            population_path=population_path,
            scenario_manifest_path=scenarios_path,
            raw_dir=raw_dir,
            outdir=outdir,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {report_path}")
    print(ROBUSTNESS_NOTICE)
    print(ROBUSTNESS_GENERALIZATION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
