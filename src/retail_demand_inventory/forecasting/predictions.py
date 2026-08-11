"""Recursive multi-step prediction helpers.

`recursive_multistep` generates a horizon of forecasts one step at a time:
each step appends the previous prediction to the running series so that lags
and rolling statistics for the next step are available. Predictions are
clamped to non-negative values because demand is non-negative.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date

from .features import build_feature_row, feature_names


def recursive_multistep(
    *,
    history_values: Sequence[float],
    future_dates: Sequence[date],
    max_lag: int,
    windows: Sequence[int],
    predict_one: Callable[[list[float]], float],
) -> tuple[float, ...]:
    """Predict future demand one step at a time, feeding predictions back as history."""
    values: list[float] = list(history_values)
    names = feature_names(max_lag, windows)
    if len(values) < max(max_lag, *windows):
        raise ValueError("history too short for recursive multi-step prediction")
    out: list[float] = []
    for when in future_dates:
        row = build_feature_row(values, when, max_lag=max_lag, windows=windows)
        vector = [row[name] for name in names]
        predicted = max(0.0, float(predict_one(vector)))
        out.append(predicted)
        values.append(predicted)
    return tuple(out)
