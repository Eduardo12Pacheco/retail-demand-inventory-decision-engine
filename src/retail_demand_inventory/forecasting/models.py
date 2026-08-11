"""Deterministic forecast models: moving average, SES, and a supervised GBDT.

Hyperparameters are fixed, documented defaults; no per-SKU tuning is performed
(see docs/evaluation-protocol.md). All models are deterministic:

- `MovingAverageForecaster` and `SESForecaster` are closed-form.
- `HistGradientBoostingForecaster` is a supervised `HistGradientBoostingRegressor`
  trained on prior lags + rolling statistics + calendar features and produces
  the horizon via recursive multi-step prediction. Histogram gradient boosting
  is deterministic for a fixed dataset (no randomness in splits), so two runs
  with the same history produce identical forecasts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..data import DemandTable
from .base import (
    Forecast,
    Forecaster,
    ForecastPoint,
    FutureContext,
    InsufficientHistoryError,
    require_single_sku,
)
from .features import build_supervised_dataset
from .predictions import recursive_multistep


@dataclass
class MovingAverageForecaster(Forecaster):
    """Flat forecast equal to the mean of the last `window` observations."""

    model_id = "moving_average"
    model_version = "1.0"

    window: int = 7
    min_history: int = 7

    _level: float = float("nan")

    def __post_init__(self) -> None:
        if self.window <= 0:
            raise ValueError("window must be positive")
        self.min_history = self.window

    def fit(self, train_data: DemandTable) -> MovingAverageForecaster:
        sku = require_single_sku(train_data)
        series = train_data.daily_series(sku)
        if len(series) < self.min_history:
            raise InsufficientHistoryError(
                f"{self.model_id} needs >= {self.min_history} observations; got {len(series)}"
            )
        window_values = [value for _, value in series[-self.window :]]
        self._level = sum(window_values) / len(window_values)
        self._sku = sku
        return self

    def predict(self, context: FutureContext, horizon: int) -> Forecast:
        if len(context.dates) != horizon:
            raise ValueError("context.dates length must equal horizon")
        if self._level != self._level:
            raise RuntimeError(f"{self.model_id}.predict called before fit")
        return Forecast(
            sku=self._sku,
            model_id=self.model_id,
            model_version=self.model_version,
            points=tuple(ForecastPoint(d, self._level) for d in context.dates),
        )


@dataclass
class SESForecaster(Forecaster):
    """Simple exponential smoothing with a fixed smoothing factor.

    `alpha` is fixed (no optimization on the evaluation window): 0 < alpha < 1.
    The smoothed level after the training series is the forecast for all
    future days.
    """

    model_id = "ses"
    model_version = "1.0"
    min_history = 2

    alpha: float = 0.3

    _level: float = float("nan")

    def __post_init__(self) -> None:
        if not 0.0 < self.alpha < 1.0:
            raise ValueError("alpha must be in (0, 1)")

    def fit(self, train_data: DemandTable) -> SESForecaster:
        sku = require_single_sku(train_data)
        series = train_data.daily_series(sku)
        if len(series) < self.min_history:
            raise InsufficientHistoryError(
                f"{self.model_id} needs >= {self.min_history} observations; got {len(series)}"
            )
        level = series[0][1]
        for _, value in series[1:]:
            level = self.alpha * value + (1.0 - self.alpha) * level
        self._level = level
        self._sku = sku
        return self

    def predict(self, context: FutureContext, horizon: int) -> Forecast:
        if len(context.dates) != horizon:
            raise ValueError("context.dates length must equal horizon")
        if self._level != self._level:
            raise RuntimeError(f"{self.model_id}.predict called before fit")
        return Forecast(
            sku=self._sku,
            model_id=self.model_id,
            model_version=self.model_version,
            points=tuple(ForecastPoint(d, self._level) for d in context.dates),
        )


@dataclass
class HistGradientBoostingForecaster(Forecaster):
    """Supervised histogram gradient boosting over lags, rolling stats, and calendar features.

    Recursive multi-step: each future prediction is appended to the running
    series and used as history for the next step. Deterministic configuration:
    no early stopping, fixed iteration count, fixed learning rate and tree
    sizes.
    """

    model_id = "hist_gradient_boosting"
    model_version = "1.0"

    max_lag: int = 7
    rolling_windows: tuple[int, ...] = (7,)
    min_samples_for_fit: int = 14
    max_iter: int = 200
    learning_rate: float = 0.05
    max_leaf_nodes: int = 15
    min_samples_leaf: int = 5

    _model: Any = None
    _history_values: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if self.max_lag <= 0:
            raise ValueError("max_lag must be positive")
        if any(w <= 0 for w in self.rolling_windows):
            raise ValueError("rolling windows must be positive")
        if self.min_samples_for_fit <= 0:
            raise ValueError("min_samples_for_fit must be positive")
        self.min_history = (
            max(self.max_lag, *self.rolling_windows) + self.min_samples_for_fit
        )

    def fit(self, train_data: DemandTable) -> HistGradientBoostingForecaster:
        from sklearn.ensemble import HistGradientBoostingRegressor

        sku = require_single_sku(train_data)
        series = train_data.daily_series(sku)
        if len(series) < self.min_history:
            raise InsufficientHistoryError(
                f"{self.model_id} needs >= {self.min_history} observations; got {len(series)}"
            )
        values = [value for _, value in series]
        dates = [when for when, _ in series]
        _, rows, targets = build_supervised_dataset(
            values, dates, max_lag=self.max_lag, windows=self.rolling_windows
        )
        estimator = HistGradientBoostingRegressor(
            max_iter=self.max_iter,
            learning_rate=self.learning_rate,
            max_leaf_nodes=self.max_leaf_nodes,
            min_samples_leaf=self.min_samples_leaf,
            early_stopping=False,
            random_state=0,
        )
        estimator.fit(rows, targets)
        self._model = estimator
        self._history_values = tuple(values)
        self._sku = sku
        return self

    def predict(self, context: FutureContext, horizon: int) -> Forecast:
        if len(context.dates) != horizon:
            raise ValueError("context.dates length must equal horizon")
        if self._model is None:
            raise RuntimeError(f"{self.model_id}.predict called before fit")
        values = recursive_multistep(
            history_values=self._history_values,
            future_dates=context.dates,
            max_lag=self.max_lag,
            windows=self.rolling_windows,
            predict_one=lambda row: self._model.predict([row])[0],
        )
        return Forecast(
            sku=self._sku,
            model_id=self.model_id,
            model_version=self.model_version,
            points=tuple(ForecastPoint(d, v) for d, v in zip(context.dates, values)),
        )
