"""test_publish - test chip_timing_analysis.report.publish"""

import pytest

from chip_timing_analysis.report.publish import publish, _find_changed_race_dates
from chip_timing_analysis.report.summary_merge import MARKER_TABLE

_SUMMARY_HEADER = (
    "| Date | Distance | Participants | Zero Reads | Missed Start | Missed Finish | "
    "% Missed | Peak (60s) | Peak (15s) | Notes |"
)
_SUMMARY_SEP = "|---|---|---|---|---|---|---|---|---|---|"

_SUMMARY_TEXT = (
    "# Timing Summary\n\n"
    "One row per race analyzed, most recent first. See the [column legend](SUMMARY-LEGEND.md) "
    "for what each column means.\n\n"
    f"{_SUMMARY_HEADER}\n{_SUMMARY_SEP}\n"
    "| [2026-07-04](2026-07-04.md) | 5K | 111 | 0 | 1 | 3 | 1.8% | 11 | 7 | note |\n"
    "| [2026-05-25](2026-05-25.md) | 5K | 261 | 0 | 5 | 3 | 1.5% | 27 | 11 | note |\n"
)


def _make_reports_dir(tmp_path, races: dict[str, str]):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "SUMMARY.md").write_text(_SUMMARY_TEXT, encoding="utf-8")
    (reports_dir / "SUMMARY-LEGEND.md").write_text("# Legend\n", encoding="utf-8")
    for date, content in races.items():
        (reports_dir / f"{date}.md").write_text(content, encoding="utf-8")
    return reports_dir


def _make_fsrc_tech_dir(tmp_path):
    dest_dir = tmp_path / "fsrc-tech" / "docs" / "race-services" / "reports"
    dest_dir.mkdir(parents=True)
    return tmp_path / "fsrc-tech", dest_dir


# ----------------------------------------------------------------------
# publish (single race_date)
# ----------------------------------------------------------------------

def test_publish_copies_report_summary_and_legend(tmp_path, monkeypatch):
    _make_reports_dir(tmp_path, {"2026-07-04": "# Indy report\n"})
    fsrc_tech_dir, dest_dir = _make_fsrc_tech_dir(tmp_path)
    monkeypatch.chdir(tmp_path)

    publish("2026-07-04", str(fsrc_tech_dir))

    assert (dest_dir / "2026-07-04.md").read_text(encoding="utf-8") == "# Indy report\n"
    # no pre-existing README -> nothing hand-maintained to protect -> verbatim copy
    assert (dest_dir / "README.md").read_text(encoding="utf-8") == _SUMMARY_TEXT
    assert (dest_dir / "SUMMARY-LEGEND.md").read_text(encoding="utf-8") == "# Legend\n"


def test_publish_merges_into_marked_up_readme(tmp_path, monkeypatch):
    _make_reports_dir(tmp_path, {"2026-07-04": "# Indy report\n"})
    fsrc_tech_dir, dest_dir = _make_fsrc_tech_dir(tmp_path)
    monkeypatch.chdir(tmp_path)

    from chip_timing_analysis.report.summary_merge import (
        MARKER_OVERALL_END,
        MARKER_OVERALL_START,
    )

    (dest_dir / "README.md").write_text(
        "# Timing Summary\n\n"
        "## Overall (all races to date)\n\n"
        f"{MARKER_OVERALL_START}\n\n"
        "- **1 timed participant** over 1 race.\n\n"
        f"{MARKER_OVERALL_END}\n\n"
        "Every finish miss to date was recovered via backup timing.\n\n"
        "## Per race\n\n"
        f"{MARKER_TABLE}\n{_SUMMARY_HEADER}\n{_SUMMARY_SEP}\n"
        "| [2026-09-05](2026-09-05.md) | 5 Miles | 23 | 0 | 0 | 0 | 0.0% | 4 | 2 | practice race |\n"
        "| [2026-07-04](2026-07-04.md) | 5K | 111 | 0 | 1 | 3 | 1.8% | 11 | 7 | stale note |\n",
        encoding="utf-8",
    )

    publish("2026-07-04", str(fsrc_tech_dir))

    readme = (dest_dir / "README.md").read_text(encoding="utf-8")
    # hand-maintained preamble prose survives
    assert "Every finish miss to date was recovered via backup timing." in readme
    # hand-added row for a race the pipeline can't ingest survives
    assert "| [2026-09-05](2026-09-05.md) | 5 Miles | 23 |" in readme
    # pipeline row replaces the hand-edited copy of the same date
    assert "| note |" in readme
    assert "stale note" not in readme
    # Overall block regenerated from the merged set (23 + 111 + 261)
    assert "- **395 timed participants** over 3 races." in readme
    assert "- **1 timed participant** over 1 race." not in readme


def test_publish_missing_race_report_raises(tmp_path, monkeypatch):
    _make_reports_dir(tmp_path, {})
    fsrc_tech_dir, _ = _make_fsrc_tech_dir(tmp_path)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError):
        publish("2026-07-04", str(fsrc_tech_dir))


def test_publish_missing_summary_raises(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    fsrc_tech_dir, _ = _make_fsrc_tech_dir(tmp_path)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError):
        publish(None, str(fsrc_tech_dir), new=True)


def test_publish_invalid_fsrc_tech_dir_raises(tmp_path, monkeypatch):
    _make_reports_dir(tmp_path, {"2026-07-04": "# report\n"})
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError):
        publish("2026-07-04", str(tmp_path / "not-a-real-checkout"))


# ----------------------------------------------------------------------
# publish --new
# ----------------------------------------------------------------------

def test_publish_new_copies_only_missing_or_changed_reports(tmp_path, monkeypatch):
    _make_reports_dir(tmp_path, {"2026-07-04": "# Indy\n", "2026-05-25": "# Panda\n"})
    fsrc_tech_dir, dest_dir = _make_fsrc_tech_dir(tmp_path)
    (dest_dir / "2026-05-25.md").write_text("# Panda\n", encoding="utf-8")  # already up to date
    monkeypatch.chdir(tmp_path)

    publish(None, str(fsrc_tech_dir), new=True)

    assert (dest_dir / "2026-07-04.md").read_text(encoding="utf-8") == "# Indy\n"


def test_publish_new_with_nothing_changed_still_refreshes_summary(tmp_path, monkeypatch, capsys):
    _make_reports_dir(tmp_path, {"2026-05-25": "# Panda\n"})
    fsrc_tech_dir, dest_dir = _make_fsrc_tech_dir(tmp_path)
    (dest_dir / "2026-05-25.md").write_text("# Panda\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    publish(None, str(fsrc_tech_dir), new=True)

    out = capsys.readouterr().out
    assert "no new or changed" in out
    assert (dest_dir / "README.md").exists()


# ----------------------------------------------------------------------
# _find_changed_race_dates
# ----------------------------------------------------------------------

def test_find_changed_includes_missing_reports(tmp_path):
    reports_dir = _make_reports_dir(tmp_path, {"2026-07-04": "# Indy\n"})
    _, dest_dir = _make_fsrc_tech_dir(tmp_path)

    changed = _find_changed_race_dates(reports_dir, dest_dir)

    assert changed == ["2026-07-04"]


def test_find_changed_includes_text_different_reports(tmp_path):
    reports_dir = _make_reports_dir(tmp_path, {"2026-07-04": "# Indy v2\n"})
    _, dest_dir = _make_fsrc_tech_dir(tmp_path)
    (dest_dir / "2026-07-04.md").write_text("# Indy v1\n", encoding="utf-8")

    changed = _find_changed_race_dates(reports_dir, dest_dir)

    assert changed == ["2026-07-04"]


def test_find_changed_excludes_identical_reports(tmp_path):
    reports_dir = _make_reports_dir(tmp_path, {"2026-07-04": "# Indy\n"})
    _, dest_dir = _make_fsrc_tech_dir(tmp_path)
    (dest_dir / "2026-07-04.md").write_text("# Indy\n", encoding="utf-8")

    assert _find_changed_race_dates(reports_dir, dest_dir) == []


def test_find_changed_excludes_summary_and_legend_files(tmp_path):
    reports_dir = _make_reports_dir(tmp_path, {})
    _, dest_dir = _make_fsrc_tech_dir(tmp_path)

    changed = _find_changed_race_dates(reports_dir, dest_dir)

    assert changed == []


def test_find_changed_compares_as_text_not_bytes(tmp_path):
    # \r\n vs \n with otherwise-identical content must read as unchanged --
    # Path.read_text() normalizes line endings on read (universal newlines),
    # unlike a raw byte comparison (the bug this guards against, CLAUDE.md).
    reports_dir = _make_reports_dir(tmp_path, {"2026-04-04": "# Wild Trail\nline two\n"})
    _, dest_dir = _make_fsrc_tech_dir(tmp_path)
    (dest_dir / "2026-04-04.md").write_bytes(b"# Wild Trail\r\nline two\r\n")

    changed = _find_changed_race_dates(reports_dir, dest_dir)

    assert changed == []
