"""test_start_density - test chip_timing_analysis.analysis.start_density"""

import pandas as pd

from chip_timing_analysis.analysis.start_density import (
    START_WINDOW,
    rolling_start_rate,
    start_spread,
)

GUN = pd.Timestamp("2026-07-04 08:00:00")


def _classified(*offsets_sec) -> pd.DataFrame:
    return pd.DataFrame({
        "bib": range(1, len(offsets_sec) + 1),
        "start_time": [GUN + pd.Timedelta(seconds=s) if s is not None else pd.NaT for s in offsets_sec],
    })


def test_start_window_constant():
    assert START_WINDOW == pd.Timedelta(seconds=1)


# ----------------------------------------------------------------------
# rolling_start_rate
# ----------------------------------------------------------------------

def test_rolling_start_rate_counts_within_one_second():
    classified = _classified(0.0, 0.3, 0.9, 2.5)

    result = rolling_start_rate(classified)

    assert result["starters_in_window"].tolist() == [1, 2, 3, 1]


def test_rolling_start_rate_sorts_and_skips_missing_starts():
    classified = _classified(0.9, None, 0.0)

    result = rolling_start_rate(classified)

    assert result["bib"].tolist() == [3, 1]
    assert result["starters_in_window"].tolist() == [1, 2]


def test_rolling_start_rate_no_starts_is_empty():
    result = rolling_start_rate(_classified(None))

    assert result.empty


# ----------------------------------------------------------------------
# start_spread
# ----------------------------------------------------------------------

def test_start_spread_is_quantile_seconds_after_gun():
    classified = _classified(*range(1, 11))  # 1..10s after the gun

    assert start_spread(classified, GUN, quantile=0.9) == 9.1


def test_start_spread_none_without_start_reads():
    assert start_spread(_classified(None), GUN) is None
