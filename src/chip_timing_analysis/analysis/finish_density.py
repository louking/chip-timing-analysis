"""Finish-line density: how many runners are crossing the finish line per
unit time, independent of any downstream bib-scan queue (see queue_lag.py
for that -- this is about congestion at the mat itself, e.g. for gauging
whether the finish chute/funnel needs to be wider, not about the scanner).
"""

from __future__ import annotations

import pandas as pd

from chip_timing_analysis.analysis.timing_utils import rolling_count

# 60s matches the finish-line-timing field's standard "runners per minute"
# unit (see RRTC's peak-arrival theory, P = 0.6*N/D -- CLAUDE.md). 15s is a
# shorter "burst" window: small local races (FSRC's typical 100-150 field)
# tend to cluster in short bursts (a few finishers together) rather than
# sustain a competitive-race-style peak, which a 60s window can smooth over.
STANDARD_WINDOW = pd.Timedelta(seconds=60)
BURST_WINDOW = pd.Timedelta(seconds=15)


def finish_density(classified: pd.DataFrame, bin_width: pd.Timedelta = pd.Timedelta(seconds=30)) -> pd.DataFrame:
    """Bin finish_time into bin_width buckets and count finishers per bucket."""
    finishes = classified.dropna(subset=["finish_time"]).copy()
    finishes["bin_start"] = finishes["finish_time"].dt.floor(bin_width)
    return finishes.groupby("bin_start").size().rename("n_finishers").reset_index()


def rolling_finish_rate(classified: pd.DataFrame, window: pd.Timedelta = STANDARD_WINDOW) -> pd.DataFrame:
    """For each bib, count of finishers (including itself) within `window`
    centered on/ending at its own finish_time."""
    finishes = classified.dropna(subset=["finish_time"]).sort_values("finish_time").copy()
    finishes["finishers_in_window"] = rolling_count(finishes["finish_time"], window, include_self=True)
    return finishes


def finish_gaps(classified: pd.DataFrame) -> pd.Series:
    """Time gap (seconds) between consecutive finishers, sorted by finish_time."""
    finishes = classified.dropna(subset=["finish_time"]).sort_values("finish_time")
    return finishes["finish_time"].diff().dt.total_seconds().dropna()


def summary(classified: pd.DataFrame, windows: tuple[pd.Timedelta, ...] = (STANDARD_WINDOW, BURST_WINDOW)) -> None:
    finishes = classified.dropna(subset=["finish_time"])
    print(f"finishers: {len(finishes)}")
    if finishes.empty:
        return

    span_sec = (finishes["finish_time"].max() - finishes["finish_time"].min()).total_seconds()
    print(f"finish window span: {span_sec:.0f}s ({span_sec / 60:.1f} min)")
    print(f"overall avg rate: {len(finishes) / span_sec * 60:.2f} finishers/min")

    gaps = finish_gaps(classified)
    print("\ngap between consecutive finishers (sec):")
    print(gaps.describe())
    print(f"5 tightest gaps (sec): {sorted(gaps)[:5]}")

    for window in windows:
        rolled = rolling_finish_rate(classified, window)
        peak = rolled.loc[rolled["finishers_in_window"].idxmax()]
        print(f"\npeak density ({window}): {peak['finishers_in_window']} finishers, window ending near {peak['finish_time']}")
        print(f"finishers-in-{window} distribution:")
        print(rolled["finishers_in_window"].describe())
