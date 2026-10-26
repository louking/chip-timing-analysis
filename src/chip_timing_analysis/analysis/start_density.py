"""Start-line density: how many runners cross the start mats per unit time.
A mass start packs the field into a few seconds, so the useful window is
much shorter than finish_density.py's: peak crossings per second, which is
what the start mats have to read through at once.
"""

from __future__ import annotations

import pandas as pd

from chip_timing_analysis.analysis.timing_utils import rolling_count

START_WINDOW = pd.Timedelta(seconds=1)


def rolling_start_rate(classified: pd.DataFrame, window: pd.Timedelta = START_WINDOW) -> pd.DataFrame:
    """For each bib with a start read, count of start crossings (including
    itself) within `window` ending at its own start_time."""
    starts = classified.dropna(subset=["start_time"]).sort_values("start_time").copy()
    starts["starters_in_window"] = rolling_count(starts["start_time"], window, include_self=True)
    return starts


def start_spread(classified: pd.DataFrame, gun_time: pd.Timestamp, quantile: float = 0.9) -> float | None:
    """Seconds after gun_time by which `quantile` of start crossings had
    happened (None if there are no start reads). Can be slightly negative
    for a tiny field, since start reads are allowed just before the gun."""
    starts = classified["start_time"].dropna()
    if starts.empty:
        return None
    return (starts.quantile(quantile) - gun_time).total_seconds()
