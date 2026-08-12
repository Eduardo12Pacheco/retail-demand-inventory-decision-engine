from __future__ import annotations

from datetime import timedelta

from retail_demand_inventory.data.splits import expanding_origins
from retail_demand_inventory.evaluation.backtesting import (
    evaluate_final_test,
    run_backtest,
    select_best_model,
    summarize,
)
from retail_demand_inventory.forecasting import (
    HistGradientBoostingForecaster,
    MovingAverageForecaster,
    NaiveForecaster,
    SESForecaster,
)


def _models():
    return (
        NaiveForecaster(),
        MovingAverageForecaster(window=7),
        SESForecaster(alpha=0.3),
        HistGradientBoostingForecaster(),
    )


def test_backtest_never_touches_final_test(fixture_table) -> None:
    calendar = tuple(sorted({r.date for r in fixture_table.records}))
    splits = expanding_origins(
        calendar, min_train_periods=42, horizon=7, final_test_periods=14
    )
    report = run_backtest(fixture_table, _models(), splits.folds, horizon=7)
    final_test_set = set(splits.final_test_dates)
    for ff in report.folds:
        assert not (set(ff.dates) & final_test_set)


def test_backtest_produces_fold_model_grid(fixture_table) -> None:
    calendar = tuple(sorted({r.date for r in fixture_table.records}))
    splits = expanding_origins(
        calendar, min_train_periods=42, horizon=7, final_test_periods=14
    )
    report = run_backtest(fixture_table, _models(), splits.folds, horizon=7)
    expected = len(fixture_table.skus) * len(splits.folds) * 4
    assert len(report.folds) == expected
    by_model = {ff.model_id for ff in report.folds}
    assert by_model == {"naive", "moving_average", "ses", "hist_gradient_boosting"}
    assert all(
        set(ff.metrics) == {"mae", "rmse", "wmape", "mase"} for ff in report.folds
    )


def test_insufficient_history_falls_back_to_naive(table_factory) -> None:
    from datetime import date as d

    from retail_demand_inventory.data import DemandRecord, DemandTable
    from retail_demand_inventory.data.splits import Fold

    start = d(2024, 1, 1)
    records = [
        DemandRecord("s", start + timedelta(days=i), 1.0, category="c")
        for i in range(60)
    ]
    table = DemandTable.from_records(records)
    folds = (
        Fold(
            0,
            tuple(start + timedelta(days=i) for i in range(5)),
            tuple(start + timedelta(days=i) for i in range(5, 12)),
        ),
    )
    models = (MovingAverageForecaster(window=100),)
    report = run_backtest(table, models, folds, horizon=7)
    ff = report.folds[0]
    assert ff.insufficient_history is True
    assert ff.model_id == "naive"
    assert "fell back to naive" in ff.fallback_reason
    assert ff.metrics["mae"] is not None


def test_select_best_model_rule() -> None:
    from retail_demand_inventory.evaluation.backtesting import ModelSummary

    lower_mae = ModelSummary(
        model_id="ses",
        model_version="1.0",
        count=2,
        count_insufficient_history=0,
        pooled_metrics={"mae": 1.0, "rmse": 2.0, "wmape": 0.5, "mase": 1.0},
        mean_of_fold_metrics={"mae": 1.0, "rmse": 2.0, "wmape": 0.5, "mase": 1.0},
        horizon=(7,),
    )
    higher_mae = ModelSummary(
        model_id="naive",
        model_version="1.0",
        count=2,
        count_insufficient_history=0,
        pooled_metrics={"mae": 2.0, "rmse": 3.0, "wmape": 0.8, "mase": 2.0},
        mean_of_fold_metrics={"mae": 2.0, "rmse": 3.0, "wmape": 0.8, "mase": 2.0},
        horizon=(7,),
    )
    assert select_best_model([higher_mae, lower_mae]).model_id == "ses"


def test_select_best_model_undefined_mae_sorts_last() -> None:
    from retail_demand_inventory.evaluation.backtesting import ModelSummary

    undefined = ModelSummary(
        model_id="bad",
        model_version="1.0",
        count=1,
        count_insufficient_history=0,
        pooled_metrics={"mae": None, "rmse": None, "wmape": None, "mase": None},
        mean_of_fold_metrics={"mae": None, "rmse": None, "wmape": None, "mase": None},
        horizon=(7,),
    )
    defined = ModelSummary(
        model_id="naive",
        model_version="1.0",
        count=1,
        count_insufficient_history=0,
        pooled_metrics={"mae": 3.0, "rmse": 4.0, "wmape": 1.0, "mase": 1.0},
        mean_of_fold_metrics={"mae": 3.0, "rmse": 4.0, "wmape": 1.0, "mase": 1.0},
        horizon=(7,),
    )
    assert select_best_model([undefined, defined]).model_id == "naive"


def test_final_test_evaluation_uses_only_pre_test_history(fixture_table) -> None:
    calendar = tuple(sorted({r.date for r in fixture_table.records}))
    splits = expanding_origins(
        calendar, min_train_periods=42, horizon=7, final_test_periods=14
    )
    sku = fixture_table.skus[0]
    result = evaluate_final_test(fixture_table, sku, NaiveForecaster(), splits)
    assert result.dates == splits.final_test_dates
    assert len(result.actual) == 14
    assert result.metrics["mae"] is not None
    pre_test = [
        v for _, v in fixture_table.daily_series(sku) if _ < splits.final_test_dates[0]
    ]
    assert set(result.predicted) == {pre_test[-1]}


def test_summaries_aggregate_per_model(fixture_table) -> None:
    calendar = tuple(sorted({r.date for r in fixture_table.records}))
    splits = expanding_origins(
        calendar, min_train_periods=42, horizon=7, final_test_periods=14
    )
    report = run_backtest(fixture_table, (NaiveForecaster(),), splits.folds, horizon=7)
    summaries = summarize(report.folds)
    assert len(summaries) == 1
    assert summaries[0].model_id == "naive"
    assert summaries[0].count == len(fixture_table.skus) * len(splits.folds)
