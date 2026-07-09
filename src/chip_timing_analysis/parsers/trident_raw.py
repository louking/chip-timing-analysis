"""Parser for raw Trident Time Machine chip-read files.

Byte offsets verified against tm-csv-connector's tridentread2obj
(tm_csv_connector/trident.py) and a real Time Machine export
(r_260704.log / f_260704.log, Indy 5000 2026-07-04).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

READ_TYPES = ("FS", "LS", "BS", "RR")

_CHIP_READ_PREFIX = "aa"
_MIN_LEN = 38  # rssi (chars 38:40) is sometimes absent


def parse_trident_raw(file_path: str | Path) -> pd.DataFrame:
    """Parse a raw Trident read file (r_*.log / f_*.log) into a DataFrame.

    Only aa-prefixed chip-read records are returned. Marker/gun-time (ab)
    records, device banner lines, and (in filtered files) interleaved JSON
    telemetry lines are all skipped.
    """
    rows = []
    with open(file_path, "r", encoding="ascii", errors="replace") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if len(line) < _MIN_LEN or line[0:2] != _CHIP_READ_PREFIX:
                continue

            date_str = line[20:26]
            hour, minute, second = line[26:28], line[28:30], line[30:32]
            hundredths = int(line[32:34], 16)
            timestamp = pd.Timestamp(
                year=2000 + int(date_str[0:2]),
                month=int(date_str[2:4]),
                day=int(date_str[4:6]),
                hour=int(hour),
                minute=int(minute),
                second=int(second),
            ) + pd.Timedelta(milliseconds=hundredths * 10)

            signal_strength = int(line[38:40], 16) if len(line) >= 40 else None

            rows.append({
                "tag_id": line[4:16],
                "reader_id": line[2],
                "mat_id": line[3],
                "timestamp": timestamp,
                "read_type": line[36:38],
                "signal_strength": signal_strength,
                "read_count": int(line[16:20]),
            })

    df = pd.DataFrame(rows, columns=[
        "tag_id", "reader_id", "mat_id", "timestamp",
        "read_type", "signal_strength", "read_count",
    ])
    if not df.empty:
        df["read_type"] = df["read_type"].astype("category")
        df["signal_strength"] = df["signal_strength"].astype("Int64")
        df["read_count"] = df["read_count"].astype("int64")
    return df


def sanity_check(df: pd.DataFrame) -> None:
    """Print quick diagnostics for a parsed raw-read DataFrame."""
    print(f"records: {len(df)}")
    if df.empty:
        return
    print(f"date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"unique tags: {df['tag_id'].nunique()}")
    print("read type distribution:")
    print(df["read_type"].value_counts().to_string())


if __name__ == "__main__":
    import sys

    df = parse_trident_raw(sys.argv[1])
    sanity_check(df)
