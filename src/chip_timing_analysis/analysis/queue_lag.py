"""Finish-to-bib-scan queue lag.

Raw lag (scan_time - finish_time) conflates two things: the fixed time it
takes a finisher to walk from the finish mat to wherever the barcode-scanner
operator is standing (which varies by race/operator choice -- e.g. at the
Indy 5000 the operator stood well back from the finish), and actual time
spent waiting in a line at the scanner. Only the second is a "queue forming"
signal.

We treat a low percentile of observed lag as the walk-only baseline (the
fastest anyone got scanned, i.e. ~zero wait), and call anything above that
"excess lag". Sustained/rising excess lag during a burst of finishers, that
later drains back down, is evidence of a real queue -- as opposed to excess
lag that's flat regardless of finisher density, which just means the
baseline estimate is off (or scans are noisy) rather than a queue.
"""

from __future__ import annotations

import pandas as pd

from chip_timing_analysis.analysis.timing_utils import rolling_count


def compute_lag(classified: pd.DataFrame, scans: pd.DataFrame) -> pd.DataFrame:
    """Join finish_time (from classify_start_finish) to the first scan at/after
    it, per bib, and compute lag in seconds.

    Returns columns: bib, finish_time, scan_time, lag_sec. Bibs with a
    finish_time but no matching scan (scan missing, or all scans for that bib
    were before its finish -- e.g. a mis-scan) get scan_time/lag_sec = NaT/NaN.
    """
    finishes = classified.dropna(subset=["finish_time"])[["bib", "finish_time"]]

    rows = []
    for bib, finish_time in finishes.itertuples(index=False):
        candidates = scans[(scans["bib"] == bib) & (scans["scan_time"] >= finish_time)]
        scan_time = candidates["scan_time"].min() if not candidates.empty else pd.NaT
        rows.append({"bib": bib, "finish_time": finish_time, "scan_time": scan_time})

    lag = pd.DataFrame(rows, columns=["bib", "finish_time", "scan_time"])
    lag["lag_sec"] = (lag["scan_time"] - lag["finish_time"]).dt.total_seconds()
    return lag


def add_excess_lag(lag: pd.DataFrame, baseline_quantile: float = 0.05) -> pd.DataFrame:
    """Add baseline_sec (a low quantile of lag_sec, the walk-only estimate)
    and excess_lag_sec (lag_sec - baseline_sec, the queue-wait estimate).
    """
    lag = lag.copy()
    baseline = lag["lag_sec"].quantile(baseline_quantile)
    lag["baseline_sec"] = baseline
    lag["excess_lag_sec"] = lag["lag_sec"] - baseline
    return lag


def add_finish_rate(lag: pd.DataFrame, window: pd.Timedelta = pd.Timedelta(seconds=60)) -> pd.DataFrame:
    """Add finishers_in_prior_window: how many bibs finished in the `window`
    preceding each bib's own finish_time. A rough measure of local finisher
    density/burstiness, to check whether excess lag tracks it.
    """
    lag = lag.sort_values("finish_time").copy()
    lag["finishers_in_prior_window"] = rolling_count(lag["finish_time"], window, include_self=False)
    return lag


def lag_histogram(lag: pd.DataFrame, column: str = "excess_lag_sec", bin_width: float = 5.0) -> pd.Series:
    """Text histogram (bin -> count) of a lag column, for quick inspection
    without a plotting dependency."""
    valid = lag[column].dropna()
    bins = ((valid // bin_width) * bin_width).astype("int64")
    return bins.value_counts().sort_index()


def summary(lag: pd.DataFrame) -> None:
    print(f"bibs with a finish: {len(lag)}")
    matched = lag.dropna(subset=["scan_time"])
    print(f"bibs with a matching scan: {len(matched)} ({len(lag) - len(matched)} missing)")
    print("\nlag_sec:")
    print(matched["lag_sec"].describe())
    print(f"90th percentile lag_sec: {matched['lag_sec'].quantile(0.90):.2f}")
    if "excess_lag_sec" in matched.columns:
        print("\nexcess_lag_sec (lag_sec - baseline):")
        print(matched["excess_lag_sec"].describe())
        print(f"90th percentile excess_lag_sec: {matched['excess_lag_sec'].quantile(0.90):.2f}")
