"""Forecasting models: interface, behavior, determinism, insufficient history."""

from __future__ import annotations

from datetime import date

import pytest

from retail_demand_inventory.forecasting import (
    FutureContext,
    HistGradientBoostingForecaster,
    InsufficientHistoryError,
    MovingAverageForecaster,
    NaiveForecaster,
    SESForecaster,
    future_context_from,
)


def _context(horizon: int = 7) -> FutureContext:
    return future_context_from(date(2024, 4, 1), horizon)


def test_naive_repeats_last_value(table_factory) -> None:
    model = NaiveForecaster().fit(table_factory([1.0, 2.0, 3.0]))
    forecast = model.predict(_context(), 7)
    assert forecast.values == (3.0,) * 7
    assert forecast.model_id == "naive"
    assert forecast.model_version == "1.0"


def test_moving_average_constant_level(table_factory) -> None:
    model = MovingAverageForecaster(window=4).fit(
        table_factory([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    )
    forecast = model.predict(_context(3), 3)
    assert forecast.values == (4.5, 4.5, 4.5)


def test_ses_smoothing(table_factory) -> None:
    # level: s1=1, s2=0.3*2+0.7*1=1.3, s3=0.3*4+0.7*1.3=2.11
    model = SESForecaster(alpha=0.3).fit(table_factory([1.0, 2.0, 4.0]))
    forecast = model.predict(_context(2), 2)
    assert forecast.values == pytest.approx((2.11, 2.11))


def test_hgb_predicts_horizon_nonnegative_and_reproducible(table_factory) -> None:
    series = [float(i % 7 + (i // 14)) for i in range(120)]
    table = table_factory(series)
    a = HistGradientBoostingForecaster().fit(table)
    b = HistGradientBoostingForecaster().fit(table)
    fa = a.predict(_context(7), 7)
    fb = b.predict(_context(7), 7)
    assert fa.horizon == 7
    assert len(fa.points) == 7
    assert all(v >= 0 for v in fa.values)
    assert fa.values == fb.values  # deterministic
    assert fa.model_id == "hist_gradient_boosting"


def test_hgb_recovers_mean_level(table_factory) -> None:
    series = [3.0 for _ in range(60)]
    model = HistGradientBoostingForecaster().fit(table_factory(series))
    forecast = model.predict(_context(7), 7)
    assert all(abs(v - 3.0) < 0.5 for v in forecast.values)


def test_insufficient_history_raises(table_factory) -> None:
    cases = (
        (NaiveForecaster(), []),
        (MovingAverageForecaster(window=7), [1.0, 2.0]),
        (SESForecaster(), [1.0]),
        (HistGradientBoostingForecaster(), [1.0, 2.0]),
    )
    for model, series in cases:
        with pytest.raises(InsufficientHistoryError):
            model.fit(table_factory(series))


def test_predict_before_fit_raises(table_factory) -> None:
    with pytest.raises(RuntimeError):
        NaiveForecaster().predict(_context(2), 2)


def test_horizon_mismatch_raises(table_factory) -> None:
    model = NaiveForecaster().fit(table_factory([1.0, 2.0]))
    with pytest.raises(ValueError):
        model.predict(_context(3), 7)


def test_fit_requires_single_sku(table_factory) -> None:
    from retail_demand_inventory.data import DemandRecord, DemandTable

    two_sku = DemandTable.from_records(
        [
            DemandRecord("a", date(2024, 1, 1), 1.0),
            DemandRecord("b", date(2024, 1, 1), 2.0),
        ]
    )
    with pytest.raises(ValueError):
        NaiveForecaster().fit(two_sku)


def test_min_history_is_exposed() -> None:
    assert NaiveForecaster().min_history == 1
    assert MovingAverageForecaster(window=7).min_history == 7
    assert SESForecaster().min_history == 2
    assert HistGradientBoostingForecaster().min_history == 21
