"""test_trident_raw - test chip_timing_analysis.parsers.trident_raw"""

import pandas as pd

from chip_timing_analysis.parsers.trident_raw import parse_trident_raw, sanity_check

from factories import aa_line, ab_line


# ----------------------------------------------------------------------
# parse_trident_raw
# ----------------------------------------------------------------------

def test_parses_aa_record_fields(tmp_path):
    ts = pd.Timestamp("2026-07-04 08:30:02.34")
    line = aa_line("00000c08c1d5", ts, reader_id="3", mat_id="4", read_type="BS", read_count=7, rssi=0xA3)
    path = tmp_path / "f_260704.log"
    path.write_text(line + "\n", encoding="ascii")

    df = parse_trident_raw(path)

    assert len(df) == 1
    row = df.iloc[0]
    assert row["tag_id"] == "00000c08c1d5"
    assert row["reader_id"] == "3"
    assert row["mat_id"] == "4"
    assert row["timestamp"] == ts
    assert row["read_type"] == "BS"
    assert row["read_count"] == 7
    assert row["signal_strength"] == 0xA3


def test_rssi_absent_is_null(tmp_path):
    ts = pd.Timestamp("2026-07-04 08:30:02.00")
    line = aa_line("00000c08c1d5", ts, rssi=None)
    assert len(line) == 38  # MIN_LEN -- no rssi field present
    path = tmp_path / "f_260704.log"
    path.write_text(line + "\n", encoding="ascii")

    df = parse_trident_raw(path)

    assert pd.isna(df.iloc[0]["signal_strength"])


def test_skips_ab_marker_lines(tmp_path):
    ts = pd.Timestamp("2026-07-04 08:30:00.00")
    lines = [ab_line(ts), aa_line("00000c08c1d5", ts, read_type="RR")]
    path = tmp_path / "r_260704.log"
    path.write_text("\n".join(lines) + "\n", encoding="ascii")

    df = parse_trident_raw(path)

    assert len(df) == 1
    assert df.iloc[0]["read_type"] == "RR"


def test_skips_banner_and_telemetry_lines(tmp_path):
    ts = pd.Timestamp("2026-07-04 08:30:00.00")
    lines = [
        "System version 1.2.3",
        "Hardware version 4.5.6",
        "Hardware MAC address 00:11:22:33:44:55",
        '{"uptime": 123, "gps": true, "battery": 87}',
        aa_line("00000c08c1d5", ts, read_type="BS"),
    ]
    path = tmp_path / "f_260704.log"
    path.write_text("\n".join(lines) + "\n", encoding="ascii")

    df = parse_trident_raw(path)

    assert len(df) == 1
    assert df.iloc[0]["read_type"] == "BS"


def test_empty_file_returns_empty_dataframe_with_expected_columns(tmp_path):
    path = tmp_path / "empty.log"
    path.write_text("", encoding="ascii")

    df = parse_trident_raw(path)

    assert df.empty
    assert list(df.columns) == [
        "tag_id", "reader_id", "mat_id", "timestamp",
        "read_type", "signal_strength", "read_count",
    ]


def test_read_type_is_categorical_and_read_count_is_int64(tmp_path):
    ts = pd.Timestamp("2026-07-04 08:30:00.00")
    path = tmp_path / "f.log"
    path.write_text(aa_line("00000c08c1d5", ts) + "\n", encoding="ascii")

    df = parse_trident_raw(path)

    assert str(df["read_type"].dtype) == "category"
    assert str(df["read_count"].dtype) == "int64"
    assert str(df["signal_strength"].dtype) == "Int64"


def test_date_before_y2k_rollover_uses_2000s(tmp_path):
    # 260704 -> 2026-07-04, not 1926-07-04 (parser hardcodes 2000 + YY)
    ts = pd.Timestamp("2026-07-04 08:30:00.00")
    path = tmp_path / "f.log"
    path.write_text(aa_line("00000c08c1d5", ts) + "\n", encoding="ascii")

    df = parse_trident_raw(path)

    assert df.iloc[0]["timestamp"].year == 2026


# ----------------------------------------------------------------------
# sanity_check
# ----------------------------------------------------------------------

def test_sanity_check_handles_empty_dataframe_without_raising(capsys):
    empty = pd.DataFrame(columns=["tag_id", "reader_id", "mat_id", "timestamp", "read_type", "signal_strength", "read_count"])

    sanity_check(empty)

    out = capsys.readouterr().out
    assert "records: 0" in out


def test_sanity_check_prints_record_count(tmp_path, capsys):
    ts = pd.Timestamp("2026-07-04 08:30:00.00")
    path = tmp_path / "f.log"
    path.write_text(aa_line("00000c08c1d5", ts) + "\n", encoding="ascii")
    df = parse_trident_raw(path)

    sanity_check(df)

    out = capsys.readouterr().out
    assert "records: 1" in out
    assert "unique tags: 1" in out
