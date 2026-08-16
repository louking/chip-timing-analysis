"""test_render - test chip_timing_analysis.report.render"""

import pandas as pd

from chip_timing_analysis.report.build import RaceReport
from chip_timing_analysis.report.render import (
    _fmt_ts,
    _fmt_time,
    _reconcile_backup,
    _render_read_reliability,
    _summary_notes_cell,
    render_summary_row,
    render_summary_legend,
    append_summary_row,
    _SUMMARY_HEADER,
)

GUN = pd.Timestamp("2026-05-25 09:00:00")


def _bibs_df(bibs, extra: dict | None = None) -> pd.DataFrame:
    data = {"bib": bibs}
    if extra:
        data.update(extra)
    return pd.DataFrame(data)


def _report(**overrides) -> RaceReport:
    defaults = dict(
        race_name="Test Race", race_date="2026-05-25", distance="5K", gun_time=GUN,
        n_bib_chip_entries=10, n_participants=10,
        no_chip_assigned=_bibs_df([], {"finish_time": []}),
        zero_reads=_bibs_df([]), missed_start_only=_bibs_df([]), missed_finish_only=_bibs_df([]),
        density_rolling=pd.DataFrame({"finishers_in_window": [3]}),
        density_rolling_burst=pd.DataFrame({"finishers_in_window": [2]}),
        known_drops=[],
    )
    defaults.update(overrides)
    return RaceReport(**defaults)


# ----------------------------------------------------------------------
# _fmt_ts / _fmt_time
# ----------------------------------------------------------------------

def test_fmt_ts_shows_hundredths_not_microseconds():
    ts = pd.Timestamp("2026-07-04 08:49:19.300000")

    assert _fmt_ts(ts) == "2026-07-04 08:49:19.30"


def test_fmt_ts_nat_is_empty_string():
    assert _fmt_ts(pd.NaT) == ""


def test_fmt_time_omits_date():
    ts = pd.Timestamp("2026-07-04 08:49:19.300000")

    assert _fmt_time(ts) == "08:49:19.30"


def test_fmt_time_nat_is_empty_string():
    assert _fmt_time(pd.NaT) == ""


def test_fmt_ts_truncates_not_rounds():
    ts = pd.Timestamp("2026-07-04 08:49:19.999999")

    assert _fmt_ts(ts) == "2026-07-04 08:49:19.99"


# ----------------------------------------------------------------------
# _reconcile_backup
# ----------------------------------------------------------------------

def test_reconcile_backup_unavailable_reports_all_misses_as_unrecovered():
    report = _report(missed_finish_only=_bibs_df([598, 606]))

    recon = _reconcile_backup(report)

    assert recon["available"] is False
    assert recon["n_unrecovered"] == 2
    assert recon["unrecovered_bibs"] == [598, 606]


def test_reconcile_backup_splits_recovered_and_unrecovered():
    report = _report(
        missed_finish_only=_bibs_df([598, 606, 630]),
        backup=_bibs_df([598, 606], {"name": ["a", "b"]}),  # only 2 of the 3 misses recovered
    )

    recon = _reconcile_backup(report)

    assert recon["available"] is True
    assert recon["n_zero_read"] == 2
    assert recon["n_unrecovered"] == 1
    assert recon["unrecovered_bibs"] == [630]


def test_reconcile_backup_confirmed_drops_are_a_separate_bucket_not_nested():
    # a drop's missing finish must not inflate n_unrecovered/n_zero_read
    report = _report(
        missed_finish_only=_bibs_df([267, 998]),
        known_drops=[267],
        backup=_bibs_df([], {"name": []}),
    )

    recon = _reconcile_backup(report)

    assert recon["n_drops"] == 1
    assert recon["drop_bibs"] == [267]
    assert recon["n_unrecovered"] == 1
    assert recon["unrecovered_bibs"] == [998]


def test_reconcile_backup_network_interruption_excludes_no_chip_bibs():
    # a no-chip-assigned bib is also backup-used and also not a finish miss,
    # but for a different reason -- must not be misattributed to "network
    # interruption" (the bug this test guards against).
    report = _report(
        no_chip_assigned=_bibs_df([381], {"finish_time": [GUN + pd.Timedelta(minutes=40)]}),
        backup=_bibs_df([381, 576], {"name": ["a", "b"]}),
    )

    recon = _reconcile_backup(report)

    assert recon["network_bibs"] == [576]
    assert recon["n_network"] == 1


# ----------------------------------------------------------------------
# _render_read_reliability
# ----------------------------------------------------------------------

def test_render_read_reliability_reports_finish_miss_percentage():
    report = _report(n_participants=110, missed_finish_only=_bibs_df([598, 606, 630]))

    lines = _render_read_reliability(report, include_bibs=False)

    assert any("3 of 110 chips were not read at the finish (2.7%)" in line for line in lines)


def test_render_read_reliability_include_bibs_appends_bib_numbers():
    report = _report(missed_finish_only=_bibs_df([598]))

    with_bibs = _render_read_reliability(report, include_bibs=True)
    without_bibs = _render_read_reliability(report, include_bibs=False)

    assert any("598" in line for line in with_bibs)
    assert not any("598" in line for line in without_bibs)


def test_render_read_reliability_no_no_chip_line_when_none():
    report = _report()

    lines = _render_read_reliability(report, include_bibs=False)

    assert not any("no chip assigned" in line for line in lines)


def test_render_read_reliability_backup_unavailable_says_so():
    report = _report(missed_finish_only=_bibs_df([1]))

    lines = _render_read_reliability(report, include_bibs=False)

    assert any("not available" in line for line in lines)


# ----------------------------------------------------------------------
# _summary_notes_cell
# ----------------------------------------------------------------------

def test_summary_notes_cell_dash_when_empty():
    report = _report(notes=[])

    assert _summary_notes_cell(report) == "—"


def test_summary_notes_cell_prepends_no_chip_count():
    report = _report(notes=["a note"], no_chip_assigned=_bibs_df([1, 2], {"finish_time": [GUN, GUN]}))

    cell = _summary_notes_cell(report)

    assert cell.startswith("2 no chip assigned")


def test_summary_notes_cell_truncates_long_text():
    long_note = "x" * 100
    report = _report(notes=[long_note])

    cell = _summary_notes_cell(report)

    assert len(cell) == 61  # 60 chars + ellipsis
    assert cell.endswith("…")


# ----------------------------------------------------------------------
# render_summary_row / append_summary_row
# ----------------------------------------------------------------------

def test_render_summary_row_links_to_race_date_report():
    report = _report(race_date="2026-05-25")

    row = render_summary_row(report)

    assert "[2026-05-25](2026-05-25.md)" in row


def test_append_summary_row_creates_file_with_header(tmp_path):
    report = _report(race_date="2026-05-25")
    summary_path = tmp_path / "SUMMARY.md"

    append_summary_row(report, summary_path)

    content = summary_path.read_text(encoding="utf-8")
    assert content.startswith(_SUMMARY_HEADER)
    assert "2026-05-25" in content


def test_append_summary_row_writes_legend_file_alongside(tmp_path):
    report = _report()
    summary_path = tmp_path / "SUMMARY.md"

    append_summary_row(report, summary_path)

    legend_path = tmp_path / "SUMMARY-LEGEND.md"
    assert legend_path.exists()
    assert legend_path.read_text(encoding="utf-8") == render_summary_legend()


def test_append_summary_row_out_of_order_insertion(tmp_path):
    summary_path = tmp_path / "SUMMARY.md"
    append_summary_row(_report(race_date="2026-07-04"), summary_path)
    append_summary_row(_report(race_date="2026-05-25"), summary_path)  # added after, but earlier date

    content = summary_path.read_text(encoding="utf-8")
    idx_july = content.index("2026-07-04")
    idx_may = content.index("2026-05-25")
    assert idx_july < idx_may  # most recent race still listed first


def test_append_summary_row_replaces_existing_row_for_same_race(tmp_path):
    summary_path = tmp_path / "SUMMARY.md"
    append_summary_row(_report(race_date="2026-05-25", n_participants=10), summary_path)
    append_summary_row(_report(race_date="2026-05-25", n_participants=99), summary_path)

    content = summary_path.read_text(encoding="utf-8")
    assert content.count("[2026-05-25]") == 1  # exactly one row for this race, not two
    assert "| 99 |" in content


def test_append_summary_row_rewrites_header_from_current_constant(tmp_path):
    # a header/column-label change in code must propagate to an existing
    # summary file on the next race generated, not stay stuck with whatever
    # text was previously written to disk (bug found 2026-07-13, see CLAUDE.md)
    summary_path = tmp_path / "SUMMARY.md"
    stale_header = "# Old Stale Header\n\n| Date | Old Col |\n|---|---|\n"
    summary_path.write_text(stale_header, encoding="utf-8")

    append_summary_row(_report(race_date="2026-05-25"), summary_path)

    content = summary_path.read_text(encoding="utf-8")
    assert content.startswith(_SUMMARY_HEADER)
    assert "Old Stale Header" not in content
