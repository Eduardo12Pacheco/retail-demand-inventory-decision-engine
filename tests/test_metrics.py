from __future__ import annotations

import pytest

from retail_demand_inventory.evaluation.metrics import (
    mae,
    mase,
    rmse,
    training_naive_errors,
    wmape,
)


def test_mae_and_rmse_known_values() -> None:
    actual = [1.0, 2.0, 3.0]
    predicted = [1.5, 2.5, 3.5]
    assert mae(actual, predicted) == pytest.approx(0.5)
    assert rmse(actual, predicted) == pytest.approx(0.5)


def test_wmape() -> None:
    actual = [1.0, 2.0, 3.0]
    predicted = [1.5, 2.5, 3.5]
    assert wmape(actual, predicted) == pytest.approx(0.25)


def test_wmape_zero_denominator_is_none() -> None:
    assert wmape([0.0, 0.0], [1.0, 2.0]) is None


def test_mase_uses_training_naive_errors() -> None:
    actual = [10.0, 10.0, 10.0]
    predicted = [12.0, 12.0, 12.0]
    training_naive = training_naive_errors([5.0, 5.0, 5.0])
    assert mase(actual, predicted, training_naive) is None
    training_naive = training_naive_errors([5.0, 7.0, 8.0])
    assert mase(actual, predicted, training_naive) == pytest.approx(2.0 / 1.5)


def test_mase_zero_naive_mean_is_none() -> None:
    assert mase([1.0, 2.0], [1.0, 2.0], [0.0, 0.0]) is None


def test_mase_missing_training_errors_is_none() -> None:
    assert mase([1.0, 2.0], [1.0, 2.0], None) is None
    assert mase([1.0, 2.0], [1.0, 2.0], []) is None


def test_empty_series_metrics_are_none() -> None:
    assert mae([], []) is None
    assert rmse([], []) is None


def test_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        mae([1.0], [1.0, 2.0])


def test_training_naive_errors() -> None:
    assert training_naive_errors([3.0, 5.0, 6.0]) == (2.0, 1.0)
    assert training_naive_errors([1.0]) == ()
