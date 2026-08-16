"""test_tm_data - test chip_timing_analysis.parsers.tm_data"""

import pandas as pd

from chip_timing_analysis.parsers.tm_data import parse_tm_data, sanity_check


# ----------------------------------------------------------------------
# parse_tm_data
# ----------------------------------------------------------------------

def test_parses_seq_bib_and_time(tmp_path):
    path = tmp_path / "tm-data.csv"
    path.write_text("1,101,08:49:19.30\n2,102,08:49:22.05\n", encoding="utf-8")

    df = parse_tm_data(path)

    assert list(df.columns) == ["seq", "bib", "finish_time"]
    assert df["seq"].tolist() == [1, 2]
    assert df["bib"].tolist() == [101, 102]


def test_finish_time_without_race_date_is_time_of_day(tmp_path):
    path = tmp_path / "tm-data.csv"
    path.write_text("1,101,08:49:19.30\n", encoding="utf-8")

    df = parse_tm_data(path)

    assert df.iloc[0]["finish_time"] == pd.Timedelta(hours=8, minutes=49, seconds=19, milliseconds=300)


def test_finish_time_with_race_date_is_full_timestamp(tmp_path):
    path = tmp_path / "tm-data.csv"
    path.write_text("1,101,08:49:19.30\n", encoding="utf-8")

    df = parse_tm_data(path, race_date="2026-07-04")

    assert df.iloc[0]["finish_time"] == pd.Timestamp("2026-07-04 08:49:19.30")


def test_bib_and_seq_are_int64(tmp_path):
    path = tmp_path / "tm-data.csv"
    path.write_text("1,101,08:49:19.30\n", encoding="utf-8")

    df = parse_tm_data(path)

    assert str(df["seq"].dtype) == "int64"
    assert str(df["bib"].dtype) == "int64"


def test_empty_file_returns_empty_dataframe(tmp_path):
    path = tmp_path / "tm-data.csv"
    path.write_text("", encoding="utf-8")

    df = parse_tm_data(path)

    assert df.empty
    assert list(df.columns) == ["seq", "bib", "finish_time"]


# ----------------------------------------------------------------------
# sanity_check
# ----------------------------------------------------------------------

def test_sanity_check_warns_on_duplicate_bib(tmp_path, capsys):
    path = tmp_path / "tm-data.csv"
    path.write_text("1,101,08:49:19.30\n2,101,08:50:00.00\n", encoding="utf-8")
    df = parse_tm_data(path)

    sanity_check(df)

    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "share a bib" in out


def test_sanity_check_handles_empty_dataframe(capsys):
    empty = pd.DataFrame(columns=["seq", "bib", "finish_time"])

    sanity_check(empty)

    out = capsys.readouterr().out
    assert "records: 0" in out
