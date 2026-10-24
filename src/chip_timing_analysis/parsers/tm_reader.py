"""Parser for the tm-csv-connector tm-reader service log.

Like barcode-scanner.log, this is the connector's own long-running
operational log (standard Python `logging` format), not race-scoped. The
useful lines are the Time Machine's own finish entries as they arrive over
its serial link:

    2026-10-03 08:35:54,463 tm-reader DEBUG: time machine msg processed: b'\\x1411 003 0003 00:20:52.55   00462'

The Time Machine sends *elapsed* time since its own clock start, not time of
day. tmtility turns that into the time of day written to tm-data.csv (and
sent to RDS) by adding a start time copied from RDS's display, which drops
the fractional seconds -- so tm-data.csv's clock is RDS's gun time floored to
the second, plus elapsed. The log line's own timestamp is the tmtility
laptop's clock, the same clock barcode-scanner.log uses. Comparing the two
gives the offset between the scanner log and the finish times (see
analysis.queue_lag.scanner_clock_offset()).

The TM's clock start/reset (`XC 00:00:00.00`, pressed by hand) is read
separately by parse_tm_resets(): each entry's elapsed time counts from the
most recent one, so it tells a pre-race test entry apart from a race entry.
Other message shapes (`XC` with a nonzero time, `EVENT 045`) are skipped.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pandas as pd

_ENTRY_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
    r"tm-reader DEBUG: time machine msg processed: b'.*?"
    r"(?P<pos>\d{3}) \d{4} (?P<elapsed>\d{2}:\d{2}:\d{2}\.\d{2})"
)


def parse_tm_entries(
    file_path: str | Path,
    start: str | dt.datetime | None = None,
    end: str | dt.datetime | None = None,
) -> pd.DataFrame:
    """Extract Time Machine finish entries (columns: recv_time, pos, elapsed)
    from a tm-reader.log. recv_time is on the tmtility laptop's clock; pos is
    the TM's own sequence number (tm-data.csv's seq, before any edits);
    elapsed is time since the TM's clock start. start/end optionally bound
    recv_time to the race's window."""
    rows = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = _ENTRY_RE.match(line)
            if not m:
                continue
            rows.append({
                "recv_time": pd.Timestamp(m.group("ts").replace(",", ".")),
                "pos": int(m.group("pos")),
                "elapsed": pd.Timedelta(m.group("elapsed")),
            })

    df = pd.DataFrame(rows, columns=["recv_time", "pos", "elapsed"])
    if df.empty:
        return df

    df["pos"] = df["pos"].astype("int64")
    if start is not None:
        df = df[df["recv_time"] >= pd.Timestamp(start)]
    if end is not None:
        df = df[df["recv_time"] <= pd.Timestamp(end)]
    return df.reset_index(drop=True)


_RESET_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
    r"tm-reader DEBUG: time machine msg processed: b'.*?XC 00:00:00\.00 "
)


def parse_tm_resets(
    file_path: str | Path,
    start: str | dt.datetime | None = None,
    end: str | dt.datetime | None = None,
) -> pd.Series:
    """recv_time of each Time Machine clock reset (`XC 00:00:00.00`) in a
    tm-reader.log, on the tmtility laptop's clock, in log order. start/end
    optionally bound it to the race's window."""
    times = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = _RESET_RE.match(line)
            if m:
                times.append(pd.Timestamp(m.group("ts").replace(",", ".")))

    resets = pd.Series(times, dtype="datetime64[ns]", name="recv_time")
    if start is not None:
        resets = resets[resets >= pd.Timestamp(start)]
    if end is not None:
        resets = resets[resets <= pd.Timestamp(end)]
    return resets.reset_index(drop=True)


def sanity_check(df: pd.DataFrame) -> None:
    print(f"entries: {len(df)}")
    if df.empty:
        return
    print(f"recv_time range: {df['recv_time'].min()} to {df['recv_time'].max()}")
    print(f"pos range: {df['pos'].min()} to {df['pos'].max()}")
    print(f"elapsed range: {df['elapsed'].min()} to {df['elapsed'].max()}")


if __name__ == "__main__":
    import sys

    start = sys.argv[2] if len(sys.argv) > 2 else None
    end = sys.argv[3] if len(sys.argv) > 3 else None
    df = parse_tm_entries(sys.argv[1], start=start, end=end)
    sanity_check(df)
