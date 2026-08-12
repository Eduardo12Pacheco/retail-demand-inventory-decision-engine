from __future__ import annotations

from collections.abc import Sequence
from datetime import date

CALENDAR_FEATURES = (
    "day_of_week",
    "day_of_month",
    "month",
    "day_of_year",
    "is_weekend",
)


def calendar_features(when: date) -> dict[str, float]:
    return {
        "day_of_week": float(when.weekday()),
        "day_of_month": float(when.day),
        "month": float(when.month),
        "day_of_year": float(when.timetuple().tm_yday),
        "is_weekend": 1.0 if when.weekday() >= 5 else 0.0,
    }


def feature_names(max_lag: int, windows: Sequence[int]) -> list[str]:
    names: list[str] = []
    names.extend(f"lag_{i}" for i in range(1, max_lag + 1))
    for w in sorted(windows):
        names.extend((f"roll_mean_{w}", f"roll_std_{w}"))
    names.extend(CALENDAR_FEATURES)
    return names


def build_feature_row(
    values: Sequence[float],
    when: date,
    *,
    max_lag: int,
    windows: Sequence[int],
) -> dict[str, float]:
    if len(values) < max(max_lag, *windows):
        raise ValueError(
            f"not enough history for features: need >= {max(max_lag, *windows)}, got {len(values)}"
        )
    row: dict[str, float] = {}
    for i in range(1, max_lag + 1):
        row[f"lag_{i}"] = float(values[-i])
    for w in sorted(windows):
        window = values[-w:]
        mean = sum(window) / w
        row[f"roll_mean_{w}"] = mean
        variance = sum((v - mean) ** 2 for v in window) / w
        row[f"roll_std_{w}"] = variance**0.5
    row.update(calendar_features(when))
    return row


def build_supervised_dataset(
    series: Sequence[float],
    dates: Sequence[date],
    *,
    max_lag: int,
    windows: Sequence[int],
) -> tuple[list[str], list[list[float]], list[float]]:
    names = feature_names(max_lag, windows)
    offset = max(max_lag, *windows)
    rows: list[list[float]] = []
    targets: list[float] = []
    for index in range(offset, len(series)):
        row = build_feature_row(
            series[:index], dates[index], max_lag=max_lag, windows=windows
        )
        rows.append([row[name] for name in names])
        targets.append(float(series[index]))
    return names, rows, targets
