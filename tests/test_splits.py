from __future__ import annotations

from datetime import date, timedelta

import pytest

from retail_demand_inventory.data.splits import (
    SplitError,
    expanding_origins,
    rolling_origins,
)


def _calendar(days: int, start: date = date(2024, 1, 1)) -> list[date]:
    return [start + timedelta(days=i) for i in range(days)]


def test_expanding_folds_are_disjoint_and_ordered() -> None:
    calendar = _calendar(120)
    splits = expanding_origins(
        calendar,
        min_train_periods=42,
        horizon=7,
        final_test_periods=14,
    )
    splits.require_valid()
    assert len(splits.folds) == 9
    seen: set[date] = set()
    for fold in splits.folds:
        assert len(fold.validation_dates) == 7
        assert not (seen & set(fold.validation_dates))
        seen |= set(fold.validation_dates)
    train_lengths = [len(fold.train_dates) for fold in splits.folds]
    assert train_lengths == sorted(train_lengths)
    assert train_lengths[0] == 42


def test_final_test_is_untouched() -> None:
    calendar = _calendar(120)
    splits = expanding_origins(
        calendar, min_train_periods=42, horizon=7, final_test_periods=14
    )
    assert splits.final_test_dates == tuple(calendar[-14:])
    all_fold_dates = {
        d for f in splits.folds for d in (*f.train_dates, *f.validation_dates)
    }
    assert not (set(splits.final_test_dates) & all_fold_dates)


def test_no_train_validation_overlap() -> None:
    splits = expanding_origins(
        _calendar(120), min_train_periods=42, horizon=7, final_test_periods=14
    )
    for fold in splits.folds:
        assert not (set(fold.train_dates) & set(fold.validation_dates))


def test_rolling_window_is_fixed() -> None:
    calendar = _calendar(120)
    splits = rolling_origins(
        calendar,
        min_train_periods=42,
        horizon=7,
        final_test_periods=14,
        rolling_train_periods=50,
    )
    lengths = [len(fold.train_dates) for fold in splits.folds]
    assert all(length >= 42 for length in lengths)
    assert lengths[-1] == 50
    assert splits.final_test_dates == tuple(calendar[-14:])


def test_splits_are_deterministic() -> None:
    calendar = _calendar(120)
    a = expanding_origins(
        calendar, min_train_periods=42, horizon=7, final_test_periods=14
    )
    b = expanding_origins(
        calendar, min_train_periods=42, horizon=7, final_test_periods=14
    )
    assert a == b


def test_not_enough_history_raises() -> None:
    with pytest.raises(SplitError):
        expanding_origins(
            _calendar(50), min_train_periods=42, horizon=7, final_test_periods=14
        )


def test_validation_rejects_overlap_constructed_by_hand() -> None:
    from retail_demand_inventory.data.splits import Fold, TimeSplits

    calendar = tuple(_calendar(30))
    bad = TimeSplits(
        calendar=calendar,
        folds=(Fold(0, calendar[:10], calendar[5:12]),),
        final_test_dates=calendar[28:30],
    )
    assert bad.validate() != ()


def test_step_horizon_gives_disjoint_windows_even_with_rolling() -> None:
    splits = rolling_origins(
        _calendar(120),
        min_train_periods=42,
        horizon=7,
        final_test_periods=14,
        rolling_train_periods=40,
    )
    seen: set[date] = set()
    for fold in splits.folds:
        assert not (seen & set(fold.validation_dates))
        seen |= set(fold.validation_dates)
