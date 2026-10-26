"""test_finish_density - test chip_timing_analysis.analysis.finish_density"""

import pandas as pd

from chip_timing_analysis.analysis.finish_density import (
    STANDARD_WINDOW,
    BURST_WINDOW,
    SHORT_BURST_WINDOW,
    finish_density,
    rolling_finish_rate,
    finish_gaps,
)

FT = pd.Timestamp("2026-07-04 09:00:00")


def _classified(*offsets_sec) -> pd.DataFrame:
    return pd.DataFrame({
        "bib": range(1, len(offsets_sec) + 1),
        "finish_time": [FT + pd.Timedelta(seconds=s) if s is not None else pd.NaT for s in offsets_sec],
    })


def test_standard_and_burst_window_constants():
    assert STANDARD_WINDOW == pd.Timedelta(seconds=60)
    assert BURST_WINDOW == pd.Timedelta(seconds=15)
    assert SHORT_BURST_WINDOW == pd.Timedelta(seconds=5)


# ----------------------------------------------------------------------
# finish_density
# ----------------------------------------------------------------------

def test_bins_finishers_into_bucket_of_bin_width():
    classified = _classified(0, 5, 10, 40)  # first 3 in one 30s bucket, 4th in the next

    density = finish_density(classified, bin_width=pd.Timedelta(seconds=30))

    counts = dict(zip(density["bin_start"], density["n_finishers"]))
    assert counts[FT] == 3
    assert counts[FT + pd.Timedelta(seconds=30)] == 1


def test_excludes_bibs_with_no_finish_time():
    classified = _classified(0, None)

    density = finish_density(classified, bin_width=pd.Timedelta(seconds=30))

    assert density["n_finishers"].sum() == 1


# ----------------------------------------------------------------------
# rolling_finish_rate
# ----------------------------------------------------------------------

def test_rolling_finish_rate_includes_self():
    classified = _classified(0, 5, 10)

    result = rolling_finish_rate(classified, window=pd.Timedelta(seconds=60))

    # every finisher is within 60s of every other -- each should see all 3
    assert result["finishers_in_window"].tolist() == [1, 2, 3]


def test_rolling_finish_rate_excludes_bibs_with_no_finish():
    classified = _classified(0, None, 5)

    result = rolling_finish_rate(classified)

    assert len(result) == 2


# ----------------------------------------------------------------------
# finish_gaps
# ----------------------------------------------------------------------

def test_finish_gaps_between_consecutive_finishers():
    classified = _classified(0, 5, 20)

    gaps = finish_gaps(classified)

    assert gaps.tolist() == [5.0, 15.0]


def test_finish_gaps_sorts_before_diffing():
    classified = _classified(20, 0, 5)  # out of order input

    gaps = finish_gaps(classified)

    assert gaps.tolist() == [5.0, 15.0]


def test_finish_gaps_single_finisher_is_empty():
    classified = _classified(0)

    gaps = finish_gaps(classified)

    assert gaps.empty
