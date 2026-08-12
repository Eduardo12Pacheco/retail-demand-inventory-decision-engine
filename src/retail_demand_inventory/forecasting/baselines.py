from __future__ import annotations

from dataclasses import dataclass

from ..data import DemandTable
from .base import (
    Forecast,
    Forecaster,
    ForecastPoint,
    FutureContext,
    InsufficientHistoryError,
    require_single_sku,
)


@dataclass
class NaiveForecaster(Forecaster):
    model_id = "naive"
    model_version = "1.0"
    min_history = 1

    _last: float = float("nan")

    def fit(self, train_data: DemandTable) -> NaiveForecaster:
        sku = require_single_sku(train_data)
        series = train_data.daily_series(sku)
        if len(series) < self.min_history:
            raise InsufficientHistoryError(
                f"{self.model_id} needs >= {self.min_history} observations; got {len(series)}"
            )
        self._last = series[-1][1]
        self._sku = sku
        return self

    def predict(self, context: FutureContext, horizon: int) -> Forecast:
        if len(context.dates) != horizon:
            raise ValueError("context.dates length must equal horizon")
        if self._last != self._last:
            raise RuntimeError(f"{self.model_id}.predict called before fit")
        return Forecast(
            sku=self._sku,
            model_id=self.model_id,
            model_version=self.model_version,
            points=tuple(ForecastPoint(d, self._last) for d in context.dates),
        )
