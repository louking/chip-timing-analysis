"""Shared reader for the "sending to backend" lines in tmtility's client logs.

tm-reader.log and barcode-scanner.log both log each message the client
sends to the tmtility backend, as a Python dict literal:

    2026-10-25 09:17:40,359 tm-reader DEBUG: sending to backend: {'opcode': 'select', 'raceid': '6', 'pos': 1, 'time': '00:17:39.01', 'bibno': 365}
    2026-10-25 09:19:32,992 barcode-scanner DEBUG: sending to backend: {'opcode': 'scannedbib', 'raceid': '6', 'bibno': '264'}

The line's timestamp is when the client sent the message, so it trails the
event itself (TM button press, scan) by the client's queueing delay, up to
~0.3s. Both logs are on the tmtility laptop's clock.

The logs contain runs of NUL bytes (seen at the start of a line after the
log was reopened), which are stripped before matching.
"""

from __future__ import annotations

import ast
import datetime as dt
import re
from pathlib import Path
from typing import Iterator

import pandas as pd

_SEND_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) \S+ DEBUG: sending to backend: (?P<msg>\{.*\})\s*$"
)


def backend_messages(
    file_path: str | Path,
    start: str | dt.datetime | None = None,
    end: str | dt.datetime | None = None,
    raceid: str | int | None = None,
) -> Iterator[tuple[pd.Timestamp, dict]]:
    """Yield (send_time, message dict) for each "sending to backend" line.
    start/end bound send_time (start inclusive, end exclusive); raceid keeps
    only messages for that tmtility race. Lines whose message doesn't parse
    are skipped."""
    start = pd.Timestamp(start) if start is not None else None
    end = pd.Timestamp(end) if end is not None else None
    raceid = str(raceid) if raceid is not None else None

    with open(file_path, "rb") as f:
        text = f.read().replace(b"\0", b"").decode("utf-8", "replace")

    for line in text.splitlines():
        m = _SEND_RE.match(line)
        if not m:
            continue
        t = pd.Timestamp(m.group("ts").replace(",", "."))
        if (start is not None and t < start) or (end is not None and t >= end):
            continue
        try:
            msg = ast.literal_eval(m.group("msg"))
        except (ValueError, SyntaxError):
            continue
        if not isinstance(msg, dict):
            continue
        if raceid is not None and str(msg.get("raceid")) != raceid:
            continue
        yield t, msg
