"""test_tmtility_log - test chip_timing_analysis.parsers.tmtility_log"""

import pandas as pd

from chip_timing_analysis.parsers.tmtility_log import backend_messages


def _send(ts: str, msg: str, client: str = "tm-reader") -> str:
    return f"{ts} {client} DEBUG: sending to backend: {msg}"


def _write(tmp_path, lines, raw_prefix: bytes = b""):
    path = tmp_path / "client.log"
    path.write_bytes(raw_prefix + ("\n".join(lines) + "\n").encode("utf-8"))
    return path


def test_yields_time_and_message(tmp_path):
    path = _write(tmp_path, [_send("2026-10-25 09:17:40,359", "{'opcode': 'select', 'raceid': '6', 'pos': 1, 'bibno': 365}")])

    out = list(backend_messages(path))

    assert out == [(pd.Timestamp("2026-10-25 09:17:40.359"), {"opcode": "select", "raceid": "6", "pos": 1, "bibno": 365})]


def test_strips_nul_bytes_at_line_start(tmp_path):
    path = _write(tmp_path, [_send("2026-10-25 09:17:40,359", "{'opcode': 'primary', 'raceid': '6', 'pos': 1}")],
                  raw_prefix=b"\0" * 65)

    assert len(list(backend_messages(path))) == 1


def test_skips_error_and_unrelated_lines(tmp_path):
    lines = [
        "2026-10-25 09:17:40,000 tm-reader ERROR: error sending to backend: status = 500",
        "2026-10-25 09:17:40,001 websockets.server INFO: connection open",
        _send("2026-10-25 09:17:40,002", "{not a dict literal"),
    ]

    assert list(backend_messages(_write(tmp_path, lines))) == []


def test_filters_by_raceid_and_window(tmp_path):
    lines = [
        _send("2026-10-24 09:00:00,000", "{'opcode': 'primary', 'raceid': '6', 'pos': 1}"),
        _send("2026-10-25 09:00:00,000", "{'opcode': 'primary', 'raceid': '5', 'pos': 1}"),
        _send("2026-10-25 09:00:01,000", "{'opcode': 'primary', 'raceid': '6', 'pos': 2}"),
        _send("2026-10-26 00:00:00,000", "{'opcode': 'primary', 'raceid': '6', 'pos': 3}"),
    ]

    out = list(backend_messages(_write(tmp_path, lines), start="2026-10-25", end="2026-10-26", raceid=6))

    assert [msg["pos"] for _, msg in out] == [2]
