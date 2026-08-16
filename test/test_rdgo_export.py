"""test_rdgo_export - test chip_timing_analysis.parsers.rdgo_export"""

import json
import zipfile

import pandas as pd
import pytest

from chip_timing_analysis.parsers.rdgo_export import (
    parse_rdgo_export,
    is_chip_device,
    device_label,
    gun_time,
    n_registered,
    bib_gap_factors,
    distance_label,
    bib_chip,
    known_drops,
    classify_start_finish,
    backup_time_selected,
)

from factories import make_export, make_participant, make_read

GUN = pd.Timestamp("2026-05-25 09:00:00")


# ----------------------------------------------------------------------
# parse_rdgo_export
# ----------------------------------------------------------------------

def test_parses_race_json_and_filterer_data_from_zip(tmp_path):
    race_json = {
        "race": {"name": "Test Race", "start_date": "2026-05-25", "integration_data": {"timezone": "UTC"}},
        "scored_events": [{"scored_event_name": "5K", "min_finish_time": 840000, "actual_start_ts": int(GUN.value // 1_000_000), "included_event_ids": ["100"]}],
        "timing_locations": [{"gap_factors": [840000]}],
        "integration_events": [{"event_id": "100", "distance": "5K"}],
        "devices": [{"device_id": 1, "device_display_name": "Time Machine-FILE"}],
    }
    filterer = {"entity_map": [], "read_data": {}}
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("Test Race.json", json.dumps(race_json))
        zf.writestr("filterer.data", json.dumps(filterer))
        zf.writestr("logs/main.log", "unrelated diagnostic content")

    export = parse_rdgo_export(zip_path)

    assert export.race["name"] == "Test Race"
    assert export.entity_map == []
    assert export.devices == {1: {"device_id": 1, "device_display_name": "Time Machine-FILE"}}


def test_filterer_data_not_mistaken_for_the_race_json_member(tmp_path):
    # filterer.data is easy to mistake for a race json member since it sits
    # alongside main.log/api.log -- the race json lookup must exclude it by
    # name, not just by picking "a json file".
    race_json = {
        "race": {"name": "R", "start_date": "2026-05-25", "integration_data": {"timezone": "UTC"}},
        "scored_events": [], "timing_locations": [{}], "devices": [],
    }
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("filterer.data", json.dumps({"entity_map": [], "read_data": {}}))
        zf.writestr("R.json", json.dumps(race_json))

    export = parse_rdgo_export(zip_path)

    assert export.race["name"] == "R"


# ----------------------------------------------------------------------
# is_chip_device / device_label
# ----------------------------------------------------------------------

def test_is_chip_device_true_for_device_with_hardware_name():
    export = make_export()

    assert is_chip_device(export, 2) is True  # Trident, has hardware_name


def test_is_chip_device_false_for_file_fed_device():
    export = make_export()

    assert is_chip_device(export, 1) is False  # Time Machine, no hardware_name


def test_is_chip_device_none_for_unknown_device_id():
    export = make_export()

    assert is_chip_device(export, 999) is None


def test_is_chip_device_none_for_none_device_id():
    export = make_export()

    assert is_chip_device(export, None) is None


def test_is_chip_device_none_for_nan_device_id():
    export = make_export()

    assert is_chip_device(export, float("nan")) is None


def test_device_label_returns_display_name():
    export = make_export()

    assert device_label(export, 2) == "Trident UHF8 A-DIRECT"


def test_device_label_none_for_unknown_device():
    export = make_export()

    assert device_label(export, 999) is None


# ----------------------------------------------------------------------
# gun_time
# ----------------------------------------------------------------------

def test_gun_time_reads_actual_start_ts_in_utc():
    export = make_export(gun_time=GUN, timezone="UTC")

    assert gun_time(export) == GUN


def test_gun_time_converts_from_timezone():
    # actual_start_ts is a UTC epoch; a race in a UTC-4 zone should read back
    # 4 hours earlier as a naive local wall-clock time
    export = make_export(gun_time=GUN, timezone="America/New_York")

    result = gun_time(export)

    assert result == GUN - pd.Timedelta(hours=4)  # EDT in May


def test_gun_time_raises_on_staggered_start():
    export = make_export(scored_events=[
        {"scored_event_name": "5K", "min_finish_time": 840000, "actual_start_ts": int(GUN.value // 1_000_000), "included_event_ids": ["100"]},
        {"scored_event_name": "10K", "min_finish_time": 1800000, "actual_start_ts": int(GUN.value // 1_000_000) + 60000, "included_event_ids": ["101"]},
    ])

    with pytest.raises(ValueError, match="staggered-start"):
        gun_time(export)


# ----------------------------------------------------------------------
# n_registered
# ----------------------------------------------------------------------

def test_n_registered_counts_entities_in_scored_event():
    export = make_export(entity_map=[
        make_participant(101, scoring_entity_id=1, event_id="100"),
        make_participant(102, scoring_entity_id=2, event_id="100"),
        make_participant(None, scoring_entity_id=3, event_id="999"),  # different event
    ])

    assert n_registered(export) == 2


def test_n_registered_includes_no_shows_without_a_bib():
    # a no-show may never have been assigned a bib at all -- must still count
    export = make_export(entity_map=[
        make_participant(None, scoring_entity_id=1, event_id="100", rdgo_dns=True, rdgo_dnf=True),
    ])

    assert n_registered(export) == 1


def test_n_registered_excludes_companion_division_outside_scored_event():
    export = make_export(entity_map=[
        make_participant(101, scoring_entity_id=1, event_id="100"),
    ], integration_events=[{"event_id": "100", "distance": "5K"}, {"event_id": "999", "distance": "5K"}])
    export.entity_map.append(make_participant(500, scoring_entity_id=2, event_id="999"))

    assert n_registered(export) == 1


# ----------------------------------------------------------------------
# bib_gap_factors
# ----------------------------------------------------------------------

def test_bib_gap_factors_maps_bib_to_own_scored_event_gap():
    se_5k = {"scored_event_name": "5K", "min_finish_time": 14 * 60 * 1000, "actual_start_ts": 0, "included_event_ids": ["100"]}
    se_10k = {"scored_event_name": "10K", "min_finish_time": 30 * 60 * 1000, "actual_start_ts": 0, "included_event_ids": ["200"]}
    export = make_export(
        scored_events=[se_5k, se_10k],
        integration_events=[{"event_id": "100", "distance": "5K"}, {"event_id": "200", "distance": "10K"}],
        entity_map=[
            make_participant(101, scoring_entity_id=1, event_id="100"),
            make_participant(201, scoring_entity_id=2, event_id="200"),
        ],
    )

    result = bib_gap_factors(export)

    assert result[101] == pd.Timedelta(minutes=14)
    assert result[201] == pd.Timedelta(minutes=30)


def test_bib_gap_factors_excludes_bib_with_no_bib_num():
    export = make_export(entity_map=[make_participant(None, scoring_entity_id=1, event_id="100")])

    assert bib_gap_factors(export) == {}


# ----------------------------------------------------------------------
# distance_label
# ----------------------------------------------------------------------

def test_distance_label_single_distance():
    export = make_export()

    assert distance_label(export) == "5K"


def test_distance_label_agrees_across_multiple_included_event_ids():
    # Panda 5K case: two age-based registration categories, both "5K"
    export = make_export(
        scored_events=[{"scored_event_name": "5K", "min_finish_time": 840000, "actual_start_ts": 0, "included_event_ids": ["100", "101"]}],
        integration_events=[{"event_id": "100", "distance": "5K"}, {"event_id": "101", "distance": "5K"}],
    )

    assert distance_label(export) == "5K"


def test_distance_label_combines_multiple_scored_events():
    export = make_export(
        scored_events=[
            {"scored_event_name": "5K", "min_finish_time": 840000, "actual_start_ts": 0, "included_event_ids": ["100"]},
            {"scored_event_name": "10K", "min_finish_time": 1800000, "actual_start_ts": 0, "included_event_ids": ["200"]},
        ],
        integration_events=[{"event_id": "100", "distance": "5K"}, {"event_id": "200", "distance": "10K"}],
    )

    assert distance_label(export) == "5K & 10K"


def test_distance_label_none_when_included_events_disagree():
    export = make_export(
        scored_events=[{"scored_event_name": "mixed", "min_finish_time": 840000, "actual_start_ts": 0, "included_event_ids": ["100", "200"]}],
        integration_events=[{"event_id": "100", "distance": "5K"}, {"event_id": "200", "distance": "10K"}],
    )

    assert distance_label(export) is None


def test_distance_label_none_when_field_missing():
    export = make_export(integration_events=[{"event_id": "100"}])

    assert distance_label(export) is None


# ----------------------------------------------------------------------
# bib_chip
# ----------------------------------------------------------------------

def test_bib_chip_includes_only_participants_with_a_chip():
    export = make_export(entity_map=[
        make_participant(101, scoring_entity_id=1, event_id="100", chips=["ABCDEF012345"]),
        make_participant(102, scoring_entity_id=2, event_id="100", chips=[]),  # no chip assigned
    ])

    result = bib_chip(export)

    assert result["bib"].tolist() == [101]
    assert result.iloc[0]["tag_id"] == "abcdef012345"  # lowercased


def test_bib_chip_excludes_bibs_outside_scored_event():
    export = make_export(entity_map=[
        make_participant(101, scoring_entity_id=1, event_id="999", chips=["ABCDEF012345"]),
    ])

    assert bib_chip(export).empty


def test_bib_chip_excludes_no_bib():
    export = make_export(entity_map=[
        make_participant(None, scoring_entity_id=1, event_id="100", chips=["ABCDEF012345"]),
    ])

    assert bib_chip(export).empty


# ----------------------------------------------------------------------
# known_drops
# ----------------------------------------------------------------------

def test_known_drops_requires_started_and_dnf_or_drop():
    export = make_export(entity_map=[
        make_participant(101, scoring_entity_id=1, event_id="100", rdgo_dns=False, rdgo_dnf=True),
    ])

    assert known_drops(export) == [101]


def test_known_drops_excludes_no_shows():
    # rdgo_dnf is routinely set on every non-finisher including no-shows --
    # a no-show (rdgo_dns=True) is not a "drop" (started, didn't finish)
    export = make_export(entity_map=[
        make_participant(102, scoring_entity_id=1, event_id="100", rdgo_dns=True, rdgo_dnf=True),
    ])

    assert known_drops(export) == []


def test_known_drops_via_rdgo_drop_flag_alone():
    export = make_export(entity_map=[
        make_participant(103, scoring_entity_id=1, event_id="100", rdgo_dns=False, rdgo_drop=True),
    ])

    assert known_drops(export) == [103]


def test_known_drops_excludes_finishers():
    export = make_export(entity_map=[
        make_participant(104, scoring_entity_id=1, event_id="100", rdgo_dns=False, rdgo_dnf=False, rdgo_drop=False),
    ])

    assert known_drops(export) == []


# ----------------------------------------------------------------------
# classify_start_finish
# ----------------------------------------------------------------------

def test_classify_reads_occurrence_1_and_2_from_read_data():
    export = make_export(
        entity_map=[make_participant(101, scoring_entity_id=1, event_id="100")],
        read_data={"1": [
            make_read(1, device_id=2, timestamp=GUN + pd.Timedelta(seconds=5)),
            make_read(2, device_id=2, timestamp=GUN + pd.Timedelta(minutes=20)),
        ]},
    )

    result = classify_start_finish(export)

    row = result.iloc[0]
    assert row["start_time"] == GUN + pd.Timedelta(seconds=5)
    assert row["start_device_id"] == 2
    assert row["finish_time"] == GUN + pd.Timedelta(minutes=20)
    assert row["finish_device_id"] == 2


def test_classify_missing_occurrence_is_nat_with_no_device():
    export = make_export(
        entity_map=[make_participant(101, scoring_entity_id=1, event_id="100")],
        read_data={"1": [make_read(1, device_id=2, timestamp=GUN + pd.Timedelta(seconds=5))]},
    )

    result = classify_start_finish(export)

    row = result.iloc[0]
    assert pd.isna(row["finish_time"])
    assert row["finish_device_id"] is None
    assert row["finish_n_reads"] == 0


def test_classify_includes_bibs_with_no_reads_at_all():
    export = make_export(entity_map=[make_participant(101, scoring_entity_id=1, event_id="100")])

    result = classify_start_finish(export)

    assert result["bib"].tolist() == [101]
    assert pd.isna(result.iloc[0]["start_time"])


def test_classify_excludes_entities_with_no_bib():
    export = make_export(entity_map=[make_participant(None, scoring_entity_id=1, event_id="100")])

    result = classify_start_finish(export)

    assert result.empty


# ----------------------------------------------------------------------
# backup_time_selected
# ----------------------------------------------------------------------

def test_backup_time_selected_includes_finish_not_from_chip_device():
    export = make_export(entity_map=[
        make_participant(101, scoring_entity_id=1, event_id="100", first_name="Jane", last_name="Runner"),
    ])
    classified = pd.DataFrame([{
        "bib": 101, "start_time": GUN + pd.Timedelta(seconds=5), "start_device_id": 2,
        "finish_time": GUN + pd.Timedelta(minutes=20), "finish_device_id": 1,  # Time Machine, not chip
    }])

    result = backup_time_selected(export, classified)

    assert len(result) == 1
    assert result.iloc[0]["bib"] == 101
    assert result.iloc[0]["name"] == "Jane Runner"
    assert bool(result.iloc[0]["backup_time_selected"]) is True


def test_backup_time_selected_excludes_chip_sourced_finish():
    export = make_export(entity_map=[make_participant(101, scoring_entity_id=1, event_id="100")])
    classified = pd.DataFrame([{
        "bib": 101, "start_time": GUN + pd.Timedelta(seconds=5), "start_device_id": 2,
        "finish_time": GUN + pd.Timedelta(minutes=20), "finish_device_id": 2,  # Trident, chip-sourced
    }])

    result = backup_time_selected(export, classified)

    assert result.empty


def test_backup_time_selected_excludes_bibs_with_no_finish():
    export = make_export(entity_map=[make_participant(101, scoring_entity_id=1, event_id="100")])
    classified = pd.DataFrame([{
        "bib": 101, "start_time": pd.NaT, "start_device_id": None,
        "finish_time": pd.NaT, "finish_device_id": None,
    }])

    result = backup_time_selected(export, classified)

    assert result.empty
