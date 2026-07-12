"""Parser for RaceDay Scoring's full "database export" zip.

Lou can pull this per race going forward: a zip containing `<race name>.json`
(race/participant config -- scored events, timing locations, chip_cross_ref,
participants) and `filterer.data` (a second JSON file, easy to mistake for a
log given the `.data` extension and its neighbors like `main.log`/`api.log`),
plus ~40MB of unrelated app diagnostic logs that always come bundled and
can't be separated out at export time -- everything except those two JSON
members is ignored here.

`filterer.data`'s `read_data` is RDS's own already-computed per-read scoring
decision (which occurrence -- 1=start, 2=finish; whether it was the read
actually used; which device/stream it came from), not raw reads needing
reclassification against a gun-time/gap-factor heuristic. Verified against
the Parkway Panda 5K (2026-05-25): a genuine miss is simply the *absence* of
the other occurrence for that entity, cleanly, for every case checked
(finish misses 267/303/333, start misses 110/172/173/327/341, no-chip bib
381). See CLAUDE.md and the scoping plan (2026-07-10) for the full writeup.

`entity_map` (not `chip_cross_ref`) is the right bib/chip source: it reflects
actual participant reality including a no-chip-assigned bib (empty `chips`
list), whereas `chip_cross_ref` is the broader pre-printed assignment sheet
(includes unused spare bib/chip pairs never issued to anyone -- same role as
`bib-chip.csv`'s "print-run size, not registrants" caveat).

Wired into `build_race_report()` as the normal case (2026-07-10): when a zip
is found in the race dir, it supersedes bib-chip.csv/tm-data.csv/
backup-time-selected.csv/time-machine-used.csv entirely. It does NOT replace
r_*.log/f_*.log, though -- see build.py's `network_interruption_suspects`:
`read_data` only reflects what reached RDS, not what the local Trident
device actually recorded, so a live-network dropout (Indy's 576/591 case)
would look like a genuine miss here unless cross-checked against the local
log.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class RdgoExport:
    race: dict
    scored_events: list  # ALL scored events in the export, not just one -- a
    # combined multi-distance race (e.g. Wild Trail 5K & 10K, sharing one mass
    # start/timing setup but scored as two separate RDS "scored events" with
    # different Gap Factors) needs every participant's own event, not just
    # the first. See _event_for_participant()/bib_gap_factors() below.
    timing_location: dict
    integration_events: list  # RDS's own event/distance config, keyed by
    # event_id -- a scored_event's included_event_ids reference these. Each
    # has a `distance` field (e.g. "5K") set directly by the race director,
    # not derived -- see distance_label() below.
    entity_map: list
    read_data: dict  # keyed by str(scoring_entity_id)
    devices: dict  # device_id -> device dict, from <race name>.json's `devices` list


def parse_rdgo_export(zip_path: str | Path) -> RdgoExport:
    with zipfile.ZipFile(zip_path) as zf:
        race_json_name = next(
            name for name in zf.namelist()
            if name.endswith(".json") and Path(name).name != "filterer.data"
        )
        race_json = json.loads(zf.read(race_json_name))
        filterer = json.loads(zf.read("filterer.data"))

    return RdgoExport(
        race=race_json["race"],
        scored_events=race_json["scored_events"],
        timing_location=race_json["timing_locations"][0],
        integration_events=race_json.get("integration_events", []),
        entity_map=filterer["entity_map"],
        read_data=filterer["read_data"],
        devices={d["device_id"]: d for d in race_json["devices"]},
    )


def is_chip_device(export: RdgoExport, device_id: int | None) -> bool | None:
    """Whether a read_data record's device_id is a live antenna reader (the
    chip/Trident stream) rather than a file-fed backup stream (Time Machine
    by bib scan, or a Trident File re-import) -- resolved from this race's
    own `devices` list, not a hardcoded device_id (device_id assignment is
    per-installation, e.g. on Panda 5K device_id 2 was Trident and 1 was Time
    Machine, but nothing guarantees that numbering holds on another race).
    A live reader has a `hardware_name`; a file-fed device does not.
    Returns None if device_id is unknown/missing (e.g. no read at all).
    """
    if device_id is None or pd.isna(device_id):
        return None
    device = export.devices.get(int(device_id))
    if device is None:
        return None
    return device.get("hardware_name") is not None


def device_label(export: RdgoExport, device_id: int | None) -> str | None:
    """Human-readable device name for display (e.g. "Trident UHF8 A-DIRECT",
    "Time Machine-FILE") -- prefer this over showing a bare device_id."""
    if device_id is None or pd.isna(device_id):
        return None
    device = export.devices.get(int(device_id))
    return device.get("device_display_name") if device else None


def _to_local_ts(epoch_ms: int, tz: str) -> pd.Timestamp:
    return pd.Timestamp(epoch_ms, unit="ms", tz="UTC").tz_convert(tz).tz_localize(None)


def gun_time(export: RdgoExport) -> pd.Timestamp:
    """Assumes every scored_event in the export shares one gun time -- true
    for a combined multi-distance race with a single mass start (verified on
    Wild Trail 5K & 10K: both scored events' actual_start_ts matched exactly).
    Raises if that assumption doesn't hold, rather than silently picking one,
    since a staggered-start race would need real handling, not a guess."""
    tz = export.race["integration_data"]["timezone"]
    start_ts_values = {se["actual_start_ts"] for se in export.scored_events}
    if len(start_ts_values) > 1:
        raise ValueError(
            f"scored events have different actual_start_ts ({start_ts_values}) -- "
            "this looks like a staggered-start race, not yet supported"
        )
    return _to_local_ts(export.scored_events[0]["actual_start_ts"], tz)


def bib_gap_factors(export: RdgoExport) -> dict[int, pd.Timedelta]:
    """bib -> that bib's own scored_event's Gap Factor (min_finish_time), not
    a single race-wide value -- a combined multi-distance race (e.g. Wild
    Trail 5K & 10K) has a different Gap Factor per distance (14 min / 30 min)
    even though every bib shares one timing_location. min_finish_time on the
    scored_event is the right field for this, not timing_location's own
    `gap_factors` list, which is a single shared value (coincidentally equal
    to the 5K's min_finish_time on every single-distance race checked so far
    -- Indy 5000, Panda 5K -- which is why that distinction never mattered
    until a combined race exposed it)."""
    result = {}
    for e in export.entity_map:
        p = e["entity"]["Participant"]["fields"]
        bib = p.get("bib_num")
        se = _event_for_participant(export, p)
        if bib is not None and se is not None:
            result[bib] = pd.Timedelta(milliseconds=se["min_finish_time"])
    return result


def distance_label(export: RdgoExport) -> str | None:
    """Best-effort distance label (e.g. "5K", or "5K & 10K" for a combined
    multi-distance race), read directly from the export's own
    integration_events -- each scored_event's included_event_ids references
    one or more integration_events, and RDS's own `distance` field there is
    the race director's actual configured distance, not something derived.
    Preferred over reverse-mapping Gap Factor (build.py's
    _rdgo_distance_label_from_gap_factor(), kept as a fallback for an export
    missing this field): Gap Factor (min_finish_time) is itself a
    user-adjustable timing setting, not a fixed distance encoding -- nothing
    guarantees a race director left it at the value this codebase's
    GAP_FACTOR_BY_DISTANCE assumes.

    Verified on Panda 5K: the "Panda 5K" scored_event's included_event_ids
    lists TWO integration_events (separate age-based registration
    categories, '1006552'/'1006553'), both agreeing on distance "5K" --
    multiple included_event_ids don't necessarily mean multiple distances,
    so this checks for agreement rather than assuming one-to-one.

    Returns None (triggering the caller's fallback) if any scored_event's
    included_event_ids don't resolve to a single agreed-upon distance, e.g.
    a future export where this field is missing or a scored_event legitimately
    spans mixed distances.
    """
    events_by_id = {e["event_id"]: e for e in export.integration_events}
    labels = []
    seen = set()
    for se in export.scored_events:
        distances = {
            events_by_id[eid]["distance"]
            for eid in (se.get("included_event_ids") or [])
            if eid in events_by_id and events_by_id[eid].get("distance")
        }
        if len(distances) != 1:
            return None
        label = distances.pop()
        if label not in seen:
            seen.add(label)
            labels.append(label)
    if not labels:
        return None
    return " & ".join(labels)


def _event_for_participant(export: RdgoExport, participant_fields: dict) -> dict | None:
    """Which of this export's scored_events a participant belongs to (by
    event_id membership in included_event_ids), or None if they're in none of
    them -- entity_map covers every registrant under the race umbrella (e.g.
    a companion event/division sharing the same export), not just the
    scored_event(s) this parser targets (caught during Panda 5K validation:
    entity_map had 433 registrants total, only 300 were in the "Panda 5K"
    scored event)."""
    eid = str(participant_fields.get("event_id"))
    for se in export.scored_events:
        if eid in (se.get("included_event_ids") or []):
            return se
    return None


def _in_scored_event(export: RdgoExport, participant_fields: dict) -> bool:
    return _event_for_participant(export, participant_fields) is not None


def bib_chip(export: RdgoExport) -> pd.DataFrame:
    """bib/chip mapping (columns: bib, tag_id) for participants who actually
    have a chip -- entity_map's `chips` list is empty for a no-chip-assigned
    bib, so those are excluded here (same convention as parse_bib_chip())."""
    rows = []
    for e in export.entity_map:
        p = e["entity"]["Participant"]["fields"]
        bib = p.get("bib_num")
        chips = e.get("chips") or []
        if bib is None or not chips or not _in_scored_event(export, p):
            continue
        rows.append({"bib": bib, "tag_id": chips[0].lower()})
    return pd.DataFrame(rows, columns=["bib", "tag_id"])


def known_drops(export: RdgoExport) -> list[int]:
    """Bibs Lou marked DNF or dropped, restricted to participants who
    actually started (`rdgo_dns` False) -- "known drop" in this codebase
    specifically means "started, didn't finish" (see RaceReport.known_drops),
    not "RDS marked DNF" in general. RDS sets `rdgo_dnf` on every non-finisher
    as routine post-race bookkeeping, including no-shows who never started at
    all (`rdgo_dns` True) -- checked on Panda 5K: ~38 bibs had `rdgo_dnf=True`
    with `rdgo_dns=True` too (registered, never showed up), entirely separate
    from the 3 confirmed mid-race drops (267/303/333) and bib 375 (started,
    chip never worked -- see bib_chip()/build.py), all four of which have
    `rdgo_dns=False`. Per Lou: "drop" removes a participant from RDS's
    in-progress board, DNF doesn't, but which one she marks depends on
    workflow stage, not a consistent choice -- don't rely on `rdgo_drop`
    alone (it was False on all 4 of the real cases above, which were marked
    `rdgo_dnf` instead)."""
    bibs = []
    for e in export.entity_map:
        p = e["entity"]["Participant"]["fields"]
        bib = p.get("bib_num")
        if (
            bib is not None
            and _in_scored_event(export, p)
            and not p.get("rdgo_dns")
            and (p.get("rdgo_dnf") or p.get("rdgo_drop"))
        ):
            bibs.append(bib)
    return bibs


def classify_start_finish(export: RdgoExport) -> pd.DataFrame:
    """Bib-level start/finish classification read directly from RDS's own
    per-read scoring decision -- no gun-time/gap-factor computation needed,
    unlike analysis.start_finish.classify_start_finish()'s CSV-based
    equivalent. Same core columns (bib, start_time, start_n_reads,
    finish_time, finish_n_reads) so missed_start_reads()/missed_finish_reads()
    from analysis/start_finish.py work unchanged on this DataFrame, plus
    start_device_id/finish_device_id -- unlike the CSV path, a present
    finish_time doesn't by itself mean the chip was read at finish. Resolve
    the raw device_id via is_chip_device()/device_label() (do not assume a
    fixed device_id means "chip" or "backup" -- that assignment is
    per-installation). A finish present but not from a chip device is the
    "recovered via backup" case the CSV pipeline's backup_time_selected
    reconciliation currently has to get from a separate report.

    Includes every entity_map bib regardless of whether they have any read
    at all (e.g. a registered no-show) -- callers should apply the same
    participant-universe filter build_race_report() does (has_any_read)
    before treating a bib as a real "missed" case.
    """
    tz = export.race["integration_data"]["timezone"]
    rows = []
    for e in export.entity_map:
        p = e["entity"]["Participant"]["fields"]
        bib = p.get("bib_num")
        if bib is None:
            continue
        sid = e["entity"]["Participant"]["scoring_entity_id"]
        reads = export.read_data.get(str(sid), [])
        start = next((r for r in reads if r["occurrence"] == 1), None)
        finish = next((r for r in reads if r["occurrence"] == 2), None)
        rows.append({
            "bib": bib,
            "start_time": _to_local_ts(start["timeshift_timestamp"], tz) if start else pd.NaT,
            "start_n_reads": 1 if start else 0,
            "start_device_id": start["device_id"] if start else None,
            "finish_time": _to_local_ts(finish["timeshift_timestamp"], tz) if finish else pd.NaT,
            "finish_n_reads": 1 if finish else 0,
            "finish_device_id": finish["device_id"] if finish else None,
        })
    return pd.DataFrame(rows, columns=[
        "bib", "start_time", "start_n_reads", "start_device_id",
        "finish_time", "finish_n_reads", "finish_device_id",
    ])


def backup_time_selected(export: RdgoExport, classified: pd.DataFrame) -> pd.DataFrame:
    """Backup-timing-used table, same shape as
    parsers.backup_time_selected.parse_backup_time_selected()'s output (bib,
    name, gender, age, scored_event, clock_start_time, chip_start_time,
    finish_time, chip_time_elapsed, clock_time_elapsed, backup_time_selected)
    -- built directly from filterer.data instead of a separate hand-exported
    report. A finish present but not sourced from a chip device (see
    is_chip_device()) is the "backup timing used" case.
    """
    gun = gun_time(export)
    name_info = {}
    scored_event_name_by_bib = {}
    for e in export.entity_map:
        p = e["entity"]["Participant"]["fields"]
        bib = p.get("bib_num")
        if bib is not None:
            name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
            name_info[bib] = (name, p.get("gender"), p.get("age"))
            se = _event_for_participant(export, p)
            if se is not None:
                scored_event_name_by_bib[bib] = se.get("scored_event_name")

    rows = []
    for _, r in classified.iterrows():
        if pd.isna(r["finish_time"]) or is_chip_device(export, r.get("finish_device_id")):
            continue
        bib = r["bib"]
        name, gender, age = name_info.get(bib, (None, None, None))
        chip_start = r["start_time"] if pd.notna(r["start_time"]) else pd.NaT
        rows.append({
            "bib": bib,
            "name": name,
            "gender": gender,
            "age": age,
            "scored_event": scored_event_name_by_bib.get(bib),
            "clock_start_time": gun,
            "chip_start_time": chip_start,
            "finish_time": r["finish_time"],
            "chip_time_elapsed": (r["finish_time"] - chip_start) if pd.notna(chip_start) else pd.NaT,
            "clock_time_elapsed": r["finish_time"] - gun,
            "backup_time_selected": True,
        })
    return pd.DataFrame(rows, columns=[
        "bib", "name", "gender", "age", "scored_event", "clock_start_time",
        "chip_start_time", "finish_time", "chip_time_elapsed", "clock_time_elapsed",
        "backup_time_selected",
    ])


def sanity_check(export: RdgoExport) -> None:
    print(f"race: {export.race['name']}")
    print(f"entities: {len(export.entity_map)}")
    print(f"read_data entries: {len(export.read_data)}")
    print(f"gun_time: {gun_time(export)}")
    for se in export.scored_events:
        gap = pd.Timedelta(milliseconds=se["min_finish_time"])
        print(f"scored_event: {se.get('scored_event_name')} gap_factor={gap}")


if __name__ == "__main__":
    import sys

    export = parse_rdgo_export(sys.argv[1])
    sanity_check(export)
