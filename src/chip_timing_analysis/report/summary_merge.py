"""Merge this repo's ``reports/SUMMARY.md`` into fsrc-tech's
``docs/race-services/reports/README.md`` without clobbering hand-maintained
content there.

That destination file used to be a verbatim copy of ``SUMMARY.md`` (publish.py
step 3), but it has since grown content the pipeline can't produce:

* a hand-written preamble above the per-race table -- an "Overall (all races to
  date)" section plus prose (backup-recovery outcome, a no-chip-assigned aside,
  a note about a future rolling-12-month view);
* rows for races this pipeline can't ingest (e.g. a RaceDay Mobile practice
  race, hand-written to the sanitized format).

An unconditional ``SUMMARY.md`` -> ``README.md`` copy would wipe all of it.
This module does a structured merge instead, driven by three HTML-comment
markers (invisible in rendered Markdown):

``<!-- chip-timing-analysis:summary-table -->``
    Everything above it in the destination is a hand-maintained preamble and is
    preserved. From it down is regenerated: the column header + ``|---|``
    separator copied from ``SUMMARY.md`` (so a column rename still propagates),
    followed by the union of ``SUMMARY.md``'s rows and any hand-added
    destination rows, sorted date-descending, with pipeline rows winning for
    the dates the pipeline generates.

``<!-- chip-timing-analysis:overall:start -->`` / ``:overall:end``
    Optional, inside the preamble. The bullet list between them is regenerated
    from the merged row set (race count, total participants, zero-reads,
    start/finish misses, pooled % missed). Prose outside the markers -- before
    ``:start`` or after ``:end`` -- is untouched.

If the destination has no ``summary-table`` marker, this falls back to a
verbatim copy and returns a warning. ``publish.py`` prints the warnings.

Deliberately stdlib-only (no pandas, no import from ``render.py``) so
``publish.py`` stays free of the analysis import chain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MARKER_TABLE = "<!-- chip-timing-analysis:summary-table -->"
MARKER_OVERALL_START = "<!-- chip-timing-analysis:overall:start -->"
MARKER_OVERALL_END = "<!-- chip-timing-analysis:overall:end -->"

_DATE_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2})\]")
_ROW_DATE_RE = re.compile(r"^\|\s*\[(\d{4}-\d{2}-\d{2})\]")


@dataclass(frozen=True)
class SummaryRow:
    """The numeric columns of one per-race summary row, for the Overall
    aggregation. A row whose cells don't parse as numbers (a hand-added row
    with prose or placeholders in the count columns) yields ``None`` from
    :func:`parse_row` and is left out of the aggregation -- but still kept in
    the table itself by the merge.
    """

    date: str
    participants: int
    zero_reads: int
    missed_start: int
    missed_finish: int


def parse_row(line: str) -> SummaryRow | None:
    """Parse the count columns of a ``| [date](date.md) | dist | N | N | N | N | ... |``
    row. Returns ``None`` if the line isn't a dated row or its
    Participants/Zero Reads/Missed Start/Missed Finish cells aren't plain
    integers. The ``% Missed`` cell is deliberately not parsed -- the pooled
    figure is recomputed from the counts, so a loose value there (a hand-added
    row) doesn't drop the row from the totals.
    """
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) < 6:
        return None
    m = _DATE_RE.search(cells[0])
    if not m:
        return None
    try:
        return SummaryRow(
            date=m.group(1),
            participants=int(cells[2]),
            zero_reads=int(cells[3]),
            missed_start=int(cells[4]),
            missed_finish=int(cells[5]),
        )
    except ValueError:
        return None


def _plural(n: int, singular: str, plural: str) -> str:
    return singular if n == 1 else plural


def render_overall(row_lines: list[str]) -> list[str]:
    """The regenerated Overall bullet list, from the merged row set. Rows that
    don't parse numerically are excluded. Returns ``[]`` (caller keeps the
    existing block) when nothing parses.
    """
    rows = [r for r in (parse_row(ln) for ln in row_lines) if r is not None]
    if not rows:
        return []
    n_races = len(rows)
    participants = sum(r.participants for r in rows)
    zero_reads = sum(r.zero_reads for r in rows)
    starts = sum(r.missed_start for r in rows)
    finishes = sum(r.missed_finish for r in rows)
    # pooled ratio of missed opportunities to total opportunities (2 per
    # participant), not an average of the per-race rounded percentages
    pooled = (starts + finishes) / (participants * 2) * 100 if participants else 0.0

    def pct(n: int) -> str:
        return f"{n / participants * 100:.1f}" if participants else "0.0"

    return [
        f"- **{participants} timed {_plural(participants, 'participant', 'participants')}** "
        f"over {n_races} {_plural(n_races, 'race', 'races')}.",
        f"- **{zero_reads} non-functioning {_plural(zero_reads, 'chip', 'chips')}** "
        f"(chip assigned but not read at start or finish).",
        f"- **{finishes} finish-line read {_plural(finishes, 'miss', 'misses')}** "
        f"({pct(finishes)}% of participants).",
        f"- **{starts} start-line read {_plural(starts, 'miss', 'misses')}** "
        f"({pct(starts)}% of participants).",
        f"- **~{pooled:.1f}%** of all chip read opportunities (start + finish) "
        f"missed, pooled across races.",
    ]


def _split_table(lines: list[str]) -> tuple[str, str, list[str]] | None:
    """Locate a Markdown table: return ``(header_line, separator_line,
    dated_row_lines)`` or ``None``. The separator is the ``|---|---|`` line;
    rows are only those whose first cell is a ``[YYYY-MM-DD](...)`` link.
    """
    for i in range(len(lines) - 1):
        cur, nxt = lines[i].strip(), lines[i + 1].strip()
        if not cur.startswith("|") or not nxt.startswith("|"):
            continue
        if set(nxt) <= set("|-: ") and "-" in nxt:
            rows = [ln.rstrip() for ln in lines[i + 2 :] if _ROW_DATE_RE.match(ln.strip())]
            return lines[i].rstrip(), lines[i + 1].rstrip(), rows
    return None


def _merge_rows(src_rows: list[str], dest_rows: list[str]) -> list[str]:
    """Union src (pipeline) and dest (hand-added) rows by date, src winning on
    conflict, sorted date-descending.
    """
    by_date: dict[str, str] = {}
    for line in dest_rows:
        m = _ROW_DATE_RE.match(line.strip())
        if m:
            by_date[m.group(1)] = line.rstrip()
    for line in src_rows:  # pipeline rows overwrite hand-added ones for the same date
        m = _ROW_DATE_RE.match(line.strip())
        if m:
            by_date[m.group(1)] = line.rstrip()
    return [by_date[d] for d in sorted(by_date, reverse=True)]


def _regen_overall(preamble: list[str], merged_rows: list[str], warnings: list[str]) -> list[str]:
    """Replace the lines between the overall:start/end markers (exclusive) with
    a freshly rendered bullet list. Markers and everything outside them are
    left as-is. A no-op if the markers are absent, out of order, or the row
    set produces no bullets.
    """
    try:
        s = next(i for i, ln in enumerate(preamble) if ln.strip() == MARKER_OVERALL_START)
        e = next(i for i, ln in enumerate(preamble) if ln.strip() == MARKER_OVERALL_END)
    except StopIteration:
        return preamble
    if e <= s:
        warnings.append(
            f"`{MARKER_OVERALL_END}` does not follow `{MARKER_OVERALL_START}`; "
            "left the Overall block untouched"
        )
        return preamble
    bullets = render_overall(merged_rows)
    if not bullets:
        return preamble
    n_excluded = sum(1 for ln in merged_rows if parse_row(ln) is None)
    if n_excluded:
        warnings.append(
            f"{n_excluded} table row(s) had non-numeric count cells and were left "
            "out of the regenerated Overall totals"
        )
    return preamble[: s + 1] + [""] + bullets + [""] + preamble[e:]


def merge_summary_into_readme(src_summary: str, dest_readme: str | None) -> tuple[str, list[str]]:
    """Merge ``src_summary`` (this repo's ``reports/SUMMARY.md`` text) into
    ``dest_readme`` (fsrc-tech's current ``README.md`` text, or ``None`` if it
    doesn't exist yet). Returns ``(merged_text, warnings)``.

    * ``dest_readme`` is ``None`` -> nothing hand-maintained to protect; the
      source is returned verbatim.
    * ``src_summary`` has no recognizable table -> source returned verbatim
      with a warning (can't regenerate what can't be parsed).
    * ``dest_readme`` has no ``summary-table`` marker -> source returned
      verbatim with a warning (the hand-maintained preamble, if any, is lost;
      add the marker to protect it).
    * otherwise -> preamble preserved, table regenerated from the merged row
      set, Overall block regenerated if its markers are present.
    """
    warnings: list[str] = []

    src_table = _split_table(src_summary.split("\n"))
    if src_table is None:
        warnings.append("source SUMMARY.md has no recognizable table; copied it verbatim")
        return src_summary, warnings
    src_header, src_separator, src_rows = src_table

    if not dest_readme:
        return src_summary, warnings

    dest_lines = dest_readme.split("\n")
    try:
        marker_idx = next(i for i, ln in enumerate(dest_lines) if ln.strip() == MARKER_TABLE)
    except StopIteration:
        warnings.append(
            f"destination README has no `{MARKER_TABLE}` marker; overwrote it verbatim "
            "(any hand-maintained preamble was discarded -- add the marker to preserve it)"
        )
        return src_summary, warnings

    preamble = dest_lines[:marker_idx]
    dest_table = _split_table(dest_lines[marker_idx + 1 :])
    dest_rows = dest_table[2] if dest_table else []

    merged_rows = _merge_rows(src_rows, dest_rows)
    preamble = _regen_overall(preamble, merged_rows, warnings)

    out_lines = [*preamble, MARKER_TABLE, src_header, src_separator, *merged_rows]
    return "\n".join(out_lines).rstrip("\n") + "\n", warnings
