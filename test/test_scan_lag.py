"""test_scan_lag - test chip_timing_analysis.analysis.scan_lag"""

import pandas as pd

from chip_timing_analysis.analysis.scan_lag import format_text, scan_lag_summary, tm_scan_lag

T0 = pd.Timestamp("2026-10-25 09:20:00")


def _tm(rows):
    """rows: [(pos, bib, seconds after T0)]"""
    return pd.DataFrame(
        [{"send_time": T0 + pd.Timedelta(seconds=s), "opcode": "select" if b else "primary", "pos": p, "bib": b}
         for p, b, s in rows],
        columns=["send_time", "opcode", "pos", "bib"],
    )


def _scans(rows):
    """rows: [(bib, seconds after T0)]"""
    return pd.DataFrame([{"bib": b, "send_time": T0 + pd.Timedelta(seconds=s)} for b, s in rows],
                        columns=["bib", "send_time"])


# ----------------------------------------------------------------------
# tm_scan_lag
# ----------------------------------------------------------------------

def test_skips_results_without_keypad_bib():
    lag = tm_scan_lag(_tm([(1, 0, 0), (2, 101, 5)]), _scans([(101, 9)]))

    assert lag["pos"].tolist() == [2]
    assert lag.iloc[0]["lag_sec"] == 4
    assert bool(lag.iloc[0]["matched"]) is True


def test_uses_scan_nearest_the_result():
    lag = tm_scan_lag(_tm([(1, 101, 100)]), _scans([(101, 30), (101, 103), (101, 200)]))

    assert lag.iloc[0]["lag_sec"] == 3
    assert lag.iloc[0]["scan_time"] == T0 + pd.Timedelta(seconds=103)


def test_beyond_max_lag_or_no_scan_is_unmatched():
    lag = tm_scan_lag(_tm([(1, 101, 0), (2, 102, 0)]), _scans([(101, 75)]))

    assert lag["matched"].tolist() == [False, False]
    assert lag.iloc[0]["lag_sec"] == 75
    assert pd.isna(lag.iloc[1]["lag_sec"])


def test_empty_inputs_keep_columns():
    lag = tm_scan_lag(_tm([]), _scans([]))

    assert lag.empty
    assert list(lag.columns) == ["pos", "bib", "tm_time", "scan_time", "lag_sec", "matched"]


# ----------------------------------------------------------------------
# scan_lag_summary / format_text
# ----------------------------------------------------------------------

def test_summary_uses_matched_rows_only():
    lag = tm_scan_lag(_tm([(1, 101, 0), (2, 102, 0), (3, 103, 0), (4, 104, 0)]),
                      _scans([(101, 2), (102, 4), (103, 6)]))

    s = scan_lag_summary(lag)

    assert (s["n_results"], s["n_matched"]) == (4, 3)
    assert (s["median"], s["min"], s["max"]) == (4, 2, 6)


def test_summary_needs_two_matches_for_stats():
    s = scan_lag_summary(tm_scan_lag(_tm([(1, 101, 0)]), _scans([(101, 2)])))

    assert s["n_matched"] == 1
    assert s["median"] is None


def test_format_text_lists_slow_and_unmatched():
    lag = tm_scan_lag(_tm([(1, 101, 0), (2, 102, 0), (3, 103, 0)]), _scans([(101, 3), (102, 12.5)]))

    text = format_text(lag, slow=10)

    assert text.splitlines()[0] == "3 keypad results, 2 matched to their own scan, 1 not"
    assert "     2    102   12.5s" in text
    assert "     3    103   no scan" in text
