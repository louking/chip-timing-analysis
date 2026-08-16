"""test_start_finish - test chip_timing_analysis.analysis.start_finish

Follows the classification theory documented in start_finish.py's module
docstring and validated in CLAUDE.md against the Indy 5000 / Parkway Panda
5K: classify by time-of-day + Gap Factor (mat_id can't distinguish start
from finish -- same physical mats serve both).
"""

import pandas as pd
import pytest

from chip_timing_analysis.analysis.start_finish import (
    GAP_FACTOR_BY_DISTANCE,
    DEFAULT_START_OFFSET,
    DEFAULT_PRE_GUN_GRACE,
    classify_start_finish,
    missed_start_reads,
    missed_finish_reads,
)

GUN = pd.Timestamp("2026-07-04 08:30:00")
GAP = pd.Timedelta(minutes=5)  # a short gap factor keeps test timestamps readable


_READ_COLUMNS = ["tag_id", "reader_id", "mat_id", "timestamp", "read_type", "signal_strength", "read_count"]


def _reads(rows: list[dict]) -> pd.DataFrame:
    """rows: list of {tag_id, timestamp, read_type}."""
    return pd.DataFrame([
        {
            "tag_id": r["tag_id"],
            "reader_id": "1",
            "mat_id": "1",
            "timestamp": r["timestamp"],
            "read_type": r["read_type"],
            "signal_strength": 150,
            "read_count": 1,
        }
        for r in rows
    ], columns=_READ_COLUMNS)


def _bib_chip(mapping: dict) -> pd.DataFrame:
    return pd.DataFrame({"bib": list(mapping.keys()), "tag_id": list(mapping.values())})


# ----------------------------------------------------------------------
# constants
# ----------------------------------------------------------------------

def test_gap_factor_by_distance_values():
    assert GAP_FACTOR_BY_DISTANCE["5K"] == pd.Timedelta(minutes=14)
    assert GAP_FACTOR_BY_DISTANCE["10K"] == pd.Timedelta(minutes=30)
    assert GAP_FACTOR_BY_DISTANCE["10M"] == pd.Timedelta(minutes=50)


def test_default_start_offset_and_pre_gun_grace():
    assert DEFAULT_START_OFFSET == pd.Timedelta(minutes=2)
    assert DEFAULT_PRE_GUN_GRACE == pd.Timedelta(seconds=1)


# ----------------------------------------------------------------------
# basic classification
# ----------------------------------------------------------------------

def test_clean_start_and_finish_read():
    reads = _reads([
        {"tag_id": "chip1", "timestamp": GUN + pd.Timedelta(seconds=5), "read_type": "LS"},
        {"tag_id": "chip1", "timestamp": GUN + GAP + pd.Timedelta(seconds=1), "read_type": "BS"},
    ])
    bib_chip = _bib_chip({101: "chip1"})

    result = classify_start_finish(reads, bib_chip, gun_time=GUN, gap_factor=GAP)

    row = result[result["bib"] == 101].iloc[0]
    assert row["start_time"] == GUN + pd.Timedelta(seconds=5)
    assert row["start_n_reads"] == 1
    assert row["finish_time"] == GUN + GAP + pd.Timedelta(seconds=1)
    assert row["finish_n_reads"] == 1


def test_bib_with_no_reads_at_all_has_nat_start_and_finish():
    reads = _reads([])
    bib_chip = _bib_chip({101: "chip1"})

    result = classify_start_finish(reads, bib_chip, gun_time=GUN, gap_factor=GAP)

    row = result[result["bib"] == 101].iloc[0]
    assert pd.isna(row["start_time"])
    assert pd.isna(row["finish_time"])
    assert row["start_n_reads"] == 0
    assert row["finish_n_reads"] == 0


def test_one_row_per_bib_chip_bib_even_with_no_reads():
    reads = _reads([])
    bib_chip = _bib_chip({101: "chip1", 102: "chip2"})

    result = classify_start_finish(reads, bib_chip, gun_time=GUN, gap_factor=GAP)

    assert sorted(result["bib"].tolist()) == [101, 102]


def test_reads_for_unassigned_tag_are_ignored():
    # inner join on tag_id -- a read for a tag not in bib_chip contributes nothing
    reads = _reads([
        {"tag_id": "unassigned", "timestamp": GUN + pd.Timedelta(seconds=5), "read_type": "LS"},
    ])
    bib_chip = _bib_chip({101: "chip1"})

    result = classify_start_finish(reads, bib_chip, gun_time=GUN, gap_factor=GAP)

    row = result[result["bib"] == 101].iloc[0]
    assert pd.isna(row["start_time"])


# ----------------------------------------------------------------------
# start window / pre_gun_grace
# ----------------------------------------------------------------------

def test_start_window_upper_bound_is_inclusive():
    reads = _reads([{"tag_id": "chip1", "timestamp": GUN + DEFAULT_START_OFFSET, "read_type": "LS"}])
    bib_chip = _bib_chip({101: "chip1"})

    result = classify_start_finish(reads, bib_chip, gun_time=GUN, gap_factor=GAP)

    assert result.iloc[0]["start_time"] == GUN + DEFAULT_START_OFFSET


def test_start_window_just_past_offset_is_excluded():
    reads = _reads([{"tag_id": "chip1", "timestamp": GUN + DEFAULT_START_OFFSET + pd.Timedelta(seconds=1), "read_type": "LS"}])
    bib_chip = _bib_chip({101: "chip1"})

    result = classify_start_finish(reads, bib_chip, gun_time=GUN, gap_factor=GAP)

    assert pd.isna(result.iloc[0]["start_time"])


def test_pre_gun_grace_allows_a_read_just_before_gun_time():
    # front-of-field runner whose chip crosses a fraction of a second before
    # the automatic GUNTIME marker registers (Parkway Panda 5K bibs 180/314/349)
    reads = _reads([{"tag_id": "chip1", "timestamp": GUN - pd.Timedelta(milliseconds=300), "read_type": "LS"}])
    bib_chip = _bib_chip({101: "chip1"})

    result = classify_start_finish(reads, bib_chip, gun_time=GUN, gap_factor=GAP)

    assert result.iloc[0]["start_time"] == GUN - pd.Timedelta(milliseconds=300)


def test_read_before_pre_gun_grace_window_is_excluded_as_noise():
    # a bench-test chip read tens of minutes before gun_time must not be
    # mistaken for a start (Panda 5K bib 375)
    reads = _reads([{"tag_id": "chip1", "timestamp": GUN - pd.Timedelta(minutes=58), "read_type": "LS"}])
    bib_chip = _bib_chip({101: "chip1"})

    result = classify_start_finish(reads, bib_chip, gun_time=GUN, gap_factor=GAP)

    assert pd.isna(result.iloc[0]["start_time"])


def test_custom_pre_gun_grace_is_respected():
    reads = _reads([{"tag_id": "chip1", "timestamp": GUN - pd.Timedelta(seconds=3), "read_type": "LS"}])
    bib_chip = _bib_chip({101: "chip1"})

    result = classify_start_finish(reads, bib_chip, gun_time=GUN, gap_factor=GAP, pre_gun_grace=pd.Timedelta(seconds=5))

    assert result.iloc[0]["start_time"] == GUN - pd.Timedelta(seconds=3)


def test_start_time_uses_ls_read_type_only():
    # only a BS read in the start window -- no LS -- so start_time is NaT,
    # but start_n_reads still counts the BS read (occurrence-1 group size,
    # not filtered by read_type -- see _first_occurrence_picks).
    reads = _reads([{"tag_id": "chip1", "timestamp": GUN + pd.Timedelta(seconds=5), "read_type": "BS"}])
    bib_chip = _bib_chip({101: "chip1"})

    result = classify_start_finish(reads, bib_chip, gun_time=GUN, gap_factor=GAP)

    row = result.iloc[0]
    assert pd.isna(row["start_time"])
    assert row["start_n_reads"] == 1


# ----------------------------------------------------------------------
# finish window / occurrence splitting
# ----------------------------------------------------------------------

def test_finish_window_lower_bound_is_inclusive():
    reads = _reads([{"tag_id": "chip1", "timestamp": GUN + GAP, "read_type": "BS"}])
    bib_chip = _bib_chip({101: "chip1"})

    result = classify_start_finish(reads, bib_chip, gun_time=GUN, gap_factor=GAP)

    assert result.iloc[0]["finish_time"] == GUN + GAP


def test_finish_time_uses_bs_read_of_first_occurrence_only():
    # first occurrence: the real finish crossing (LS+BS pair). A second,
    # much-later occurrence (gap >= gap_factor) is noise/a double crossing
    # and must not override the first occurrence's BS pick.
    reads = _reads([
        {"tag_id": "chip1", "timestamp": GUN + GAP, "read_type": "LS"},
        {"tag_id": "chip1", "timestamp": GUN + GAP + pd.Timedelta(seconds=1), "read_type": "BS"},
        {"tag_id": "chip1", "timestamp": GUN + GAP + GAP + pd.Timedelta(seconds=1), "read_type": "BS"},
    ])
    bib_chip = _bib_chip({101: "chip1"})

    result = classify_start_finish(reads, bib_chip, gun_time=GUN, gap_factor=GAP)

    row = result.iloc[0]
    assert row["finish_time"] == GUN + GAP + pd.Timedelta(seconds=1)
    assert row["finish_n_reads"] == 2  # only the first occurrence's 2 reads


def test_finish_occurrence_boundary_gap_exactly_at_gap_factor_starts_new_occurrence():
    reads = _reads([
        {"tag_id": "chip1", "timestamp": GUN + GAP, "read_type": "BS"},
        {"tag_id": "chip1", "timestamp": GUN + GAP + GAP, "read_type": "BS"},  # gap == GAP -> new occurrence
    ])
    bib_chip = _bib_chip({101: "chip1"})

    result = classify_start_finish(reads, bib_chip, gun_time=GUN, gap_factor=GAP)

    assert result.iloc[0]["finish_time"] == GUN + GAP
    assert result.iloc[0]["finish_n_reads"] == 1


def test_finish_time_nat_when_first_occurrence_has_no_bs_read():
    reads = _reads([{"tag_id": "chip1", "timestamp": GUN + GAP, "read_type": "LS"}])
    bib_chip = _bib_chip({101: "chip1"})

    result = classify_start_finish(reads, bib_chip, gun_time=GUN, gap_factor=GAP)

    row = result.iloc[0]
    assert pd.isna(row["finish_time"])
    assert row["finish_n_reads"] == 1


def test_start_and_finish_are_independent_for_the_same_tag():
    # a read between the two windows (neither in [gun-grace, gun+offset] nor
    # >= gun+gap_factor) contributes to neither
    reads = _reads([
        {"tag_id": "chip1", "timestamp": GUN + pd.Timedelta(seconds=5), "read_type": "LS"},
        {"tag_id": "chip1", "timestamp": GUN + pd.Timedelta(minutes=3), "read_type": "RR"},
        {"tag_id": "chip1", "timestamp": GUN + GAP, "read_type": "BS"},
    ])
    bib_chip = _bib_chip({101: "chip1"})

    result = classify_start_finish(reads, bib_chip, gun_time=GUN, gap_factor=GAP)

    row = result.iloc[0]
    assert row["start_time"] == GUN + pd.Timedelta(seconds=5)
    assert row["finish_time"] == GUN + GAP


# ----------------------------------------------------------------------
# missed_start_reads / missed_finish_reads
# ----------------------------------------------------------------------

def test_missed_start_reads_returns_only_nat_start_bibs():
    reads = _reads([
        {"tag_id": "chip1", "timestamp": GUN + pd.Timedelta(seconds=5), "read_type": "LS"},
        {"tag_id": "chip2", "timestamp": GUN + GAP, "read_type": "BS"},  # finish only, no start read
    ])
    bib_chip = _bib_chip({101: "chip1", 102: "chip2"})
    classified = classify_start_finish(reads, bib_chip, gun_time=GUN, gap_factor=GAP)

    missed = missed_start_reads(classified)

    assert missed["bib"].tolist() == [102]


def test_missed_finish_reads_returns_only_nat_finish_bibs():
    reads = _reads([{"tag_id": "chip1", "timestamp": GUN + pd.Timedelta(seconds=5), "read_type": "LS"}])
    bib_chip = _bib_chip({101: "chip1", 102: "chip2"})
    classified = classify_start_finish(reads, bib_chip, gun_time=GUN, gap_factor=GAP)

    missed = missed_finish_reads(classified)

    assert missed["bib"].tolist() == [101, 102]


def test_missed_start_and_finish_are_empty_when_everyone_has_both():
    reads = _reads([
        {"tag_id": "chip1", "timestamp": GUN + pd.Timedelta(seconds=5), "read_type": "LS"},
        {"tag_id": "chip1", "timestamp": GUN + GAP, "read_type": "BS"},
    ])
    bib_chip = _bib_chip({101: "chip1"})
    classified = classify_start_finish(reads, bib_chip, gun_time=GUN, gap_factor=GAP)

    assert missed_start_reads(classified).empty
    assert missed_finish_reads(classified).empty
