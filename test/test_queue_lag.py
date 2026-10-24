"""test_queue_lag - test chip_timing_analysis.analysis.queue_lag"""

import pandas as pd

from chip_timing_analysis.analysis.queue_lag import (
    compute_lag,
    add_excess_lag,
    add_finish_rate,
    lag_histogram,
    scanner_clock_offset,
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


# ----------------------------------------------------------------------
# scanner_clock_offset
# ----------------------------------------------------------------------

def _tm_entries(rows: list[tuple]) -> pd.DataFrame:
    """rows: list of (recv_time, elapsed_sec)."""
    return pd.DataFrame(
        [{"recv_time": r, "pos": i + 1, "elapsed": pd.Timedelta(seconds=e)} for i, (r, e) in enumerate(rows)],
        columns=["recv_time", "pos", "elapsed"],
    )


def test_scanner_clock_offset_uses_floored_gun_time():
    gun = pd.Timestamp("2026-10-03 08:15:28.825")
    # TM clock started at 08:15:01.90 laptop time; zero-delay entry
    entries = _tm_entries([(pd.Timestamp("2026-10-03 08:33:24.40"), 1102.50)])

    offset = scanner_clock_offset(entries, gun)

    # floor(gun) 08:15:28 + 18:22.50 = 08:33:50.50, minus 08:33:24.40
    assert offset == pd.Timedelta(seconds=26.10)


def test_scanner_clock_offset_takes_least_delayed_entry():
    gun = pd.Timestamp("2026-10-03 08:15:00")
    entries = _tm_entries([
        (pd.Timestamp("2026-10-03 08:35:00.30"), 1200),  # 0.3s delay
        (pd.Timestamp("2026-10-03 08:36:00.10"), 1260),  # 0.1s delay
    ])

    assert scanner_clock_offset(entries, gun) == pd.Timedelta(seconds=-0.10)


def test_scanner_clock_offset_ignores_outlier_test_entry():
    gun = pd.Timestamp("2026-10-03 08:15:00")
    entries = _tm_entries([
        (pd.Timestamp("2026-10-03 07:10:02"), 5),  # pre-race test press
        (pd.Timestamp("2026-10-03 08:35:00.20"), 1200),
        (pd.Timestamp("2026-10-03 08:36:00.20"), 1260),
    ])

    assert scanner_clock_offset(entries, gun) == pd.Timedelta(seconds=-0.20)


def test_scanner_clock_offset_none_when_no_entries_after_race_reset():
    # Mustang's Milestone 5K: TM reset at the start, then failed; only entry
    # was a test press after an earlier reset
    gun = pd.Timestamp("2026-10-24 08:30:27.78")
    entries = _tm_entries([(pd.Timestamp("2026-10-24 07:40:33.59"), 10.83)])
    resets = pd.Series([pd.Timestamp("2026-10-24 07:40:22.51"), pd.Timestamp("2026-10-24 08:30:29.65")])

    assert scanner_clock_offset(entries, gun, resets=resets) is None


def test_scanner_clock_offset_uses_entries_after_reset_nearest_gun():
    gun = pd.Timestamp("2026-10-03 08:15:00")
    entries = _tm_entries([
        (pd.Timestamp("2026-10-03 08:14:00.00"), 30),  # test press after 08:13:30 reset
        (pd.Timestamp("2026-10-03 08:35:01.20"), 1200),
        (pd.Timestamp("2026-10-03 08:36:01.20"), 1260),
    ])
    resets = pd.Series([pd.Timestamp("2026-10-03 08:13:30"), pd.Timestamp("2026-10-03 08:15:01")])

    # the test press alone would give +0:00:30 - 1 min = -30s; it's dropped
    assert scanner_clock_offset(entries, gun, resets=resets) == pd.Timedelta(seconds=-1.20)


def test_scanner_clock_offset_drops_entries_after_next_reset():
    gun = pd.Timestamp("2026-10-03 08:15:00")
    entries = _tm_entries([
        (pd.Timestamp("2026-10-03 08:35:00.20"), 1200),
        (pd.Timestamp("2026-10-03 10:00:10.00"), 10),  # after a later reset
    ])
    resets = pd.Series([pd.Timestamp("2026-10-03 08:15:00"), pd.Timestamp("2026-10-03 10:00:00")])

    assert scanner_clock_offset(entries, gun, resets=resets) == pd.Timedelta(seconds=-0.20)


def test_scanner_clock_offset_none_without_entries():
    assert scanner_clock_offset(_tm_entries([]), pd.Timestamp("2026-10-03 08:15:00")) is None
