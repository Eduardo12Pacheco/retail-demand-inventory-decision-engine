from __future__ import annotations

import math
from collections.abc import Sequence


def _pairs(
    actual: Sequence[float], predicted: Sequence[float]
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    if len(actual) != len(predicted):
        raise ValueError(
            f"actual and predicted lengths differ: {len(actual)} vs {len(predicted)}"
        )
    return tuple(float(a) for a in actual), tuple(float(p) for p in predicted)


def _abs_errors(
    actual: Sequence[float], predicted: Sequence[float]
) -> tuple[float, ...]:
    a, p = _pairs(actual, predicted)
    return tuple(abs(a_i - p_i) for a_i, p_i in zip(a, p))


def mae(actual: Sequence[float], predicted: Sequence[float]) -> float | None:
    errors = _abs_errors(actual, predicted)
    if not errors:
        return None
    return sum(errors) / len(errors)


def rmse(actual: Sequence[float], predicted: Sequence[float]) -> float | None:
    a, p = _pairs(actual, predicted)
    if not a:
        return None
    squared = sum((a_i - p_i) ** 2 for a_i, p_i in zip(a, p))
    return math.sqrt(squared / len(a))


def wmape(actual: Sequence[float], predicted: Sequence[float]) -> float | None:
    errors = _abs_errors(actual, predicted)
    denominator = sum(float(a) for a in actual)
    if denominator == 0:
        return None
    return sum(errors) / denominator


def mase(
    actual: Sequence[float],
    predicted: Sequence[float],
    training_naive_errors: Sequence[float] | None,
) -> float | None:
    errors = _abs_errors(actual, predicted)
    if not errors:
        return None
    if training_naive_errors is None or not training_naive_errors:
        return None
    denominator = sum(abs(float(e)) for e in training_naive_errors) / len(
        training_naive_errors
    )
    if denominator == 0:
        return None
    return (sum(errors) / len(errors)) / denominator


def training_naive_errors(series: Sequence[float]) -> tuple[float, ...]:
    if len(series) < 2:
        return ()
    return tuple(
        abs(float(series[t]) - float(series[t - 1])) for t in range(1, len(series))
    )


def metric_names() -> tuple[str, ...]:
    return ("mae", "rmse", "wmape", "mase")


def compute_metrics(
    actual: Sequence[float],
    predicted: Sequence[float],
    training_naive_errors: Sequence[float] | None,
) -> dict[str, float | None]:
    return {
        "mae": mae(actual, predicted),
        "rmse": rmse(actual, predicted),
        "wmape": wmape(actual, predicted),
        "mase": mase(actual, predicted, training_naive_errors),
    }
