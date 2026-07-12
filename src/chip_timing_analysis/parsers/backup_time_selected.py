"""Parser for RDS's "Backup Time Selected" / "Time Machine - Used" Data Check
report exports.

Ground truth for which bibs needed a backup stream on race day. RDS supports
two backup streams for chip races: Time Machine (TM) and a "Trident File"
backup (the uploaded Trident log files themselves, re-imported after the
fact). "Backup Time Selected" covers *either* source and doesn't distinguish
which; "Time Machine - Used" is TM specifically (same row layout, minus the
Backup Time Selected column -- every row implicitly used TM). For Indy the
two reports are identical (Trident File backup was never uploaded, so every
backup case was TM), but don't assume that holds for other races -- if
Trident File backup had been uploaded, "Backup Time Selected" could show
more bibs than "Time Machine - Used" alone.

Local Trident log files can't distinguish a genuine missed read from a
live-network dropout that never reached RDS (see CLAUDE.md) -- these reports
are the only way to know for sure. Cross-reference their bibs against
missed_finish_reads() / classify_start_finish() output.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd


def _parse_elapsed(value: str) -> pd.Timedelta:
    if pd.isna(value) or not str(value).strip():
        return pd.NaT
    return pd.to_timedelta("0:" + str(value).strip())


def parse_backup_time_selected(file_path: str | Path, race_date: str | dt.date | None = None) -> pd.DataFrame:
    """Parse an RDS "Backup Time Selected" or "Time Machine - Used" Data Check
    report CSV (same layout; the latter omits the Backup Time Selected column
    since it's implicitly True for every row -- see module docstring).

    Row 1 of the file is a title row; row 2 is the real header. Returns
    columns: bib, name, gender, age, scored_event, clock_start_time,
    chip_start_time, finish_time (the scored time RDS used), chip_time_elapsed,
    clock_time_elapsed, backup_time_selected (bool). *_time columns are full
    timestamps if race_date is given, else bare time-of-day.
    """
    df = pd.read_csv(file_path, skiprows=1)
    df.columns = [c.strip() for c in df.columns]

    def to_ts(col: str) -> pd.Series:
        # Chip Start Time of Day is blank for a bib with no chip assigned at
        # all (backup was its only possible source, so there's no chip start
        # to report) -- leave those as NaT rather than failing the parse.
        blank = df[col].isna() | (df[col].astype(str).str.strip() == "")
        if race_date is None:
            parsed = pd.to_datetime(df[col].mask(blank), errors="coerce")
            return parsed.dt.time
        return pd.to_datetime(str(race_date) + " " + df[col].mask(blank, "").astype(str), errors="coerce")

    if "Backup Time Selected" in df.columns:
        backup_time_selected = df["Backup Time Selected"].astype(str).str.strip().str.lower().eq("yes")
    else:
        backup_time_selected = pd.Series(True, index=df.index)

    return pd.DataFrame({
        "bib": df["Bib"].astype("int64"),
        "name": df["Name"],
        "gender": df["Gender"],
        "age": df["Age"].astype("int64"),
        "scored_event": df["Scored Event"],
        "clock_start_time": to_ts("Clock Start Time of Day"),
        "chip_start_time": to_ts("Chip Start Time of Day"),
        "finish_time": to_ts("Finish Time of Day"),
        "chip_time_elapsed": df["Chip Time"].apply(_parse_elapsed),
        "clock_time_elapsed": df["Clock Time"].apply(_parse_elapsed),
        "backup_time_selected": backup_time_selected,
    })


def sanity_check(df: pd.DataFrame) -> None:
    print(f"records: {len(df)}")
    if df.empty:
        return
    print(f"bibs: {sorted(df['bib'])}")
    print(f"all backup_time_selected=True: {bool(df['backup_time_selected'].all())}")


if __name__ == "__main__":
    import sys

    race_date = sys.argv[2] if len(sys.argv) > 2 else None
    result = parse_backup_time_selected(sys.argv[1], race_date=race_date)
    sanity_check(result)
