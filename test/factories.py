"""Shared test-data builders.

Not a conftest.py: these take enough parameters that fixture injection
doesn't fit well, so tests import and call them directly (same pattern as
members' fakecurrentuser.py/fakediscourse.py helper modules).
"""

from __future__ import annotations

import pandas as pd


def aa_line(
    tag_id: str,
    timestamp: pd.Timestamp,
    reader_id: str = "1",
    mat_id: str = "1",
    read_type: str = "LS",
    read_count: int = 1,
    rssi: int | None = None,
) -> str:
    """Build a raw Trident 'aa' chip-read record line (see
    parsers/trident_raw.py for the byte-offset layout)."""
    date_str = timestamp.strftime("%y%m%d")
    time_str = timestamp.strftime("%H%M%S")
    hex_hundredths = format(timestamp.microsecond // 10000, "02x")
    line = (
        "aa" + reader_id + mat_id + tag_id.ljust(12)[:12]
        + f"{read_count:04d}" + date_str + time_str + hex_hundredths
        + "00" + read_type
    )
    if rssi is not None:
        line += format(rssi, "02x")
    return line


def ab_line(timestamp: pd.Timestamp, reader_id: str = "1") -> str:
    """Build a raw Trident 'ab' GUNTIME marker line (30 chars, see
    parsers/trident_raw.py's module docstring / CLAUDE.md)."""
    date_str = timestamp.strftime("%y%m%d")
    time_str = timestamp.strftime("%H%M%S")
    hex_hundredths = format(timestamp.microsecond // 10000, "02x")
    return "ab" + reader_id + ("0" * 5) + date_str + ("0" * 2) + time_str + hex_hundredths + ("0" * 6)


def make_participant(
    bib: int | None,
    scoring_entity_id: int,
    event_id: str = "100",
    chips: list[str] | None = None,
    rdgo_dns: bool = False,
    rdgo_dnf: bool = False,
    rdgo_drop: bool = False,
    first_name: str = "Test",
    last_name: str = "Runner",
    gender: str = "M",
    age: int = 30,
) -> dict:
    """An entity_map entry (see parsers/rdgo_export.py)."""
    return {
        "entity": {
            "Participant": {
                "scoring_entity_id": scoring_entity_id,
                "fields": {
                    "bib_num": bib,
                    "event_id": event_id,
                    "first_name": first_name,
                    "last_name": last_name,
                    "gender": gender,
                    "age": age,
                    "rdgo_dns": rdgo_dns,
                    "rdgo_dnf": rdgo_dnf,
                    "rdgo_drop": rdgo_drop,
                },
            }
        },
        "chips": chips or [],
    }


def make_read(occurrence: int, device_id: int, timestamp: pd.Timestamp) -> dict:
    return {
        "occurrence": occurrence,
        "device_id": device_id,
        "timeshift_timestamp": int(timestamp.value // 1_000_000),
    }


def make_export(
    *,
    race: dict | None = None,
    scored_events: list | None = None,
    timing_location: dict | None = None,
    integration_events: list | None = None,
    entity_map: list | None = None,
    read_data: dict | None = None,
    devices: dict | None = None,
    timezone: str = "UTC",
    gun_time: pd.Timestamp = pd.Timestamp("2026-05-25 09:00:00"),
):
    """A minimal RdgoExport, defaulting to a single 5K scored event with no
    participants -- override individual pieces per test. timezone defaults
    to UTC so gun_time epoch<->wall-clock arithmetic in tests is trivial;
    pass a real tz to specifically exercise the tz-conversion path.
    """
    from chip_timing_analysis.parsers.rdgo_export import RdgoExport

    race = race or {
        "name": "Test Race",
        "start_date": gun_time.strftime("%Y-%m-%d"),
        "integration_data": {"timezone": timezone},
    }
    scored_events = scored_events if scored_events is not None else [{
        "scored_event_name": "Test 5K",
        "min_finish_time": 14 * 60 * 1000,
        "actual_start_ts": int(gun_time.value // 1_000_000),
        "included_event_ids": ["100"],
    }]
    integration_events = integration_events if integration_events is not None else [
        {"event_id": "100", "distance": "5K"},
    ]
    devices = devices if devices is not None else {
        1: {"device_id": 1, "device_display_name": "Time Machine-FILE"},
        2: {"device_id": 2, "hardware_name": "Trident UHF8", "device_display_name": "Trident UHF8 A-DIRECT"},
    }
    return RdgoExport(
        race=race,
        scored_events=scored_events,
        timing_location=timing_location or {},
        integration_events=integration_events,
        entity_map=entity_map or [],
        read_data=read_data or {},
        devices=devices,
    )
