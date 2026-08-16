"""test_bib_chip - test chip_timing_analysis.parsers.bib_chip"""

import pandas as pd

from chip_timing_analysis.parsers.bib_chip import parse_bib_chip, sanity_check


# ----------------------------------------------------------------------
# parse_bib_chip
# ----------------------------------------------------------------------

def test_parses_bib_and_tag_id(tmp_path):
    path = tmp_path / "bib-chip.csv"
    path.write_text("bib,chip\n101,00000C08C1D5\n102,00000C08C225\n", encoding="utf-8")

    df = parse_bib_chip(path)

    assert list(df.columns) == ["bib", "tag_id"]
    assert df["bib"].tolist() == [101, 102]
    assert df["tag_id"].tolist() == ["00000c08c1d5", "00000c08c225"]


def test_tag_id_is_lowercased_to_match_raw_read_case(tmp_path):
    # bib-chip.csv stores chip uppercase; the raw log's tag_id is lowercase --
    # this must normalize so the two can be joined on tag_id.
    path = tmp_path / "bib-chip.csv"
    path.write_text("bib,chip\n101,ABCDEF012345\n", encoding="utf-8")

    df = parse_bib_chip(path)

    assert df.iloc[0]["tag_id"] == "abcdef012345"


def test_bib_is_int64(tmp_path):
    path = tmp_path / "bib-chip.csv"
    path.write_text("bib,chip\n101,00000c08c1d5\n", encoding="utf-8")

    df = parse_bib_chip(path)

    assert str(df["bib"].dtype) == "int64"


def test_empty_file_returns_empty_dataframe(tmp_path):
    path = tmp_path / "bib-chip.csv"
    path.write_text("bib,chip\n", encoding="utf-8")

    df = parse_bib_chip(path)

    assert df.empty
    assert list(df.columns) == ["bib", "tag_id"]


# ----------------------------------------------------------------------
# sanity_check
# ----------------------------------------------------------------------

def test_sanity_check_warns_on_duplicate_tag_id(tmp_path, capsys):
    path = tmp_path / "bib-chip.csv"
    path.write_text("bib,chip\n101,00000c08c1d5\n102,00000c08c1d5\n", encoding="utf-8")
    df = parse_bib_chip(path)

    sanity_check(df)

    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "share a tag_id" in out


def test_sanity_check_no_warning_when_tags_unique(tmp_path, capsys):
    path = tmp_path / "bib-chip.csv"
    path.write_text("bib,chip\n101,00000c08c1d5\n102,00000c08c225\n", encoding="utf-8")
    df = parse_bib_chip(path)

    sanity_check(df)

    out = capsys.readouterr().out
    assert "WARNING" not in out
