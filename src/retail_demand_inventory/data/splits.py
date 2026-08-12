from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date


class SplitError(ValueError):
    pass


@dataclass(frozen=True)
class Fold:
    index: int
    train_dates: tuple[date, ...]
    validation_dates: tuple[date, ...]


@dataclass(frozen=True)
class TimeSplits:
    calendar: tuple[date, ...]
    folds: tuple[Fold, ...]
    final_test_dates: tuple[date, ...]

    def validate(self) -> tuple[str, ...]:
        problems: list[str] = []
        if len(set(self.calendar)) != len(self.calendar):
            problems.append("calendar contains duplicate dates")
        if tuple(self.calendar) != tuple(sorted(self.calendar)):
            problems.append("calendar is not sorted")
        final_set = set(self.final_test_dates)
        for fold in self.folds:
            train_set = set(fold.train_dates)
            val_set = set(fold.validation_dates)
            if train_set & val_set:
                problems.append(f"fold {fold.index}: train overlaps validation")
            if train_set & final_set:
                problems.append(f"fold {fold.index}: train overlaps final test")
            if val_set & final_set:
                problems.append(f"fold {fold.index}: validation overlaps final test")
        seen_windows: list[set[date]] = []
        for fold in self.folds:
            for other in seen_windows:
                if set(fold.validation_dates) & other:
                    problems.append(
                        f"fold {fold.index}: validation overlaps an earlier fold"
                    )
                    break
            seen_windows.append(set(fold.validation_dates))
        return tuple(problems)

    def require_valid(self) -> None:
        problems = self.validate()
        if problems:
            raise SplitError("; ".join(problems))


def _build_folds(
    calendar: tuple[date, ...],
    *,
    min_train_periods: int,
    horizon: int,
    final_test_periods: int,
    step: int,
    train_window: int | None,
) -> tuple[Fold, ...]:
    total = len(calendar)
    if total <= 0:
        raise SplitError("calendar is empty")
    if min_train_periods <= 0:
        raise SplitError("min_train_periods must be positive")
    if horizon <= 0:
        raise SplitError("horizon must be positive")
    if final_test_periods < 0:
        raise SplitError("final_test_periods must be non-negative")
    if step <= 0:
        raise SplitError("step must be positive")
    if final_test_periods + min_train_periods + horizon > total:
        raise SplitError(
            "not enough history: need min_train + horizon + final_test "
            f"<= total ({min_train_periods}+{horizon}+{final_test_periods} > {total})"
        )

    eval_end = total - final_test_periods
    folds: list[Fold] = []
    for index, origin in enumerate(
        range(min_train_periods, eval_end - horizon + 1, step)
    ):
        train = calendar[:origin]
        validation = calendar[origin : origin + horizon]
        if train_window is not None:
            train = calendar[max(0, origin - train_window) : origin]
        folds.append(
            Fold(
                index=index,
                train_dates=tuple(train),
                validation_dates=tuple(validation),
            )
        )
    return tuple(folds)


def expanding_origins(
    calendar: Sequence[date],
    *,
    min_train_periods: int,
    horizon: int,
    final_test_periods: int,
    step: int | None = None,
) -> TimeSplits:
    cal = tuple(sorted(calendar))
    step = step if step is not None else horizon
    final_test = cal[len(cal) - final_test_periods :] if final_test_periods else ()
    folds = _build_folds(
        cal,
        min_train_periods=min_train_periods,
        horizon=horizon,
        final_test_periods=final_test_periods,
        step=step,
        train_window=None,
    )
    splits = TimeSplits(calendar=cal, folds=folds, final_test_dates=tuple(final_test))
    splits.require_valid()
    return splits


def rolling_origins(
    calendar: Sequence[date],
    *,
    min_train_periods: int,
    horizon: int,
    final_test_periods: int,
    rolling_train_periods: int,
    step: int | None = None,
) -> TimeSplits:
    if rolling_train_periods <= 0:
        raise SplitError("rolling_train_periods must be positive")
    cal = tuple(sorted(calendar))
    step = step if step is not None else horizon
    final_test = cal[len(cal) - final_test_periods :] if final_test_periods else ()
    folds = _build_folds(
        cal,
        min_train_periods=min_train_periods,
        horizon=horizon,
        final_test_periods=final_test_periods,
        step=step,
        train_window=rolling_train_periods,
    )
    splits = TimeSplits(calendar=cal, folds=folds, final_test_dates=tuple(final_test))
    splits.require_valid()
    return splits
