"""test_tm_reader - test chip_timing_analysis.parsers.tm_reader"""

import pandas as pd

from chip_timing_analysis.parsers.tm_reader import parse_tm_entries, parse_tm_resets, sanity_check


def _msg_line(ts: str, payload: str) -> str:
    return f"{ts} tm-reader DEBUG: time machine msg processed: b'{payload}'"


# ----------------------------------------------------------------------
# parse_tm_entries
# ----------------------------------------------------------------------

def test_parses_entry_with_bib(tmp_path):
    path = tmp_path / "tm-reader.log"
    path.write_text(_msg_line("2026-10-03 08:35:54,463", r"\x1411 003 0003 00:20:52.55   00462") + "\n", encoding="utf-8")

    df = parse_tm_entries(path)

    assert len(df) == 1
    row = df.iloc[0]
    assert row["recv_time"] == pd.Timestamp("2026-10-03 08:35:54.463")
    assert row["pos"] == 3
    assert row["elapsed"] == pd.Timedelta("00:20:52.55")


def test_parses_entry_without_bib(tmp_path):
    path = tmp_path / "tm-reader.log"
    path.write_text(_msg_line("2026-10-03 08:33:24,572", r"\x1711 001 0001 00:18:22.50 ") + "\n", encoding="utf-8")

    df = parse_tm_entries(path)

    assert df["pos"].tolist() == [1]
    assert df.iloc[0]["elapsed"] == pd.Timedelta("00:18:22.50")


def test_skips_clock_start_event_and_unrelated_lines(tmp_path):
    lines = [
        _msg_line("2026-10-03 08:15:01,898", r"\x19XC 00:00:00.00 "),
        _msg_line("2026-10-03 08:33:24,386", r"\x00EVENT 045"),
        "2026-10-03 08:33:24,866 tm-reader DEBUG: sending to backend: {'opcode': 'primary', 'raceid': '4', 'pos': 1, 'time': '00:18:22.50'}",
        "2026-10-03 07:00:54,683 websockets.server INFO: connection open",
    ]
    path = tmp_path / "tm-reader.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert parse_tm_entries(path).empty


def test_start_end_bound_recv_time(tmp_path):
    lines = [
        _msg_line("2026-10-02 08:00:00,000", r"\x1411 001 0001 00:20:00.00   00101"),
        _msg_line("2026-10-03 08:35:54,463", r"\x1411 001 0001 00:20:52.55   00462"),
    ]
    path = tmp_path / "tm-reader.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    df = parse_tm_entries(path, start="2026-10-03", end="2026-10-04")

    assert df["recv_time"].tolist() == [pd.Timestamp("2026-10-03 08:35:54.463")]


def test_empty_file_returns_empty_frame_with_columns(tmp_path):
    path = tmp_path / "tm-reader.log"
    path.write_text("", encoding="utf-8")

    df = parse_tm_entries(path)

    assert df.empty
    assert list(df.columns) == ["recv_time", "pos", "elapsed"]


# ----------------------------------------------------------------------
# parse_tm_resets
# ----------------------------------------------------------------------

def test_parses_zero_resets_only(tmp_path):
    lines = [
        _msg_line("2026-10-03 07:09:57,041", r"\x19XC 00:00:00.00 "),
        _msg_line("2026-10-03 07:10:02,289", r"\x1411 001 0001 00:00:05.13   00123"),
        _msg_line("2026-10-03 07:12:35,166", r"\x19XC 00:02:35.62 "),
        "2026-10-03 08:15:01,897 tm-reader DEBUG: time machine data received: b'\\x19XC 00:00:00.00 \\r\\n'",
        _msg_line("2026-10-03 08:15:01,898", r"\x19XC 00:00:00.00 "),
    ]
    path = tmp_path / "tm-reader.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert parse_tm_resets(path).tolist() == [
        pd.Timestamp("2026-10-03 07:09:57.041"),
        pd.Timestamp("2026-10-03 08:15:01.898"),
    ]


def test_resets_start_end_bound_recv_time(tmp_path):
    lines = [
        _msg_line("2026-10-02 08:00:00,000", r"\x19XC 00:00:00.00 "),
        _msg_line("2026-10-03 08:15:01,898", r"\x19XC 00:00:00.00 "),
    ]
    path = tmp_path / "tm-reader.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert parse_tm_resets(path, start="2026-10-03", end="2026-10-04").tolist() == [pd.Timestamp("2026-10-03 08:15:01.898")]


def test_resets_empty_file(tmp_path):
    path = tmp_path / "tm-reader.log"
    path.write_text("", encoding="utf-8")

    assert parse_tm_resets(path).empty


# ----------------------------------------------------------------------
# sanity_check
# ----------------------------------------------------------------------

def test_sanity_check_prints_entry_count(tmp_path, capsys):
    path = tmp_path / "tm-reader.log"
    path.write_text(_msg_line("2026-10-03 08:35:54,463", r"\x1411 003 0003 00:20:52.55   00462") + "\n", encoding="utf-8")

    sanity_check(parse_tm_entries(path))

    assert "entries: 1" in capsys.readouterr().out
