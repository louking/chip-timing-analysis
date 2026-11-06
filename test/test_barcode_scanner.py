"""test_barcode_scanner - test chip_timing_analysis.parsers.barcode_scanner"""

import pandas as pd

from chip_timing_analysis.parsers.barcode_scanner import parse_barcode_scans, sanity_check


def _scan_line(ts: str, bib: int) -> str:
    return f"{ts} barcode-scanner DEBUG: barcode scanner data received: {bib}"


# ----------------------------------------------------------------------
# parse_barcode_scans
# ----------------------------------------------------------------------

def test_parses_bib_and_scan_time(tmp_path):
    path = tmp_path / "barcode-scanner.log"
    path.write_text(_scan_line("2026-07-04 08:49:25,123", 101) + "\n", encoding="utf-8")

    df = parse_barcode_scans(path)

    assert len(df) == 1
    assert df.iloc[0]["bib"] == 101
    assert df.iloc[0]["scan_time"] == pd.Timestamp("2026-07-04 08:49:25.123")


def test_ignores_unrelated_log_lines(tmp_path):
    lines = [
        "2026-07-04 08:49:00,000 barcode-scanner INFO: websocket connected",
        "2026-07-04 08:49:00,001 barcode-scanner DEBUG: sending to backend: {'opcode': 'scannedbib', 'bibno': 101}",
        _scan_line("2026-07-04 08:49:25,123", 101),
    ]
    path = tmp_path / "barcode-scanner.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    df = parse_barcode_scans(path)

    assert len(df) == 1
    assert df.iloc[0]["bib"] == 101


def test_start_bounds_to_race_window(tmp_path):
    lines = [
        _scan_line("2026-07-04 06:00:00,000", 1),  # months-old, before the race
        _scan_line("2026-07-04 08:49:25,123", 101),
    ]
    path = tmp_path / "barcode-scanner.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    df = parse_barcode_scans(path, start="2026-07-04 08:00:00")

    assert df["bib"].tolist() == [101]


def test_end_bounds_to_race_window(tmp_path):
    lines = [
        _scan_line("2026-07-04 08:49:25,123", 101),
        _scan_line("2026-11-01 06:00:00,000", 999),  # a much later race, same shared log
    ]
    path = tmp_path / "barcode-scanner.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    df = parse_barcode_scans(path, end="2026-07-04 12:00:00")

    assert df["bib"].tolist() == [101]


def test_no_bounds_returns_everything(tmp_path):
    lines = [_scan_line("2026-07-04 06:00:00,000", 1), _scan_line("2026-11-01 06:00:00,000", 999)]
    path = tmp_path / "barcode-scanner.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    df = parse_barcode_scans(path)

    assert len(df) == 2


def test_empty_file_returns_empty_dataframe(tmp_path):
    path = tmp_path / "barcode-scanner.log"
    path.write_text("", encoding="utf-8")

    df = parse_barcode_scans(path)

    assert df.empty
    assert list(df.columns) == ["bib", "scan_time"]


# ----------------------------------------------------------------------
# sanity_check
# ----------------------------------------------------------------------

def test_sanity_check_notes_rescans(tmp_path, capsys):
    lines = [_scan_line("2026-07-04 08:49:25,123", 101), _scan_line("2026-07-04 08:50:00,000", 101)]
    path = tmp_path / "barcode-scanner.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    df = parse_barcode_scans(path)

    sanity_check(df)

    out = capsys.readouterr().out
    assert "rescans" in out


def test_sanity_check_handles_empty_dataframe(capsys):
    empty = pd.DataFrame(columns=["bib", "scan_time"])

    sanity_check(empty)

    out = capsys.readouterr().out
    assert "records: 0" in out


# ----------------------------------------------------------------------
# parse_scanner_sends
# ----------------------------------------------------------------------

def _send_line(ts: str, raceid: str, bibno: str) -> str:
    return (f"{ts} barcode-scanner DEBUG: sending to backend: "
            f"{{'opcode': 'scannedbib', 'raceid': '{raceid}', 'bibno': '{bibno}'}}")


def test_parse_scanner_sends_drops_leading_zeros_and_blank_scans(tmp_path):
    from chip_timing_analysis.parsers.barcode_scanner import parse_scanner_sends

    lines = [
        _send_line("2026-10-25 09:19:32,992", "6", "0264"),
        _send_line("2026-10-25 09:19:40,000", "6", "0000"),
        _send_line("2026-10-25 09:19:42,082", "5", "236"),
    ]
    path = tmp_path / "barcode-scanner.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    df = parse_scanner_sends(path, raceid="6")

    assert df["bib"].tolist() == [264]
    assert df.iloc[0]["send_time"] == pd.Timestamp("2026-10-25 09:19:32.992")
