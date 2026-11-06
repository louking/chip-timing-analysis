"""Parser for the tm-csv-connector barcode-scanner service log.

This is the connector's own long-running operational log (standard Python
`logging` format), not race-scoped — it can span months. Callers should
always pass start/end to narrow to the race's actual window.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pandas as pd

from chip_timing_analysis.parsers.tmtility_log import backend_messages

_SCAN_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
    r"barcode-scanner DEBUG: barcode scanner data received: (?P<bib>\d+)$"
)


def parse_barcode_scans(
    file_path: str | Path,
    start: str | dt.datetime | None = None,
    end: str | dt.datetime | None = None,
) -> pd.DataFrame:
    """Extract (bib, scan_time) events from a barcode-scanner.log.

    Uses the "data received" line's timestamp, since that's the earliest
    record of the physical scan (before it's processed / posted to the
    backend). start/end optionally bound the race's time window.
    """
    rows = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = _SCAN_RE.match(line.rstrip("\n"))
            if not m:
                continue
            rows.append({
                "bib": int(m.group("bib")),
                "scan_time": pd.Timestamp(m.group("ts").replace(",", ".")),
            })

    df = pd.DataFrame(rows, columns=["bib", "scan_time"])
    if df.empty:
        return df

    df["bib"] = df["bib"].astype("int64")
    if start is not None:
        df = df[df["scan_time"] >= pd.Timestamp(start)]
    if end is not None:
        df = df[df["scan_time"] <= pd.Timestamp(end)]
    return df.reset_index(drop=True)


def parse_scanner_sends(
    file_path: str | Path,
    start: str | dt.datetime | None = None,
    end: str | dt.datetime | None = None,
    raceid: str | int | None = None,
) -> pd.DataFrame:
    """Scans as the barcode-scanner client sent them to the backend (columns:
    bib, send_time). Leading zeros are dropped as tmtility does, and a blank
    `0000` scan is skipped. Unlike parse_barcode_scans() this carries the
    tmtility race id, so raceid can keep only that race's scans; send_time
    trails the scan by the client's queueing delay. start/end bound
    send_time."""
    rows = []
    for t, msg in backend_messages(file_path, start=start, end=end, raceid=raceid):
        bibno = str(msg.get("bibno", ""))
        if msg.get("opcode") != "scannedbib" or not bibno.isdigit() or int(bibno) == 0:
            continue
        rows.append({"bib": int(bibno), "send_time": t})
    df = pd.DataFrame(rows, columns=["bib", "send_time"])
    return df.astype({"bib": "int64"})


def sanity_check(df: pd.DataFrame) -> None:
    print(f"records: {len(df)}")
    if df.empty:
        return
    print(f"unique bibs: {df['bib'].nunique()}")
    print(f"scan_time range: {df['scan_time'].min()} to {df['scan_time'].max()}")
    dupes = df[df.duplicated("bib", keep=False)]
    if not dupes.empty:
        print(f"note: {len(dupes)} rows share a bib with another scan (rescans?)")


if __name__ == "__main__":
    import sys

    start = sys.argv[2] if len(sys.argv) > 2 else None
    end = sys.argv[3] if len(sys.argv) > 3 else None
    df = parse_barcode_scans(sys.argv[1], start=start, end=end)
    sanity_check(df)
