"""Forecasting: one interface over naive, moving-average, SES, and GBDT models."""

from __future__ import annotations

from .base import (
    Forecast,
    Forecaster,
    ForecastPoint,
    FutureContext,
    InsufficientHistoryError,
    future_context_from,
    require_single_sku,
)
from .baselines import NaiveForecaster
from .features import (
    build_feature_row,
    build_supervised_dataset,
    calendar_features,
    feature_names,
)
from .models import (
    HistGradientBoostingForecaster,
    MovingAverageForecaster,
    SESForecaster,
)
from .predictions import recursive_multistep

__all__ = [
    "Forecast",
    "ForecastPoint",
    "Forecaster",
    "FutureContext",
    "HistGradientBoostingForecaster",
    "InsufficientHistoryError",
    "MovingAverageForecaster",
    "NaiveForecaster",
    "SESForecaster",
    "build_feature_row",
    "build_supervised_dataset",
    "calendar_features",
    "feature_names",
    "future_context_from",
    "recursive_multistep",
    "require_single_sku",
]
