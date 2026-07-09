"""Start/finish crossing classification.

Follows RaceDay Scoring's documented theory of operation (fsrc-tech
race-services/timing.md, and Lou's RDS setup checklist): the same physical
mat set can serve both the start and finish line, so mat_id can't be used to
tell crossings apart. Instead, classify by time-of-day + Gap Factor:

  - start:  reads in [gun_time, gun_time + start_offset] -- use the LS read.
  - finish: reads at/after gun_time + gap_factor, split into occurrences
            wherever the gap since the tag's previous read >= gap_factor;
            take the BS read of the first such occurrence (RDS's
            "Default Finish Occurrence: 2", counting the start pass as
            occurrence 1).

Validated against the Indy 5000 (5K): 107/110 known bibs' computed finish
time matched tm-data.csv within -1.4s..+1.2s; the other 3 had zero finish-
window reads at all (genuine missed finish reads, where RDS falls back to
the backup stream). See CLAUDE.md for the full writeup.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

# RDS "Min Elapsed Finish Time Allowed" / Gap Factor (occurrence 1), by race distance.
GAP_FACTOR_BY_DISTANCE = {
    "5K": pd.Timedelta(minutes=14),
    "10K": pd.Timedelta(minutes=30),
    "10M": pd.Timedelta(minutes=50),
}

DEFAULT_START_OFFSET = pd.Timedelta(minutes=2)  # RDS "Max Chip Start Time Offset"


def _split_occurrences(reads: pd.DataFrame, gap_factor: pd.Timedelta) -> pd.DataFrame:
    """Assign an `occurrence` number to each tag's (already time-scoped) reads,
    incrementing whenever the gap since that tag's previous read >= gap_factor.
    """
    reads = reads.sort_values(["tag_id", "timestamp"]).copy()
    gaps = reads.groupby("tag_id")["timestamp"].diff()
    reads["occurrence"] = (gaps.isna() | (gaps >= gap_factor)).groupby(reads["tag_id"]).cumsum()
    return reads


def _first_occurrence_picks(reads: pd.DataFrame, read_type: str, time_col: str, count_col: str) -> pd.DataFrame:
    first_occ = reads[reads["occurrence"] == 1]
    rows = []
    for bib, g in first_occ.groupby("bib"):
        hits = g[g["read_type"] == read_type]
        rows.append({
            "bib": bib,
            time_col: hits["timestamp"].iloc[0] if not hits.empty else pd.NaT,
            count_col: len(g),
        })
    return pd.DataFrame(rows, columns=["bib", time_col, count_col])


def classify_start_finish(
    reads: pd.DataFrame,
    bib_chip: pd.DataFrame,
    gun_time: dt.datetime,
    gap_factor: pd.Timedelta,
    start_offset: pd.Timedelta = DEFAULT_START_OFFSET,
) -> pd.DataFrame:
    """Classify each bib's start and finish crossing from filtered (BS/LS) reads.

    reads: parse_trident_raw() output on a filtered (f_*.log) file.
    bib_chip: parse_bib_chip() output (bib, tag_id), used to attach bibs to reads.

    Returns one row per bib with columns: bib, start_time, start_n_reads,
    finish_time, finish_n_reads. start_time/finish_time are NaT when no
    qualifying read was found -- see missed_start_reads()/missed_finish_reads().
    """
    reads = reads.merge(bib_chip[["bib", "tag_id"]], on="tag_id", how="inner")

    start_window = reads[reads["timestamp"].between(gun_time, gun_time + start_offset)]
    finish_window = reads[reads["timestamp"] >= gun_time + gap_factor]

    starts = _first_occurrence_picks(_split_occurrences(start_window, gap_factor), "LS", "start_time", "start_n_reads")
    finishes = _first_occurrence_picks(_split_occurrences(finish_window, gap_factor), "BS", "finish_time", "finish_n_reads")

    result = (
        bib_chip[["bib"]].drop_duplicates()
        .merge(starts, on="bib", how="left")
        .merge(finishes, on="bib", how="left")
    )
    result["start_n_reads"] = result["start_n_reads"].fillna(0).astype("int64")
    result["finish_n_reads"] = result["finish_n_reads"].fillna(0).astype("int64")
    return result


def missed_start_reads(classified: pd.DataFrame) -> pd.DataFrame:
    """Bibs with no qualifying read in the start window."""
    return classified[classified["start_time"].isna()]


def missed_finish_reads(classified: pd.DataFrame) -> pd.DataFrame:
    """Bibs with no qualifying read in the finish window.

    RDS would fall back to the backup stream (e.g. tm-data.csv) for these.
    """
    return classified[classified["finish_time"].isna()]
