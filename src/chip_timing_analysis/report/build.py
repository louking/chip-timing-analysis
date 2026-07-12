"""Gathers all per-race analysis into a single RaceReport, ready to render
(see render.py) as a detailed or sanitized markdown report.
"""

from __future__ import annotations

import glob
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from chip_timing_analysis.parsers.trident_raw import parse_trident_raw
from chip_timing_analysis.parsers.bib_chip import parse_bib_chip
from chip_timing_analysis.parsers.tm_data import parse_tm_data
from chip_timing_analysis.parsers.barcode_scanner import parse_barcode_scans
from chip_timing_analysis.parsers.backup_time_selected import parse_backup_time_selected
from chip_timing_analysis.parsers import rdgo_export
from chip_timing_analysis.analysis.start_finish import (
    classify_start_finish,
    missed_start_reads,
    missed_finish_reads,
    GAP_FACTOR_BY_DISTANCE,
)
from chip_timing_analysis.analysis.queue_lag import compute_lag, add_excess_lag, add_finish_rate
from chip_timing_analysis.analysis.finish_density import finish_density, rolling_finish_rate, finish_gaps, STANDARD_WINDOW, BURST_WINDOW
from chip_timing_analysis.analysis.mat_reliability import (
    mat_summary as compute_mat_summary,
    flag_weak_mats,
    mat_reliability_verdict,
)


@dataclass
class RaceReport:
    race_name: str
    race_date: str
    distance: str
    gun_time: pd.Timestamp

    n_bib_chip_entries: int  # bib-chip.csv row count -- the print-run/assignment sheet size, NOT registrants
    n_participants: int  # our own confirmed-participant count: union of tm-data.csv bibs and any bib with a chip read

    # Authoritative counts from RDS's own official results, if Lou supplies them --
    # we have no parser/data source for these (no registration-system export yet),
    # and they can differ from n_participants (e.g. Indy: n_participants=111 by our
    # data, but official was 110 starters/109 finishers -- reconciling the exact gap
    # requires RDS's own participant list, which we don't have).
    n_registered: int | None = None
    n_starters: int | None = None
    n_finishers: int | None = None

    classified: pd.DataFrame = None  # classify_start_finish output, restricted to participants
    tm_data: pd.DataFrame = None  # parse_tm_data() output -- the reliable, always-available finish_time source
    # (backup_time_selected.csv/time-machine-used.csv is optional and usually NOT supplied -- render.py
    # must not depend on it for anything beyond confirming which bibs used backup / the name lookup)

    # Missed reads, split by pattern -- distinguishes "chip never worked at all"
    # (zero_reads) from a one-off miss at a single location, and separately
    # flags participants who never had a chip assigned in the first place
    # (e.g. a bib handed out with no chip attached -- doesn't show up as a
    # "missed read" since there's no bib-chip.csv row to read against).
    no_chip_assigned: pd.DataFrame = None  # participant bibs with no bib-chip.csv entry at all
    zero_reads: pd.DataFrame = None  # chip assigned, but no start AND no finish read
    missed_start_only: pd.DataFrame = None  # has a finish read, but no start read
    missed_finish_only: pd.DataFrame = None  # has a start read, but no finish read

    backup: pd.DataFrame | None = None  # parse_backup_time_selected output, if available
    lag: pd.DataFrame | None = None  # compute_lag + add_excess_lag + add_finish_rate output
    density_bins: pd.DataFrame | None = None  # finish_density() output
    density_rolling: pd.DataFrame | None = None  # rolling_finish_rate(), STANDARD_WINDOW (60s) -- matches RRTC's rpm convention
    density_rolling_burst: pd.DataFrame | None = None  # rolling_finish_rate(), BURST_WINDOW (15s) -- catches short clusters a 60s window smooths over
    finish_gap_sec: pd.Series | None = None  # finish_gaps() output

    # Raw (r_*.log, RR-type) per-mat diagnostics: is any antenna reading
    # weakly (low signal strength) or being missed almost entirely, which
    # could point to a cabling/power problem. Detailed report only;
    # de-emphasized to a one-liner unless mat_reliability_verdict flags a
    # systemic_signal. mat_summary is None if no r_*.log was found.
    mat_summary: pd.DataFrame | None = None  # compute_mat_summary() output, one row per mat_id
    mat_reliability_verdict: dict | None = None  # mat_reliability_verdict() output

    # Free-text operational notes (e.g. "brief network outage, did not affect
    # results") -- known-good context a human supplies; not auto-detected.
    # `notes` must stay bib/name-free: it's shown verbatim in the detailed
    # report AND the sanitized report AND the running summary. `detail_notes`
    # can name specific bibs/individuals and is shown ONLY in the private
    # detailed report (e.g. "bib 641 missed its start read due to crowd
    # density at the start line").
    notes: list[str] = field(default_factory=list)
    detail_notes: list[str] = field(default_factory=list)

    # Bibs confirmed (by Lou, not detectable from data) as a legitimate drop --
    # started, didn't finish, no chip/backup data because there's genuinely
    # nothing to record. Lets the report reserve "needs review" language for
    # finish misses that are still actually unexplained.
    known_drops: list[int] = field(default_factory=list)

    # Bibs where the rdgo export path (see below) reports a missed start or
    # finish, but the local Trident device log (f_*.log) independently shows
    # a qualifying read anyway. The rdgo export only reflects what RDS's
    # `read_data` kept, not every read attempt, so this can mean either of
    # two different things and the export alone can't tell them apart:
    # (a) a genuine live-network dropout (the failure mode behind Indy's
    # 576/591 case, found before this repo had the rdgo export path at all),
    # or (b) the local log's read falls in the same "just before gun_time"
    # edge case analysis/start_finish.py's own pre_gun_grace was built to
    # handle (found on Panda 5K: 180/314/349 -- RDS's own scoring apparently
    # has no equivalent grace period, or at least none visible from this
    # export). Don't assume every entry here is a network issue -- check
    # each bib's actual read timing before treating it as one. Only computed
    # when both the rdgo export and f_*.log are present for the same race.
    network_interruption_suspects: list[int] = field(default_factory=list)

    def finish_miss_bibs(self) -> set:
        """All bibs with no finish read: zero_reads + missed_finish_only.
        Includes confirmed drops (see genuine_finish_miss_bibs() for the
        version that excludes them) -- this raw set is what the backup-
        report reconciliation needs to work from."""
        return set(self.zero_reads["bib"]) | set(self.missed_finish_only["bib"])

    def genuine_finish_miss_bibs(self) -> set:
        """finish_miss_bibs() minus confirmed drops (known_drops). A
        confirmed drop (started, did not finish) has no finish read by
        definition -- there was never a finish to read -- so it isn't a
        chip-reading failure and shouldn't count toward "chips not read at
        finish" or the missed-read percentage. Use this, not
        finish_miss_bibs(), for any headline miss count/percentage."""
        return self.finish_miss_bibs() - set(self.known_drops)

    def pct_read_opportunities_missed(self) -> float:
        """% of (participant x 2 opportunities: start + finish) that went
        unread. Denominator is every participant (no_chip_assigned bibs
        included -- they're still real participants), but the numerator only
        counts opportunities where a chip actually existed to be read:
        zero_reads counts as both opportunities missed (a chip was assigned
        and never worked), but no_chip_assigned does NOT (per Lou: there was
        no chip, so there was no chip-read opportunity to miss in the first
        place -- changed 2026-07-10, previously counted no_chip_assigned as 2
        missed each too). Confirmed drops' "missing" finish read is excluded
        -- see genuine_finish_miss_bibs()."""
        total_opportunities = self.n_participants * 2
        if total_opportunities == 0:
            return 0.0
        drop_bibs = set(self.known_drops)
        n_zero_read_drops = len(drop_bibs & set(self.zero_reads["bib"]))
        n_finish_only_drops = len(drop_bibs & set(self.missed_finish_only["bib"]))
        total_missed = (
            2 * len(self.zero_reads)
            + len(self.missed_start_only)
            + len(self.missed_finish_only)
            - 2 * n_zero_read_drops
            - n_finish_only_drops
        )
        return total_missed / total_opportunities * 100


def _find_one(pattern: str) -> str | None:
    matches = glob.glob(pattern)
    return matches[0] if matches else None


def _csv_classify_grouped(
    reads: pd.DataFrame,
    bib_chip: pd.DataFrame,
    gun_time: pd.Timestamp,
    bib_gap_factors: dict,
) -> pd.DataFrame:
    """Run analysis.start_finish.classify_start_finish() once per distinct
    gap factor present among bib_chip's bibs, rather than a single shared
    value -- a combined multi-distance race (e.g. Wild Trail 5K & 10K) has a
    different Gap Factor per distance (see rdgo_export.bib_gap_factors()),
    and applying one race-wide value would misclassify one distance's finish
    occurrences. Bibs missing from bib_gap_factors (not in any scored event)
    are dropped, same as classify_start_finish's own bib_chip join would do."""
    grouped = bib_chip.assign(_gap_factor=bib_chip["bib"].map(bib_gap_factors)).dropna(subset=["_gap_factor"])
    parts = [
        classify_start_finish(reads, group.drop(columns="_gap_factor"), gun_time=gun_time, gap_factor=gf)
        for gf, group in grouped.groupby("_gap_factor")
    ]
    return pd.concat(parts, ignore_index=True) if parts else classify_start_finish(reads, bib_chip.iloc[0:0], gun_time=gun_time, gap_factor=pd.Timedelta(0))


def _rdgo_distance_label(rdgo: rdgo_export.RdgoExport) -> str:
    """Best-effort distance label for the race, preferring
    rdgo_export.distance_label() (reads the race director's actual
    configured distance straight from the export's integration_events) and
    falling back to a Gap-Factor reverse-mapping only if that's unavailable
    (e.g. an export missing the field). Gap Factor (min_finish_time) is a
    user-adjustable timing setting, not a fixed distance encoding, so it's
    deliberately not the primary source -- see rdgo_export.distance_label()'s
    docstring for why, and the Panda 5K multi-included_event_ids case it
    already handles that this fallback does not."""
    label = rdgo_export.distance_label(rdgo)
    if label is not None:
        return label
    reverse = {v: k for k, v in GAP_FACTOR_BY_DISTANCE.items()}
    labels = {}
    for se in rdgo.scored_events:
        gap = pd.Timedelta(milliseconds=se["min_finish_time"])
        labels[gap] = reverse.get(gap, se.get("scored_event_name", "unknown"))
    return " & ".join(labels[gap] for gap in sorted(labels))


def _network_interruption_suspects(
    rdgo: rdgo_export.RdgoExport,
    classified_all: pd.DataFrame,
    reads: pd.DataFrame,
    bib_chip: pd.DataFrame,
    gun_time: pd.Timestamp,
    bib_gap_factors: dict,
) -> list[int]:
    """Cross-check every rdgo-reported miss against the local Trident log --
    see RaceReport.network_interruption_suspects. reads/bib_chip are the same
    f_*.log/rdgo-derived bib-chip mapping already loaded by the caller."""
    csv_classified = _csv_classify_grouped(reads, bib_chip, gun_time, bib_gap_factors)
    csv_by_bib = csv_classified.set_index("bib")
    rdgo_by_bib = classified_all.set_index("bib")
    miss_bibs = set(missed_start_reads(classified_all)["bib"]) | set(missed_finish_reads(classified_all)["bib"])

    suspects = []
    for bib in sorted(miss_bibs):
        if bib not in csv_by_bib.index:
            continue
        rdgo_row = rdgo_by_bib.loc[bib]
        csv_row = csv_by_bib.loc[bib]
        if pd.isna(rdgo_row["start_time"]) and pd.notna(csv_row["start_time"]):
            suspects.append(bib)
        elif pd.isna(rdgo_row["finish_time"]) and pd.notna(csv_row["finish_time"]):
            suspects.append(bib)
    return suspects


def build_race_report(
    race_dir: str | Path,
    race_name: str | None = None,
    race_date: str | None = None,
    distance: str | None = None,
    gun_time: str | pd.Timestamp | None = None,
    notes: list[str] | None = None,
    detail_notes: list[str] | None = None,
    n_registered: int | None = None,
    n_starters: int | None = None,
    n_finishers: int | None = None,
    known_drops: list[int] | None = None,
    exclude_bibs: list[int] | None = None,
) -> RaceReport:
    """Build a RaceReport for the race in `race_dir` (a data/<date>-<slug>/
    directory following this repo's layout -- see CLAUDE.md).

    If an RDS full-database-export zip is found in race_dir, it's the normal
    ingestion path (see CLAUDE.md / parsers/rdgo_export.py): bib-chip.csv,
    tm-data.csv, and backup-time-selected.csv/time-machine-used.csv are not
    read at all in that case, and gun_time/race_name/race_date/distance are
    all optional -- any left None are derived from the export (gun_time from
    its GUNTIME marker; race_name from `race["name"]`; race_date from
    `race["start_date"]`, RDS's own configured race date; distance from each
    scored_event's own integration_events, RDS's own configured distance --
    see rdgo_export.distance_label() -- falling back to a Gap-Factor reverse
    mapping only if that's unavailable, since Gap Factor is itself a
    user-adjustable timing setting, not a distance encoding). Pass any of
    them explicitly to override the derived value (e.g. a cleaner display
    name than RDS's own). Falls back to the original CSV-export-based
    ingestion (gun_time/race_name/race_date/distance all required, distance
    must be a key of GAP_FACTOR_BY_DISTANCE) when no zip is present -- e.g.
    Indy 5000, which predates this export existing.

    n_registered/n_starters/n_finishers are optional authoritative overrides
    from RDS's own results -- see RaceReport docstring for why they're manual.
    notes must stay bib/name-free (shown everywhere); detail_notes can name
    bibs/individuals (shown only in the private detailed report). known_drops
    are bibs confirmed as a legitimate DNF, so the report doesn't flag them
    as needing review -- when using the rdgo path, this is unioned with bibs
    RDS itself marked DNF/dropped (rdgo_export.known_drops()). exclude_bibs
    are bibs Lou confirms should not count as a participant at all -- not
    detectable from data, e.g. a registration whose chip cross-reference in
    RDS is a data-entry error (a test chip that was never actually issued to
    that participant, distinct from known_drops' "started, didn't finish";
    excluded from every count entirely, not just re-bucketed).
    """
    race_dir = Path(race_dir)
    known_drops = set(known_drops or [])
    exclude_bibs = set(exclude_bibs or [])

    rdgo_zip = _find_one(str(race_dir / "*.zip"))
    rdgo = rdgo_export.parse_rdgo_export(rdgo_zip) if rdgo_zip else None

    filtered_log = _find_one(str(race_dir / "f_*.log"))
    reads = parse_trident_raw(filtered_log) if filtered_log else None

    network_interruption_suspects: list[int] = []

    if rdgo is not None:
        gun_time = pd.Timestamp(gun_time) if gun_time is not None else rdgo_export.gun_time(rdgo)
        if race_name is None:
            race_name = rdgo.race["name"]
        if race_date is None:
            # race['start_date'] is RDS's own configured race date (already
            # "YYYY-MM-DD") -- preferred over deriving from gun_time's own
            # date, which requires a timezone conversion and could in
            # principle land on a different calendar date than the race is
            # actually configured for (e.g. a very late-night race).
            race_date = rdgo.race["start_date"]
        if distance is None:
            distance = _rdgo_distance_label(rdgo)
        bib_gap_factors = rdgo_export.bib_gap_factors(rdgo)
        bib_chip = rdgo_export.bib_chip(rdgo)
        classified_all_raw = rdgo_export.classify_start_finish(rdgo)
        known_drops |= set(rdgo_export.known_drops(rdgo))
        n_bib_chip_entries = len(bib_chip)

        # tm_data/backup are derived from the *unrestricted* classification --
        # a no-chip bib's backup-sourced finish still needs to show up here
        # (it feeds no_chip_assigned below).
        tm_data = classified_all_raw.loc[classified_all_raw["finish_time"].notna(), ["bib", "finish_time"]].reset_index(drop=True)
        tm_data.insert(0, "seq", range(1, len(tm_data) + 1))

        backup = rdgo_export.backup_time_selected(rdgo, classified_all_raw)
        if backup.empty:
            backup = None

        # analysis.start_finish.classify_start_finish() (the CSV path) only
        # ever produces rows for bib_chip's own bibs -- a no-chip bib never
        # appears in *its* classified_all at all, only via no_chip_assigned
        # (sourced from tm_data). rdgo_export.classify_start_finish() includes
        # every entity_map bib by design (see its docstring), so restrict to
        # the same has-chip population here for parity, or a no-chip bib's
        # backup-only finish would wrongly count as a "missed start".
        has_chip_bibs = set(bib_chip["bib"])
        classified_all = classified_all_raw[classified_all_raw["bib"].isin(has_chip_bibs)].reset_index(drop=True)

        # RDS's own occurrence data has no equivalent to pre_gun_grace: a few
        # front-of-field runners' chips cross a fraction of a second before
        # the automatic GUNTIME marker registers (analysis/start_finish.py's
        # own fix for this -- see CLAUDE.md), but read_data simply lacks
        # occurrence 1 for them, indistinguishable in shape from a genuine
        # missed start. Backfill specifically that case from the local
        # Trident log before treating a missing start as real, or this
        # ingestion path silently regresses a bug already fixed on the CSV
        # path (found on Panda 5K: bibs 180/314/349). Only the pre-gun-grace
        # case is backfilled here -- a local read at a normal post-gun time
        # that RDS's own record still lacks is a different, more concerning
        # question, left to network_interruption_suspects below rather than
        # silently patched.
        if reads is not None:
            csv_classified = _csv_classify_grouped(reads, bib_chip, gun_time, bib_gap_factors)
            csv_start_by_bib = csv_classified.set_index("bib")["start_time"]
            trident_device_id = next(
                (device_id for device_id, d in rdgo.devices.items() if d.get("hardware_name")), None
            )
            missing_start = classified_all["start_time"].isna()
            for idx in classified_all.index[missing_start]:
                bib = classified_all.at[idx, "bib"]
                csv_start = csv_start_by_bib.get(bib)
                if pd.notna(csv_start) and csv_start < gun_time:
                    classified_all.at[idx, "start_time"] = csv_start
                    classified_all.at[idx, "start_n_reads"] = 1
                    classified_all.at[idx, "start_device_id"] = trident_device_id

        # read_data only reflects what reached RDS live -- cross-check every
        # remaining rdgo-reported miss against the local Trident log
        # independently (see RaceReport.network_interruption_suspects), when
        # we have one.
        if reads is not None:
            network_interruption_suspects = _network_interruption_suspects(
                rdgo, classified_all, reads, bib_chip, gun_time, bib_gap_factors
            )

        # missed_start_only/missed_finish_only mean "the chip specifically
        # missed this crossing" (that's the CSV path's only possible meaning,
        # since it only ever sees chip data) -- but rdgo's classified_all
        # counts a backup-substituted finish as "present" too (RDS correctly
        # scored it, so it's not a miss from RDS's point of view). Null out a
        # non-chip-sourced start/finish here so miss-detection below sees the
        # same "did the CHIP read this" question the CSV path always asked;
        # `classified` (below) keeps the real, backup-inclusive times for
        # every other purpose (density, lag, the rendered per-bib tables).
        # Caught during Panda 5K validation: without this, bibs 148/277/331
        # (chip missed, backup correctly recovered) were misrendered as
        # "network interruption" instead of "recovered via backup".
        is_start_chip = classified_all["start_device_id"].map(lambda d: bool(rdgo_export.is_chip_device(rdgo, d)))
        is_finish_chip = classified_all["finish_device_id"].map(lambda d: bool(rdgo_export.is_chip_device(rdgo, d)))
        chip_only_classified = classified_all.assign(
            start_time=classified_all["start_time"].where(is_start_chip),
            finish_time=classified_all["finish_time"].where(is_finish_chip),
        )
    else:
        if gun_time is None:
            raise ValueError("gun_time is required when no RDS database export (zip) is present in race_dir")
        if race_name is None or race_date is None or distance is None:
            raise ValueError(
                "race_name/race_date/distance are required when no RDS database export "
                "(zip) is present in race_dir -- there's no export to derive them from"
            )
        if reads is None:
            raise FileNotFoundError(f"no f_*.log found in {race_dir}")
        gun_time = pd.Timestamp(gun_time)
        gap_factor = GAP_FACTOR_BY_DISTANCE[distance]
        bib_chip = parse_bib_chip(race_dir / "bib-chip.csv")
        tm_data = parse_tm_data(race_dir / "tm-data.csv", race_date=race_date)
        classified_all = classify_start_finish(reads, bib_chip, gun_time=gun_time, gap_factor=gap_factor)
        n_bib_chip_entries = len(bib_chip)
        chip_only_classified = classified_all  # already chip-only by construction

        backup_path = _find_one(str(race_dir / "backup-time-selected.csv")) or _find_one(str(race_dir / "time-machine-used.csv"))
        backup = parse_backup_time_selected(backup_path, race_date=race_date) if backup_path else None

    if exclude_bibs:
        bib_chip = bib_chip[~bib_chip["bib"].isin(exclude_bibs)].reset_index(drop=True)
        classified_all = classified_all[~classified_all["bib"].isin(exclude_bibs)].reset_index(drop=True)
        chip_only_classified = chip_only_classified[~chip_only_classified["bib"].isin(exclude_bibs)].reset_index(drop=True)
        tm_data = tm_data[~tm_data["bib"].isin(exclude_bibs)].reset_index(drop=True)
        known_drops -= exclude_bibs
        if backup is not None:
            backup = backup[~backup["bib"].isin(exclude_bibs)].reset_index(drop=True)

    # Participants = anyone in tm-data.csv (or its rdgo-derived equivalent),
    # UNION anyone with any chip read at all. The union matters: a bib can
    # have a clean start read yet never show up in tm-data.csv (no finish, no
    # backup entry either) -- e.g. Indy bib 658. Filtering to tm-data.csv
    # alone would silently drop that person from every count instead of
    # surfacing them as a finish miss.
    has_any_read = classified_all["start_time"].notna() | classified_all["finish_time"].notna()
    participant_bibs = set(tm_data["bib"]) | set(classified_all.loc[has_any_read, "bib"])
    classified = classified_all[classified_all["bib"].isin(participant_bibs)].reset_index(drop=True)

    no_chip_bibs = sorted(participant_bibs - set(bib_chip["bib"]))
    no_chip_assigned = tm_data[tm_data["bib"].isin(no_chip_bibs)][["bib", "finish_time"]]

    # "missed" = the chip didn't read it -- use chip_only_classified (for the
    # rdgo path, backup-substituted reads null'd out; for the CSV path, the
    # same object as classified_all, already chip-only) restricted to the
    # same participant population, but keep the real, backup-inclusive rows
    # from `classified` as the output (so e.g. missed_finish_only still shows
    # its actual recovered finish_time, not NaT).
    chip_only_participants = chip_only_classified[chip_only_classified["bib"].isin(participant_bibs)]
    missed_start_bibs = set(missed_start_reads(chip_only_participants)["bib"])
    missed_finish_bibs = set(missed_finish_reads(chip_only_participants)["bib"])
    zero_read_bibs = missed_start_bibs & missed_finish_bibs

    zero_reads = classified[classified["bib"].isin(zero_read_bibs)]
    missed_start_only = classified[classified["bib"].isin(missed_start_bibs - zero_read_bibs)]
    missed_finish_only = classified[classified["bib"].isin(missed_finish_bibs - zero_read_bibs)]

    # r_*.log (RR, every individual antenna ping) is separate from f_*.log
    # (used above for start/finish classification) -- filtering collapses
    # exactly the per-mat density/signal-strength signal this diagnostic
    # needs. Optional: older/incomplete race folders may not have it.
    raw_log = _find_one(str(race_dir / "r_*.log"))
    raw_reads = parse_trident_raw(raw_log) if raw_log else None
    mat_summ = compute_mat_summary(raw_reads) if raw_reads is not None else None
    mat_verdict = mat_reliability_verdict(mat_summ, flag_weak_mats(mat_summ)) if mat_summ is not None else None

    # barcode-scanner.log is shared/long-lived, lives one level up at data/logs/, not per-race
    scanner_log = _find_one(str(race_dir.parent / "logs" / "barcode-scanner.log"))
    lag = None
    if scanner_log:
        window_start = classified["finish_time"].min() - pd.Timedelta(minutes=5)
        window_end = classified["finish_time"].max() + pd.Timedelta(minutes=5)
        scans = parse_barcode_scans(scanner_log, start=window_start, end=window_end)
        lag = compute_lag(classified, scans)
        lag = add_excess_lag(lag)
        lag = add_finish_rate(lag)

    return RaceReport(
        race_name=race_name,
        race_date=race_date,
        distance=distance,
        gun_time=gun_time,
        n_bib_chip_entries=n_bib_chip_entries,
        n_participants=len(participant_bibs),
        n_registered=n_registered,
        n_starters=n_starters,
        n_finishers=n_finishers,
        classified=classified,
        tm_data=tm_data,
        no_chip_assigned=no_chip_assigned,
        zero_reads=zero_reads,
        missed_start_only=missed_start_only,
        missed_finish_only=missed_finish_only,
        backup=backup,
        lag=lag,
        density_bins=finish_density(classified),
        density_rolling=rolling_finish_rate(classified, window=STANDARD_WINDOW),
        density_rolling_burst=rolling_finish_rate(classified, window=BURST_WINDOW),
        finish_gap_sec=finish_gaps(classified),
        mat_summary=mat_summ,
        mat_reliability_verdict=mat_verdict,
        notes=notes or [],
        detail_notes=detail_notes or [],
        known_drops=sorted(known_drops),
        network_interruption_suspects=network_interruption_suspects,
    )
