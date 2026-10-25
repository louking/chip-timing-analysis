"""test_build - test chip_timing_analysis.report.build"""

import pandas as pd
import pytest

from chip_timing_analysis.report.build import (
    RaceReport,
    _find_one,
    _csv_classify_grouped,
    _late_starts_grouped,
    _rdgo_distance_label,
    _backfill_from_local_log,
    _build_no_chip_report,
)
from chip_timing_analysis.parsers import rdgo_export

from factories import make_export, make_participant, make_read

GUN = pd.Timestamp("2026-05-25 09:00:00")


def _bibs_df(bibs: list[int]) -> pd.DataFrame:
    return pd.DataFrame({"bib": bibs})


def _report(**overrides) -> RaceReport:
    defaults = dict(
        race_name="Test Race", race_date="2026-05-25", distance="5K", gun_time=GUN,
        n_bib_chip_entries=10, n_participants=10,
        zero_reads=_bibs_df([]), missed_start_only=_bibs_df([]), missed_finish_only=_bibs_df([]),
        known_drops=[],
    )
    defaults.update(overrides)
    return RaceReport(**defaults)


# ----------------------------------------------------------------------
# RaceReport.finish_miss_bibs / genuine_finish_miss_bibs
# ----------------------------------------------------------------------

def test_finish_miss_bibs_unions_zero_reads_and_missed_finish_only():
    report = _report(zero_reads=_bibs_df([1, 2]), missed_finish_only=_bibs_df([3]))

    assert report.finish_miss_bibs() == {1, 2, 3}


def test_genuine_finish_miss_bibs_excludes_known_drops():
    report = _report(zero_reads=_bibs_df([1, 2]), missed_finish_only=_bibs_df([3]), known_drops=[2])

    assert report.genuine_finish_miss_bibs() == {1, 3}


def test_genuine_finish_miss_bibs_unaffected_by_drop_not_in_finish_miss_set():
    report = _report(missed_finish_only=_bibs_df([3]), known_drops=[999])

    assert report.genuine_finish_miss_bibs() == {3}


# ----------------------------------------------------------------------
# RaceReport.start_miss_bibs / genuine_start_miss_bibs
# ----------------------------------------------------------------------

def test_start_miss_bibs_unions_zero_reads_and_missed_start_only():
    report = _report(zero_reads=_bibs_df([1]), missed_start_only=_bibs_df([4, 5]))

    assert report.start_miss_bibs() == {1, 4, 5}


def test_genuine_start_miss_bibs_excludes_known_drops():
    report = _report(zero_reads=_bibs_df([1]), missed_start_only=_bibs_df([4, 5]), known_drops=[5])

    assert report.genuine_start_miss_bibs() == {1, 4}


# ----------------------------------------------------------------------
# RaceReport.pct_read_opportunities_missed
# ----------------------------------------------------------------------

def test_pct_read_opportunities_missed_basic_formula():
    # 2 zero_reads (2 opportunities each) + 1 missed_start_only + 2 missed_finish_only
    # = 7 missed of 10*2=20 opportunities
    report = _report(
        n_participants=10,
        zero_reads=_bibs_df([1, 2]),
        missed_start_only=_bibs_df([3]),
        missed_finish_only=_bibs_df([4, 5]),
    )

    assert report.pct_read_opportunities_missed() == pytest.approx(35.0)


def test_pct_read_opportunities_missed_excludes_zero_read_drop_as_2_opportunities():
    report = _report(
        n_participants=10,
        zero_reads=_bibs_df([1, 2]),
        missed_start_only=_bibs_df([3]),
        missed_finish_only=_bibs_df([4, 5]),
        known_drops=[1],  # a zero-read drop excludes 2 opportunities from the numerator
    )

    assert report.pct_read_opportunities_missed() == pytest.approx(25.0)


def test_pct_read_opportunities_missed_excludes_finish_only_drop_as_1_opportunity():
    report = _report(
        n_participants=10,
        zero_reads=_bibs_df([1, 2]),
        missed_start_only=_bibs_df([3]),
        missed_finish_only=_bibs_df([4, 5]),
        known_drops=[4],  # a finish-only drop excludes 1 opportunity
    )

    assert report.pct_read_opportunities_missed() == pytest.approx(30.0)


def test_pct_read_opportunities_missed_zero_participants_is_zero():
    report = _report(n_participants=0)

    assert report.pct_read_opportunities_missed() == 0.0


def test_pct_read_opportunities_missed_no_misses_is_zero():
    report = _report(n_participants=10)

    assert report.pct_read_opportunities_missed() == 0.0


# ----------------------------------------------------------------------
# _find_one
# ----------------------------------------------------------------------

def test_find_one_returns_first_match(tmp_path):
    (tmp_path / "f_260704.log").write_text("x", encoding="utf-8")

    result = _find_one(str(tmp_path / "f_*.log"))

    assert result == str(tmp_path / "f_260704.log")


def test_find_one_returns_none_when_no_match(tmp_path):
    result = _find_one(str(tmp_path / "f_*.log"))

    assert result is None


# ----------------------------------------------------------------------
# _rdgo_distance_label
# ----------------------------------------------------------------------

def test_rdgo_distance_label_prefers_integration_events_field():
    export = make_export()  # default: single 5K scored event, integration_events has distance="5K"

    assert _rdgo_distance_label(export) == "5K"


def test_rdgo_distance_label_falls_back_to_gap_factor_reverse_mapping():
    export = make_export(
        scored_events=[{"scored_event_name": "5K", "min_finish_time": 14 * 60 * 1000, "actual_start_ts": 0, "included_event_ids": ["100"]}],
        integration_events=[{"event_id": "100"}],  # no distance field -> distance_label() returns None
    )

    assert _rdgo_distance_label(export) == "5K"


def test_rdgo_distance_label_fallback_uses_scored_event_name_for_unknown_gap_factor():
    export = make_export(
        scored_events=[{"scored_event_name": "Fun Run", "min_finish_time": 999, "actual_start_ts": 0, "included_event_ids": ["100"]}],
        integration_events=[{"event_id": "100"}],
    )

    assert _rdgo_distance_label(export) == "Fun Run"


def test_rdgo_distance_label_fallback_combines_multiple_events_in_gap_order():
    export = make_export(
        scored_events=[
            {"scored_event_name": "10K", "min_finish_time": 30 * 60 * 1000, "actual_start_ts": 0, "included_event_ids": ["200"]},
            {"scored_event_name": "5K", "min_finish_time": 14 * 60 * 1000, "actual_start_ts": 0, "included_event_ids": ["100"]},
        ],
        integration_events=[{"event_id": "100"}, {"event_id": "200"}],
    )

    assert _rdgo_distance_label(export) == "5K & 10K"


# ----------------------------------------------------------------------
# _csv_classify_grouped
# ----------------------------------------------------------------------

_READ_COLUMNS = ["tag_id", "reader_id", "mat_id", "timestamp", "read_type", "signal_strength", "read_count"]


def _reads(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "tag_id": r["tag_id"], "reader_id": "1", "mat_id": "1", "timestamp": r["timestamp"],
            "read_type": r["read_type"], "signal_strength": 150, "read_count": 1,
        }
        for r in rows
    ], columns=_READ_COLUMNS)


def test_csv_classify_grouped_applies_per_bib_gap_factor():
    # bib 101 (5K, 14min gap) finishes at gun+15min -- qualifies as a finish
    # for the 5K gap factor but would NOT for a 30min (10K) gap factor.
    reads = _reads([{"tag_id": "chip1", "timestamp": GUN + pd.Timedelta(minutes=15), "read_type": "BS"}])
    bib_chip = pd.DataFrame({"bib": [101], "tag_id": ["chip1"]})
    gap_factors = {101: pd.Timedelta(minutes=14)}

    result = _csv_classify_grouped(reads, bib_chip, GUN, gap_factors)

    assert result.iloc[0]["finish_time"] == GUN + pd.Timedelta(minutes=15)


def test_csv_classify_grouped_splits_bibs_by_distinct_gap_factor():
    reads = _reads([
        {"tag_id": "chip5k", "timestamp": GUN + pd.Timedelta(minutes=15), "read_type": "BS"},
        {"tag_id": "chip10k", "timestamp": GUN + pd.Timedelta(minutes=15), "read_type": "BS"},
    ])
    bib_chip = pd.DataFrame({"bib": [101, 201], "tag_id": ["chip5k", "chip10k"]})
    gap_factors = {101: pd.Timedelta(minutes=14), 201: pd.Timedelta(minutes=30)}

    result = _csv_classify_grouped(reads, bib_chip, GUN, gap_factors)

    row_5k = result[result["bib"] == 101].iloc[0]
    row_10k = result[result["bib"] == 201].iloc[0]
    assert row_5k["finish_time"] == GUN + pd.Timedelta(minutes=15)  # past the 14min 5K gap
    assert pd.isna(row_10k["finish_time"])  # before the 30min 10K gap -- not a finish yet


def test_late_starts_grouped_applies_per_bib_gap_factor():
    # both cross at gun+20min: before the 10K's 30min finish window opens
    # (a late start), but inside the 5K's 14min finish window (not one)
    reads = _reads([
        {"tag_id": "chip5k", "timestamp": GUN + pd.Timedelta(minutes=20), "read_type": "LS"},
        {"tag_id": "chip10k", "timestamp": GUN + pd.Timedelta(minutes=20), "read_type": "LS"},
    ])
    bib_chip = pd.DataFrame({"bib": [101, 201], "tag_id": ["chip5k", "chip10k"]})
    gap_factors = {101: pd.Timedelta(minutes=14), 201: pd.Timedelta(minutes=30)}

    result = _late_starts_grouped(reads, bib_chip, GUN, gap_factors)

    assert result["bib"].tolist() == [201]


def test_late_starts_grouped_empty_bib_chip_returns_empty():
    bib_chip = pd.DataFrame({"bib": pd.Series([], dtype="int64"), "tag_id": pd.Series([], dtype="object")})

    result = _late_starts_grouped(_reads([]), bib_chip, GUN, {})

    assert result.empty
    assert "late_start_time" in result.columns


def test_csv_classify_grouped_drops_bibs_missing_a_gap_factor():
    reads = _reads([])
    bib_chip = pd.DataFrame({"bib": [101, 999], "tag_id": ["chip1", "chip999"]})
    gap_factors = {101: pd.Timedelta(minutes=14)}  # 999 has no scored event

    result = _csv_classify_grouped(reads, bib_chip, GUN, gap_factors)

    assert result["bib"].tolist() == [101]


def test_csv_classify_grouped_empty_bib_chip_returns_empty():
    reads = _reads([])
    bib_chip = pd.DataFrame(columns=["bib", "tag_id"])

    result = _csv_classify_grouped(reads, bib_chip, GUN, {})

    assert result.empty


# ----------------------------------------------------------------------
# _backfill_from_local_log
# ----------------------------------------------------------------------

def _classified_all(rows: list[dict]) -> pd.DataFrame:
    cols = ["bib", "start_time", "start_n_reads", "start_device_id", "finish_time", "finish_n_reads", "finish_device_id"]
    return pd.DataFrame(rows, columns=cols)


def _csv_classified(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["bib", "start_time", "start_n_reads", "finish_time", "finish_n_reads"])


def _rdgo():
    return make_export()  # device 2 = Trident (chip), device 1 = Time Machine


def test_backfill_pre_gun_grace_start_is_silent_not_a_suspect():
    classified_all = _classified_all([{
        "bib": 101, "start_time": pd.NaT, "start_n_reads": 0, "start_device_id": None,
        "finish_time": pd.NaT, "finish_n_reads": 0, "finish_device_id": None,
    }])
    csv_classified = _csv_classified([{
        "bib": 101, "start_time": GUN - pd.Timedelta(milliseconds=200), "start_n_reads": 1,
        "finish_time": pd.NaT, "finish_n_reads": 0,
    }])

    result, suspects = _backfill_from_local_log(classified_all, csv_classified, _rdgo(), trident_device_id=2, gun_time=GUN)

    assert result.iloc[0]["start_time"] == GUN - pd.Timedelta(milliseconds=200)
    assert result.iloc[0]["start_device_id"] == 2
    assert suspects == []


def test_backfill_post_gun_start_is_flagged_as_network_suspect():
    classified_all = _classified_all([{
        "bib": 101, "start_time": pd.NaT, "start_n_reads": 0, "start_device_id": None,
        "finish_time": pd.NaT, "finish_n_reads": 0, "finish_device_id": None,
    }])
    csv_classified = _csv_classified([{
        "bib": 101, "start_time": GUN + pd.Timedelta(seconds=5), "start_n_reads": 1,
        "finish_time": pd.NaT, "finish_n_reads": 0,
    }])

    result, suspects = _backfill_from_local_log(classified_all, csv_classified, _rdgo(), trident_device_id=2, gun_time=GUN)

    assert result.iloc[0]["start_time"] == GUN + pd.Timedelta(seconds=5)
    assert suspects == [101]


def test_backfill_missing_finish_backfilled_and_flagged():
    classified_all = _classified_all([{
        "bib": 101, "start_time": GUN, "start_n_reads": 1, "start_device_id": 2,
        "finish_time": pd.NaT, "finish_n_reads": 0, "finish_device_id": None,
    }])
    csv_classified = _csv_classified([{
        "bib": 101, "start_time": GUN, "start_n_reads": 1,
        "finish_time": GUN + pd.Timedelta(minutes=20), "finish_n_reads": 1,
    }])

    result, suspects = _backfill_from_local_log(classified_all, csv_classified, _rdgo(), trident_device_id=2, gun_time=GUN)

    assert result.iloc[0]["finish_time"] == GUN + pd.Timedelta(minutes=20)
    assert result.iloc[0]["finish_device_id"] == 2
    assert suspects == [101]


def test_backfill_leaves_already_chip_sourced_reads_untouched():
    classified_all = _classified_all([{
        "bib": 101, "start_time": GUN, "start_n_reads": 1, "start_device_id": 2,
        "finish_time": GUN + pd.Timedelta(minutes=20), "finish_n_reads": 1, "finish_device_id": 2,
    }])
    csv_classified = _csv_classified([{
        "bib": 101, "start_time": GUN, "start_n_reads": 1,
        "finish_time": GUN + pd.Timedelta(minutes=20, seconds=30), "finish_n_reads": 1,
    }])

    result, suspects = _backfill_from_local_log(classified_all, csv_classified, _rdgo(), trident_device_id=2, gun_time=GUN)

    assert result.iloc[0]["finish_time"] == GUN + pd.Timedelta(minutes=20)  # unchanged
    assert suspects == []


def test_backfill_does_not_override_backup_sourced_finish_when_local_log_has_nothing():
    classified_all = _classified_all([{
        "bib": 101, "start_time": GUN, "start_n_reads": 1, "start_device_id": 2,
        "finish_time": GUN + pd.Timedelta(minutes=20), "finish_n_reads": 1, "finish_device_id": 1,  # TM-sourced
    }])
    csv_classified = _csv_classified([{
        "bib": 101, "start_time": GUN, "start_n_reads": 1,
        "finish_time": pd.NaT, "finish_n_reads": 0,  # local log has nothing
    }])

    result, suspects = _backfill_from_local_log(classified_all, csv_classified, _rdgo(), trident_device_id=2, gun_time=GUN)

    assert result.iloc[0]["finish_time"] == GUN + pd.Timedelta(minutes=20)  # stays TM-sourced
    assert result.iloc[0]["finish_device_id"] == 1
    assert suspects == []


def test_backfill_skips_bib_absent_from_local_log():
    classified_all = _classified_all([{
        "bib": 999, "start_time": pd.NaT, "start_n_reads": 0, "start_device_id": None,
        "finish_time": pd.NaT, "finish_n_reads": 0, "finish_device_id": None,
    }])
    csv_classified = _csv_classified([])  # bib 999 never in bib_chip.csv's local-log classification

    result, suspects = _backfill_from_local_log(classified_all, csv_classified, _rdgo(), trident_device_id=2, gun_time=GUN)

    assert pd.isna(result.iloc[0]["start_time"])
    assert suspects == []


# ----------------------------------------------------------------------
# _build_no_chip_report
# ----------------------------------------------------------------------

def _no_chip_export(entity_map, read_data):
    return make_export(
        scored_events=[{
            "scored_event_name": "5k Run - Timed Event",
            "min_finish_time": None,
            "actual_start_ts": int(GUN.value // 1_000_000),
            "included_event_ids": ["100"],
            "starting_point_id": None,
            "default_segment_finish_occurrence": 1,
        }],
        devices={2: {"device_id": 2, "hardware_name": None, "device_display_name": "Time Machine-FILE"}},
        entity_map=entity_map,
        read_data=read_data,
    )


def _build_no_chip(export, tmp_path, **overrides):
    kwargs = dict(
        race_dir=tmp_path / "race", rdgo=export, race_name="Test", race_date="2026-05-25",
        distance="5K", gun_time=GUN, notes=None, detail_notes=None, n_registered=None,
        n_starters=None, n_finishers=None, known_drops=set(), exclude_bibs=set(),
    )
    kwargs.update(overrides)
    return _build_no_chip_report(**kwargs)


def test_build_no_chip_report_counts_finishers_only(tmp_path):
    export = _no_chip_export(
        entity_map=[
            make_participant(101, scoring_entity_id=1, event_id="100", checked_in=True),
            make_participant(102, scoring_entity_id=2, event_id="100", checked_in=True),
            make_participant(103, scoring_entity_id=3, event_id="100", checked_in=True, rdgo_dns=True),
            make_participant(201, scoring_entity_id=4, event_id="999", checked_in=True),  # untimed event
        ],
        read_data={
            "1": [make_read(1, device_id=2, timestamp=GUN + pd.Timedelta(minutes=25))],
            "2": [make_read(1, device_id=2, timestamp=GUN + pd.Timedelta(minutes=20))],
            "4": [make_read(1, device_id=2, timestamp=GUN + pd.Timedelta(minutes=30))],
        },
    )

    report = _build_no_chip(export, tmp_path)

    assert report.chip_timed is False
    assert report.n_participants == 2
    assert report.classified["bib"].tolist() == [102, 101]  # finish order
    assert report.checked_in_no_finish == [103]
    assert report.no_chip_assigned.empty
    assert report.zero_reads.empty and report.missed_start_only.empty and report.missed_finish_only.empty
    assert report.pct_read_opportunities_missed() == 0.0
    assert report.lag is None  # no logs/barcode-scanner.log next to race_dir


def test_build_no_chip_report_applies_exclude_bibs(tmp_path):
    export = _no_chip_export(
        entity_map=[
            make_participant(101, scoring_entity_id=1, event_id="100", checked_in=True),
            make_participant(102, scoring_entity_id=2, event_id="100", checked_in=True),
            make_participant(103, scoring_entity_id=3, event_id="100", checked_in=True),
        ],
        read_data={
            "1": [make_read(1, device_id=2, timestamp=GUN + pd.Timedelta(minutes=25))],
            "2": [make_read(1, device_id=2, timestamp=GUN + pd.Timedelta(minutes=20))],
        },
    )

    report = _build_no_chip(export, tmp_path, exclude_bibs={101, 103})

    assert report.classified["bib"].tolist() == [102]
    assert report.checked_in_no_finish == []
