"""test_summary_merge - test chip_timing_analysis.report.summary_merge"""

from chip_timing_analysis.report.summary_merge import (
    MARKER_OVERALL_END,
    MARKER_OVERALL_START,
    MARKER_TABLE,
    merge_summary_into_readme,
    parse_row,
    render_overall,
    is_no_chip_row,
)

_HEADER = (
    "| Date | Distance | Participants | Zero Reads | Missed Start | Missed Finish | "
    "% Missed | Peak (60s) | Peak (15s) | Notes |"
)
_SEP = "|---|---|---|---|---|---|---|---|---|---|"


def _row(date, dist="5K", participants=100, zero=0, start=1, finish=2, pct="1.5%", notes="—"):
    return (
        f"| [{date}]({date}.md) | {dist} | {participants} | {zero} | {start} | {finish} | "
        f"{pct} | 8 | 4 | {notes} |"
    )


def _src(*rows):
    return (
        "# Timing Summary\n\n"
        "One row per race analyzed, most recent first. See the [column legend](SUMMARY-LEGEND.md) "
        "for what each column means.\n\n"
        f"{_HEADER}\n{_SEP}\n" + "".join(r + "\n" for r in rows)
    )


# ----------------------------------------------------------------------
# parse_row
# ----------------------------------------------------------------------

def test_parse_row_reads_numeric_columns():
    r = parse_row(_row("2026-07-04", participants=111, zero=0, start=1, finish=3, pct="1.8%"))

    assert (r.date, r.participants, r.zero_reads, r.missed_start, r.missed_finish) == (
        "2026-07-04",
        111,
        0,
        1,
        3,
    )


def test_parse_row_rejects_non_dated_line():
    assert parse_row(f"{_HEADER}") is None
    assert parse_row(f"{_SEP}") is None
    assert parse_row("just some prose") is None


def test_parse_row_rejects_non_numeric_count_cells():
    assert parse_row(_row("2026-09-05", participants="n/a")) is None
    assert parse_row(_row("2026-09-05", zero="x")) is None
    assert parse_row(_row("2026-09-05", finish="?")) is None


def test_parse_row_tolerates_loose_percent_cell():
    # the % Missed cell isn't parsed -- pooled % is recomputed from counts,
    # so a loose value there keeps the row in the Overall totals
    r = parse_row(_row("2026-09-05", participants=23, pct="pending"))

    assert r is not None and r.participants == 23


def test_parse_row_rejects_too_few_cells():
    assert parse_row("| [2026-09-05](2026-09-05.md) | 5K |") is None


# ----------------------------------------------------------------------
# render_overall
# ----------------------------------------------------------------------

def test_render_overall_totals_and_pooled_pct():
    rows = [
        _row("2026-07-04", participants=111, zero=0, start=1, finish=3, pct="1.8%"),
        _row("2026-05-25", participants=261, zero=0, start=5, finish=3, pct="1.5%"),
        _row("2026-04-04", participants=87, zero=0, start=1, finish=1, pct="1.1%"),
        _row("2026-01-10", participants=46, zero=0, start=0, finish=2, pct="2.2%"),
        _row("2025-07-19", participants=62, zero=0, start=0, finish=1, pct="0.8%"),
        _row("2026-09-05", participants=23, zero=0, start=0, finish=0, pct="0.0%"),
    ]

    bullets = render_overall(rows)

    assert bullets == [
        "- **590 timed participants** over 6 races.",
        "- **0 non-functioning chips** (chip assigned but not read at start or finish).",
        "- **10 finish-line read misses** (1.7% of participants).",
        "- **7 start-line read misses** (1.2% of participants).",
        "- **~1.4%** of all chip read opportunities (start + finish) missed, pooled across races.",
    ]


def test_render_overall_singular_wording_for_one_race():
    bullets = render_overall([_row("2026-09-05", participants=1, zero=1, start=1, finish=1, pct="0.0%")])

    assert bullets[0] == "- **1 timed participant** over 1 race."
    assert bullets[1] == "- **1 non-functioning chip** (chip assigned but not read at start or finish)."
    assert bullets[2] == "- **1 finish-line read miss** (100.0% of participants)."
    assert bullets[3] == "- **1 start-line read miss** (100.0% of participants)."


def test_render_overall_excludes_non_numeric_rows():
    good = _row("2026-07-04", participants=100, zero=0, start=0, finish=2, pct="1.0%")
    junk = _row("2026-09-05", participants="tbd", pct="tbd")

    assert render_overall([good, junk]) == render_overall([good])
    assert render_overall([good])[0] == "- **100 timed participants** over 1 race."


def test_render_overall_empty_when_nothing_parses():
    assert render_overall([_HEADER, _SEP, "not a row"]) == []


# ----------------------------------------------------------------------
# merge_summary_into_readme -- preamble / rows / conflicts
# ----------------------------------------------------------------------

def _dest(preamble, *rows):
    return preamble + f"\n{MARKER_TABLE}\n{_HEADER}\n{_SEP}\n" + "".join(r + "\n" for r in rows)


def test_merge_preserves_preamble_verbatim():
    preamble = (
        "# Timing Summary\n\n"
        "## Overall (all races to date)\n\n"
        "Some hand-written prose the table can't produce.\n\n"
        "## Per race\n\n"
        "One row per race analyzed, most recent first."
    )
    dest = _dest(preamble, _row("2026-07-04"))
    src = _src(_row("2026-07-04"))

    merged, warnings = merge_summary_into_readme(src, dest)

    assert warnings == []
    assert merged.startswith(preamble + "\n" + MARKER_TABLE + "\n")
    assert "Some hand-written prose the table can't produce." in merged


def test_merge_keeps_hand_added_destination_row():
    dest = _dest("# Timing Summary", _row("2026-09-05", dist="5 Miles", participants=23),
                 _row("2026-07-04", participants=111))
    src = _src(_row("2026-07-04", participants=111))

    merged, _ = merge_summary_into_readme(src, dest)

    assert "[2026-09-05](2026-09-05.md)" in merged
    assert "5 Miles" in merged


def test_merge_pipeline_row_wins_on_date_conflict():
    dest = _dest("# Timing Summary", _row("2026-07-04", participants=999, finish=99))
    src = _src(_row("2026-07-04", participants=111, finish=3))

    merged, _ = merge_summary_into_readme(src, dest)

    assert "| 111 |" in merged
    assert "999" not in merged


def test_merge_sorts_rows_date_descending():
    dest = _dest("# Timing Summary", _row("2025-07-19"))
    src = _src(_row("2026-01-10"), _row("2026-07-04"), _row("2026-04-04"))

    merged, _ = merge_summary_into_readme(src, dest)

    order = [ln.split("]")[0] for ln in merged.splitlines() if ln.startswith("| [")]
    assert order == ["| [2026-07-04", "| [2026-04-04", "| [2026-01-10", "| [2025-07-19"]


def test_merge_copies_header_and_separator_from_source():
    renamed_header = _HEADER.replace("Missed Finish", "Finish Misses")
    src = (
        "# Timing Summary\n\n"
        f"{renamed_header}\n{_SEP}\n{_row('2026-07-04')}\n"
    )
    dest = _dest("# Timing Summary", _row("2026-07-04"))

    merged, _ = merge_summary_into_readme(src, dest)

    assert "Finish Misses" in merged
    assert "Missed Finish" not in merged


# ----------------------------------------------------------------------
# merge_summary_into_readme -- Overall block regeneration
# ----------------------------------------------------------------------

def test_merge_regenerates_overall_block_and_leaves_surrounding_prose():
    preamble = (
        "# Timing Summary\n\n"
        "## Overall (all races to date)\n\n"
        "Cumulative across the races below.\n\n"
        f"{MARKER_OVERALL_START}\n\n"
        "- **1 timed participant** over 1 race.\n"
        "- stale bullet that must be replaced\n\n"
        f"{MARKER_OVERALL_END}\n\n"
        "All misses were recovered via backup timing.\n\n"
        "## Per race"
    )
    dest = _dest(preamble, _row("2026-09-05", participants=23, zero=0, start=0, finish=0, pct="0.0%"))
    src = _src(_row("2026-07-04", participants=100, zero=1, start=2, finish=4, pct="3.0%"))

    merged, warnings = merge_summary_into_readme(src, dest)

    assert warnings == []
    # regenerated from the merged set: 2026-07-04 (src) + 2026-09-05 (hand-added)
    assert "- **123 timed participants** over 2 races." in merged
    assert "- **1 non-functioning chip** (chip assigned but not read at start or finish)." in merged
    assert "- **4 finish-line read misses** (3.3% of participants)." in merged
    assert "stale bullet that must be replaced" not in merged
    # prose outside the markers untouched
    assert "Cumulative across the races below." in merged
    assert "All misses were recovered via backup timing." in merged
    # markers themselves retained
    assert MARKER_OVERALL_START in merged
    assert MARKER_OVERALL_END in merged


def test_merge_warns_when_a_merged_row_is_left_out_of_overall_totals():
    preamble = (
        "# Timing Summary\n\n"
        f"{MARKER_OVERALL_START}\n\n- old\n\n{MARKER_OVERALL_END}\n"
    )
    # hand-added row with a prose count cell: kept in the table, excluded from totals
    dest = _dest(preamble, "| [2026-09-05](2026-09-05.md) | 5 Miles | tbd | 0 | 0 | 0 | n/a | 4 | 2 | practice |")
    src = _src(_row("2026-07-04", participants=100, start=0, finish=2, pct="1.0%"))

    merged, warnings = merge_summary_into_readme(src, dest)

    assert "| [2026-09-05](2026-09-05.md) | 5 Miles | tbd |" in merged  # row preserved
    assert "- **100 timed participants** over 1 race." in merged  # only the parseable row counted
    assert any("left" in w and "Overall totals" in w for w in warnings)


def test_merge_without_overall_markers_leaves_preamble_alone():
    preamble = "# Timing Summary\n\n- **stale bullet, no markers**\n"
    dest = _dest(preamble, _row("2026-07-04"))
    src = _src(_row("2026-07-04"))

    merged, warnings = merge_summary_into_readme(src, dest)

    assert warnings == []
    assert "- **stale bullet, no markers**" in merged


def test_merge_warns_when_overall_end_precedes_start():
    preamble = (
        "# Timing Summary\n\n"
        f"{MARKER_OVERALL_END}\n- bullet\n{MARKER_OVERALL_START}\n"
    )
    dest = _dest(preamble, _row("2026-07-04"))
    src = _src(_row("2026-07-04"))

    merged, warnings = merge_summary_into_readme(src, dest)

    assert any("does not follow" in w for w in warnings)
    assert "- bullet" in merged


# ----------------------------------------------------------------------
# merge_summary_into_readme -- fallbacks
# ----------------------------------------------------------------------

def test_merge_no_marker_falls_back_to_verbatim_with_warning():
    dest = "# Timing Summary\n\nhand-written index, no marker\n"
    src = _src(_row("2026-07-04"))

    merged, warnings = merge_summary_into_readme(src, dest)

    assert merged == src
    assert len(warnings) == 1
    assert MARKER_TABLE in warnings[0]


def test_merge_none_destination_returns_source_verbatim():
    src = _src(_row("2026-07-04"))

    merged, warnings = merge_summary_into_readme(src, None)

    assert merged == src
    assert warnings == []


def test_merge_source_without_table_passes_through_with_warning():
    src = "# Timing Summary\n\nno table here yet\n"
    dest = _dest("# Timing Summary", _row("2026-07-04"))

    merged, warnings = merge_summary_into_readme(src, dest)

    assert merged == src
    assert len(warnings) == 1
    assert "no recognizable table" in warnings[0]


def test_merge_output_ends_with_single_newline():
    dest = _dest("# Timing Summary", _row("2026-07-04"))
    src = _src(_row("2026-07-04"))

    merged, _ = merge_summary_into_readme(src, dest)

    assert merged.endswith("\n")
    assert not merged.endswith("\n\n")


# ----------------------------------------------------------------------
# rows for races with no chip timing
# ----------------------------------------------------------------------

_NO_CHIP_ROW = "| [2026-10-03](2026-10-03.md) | 5K | 77 | n/a | n/a | n/a | n/a | 8 | 4 | Not chip timed |"


def test_is_no_chip_row_true_for_all_na_chip_cells():
    assert is_no_chip_row(_NO_CHIP_ROW)


def test_is_no_chip_row_false_for_numeric_row():
    assert not is_no_chip_row(_row("2026-07-04"))


def test_merge_excludes_no_chip_row_from_overall_without_warning():
    preamble = (
        "# Timing Summary\n\n"
        f"{MARKER_OVERALL_START}\n\n- old\n\n{MARKER_OVERALL_END}\n"
    )
    src = _src(_NO_CHIP_ROW, _row("2026-07-04", participants=100, start=0, finish=2, pct="1.0%"))

    merged, warnings = merge_summary_into_readme(src, _dest(preamble))

    assert _NO_CHIP_ROW in merged
    assert "- **100 timed participants** over 1 race." in merged
    assert warnings == []
