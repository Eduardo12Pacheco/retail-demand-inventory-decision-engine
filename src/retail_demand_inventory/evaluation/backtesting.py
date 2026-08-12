from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from ..data import DemandTable
from ..data.splits import Fold, TimeSplits
from ..forecasting import (
    Forecast,
    Forecaster,
    FutureContext,
    InsufficientHistoryError,
    NaiveForecaster,
)
from ..versions import PROTOCOL_VERSION
from . import metrics as metric_mod

Undefined = float("inf")


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


@dataclass(frozen=True)
class FoldForecast:
    fold_index: int
    sku: str
    category: str | None
    model_id: str
    model_version: str
    dates: tuple[date, ...]
    actual: tuple[float, ...]
    predicted: tuple[float, ...]
    metrics: Mapping[str, float | None]
    insufficient_history: bool
    fallback_reason: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "fold_index": self.fold_index,
            "sku": self.sku,
            "category": self.category,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "dates": [d.isoformat() for d in self.dates],
            "actual": list(self.actual),
            "predicted": list(self.predicted),
            "metrics": dict(self.metrics),
            "insufficient_history": self.insufficient_history,
            "fallback_reason": self.fallback_reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> FoldForecast:
        return cls(
            fold_index=int(data["fold_index"]),
            sku=str(data["sku"]),
            category=str(data["category"]) if data.get("category") else None,
            model_id=str(data["model_id"]),
            model_version=str(data["model_version"]),
            dates=tuple(date.fromisoformat(d) for d in data["dates"]),
            actual=tuple(float(v) for v in data["actual"]),
            predicted=tuple(float(v) for v in data["predicted"]),
            metrics=dict(data["metrics"]),
            insufficient_history=bool(data.get("insufficient_history", False)),
            fallback_reason=data.get("fallback_reason"),
        )


@dataclass(frozen=True)
class ModelSummary:
    model_id: str
    model_version: str
    count: int
    count_insufficient_history: int
    pooled_metrics: Mapping[str, float | None]
    mean_of_fold_metrics: Mapping[str, float | None]
    horizon: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "count": self.count,
            "count_insufficient_history": self.count_insufficient_history,
            "pooled_metrics": dict(self.pooled_metrics),
            "mean_of_fold_metrics": dict(self.mean_of_fold_metrics),
            "horizon": list(self.horizon),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ModelSummary:
        return cls(
            model_id=str(data["model_id"]),
            model_version=str(data["model_version"]),
            count=int(data["count"]),
            count_insufficient_history=int(data["count_insufficient_history"]),
            pooled_metrics=dict(data["pooled_metrics"]),
            mean_of_fold_metrics=dict(data["mean_of_fold_metrics"]),
            horizon=tuple(int(h) for h in data["horizon"]),
        )


def _pooled_metrics(fold_forecasts: Sequence[FoldForecast]) -> dict[str, float | None]:
    actuals = [a for ff in fold_forecasts for a in ff.actual]
    predicted = [p for ff in fold_forecasts for p in ff.predicted]
    return metric_mod.compute_metrics(actuals, predicted, None)


def _mean_fold_metrics(
    fold_forecasts: Sequence[FoldForecast],
) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for name in metric_mod.metric_names():
        values = [
            ff.metrics[name]
            for ff in fold_forecasts
            if ff.metrics.get(name) is not None
        ]
        out[name] = _mean(values) if values else None
    return out


def summarize(fold_forecasts: Sequence[FoldForecast]) -> tuple[ModelSummary, ...]:
    by_model: dict[str, list[FoldForecast]] = {}
    for ff in fold_forecasts:
        by_model.setdefault(ff.model_id, []).append(ff)

    summaries: list[ModelSummary] = []
    for model_id in sorted(by_model):
        group = by_model[model_id]
        version = group[0].model_version
        summaries.append(
            ModelSummary(
                model_id=model_id,
                model_version=version,
                count=len(group),
                count_insufficient_history=sum(
                    1 for ff in group if ff.insufficient_history
                ),
                pooled_metrics=_pooled_metrics(group),
                mean_of_fold_metrics=_mean_fold_metrics(group),
                horizon=tuple(sorted({len(ff.dates) for ff in group})),
            )
        )
    return tuple(summaries)


def group_key(fold_forecast: FoldForecast, key: str) -> str:
    if key == "sku":
        return fold_forecast.sku
    if key == "category":
        return fold_forecast.category or "<none>"
    if key == "fold":
        return f"fold_{fold_forecast.fold_index}"
    if key == "horizon":
        return str(len(fold_forecast.dates))
    raise ValueError(f"unknown grouping key: {key}")


def grouped_summaries(
    fold_forecasts: Sequence[FoldForecast], key: str
) -> dict[str, tuple[ModelSummary, ...]]:
    groups: dict[str, list[FoldForecast]] = {}
    for ff in fold_forecasts:
        groups.setdefault(group_key(ff, key), []).append(ff)
    return {g: summarize(items) for g, items in sorted(groups.items())}


def select_best_model(summaries: Sequence[ModelSummary]) -> ModelSummary:
    if not summaries:
        raise ValueError("cannot select from empty summaries")

    def rank(s: ModelSummary) -> tuple[bool, float, bool, float, str]:
        mae = s.pooled_metrics.get("mae")
        wmape = s.pooled_metrics.get("wmape")
        return (
            mae is None,
            mae if mae is not None else Undefined,
            wmape is None,
            wmape if wmape is not None else Undefined,
            s.model_id,
        )

    return min(summaries, key=rank)


@dataclass(frozen=True)
class BacktestReport:
    protocol_version: str
    horizon: int
    folds: tuple[FoldForecast, ...]

    def model_summaries(self) -> tuple[ModelSummary, ...]:
        return summarize(self.folds)

    def summaries_by(self, key: str) -> dict[str, tuple[ModelSummary, ...]]:
        return grouped_summaries(self.folds, key)

    def to_dict(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "horizon": self.horizon,
            "folds": [ff.to_dict() for ff in self.folds],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> BacktestReport:
        return cls(
            protocol_version=str(data["protocol_version"]),
            horizon=int(data["horizon"]),
            folds=tuple(FoldForecast.from_dict(ff) for ff in data["folds"]),
        )


def _forecast_with_fallback(
    table: DemandTable,
    sku: str,
    model: Forecaster,
    train_dates: Sequence[date],
    validation_dates: Sequence[date],
    fold_index: int,
) -> FoldForecast:
    train_table = table.filter_dates(sku, train_dates)
    context = FutureContext(tuple(validation_dates))
    horizon = len(validation_dates)
    insufficient = False
    fallback_reason: str | None = None
    forecast: Forecast
    try:
        fitted = model.fit(train_table)
        forecast = fitted.predict(context, horizon)
    except InsufficientHistoryError as exc:
        insufficient = True
        fallback_reason = f"{model.model_id} fit failed: {exc}; fell back to naive"
        naive = NaiveForecaster().fit(train_table)
        forecast = naive.predict(context, horizon)

    series = [value for _, value in train_table.daily_series(sku)]
    training_naive = metric_mod.training_naive_errors(series)
    actual_values = _actuals(table, sku, validation_dates)
    fold_metrics = metric_mod.compute_metrics(
        actual_values, forecast.values, training_naive
    )
    return FoldForecast(
        fold_index=fold_index,
        sku=sku,
        category=table.category_for(sku),
        model_id=forecast.model_id,
        model_version=forecast.model_version,
        dates=tuple(validation_dates),
        actual=actual_values,
        predicted=forecast.values,
        metrics=fold_metrics,
        insufficient_history=insufficient,
        fallback_reason=fallback_reason,
    )


def _actuals(table: DemandTable, sku: str, dates: Sequence[date]) -> tuple[float, ...]:
    wanted = set(dates)
    values = [r.demand_units for r in table.series_for(sku) if r.date in wanted]
    if len(values) != len(dates):
        raise ValueError(f"sku {sku}: missing demand for requested dates")
    return tuple(values)


def run_backtest(
    table: DemandTable,
    models: Sequence[Forecaster],
    folds: Sequence[Fold],
    *,
    horizon: int,
) -> BacktestReport:
    fold_forecasts: list[FoldForecast] = []
    for fold in folds:
        for sku in table.skus:
            for model in models:
                fold_forecasts.append(
                    _forecast_with_fallback(
                        table,
                        sku,
                        copy.deepcopy(model),
                        fold.train_dates,
                        fold.validation_dates,
                        fold.index,
                    )
                )
    return BacktestReport(
        protocol_version=PROTOCOL_VERSION,
        horizon=horizon,
        folds=tuple(fold_forecasts),
    )


@dataclass(frozen=True)
class FinalTestResult:
    sku: str
    category: str | None
    model_id: str
    model_version: str
    dates: tuple[date, ...]
    actual: tuple[float, ...]
    predicted: tuple[float, ...]
    metrics: Mapping[str, float | None]

    def to_dict(self) -> dict[str, object]:
        return {
            "sku": self.sku,
            "category": self.category,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "dates": [d.isoformat() for d in self.dates],
            "actual": list(self.actual),
            "predicted": list(self.predicted),
            "metrics": dict(self.metrics),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> FinalTestResult:
        return cls(
            sku=str(data["sku"]),
            category=str(data["category"]) if data.get("category") else None,
            model_id=str(data["model_id"]),
            model_version=str(data["model_version"]),
            dates=tuple(date.fromisoformat(d) for d in data["dates"]),
            actual=tuple(float(v) for v in data["actual"]),
            predicted=tuple(float(v) for v in data["predicted"]),
            metrics=dict(data["metrics"]),
        )


def evaluate_final_test(
    table: DemandTable,
    sku: str,
    model: Forecaster,
    splits: TimeSplits,
) -> FinalTestResult:
    train_dates = [
        d for d, _ in table.daily_series(sku) if d < splits.final_test_dates[0]
    ]
    train_table = table.filter_dates(sku, train_dates)
    context = FutureContext(tuple(splits.final_test_dates))
    horizon = len(splits.final_test_dates)
    fitted = model.fit(train_table)
    forecast = fitted.predict(context, horizon)
    actual = _actuals(table, sku, splits.final_test_dates)
    series = [value for _, value in train_table.daily_series(sku)]
    fold_metrics = metric_mod.compute_metrics(
        actual, forecast.values, metric_mod.training_naive_errors(series)
    )
    return FinalTestResult(
        sku=sku,
        category=table.category_for(sku),
        model_id=forecast.model_id,
        model_version=forecast.model_version,
        dates=tuple(splits.final_test_dates),
        actual=actual,
        predicted=forecast.values,
        metrics=fold_metrics,
    )
