"""test_queue_lag - test chip_timing_analysis.analysis.queue_lag"""

import pandas as pd

from chip_timing_analysis.analysis.queue_lag import (
    compute_lag,
    add_excess_lag,
    add_finish_rate,
    lag_histogram,
)

FT = pd.Timestamp("2026-07-04 09:00:00")


def _classified(finishes: dict) -> pd.DataFrame:
    """finishes: {bib: finish_time or None}."""
    return pd.DataFrame({
        "bib": list(finishes.keys()),
        "finish_time": [pd.NaT if v is None else v for v in finishes.values()],
    })


def _scans(rows: list[tuple]) -> pd.DataFrame:
    """rows: list of (bib, scan_time)."""
    return pd.DataFrame([{"bib": b, "scan_time": t} for b, t in rows], columns=["bib", "scan_time"])


# ----------------------------------------------------------------------
# compute_lag
# ----------------------------------------------------------------------

def test_matches_first_scan_at_or_after_finish():
    classified = _classified({101: FT})
    scans = _scans([(101, FT + pd.Timedelta(seconds=5)), (101, FT + pd.Timedelta(seconds=20))])

    lag = compute_lag(classified, scans)

    assert lag.iloc[0]["scan_time"] == FT + pd.Timedelta(seconds=5)
    assert lag.iloc[0]["lag_sec"] == 5.0


def test_scan_before_finish_is_not_matched():
    # a mis-scan before the actual finish crossing shouldn't count as this bib's lag
    classified = _classified({101: FT})
    scans = _scans([(101, FT - pd.Timedelta(seconds=10))])

    lag = compute_lag(classified, scans)

    assert pd.isna(lag.iloc[0]["scan_time"])
    assert pd.isna(lag.iloc[0]["lag_sec"])


def test_no_matching_scan_for_bib_is_nan():
    classified = _classified({101: FT})
    scans = _scans([])

    lag = compute_lag(classified, scans)

    assert pd.isna(lag.iloc[0]["scan_time"])


def test_bibs_with_no_finish_time_are_excluded():
    classified = _classified({101: FT, 102: None})
    scans = _scans([(101, FT + pd.Timedelta(seconds=5))])

    lag = compute_lag(classified, scans)

    assert lag["bib"].tolist() == [101]


def test_scan_exactly_at_finish_time_matches():
    classified = _classified({101: FT})
    scans = _scans([(101, FT)])

    lag = compute_lag(classified, scans)

    assert lag.iloc[0]["lag_sec"] == 0.0


# ----------------------------------------------------------------------
# add_excess_lag
# ----------------------------------------------------------------------

def test_excess_lag_subtracts_baseline_quantile():
    lag = pd.DataFrame({"lag_sec": [1.0, 2.0, 3.0, 4.0, 100.0]})

    result = add_excess_lag(lag, baseline_quantile=0.0)

    assert result["baseline_sec"].iloc[0] == 1.0
    assert result["excess_lag_sec"].tolist() == [0.0, 1.0, 2.0, 3.0, 99.0]


def test_excess_lag_does_not_mutate_input():
    lag = pd.DataFrame({"lag_sec": [1.0, 2.0]})

    add_excess_lag(lag)

    assert "excess_lag_sec" not in lag.columns


# ----------------------------------------------------------------------
# add_finish_rate
# ----------------------------------------------------------------------

def test_finish_rate_counts_prior_finishers_in_window():
    lag = pd.DataFrame({
        "bib": [101, 102, 103],
        "finish_time": [FT, FT + pd.Timedelta(seconds=10), FT + pd.Timedelta(seconds=90)],
    })

    result = add_finish_rate(lag, window=pd.Timedelta(seconds=60))

    counts = dict(zip(result["bib"], result["finishers_in_prior_window"]))
    assert counts[101] == 0
    assert counts[102] == 1
    assert counts[103] == 0  # both prior finishers are outside the 60s window


def test_finish_rate_sorts_by_finish_time():
    lag = pd.DataFrame({
        "bib": [102, 101],
        "finish_time": [FT + pd.Timedelta(seconds=10), FT],
    })

    result = add_finish_rate(lag, window=pd.Timedelta(seconds=60))

    assert result["finish_time"].is_monotonic_increasing


# ----------------------------------------------------------------------
# lag_histogram
# ----------------------------------------------------------------------

def test_lag_histogram_bins_by_bin_width():
    lag = pd.DataFrame({"excess_lag_sec": [0.5, 1.0, 4.9, 5.0, 9.9]})

    hist = lag_histogram(lag, "excess_lag_sec", bin_width=5.0)

    assert hist.to_dict() == {0: 3, 5: 2}


def test_lag_histogram_drops_nan():
    lag = pd.DataFrame({"excess_lag_sec": [1.0, float("nan"), 2.0]})

    hist = lag_histogram(lag, "excess_lag_sec", bin_width=5.0)

    assert hist.sum() == 2
