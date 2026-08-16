"""test_timing_utils - test chip_timing_analysis.analysis.timing_utils"""

import pandas as pd

from chip_timing_analysis.analysis.timing_utils import rolling_count


def _times(*hms) -> pd.Series:
    return pd.Series([pd.Timestamp(f"2026-07-04 {h:02d}:{m:02d}:{s:02d}") for h, m, s in hms])


# ----------------------------------------------------------------------
# rolling_count
# ----------------------------------------------------------------------

def test_excludes_self_by_default():
    times = _times((8, 0, 0), (8, 0, 10), (8, 0, 20))

    counts = rolling_count(times, pd.Timedelta(seconds=30))

    assert counts == [0, 1, 2]


def test_include_self_counts_itself_too():
    times = _times((8, 0, 0), (8, 0, 10), (8, 0, 20))

    counts = rolling_count(times, pd.Timedelta(seconds=30), include_self=True)

    assert counts == [1, 2, 3]


def test_window_boundary_is_inclusive_of_window_start():
    # values[start] < t - window keeps advancing start; a point exactly
    # `window` before t is NOT dropped (only strictly-less-than is).
    times = _times((8, 0, 0), (8, 0, 30))

    counts = rolling_count(times, pd.Timedelta(seconds=30))

    assert counts == [0, 1]


def test_points_outside_window_are_excluded():
    times = _times((8, 0, 0), (8, 0, 31))

    counts = rolling_count(times, pd.Timedelta(seconds=30))

    assert counts == [0, 0]


def test_single_timestamp():
    times = _times((8, 0, 0))

    assert rolling_count(times, pd.Timedelta(seconds=30)) == [0]
    assert rolling_count(times, pd.Timedelta(seconds=30), include_self=True) == [1]


def test_empty_series_returns_empty_list():
    times = pd.Series([], dtype="datetime64[ns]")

    assert rolling_count(times, pd.Timedelta(seconds=30)) == []


def test_dense_cluster_counts_all_prior_points_in_window():
    times = _times((8, 0, 0), (8, 0, 1), (8, 0, 2), (8, 0, 3))

    counts = rolling_count(times, pd.Timedelta(seconds=60))

    assert counts == [0, 1, 2, 3]
