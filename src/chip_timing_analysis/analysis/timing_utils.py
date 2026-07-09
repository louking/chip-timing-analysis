"""Shared helpers for time-window analysis (queue_lag.py, finish_density.py)."""

from __future__ import annotations

import pandas as pd


def rolling_count(times: pd.Series, window: pd.Timedelta, include_self: bool = False) -> list[int]:
    """For each timestamp in `times` (must be sorted ascending), count how many
    other timestamps fall in the preceding `window`. If include_self, count
    the timestamp itself too (density AT that point vs density BEFORE it).
    """
    values = times.to_numpy()
    counts = []
    start = 0
    for i, t in enumerate(values):
        while values[start] < t - window:
            start += 1
        counts.append(i - start + 1 if include_self else i - start)
    return counts
