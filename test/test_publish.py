"""test_publish - test chip_timing_analysis.report.publish"""

import pytest

from chip_timing_analysis.report.publish import publish, _find_changed_race_dates


def _make_reports_dir(tmp_path, races: dict[str, str]):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "SUMMARY.md").write_text("# Timing Summary\n", encoding="utf-8")
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
    assert (dest_dir / "README.md").read_text(encoding="utf-8") == "# Timing Summary\n"
    assert (dest_dir / "SUMMARY-LEGEND.md").read_text(encoding="utf-8") == "# Legend\n"


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
