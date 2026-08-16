"""test_mat_reliability - test chip_timing_analysis.analysis.mat_reliability"""

import pandas as pd
import pytest

from chip_timing_analysis.analysis.mat_reliability import (
    mat_summary,
    flag_weak_mats,
    mat_reliability_verdict,
)


def _raw_reads(rows: list[tuple]) -> pd.DataFrame:
    """rows: list of (mat_id, tag_id, signal_strength)."""
    return pd.DataFrame([
        {"mat_id": m, "tag_id": t, "signal_strength": s}
        for m, t, s in rows
    ])


# ----------------------------------------------------------------------
# mat_summary
# ----------------------------------------------------------------------

def test_counts_reads_unique_tags_and_mean_signal_per_mat():
    raw = _raw_reads([
        ("1", "chipA", 180), ("1", "chipA", 170), ("1", "chipB", 190),
        ("2", "chipC", 150),
    ])

    summary = mat_summary(raw)

    mat1 = summary[summary["mat_id"] == "1"].iloc[0]
    assert mat1["n_reads"] == 3
    assert mat1["n_unique_tags"] == 2
    assert mat1["reads_per_tag"] == 1.5
    assert mat1["mean_signal_strength"] == pytest.approx(180.0)


def test_empty_raw_reads_returns_empty_dataframe_with_expected_columns():
    raw = pd.DataFrame(columns=["mat_id", "tag_id", "signal_strength"])

    summary = mat_summary(raw)

    assert summary.empty
    assert list(summary.columns) == ["mat_id", "n_reads", "n_unique_tags", "reads_per_tag", "mean_signal_strength"]


def test_summary_sorted_by_mat_id():
    raw = _raw_reads([("3", "chipA", 100), ("1", "chipB", 100)])

    summary = mat_summary(raw)

    assert summary["mat_id"].tolist() == ["1", "3"]


# ----------------------------------------------------------------------
# flag_weak_mats
# ----------------------------------------------------------------------

def _summary(rows: list[tuple]) -> pd.DataFrame:
    """rows: list of (mat_id, n_unique_tags, mean_signal_strength)."""
    return pd.DataFrame([
        {"mat_id": m, "n_reads": n * 2, "n_unique_tags": n, "reads_per_tag": 2.0, "mean_signal_strength": s}
        for m, n, s in rows
    ])


def test_flags_mat_with_low_coverage_relative_to_neighbors():
    summary = _summary([("1", 100, 180), ("2", 5, 180), ("3", 100, 180)])

    weak = flag_weak_mats(summary, drop_ratio=0.5)

    assert weak["mat_id"].tolist() == ["2"]


def test_flags_mat_with_low_signal_relative_to_neighbors():
    summary = _summary([("1", 100, 180), ("2", 100, 50), ("3", 100, 180)])

    weak = flag_weak_mats(summary, drop_ratio=0.5)

    assert weak["mat_id"].tolist() == ["2"]


def test_no_flag_for_smooth_taper_toward_edges():
    # coverage naturally tapers toward the edges of the mat run -- an edge
    # mat with lower coverage than the race-wide average, but consistent
    # with its one neighbor, must not be flagged
    summary = _summary([("1", 50, 180), ("2", 90, 180), ("3", 110, 180)])

    weak = flag_weak_mats(summary, drop_ratio=0.5)

    assert weak.empty


def test_edge_mat_compares_only_to_its_single_neighbor():
    summary = _summary([("1", 5, 180), ("2", 100, 180)])

    weak = flag_weak_mats(summary, drop_ratio=0.5)

    assert weak["mat_id"].tolist() == ["1"]


def test_fewer_than_two_mats_returns_empty():
    summary = _summary([("1", 100, 180)])

    weak = flag_weak_mats(summary)

    assert weak.empty


def test_empty_summary_returns_empty():
    summary = pd.DataFrame(columns=["mat_id", "n_reads", "n_unique_tags", "reads_per_tag", "mean_signal_strength"])

    weak = flag_weak_mats(summary)

    assert weak.empty


def test_drop_ratio_is_configurable():
    summary = _summary([("1", 100, 180), ("2", 60, 180), ("3", 100, 180)])

    assert flag_weak_mats(summary, drop_ratio=0.5).empty
    assert not flag_weak_mats(summary, drop_ratio=0.7).empty


# ----------------------------------------------------------------------
# mat_reliability_verdict
# ----------------------------------------------------------------------

def test_verdict_no_systemic_signal_when_no_mats_flagged():
    summary = _summary([("1", 100, 180), ("2", 100, 180)])
    weak = flag_weak_mats(summary)

    verdict = mat_reliability_verdict(summary, weak)

    assert verdict == {"n_mats": 2, "weak_mats": [], "systemic_signal": False}


def test_verdict_flags_systemic_signal_when_mats_flagged():
    summary = _summary([("1", 100, 180), ("2", 5, 180), ("3", 100, 180)])
    weak = flag_weak_mats(summary)

    verdict = mat_reliability_verdict(summary, weak)

    assert verdict["systemic_signal"] is True
    assert verdict["weak_mats"] == ["2"]
