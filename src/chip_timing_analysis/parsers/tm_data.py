"""Parser for tmtility's tm-data.csv export (structured input to RaceDay Scoring)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd


def parse_tm_data(file_path: str | Path, race_date: str | dt.date | None = None) -> pd.DataFrame:
    """Parse a tm-data.csv (no header: seq,bib,time) into a DataFrame.

    time is HH:MM:SS.hh (hundredths). If race_date is given, finish_time is
    combined into a full timestamp; otherwise it's left as a time-of-day
    (pandas.Timedelta since midnight).
    """
    df = pd.read_csv(
        file_path,
        header=None,
        names=["seq", "bib", "time_of_day"],
        dtype={"seq": "int64", "bib": "int64"},
    )
    time_delta = pd.to_timedelta(df["time_of_day"])
    if race_date is not None:
        df["finish_time"] = pd.Timestamp(race_date) + time_delta
    else:
        df["finish_time"] = time_delta
    return df[["seq", "bib", "finish_time"]]


def sanity_check(df: pd.DataFrame) -> None:
    print(f"records: {len(df)}")
    if df.empty:
        return
    print(f"unique bibs: {df['bib'].nunique()}")
    print(f"finish_time range: {df['finish_time'].min()} to {df['finish_time'].max()}")
    dupes = df[df.duplicated("bib", keep=False)]
    if not dupes.empty:
        print(f"WARNING: {len(dupes)} rows share a bib with another row")


if __name__ == "__main__":
    import sys

    race_date = sys.argv[2] if len(sys.argv) > 2 else None
    df = parse_tm_data(sys.argv[1], race_date=race_date)
    sanity_check(df)
