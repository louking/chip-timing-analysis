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
from chip_timing_analysis.analysis.start_finish import (
    classify_start_finish,
    missed_start_reads,
    missed_finish_reads,
    GAP_FACTOR_BY_DISTANCE,
)
from chip_timing_analysis.analysis.queue_lag import compute_lag, add_excess_lag, add_finish_rate
from chip_timing_analysis.analysis.finish_density import finish_density, rolling_finish_rate, finish_gaps, STANDARD_WINDOW, BURST_WINDOW


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

    def finish_miss_bibs(self) -> set:
        """All bibs with no finish read: zero_reads + missed_finish_only."""
        return set(self.zero_reads["bib"]) | set(self.missed_finish_only["bib"])

    def pct_read_opportunities_missed(self) -> float:
        """% of (participant x 2 opportunities: start + finish) that went unread.
        no_chip_assigned/zero_reads count as both opportunities missed."""
        total_opportunities = self.n_participants * 2
        if total_opportunities == 0:
            return 0.0
        total_missed = (
            2 * len(self.no_chip_assigned)
            + 2 * len(self.zero_reads)
            + len(self.missed_start_only)
            + len(self.missed_finish_only)
        )
        return total_missed / total_opportunities * 100


def _find_one(pattern: str) -> str | None:
    matches = glob.glob(pattern)
    return matches[0] if matches else None


def build_race_report(
    race_dir: str | Path,
    race_name: str,
    race_date: str,
    distance: str,
    gun_time: str | pd.Timestamp,
    notes: list[str] | None = None,
    detail_notes: list[str] | None = None,
    n_registered: int | None = None,
    n_starters: int | None = None,
    n_finishers: int | None = None,
    known_drops: list[int] | None = None,
) -> RaceReport:
    """Build a RaceReport for the race in `race_dir` (a data/<date>-<slug>/
    directory following this repo's layout -- see CLAUDE.md).

    distance must be a key of GAP_FACTOR_BY_DISTANCE (5K/10K/10M).
    n_registered/n_starters/n_finishers are optional authoritative overrides
    from RDS's own results -- see RaceReport docstring for why they're manual.
    notes must stay bib/name-free (shown everywhere); detail_notes can name
    bibs/individuals (shown only in the private detailed report). known_drops
    are bibs confirmed as a legitimate DNF, so the report doesn't flag them
    as needing review.
    """
    race_dir = Path(race_dir)
    gun_time = pd.Timestamp(gun_time)
    gap_factor = GAP_FACTOR_BY_DISTANCE[distance]

    filtered_log = _find_one(str(race_dir / "f_*.log"))
    reads = parse_trident_raw(filtered_log)
    bib_chip = parse_bib_chip(race_dir / "bib-chip.csv")
    tm_data = parse_tm_data(race_dir / "tm-data.csv", race_date=race_date)

    classified_all = classify_start_finish(reads, bib_chip, gun_time=gun_time, gap_factor=gap_factor)

    # Participants = anyone in tm-data.csv, UNION anyone with any chip read at
    # all. The union matters: a bib can have a clean start read yet never show
    # up in tm-data.csv (no finish, no backup entry either) -- e.g. Indy bib
    # 658. Filtering to tm-data.csv alone would silently drop that person from
    # every count instead of surfacing them as a finish miss.
    has_any_read = classified_all["start_time"].notna() | classified_all["finish_time"].notna()
    participant_bibs = set(tm_data["bib"]) | set(classified_all.loc[has_any_read, "bib"])
    classified = classified_all[classified_all["bib"].isin(participant_bibs)].reset_index(drop=True)

    no_chip_bibs = sorted(participant_bibs - set(bib_chip["bib"]))
    no_chip_assigned = tm_data[tm_data["bib"].isin(no_chip_bibs)][["bib", "finish_time"]]

    missed_start_bibs = set(missed_start_reads(classified)["bib"])
    missed_finish_bibs = set(missed_finish_reads(classified)["bib"])
    zero_read_bibs = missed_start_bibs & missed_finish_bibs

    zero_reads = classified[classified["bib"].isin(zero_read_bibs)]
    missed_start_only = classified[classified["bib"].isin(missed_start_bibs - zero_read_bibs)]
    missed_finish_only = classified[classified["bib"].isin(missed_finish_bibs - zero_read_bibs)]

    backup_path = _find_one(str(race_dir / "backup-time-selected.csv")) or _find_one(str(race_dir / "time-machine-used.csv"))
    backup = parse_backup_time_selected(backup_path, race_date=race_date) if backup_path else None

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
        n_bib_chip_entries=len(bib_chip),
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
        notes=notes or [],
        detail_notes=detail_notes or [],
        known_drops=known_drops or [],
    )
