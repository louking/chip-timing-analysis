"""test_backup_time_selected - test chip_timing_analysis.parsers.backup_time_selected"""

import pandas as pd

from chip_timing_analysis.parsers.backup_time_selected import parse_backup_time_selected, sanity_check

_HEADER = "Bib,Name,Gender,Age,Scored Event,Clock Start Time of Day,Chip Start Time of Day,Finish Time of Day,Chip Time,Clock Time,Backup Time Selected\n"


def _write(tmp_path, rows: list[str], title: str = "Backup Time Selected Report\n") -> "Path":
    path = tmp_path / "backup-time-selected.csv"
    path.write_text(title + _HEADER + "".join(rows), encoding="utf-8")
    return path


# ----------------------------------------------------------------------
# parse_backup_time_selected
# ----------------------------------------------------------------------

def test_skips_title_row_and_reads_real_header(tmp_path):
    path = _write(tmp_path, ["576,Jane Runner,F,34,5K,08:30:00,08:30:01.0,09:06:51.0,36:51,36:50,Yes\n"])

    df = parse_backup_time_selected(path)

    assert list(df.columns) == [
        "bib", "name", "gender", "age", "scored_event", "clock_start_time",
        "chip_start_time", "finish_time", "chip_time_elapsed", "clock_time_elapsed",
        "backup_time_selected",
    ]
    assert df.iloc[0]["bib"] == 576
    assert df.iloc[0]["name"] == "Jane Runner"


def test_backup_time_selected_yes_parses_true(tmp_path):
    path = _write(tmp_path, ["576,Jane Runner,F,34,5K,08:30:00,08:30:01.0,09:06:51.0,36:51,36:50,Yes\n"])

    df = parse_backup_time_selected(path)

    assert bool(df.iloc[0]["backup_time_selected"]) is True


def test_missing_backup_time_selected_column_defaults_true(tmp_path):
    # "Time Machine - Used" report layout: same columns minus this one --
    # every row implicitly used TM.
    header = "Bib,Name,Gender,Age,Scored Event,Clock Start Time of Day,Chip Start Time of Day,Finish Time of Day,Chip Time,Clock Time\n"
    path = tmp_path / "time-machine-used.csv"
    path.write_text("Time Machine - Used Report\n" + header + "576,Jane Runner,F,34,5K,08:30:00,08:30:01.0,09:06:51.0,36:51,36:50\n", encoding="utf-8")

    df = parse_backup_time_selected(path)

    assert bool(df.iloc[0]["backup_time_selected"]) is True


def test_blank_chip_start_time_parses_as_nat_not_a_crash(tmp_path):
    # A bib with no chip assigned at all has nothing to report for Chip Start
    # Time of Day -- must not crash the whole parse (Parkway Panda 5K case).
    path = _write(tmp_path, ["381,No Chip Runner,M,40,5K,08:30:00,,09:10:00.0,40:00,40:00,Yes\n"])

    df = parse_backup_time_selected(path)

    assert pd.isna(df.iloc[0]["chip_start_time"])


def test_elapsed_columns_parsed_as_timedelta(tmp_path):
    path = _write(tmp_path, ["576,Jane Runner,F,34,5K,08:30:00,08:30:01.0,09:06:51.0,36:51,36:50,Yes\n"])

    df = parse_backup_time_selected(path)

    assert df.iloc[0]["chip_time_elapsed"] == pd.Timedelta(minutes=36, seconds=51)
    assert df.iloc[0]["clock_time_elapsed"] == pd.Timedelta(minutes=36, seconds=50)


def test_race_date_produces_full_timestamps(tmp_path):
    path = _write(tmp_path, ["576,Jane Runner,F,34,5K,08:30:00,08:30:01.0,09:06:51.0,36:51,36:50,Yes\n"])

    df = parse_backup_time_selected(path, race_date="2026-07-04")

    assert df.iloc[0]["finish_time"] == pd.Timestamp("2026-07-04 09:06:51.0")


def test_without_race_date_time_columns_are_bare_time_of_day(tmp_path):
    path = _write(tmp_path, ["576,Jane Runner,F,34,5K,08:30:00,08:30:01.0,09:06:51.0,36:51,36:50,Yes\n"])

    df = parse_backup_time_selected(path)

    import datetime as dt
    assert df.iloc[0]["finish_time"] == dt.time(9, 6, 51)


def test_bib_and_age_are_int64(tmp_path):
    path = _write(tmp_path, ["576,Jane Runner,F,34,5K,08:30:00,08:30:01.0,09:06:51.0,36:51,36:50,Yes\n"])

    df = parse_backup_time_selected(path)

    assert str(df["bib"].dtype) == "int64"
    assert str(df["age"].dtype) == "int64"


# ----------------------------------------------------------------------
# sanity_check
# ----------------------------------------------------------------------

def test_sanity_check_reports_all_backup_selected(tmp_path, capsys):
    path = _write(tmp_path, ["576,Jane Runner,F,34,5K,08:30:00,08:30:01.0,09:06:51.0,36:51,36:50,Yes\n"])
    df = parse_backup_time_selected(path)

    sanity_check(df)

    out = capsys.readouterr().out
    assert "all backup_time_selected=True: True" in out


def test_sanity_check_handles_empty_dataframe(capsys):
    empty = pd.DataFrame(columns=[
        "bib", "name", "gender", "age", "scored_event", "clock_start_time",
        "chip_start_time", "finish_time", "chip_time_elapsed", "clock_time_elapsed",
        "backup_time_selected",
    ])

    sanity_check(empty)

    out = capsys.readouterr().out
    assert "records: 0" in out
