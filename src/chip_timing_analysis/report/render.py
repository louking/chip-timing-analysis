"""Markdown rendering for RaceReport: a detailed local report (bib-level
detail, stays out of git via data/<race>/ -- gitignored), a sanitized report
(aggregate-only, safe for fsrc-tech), and a row for the cross-race running
summary table.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from chip_timing_analysis.analysis.queue_lag import lag_histogram
from chip_timing_analysis.report.build import RaceReport

def _fmt_ts(ts) -> str:
    """Format a timestamp to hundredths precision (matches the source data's
    real precision -- pandas' default str() shows meaningless microsecond
    zeros, e.g. "08:49:19.300000" instead of "08:49:19.30")."""
    if pd.isna(ts):
        return ""
    return ts.strftime("%Y-%m-%d %H:%M:%S") + f".{ts.microsecond // 10000:02d}"


def _fmt_time(ts) -> str:
    """Time-of-day only, hundredths precision -- like _fmt_ts but without the
    date, for display alongside a race date already shown separately (e.g.
    gun time in the Overview line)."""
    if pd.isna(ts):
        return ""
    return ts.strftime("%H:%M:%S") + f".{ts.microsecond // 10000:02d}"


_MISSED_READ_CAVEAT = (
    "If missed reads cluster in time or on specific mats, that points to a systemic "
    "equipment issue (e.g. antenna positioning) rather than isolated incidents (e.g. a "
    "damaged or missing chip) -- worth checking the raw per-mat reads before concluding "
    "which it is."
)


def _reconcile_backup(report: RaceReport) -> dict:
    """Split the *genuine* finish misses (excludes confirmed drops -- see
    RaceReport.genuine_finish_miss_bibs) into "recovered via backup" vs.
    "not covered by backup at all, still unexplained". Confirmed drops are
    reported as their own separate bucket, not nested inside either of these
    -- a drop was never going to have a finish read in the first place, so
    it isn't a finish miss that needs recovering or reviewing (caught once
    already: an earlier version counted drops as a subset of "unrecovered
    finish misses", which inflated the headline miss count/percentage with
    something that isn't actually a miss). When we have RDS's own backup
    report, also split recovered cases into "no read at all" vs. "had a
    valid read that didn't reach live scoring" (network interruption).
    """
    miss_bibs = report.genuine_finish_miss_bibs()
    drop_bibs = sorted(set(report.known_drops) & report.finish_miss_bibs())

    if report.backup is None:
        unrecovered_bibs = sorted(miss_bibs)
        base = {"available": False, "n_backup": None, "n_zero_read": len(miss_bibs), "n_network": None, "network_bibs": []}
    else:
        backup_bibs = set(report.backup["bib"])
        # A backup-used bib that isn't a finish miss usually means "chip read
        # existed locally but didn't reach live scoring" (network interruption)
        # -- but a bib with no chip assigned at all is *also* backup-used and
        # *also* absent from finish_miss_bibs (it was never eligible to be
        # counted as a chip-read miss), for an entirely different, already
        # -reported reason. Exclude those so they aren't double-counted here
        # under the wrong explanation.
        no_chip_bibs = set(report.no_chip_assigned["bib"])
        network_bibs = sorted(backup_bibs - report.finish_miss_bibs() - no_chip_bibs)
        unrecovered_bibs = sorted(miss_bibs - backup_bibs)
        base = {
            "available": True,
            "n_backup": len(backup_bibs),
            "n_zero_read": len(miss_bibs & backup_bibs),
            "n_network": len(network_bibs),
            "network_bibs": network_bibs,
        }

    return {
        **base,
        "n_unrecovered": len(unrecovered_bibs),
        "unrecovered_bibs": unrecovered_bibs,
        "n_drops": len(drop_bibs),
        "drop_bibs": drop_bibs,
    }


def _render_notes(notes: list[str]) -> list[str]:
    if not notes:
        return []
    lines = ["", "## Notable Occurrences"]
    for note in notes:
        lines.append(f"- {note}")
    return lines


def _render_read_reliability(report: RaceReport, include_bibs: bool) -> list[str]:
    """Shared structure for the Read Reliability section -- used by both the
    detailed and sanitized reports so their grouping/wording can't drift
    apart (a bug: the sanitized report once indented the drop/review counts
    under the network-interruption line, implying they were a subset of it,
    when they're actually about a disjoint group -- the "not covered by
    backup at all" bucket). include_bibs=True appends bib numbers to each
    line (detailed report only).
    """
    r = report
    recon = _reconcile_backup(r)
    n_finish_miss = len(r.genuine_finish_miss_bibs())  # excludes confirmed drops -- see known_drops

    def bibs(key: str) -> str:
        return f" ({', '.join(str(b) for b in recon[key])})" if include_bibs and recon[key] else ""

    lines = [
        f"- {n_finish_miss} of {r.n_participants} chips were not read at the finish "
        f"({n_finish_miss / r.n_participants * 100:.1f}%).",
        f"- {r.pct_read_opportunities_missed():.1f}% of all chip read opportunities (start + finish combined) were missed.",
    ]
    if len(r.no_chip_assigned):
        lines.append(f"- {len(r.no_chip_assigned)} participant(s) had no chip assigned; timed via the backup timer.")
    if len(r.zero_reads):
        lines.append(f"- {len(r.zero_reads)} participant(s) had a chip assigned but no reads recorded at all (possible non-functioning chip).")

    if recon["available"]:
        lines.append(f"- Of those {n_finish_miss} finish misses, {recon['n_zero_read']} were recovered via backup timing and scored correctly.")
        if recon["n_network"]:
            lines.append(
                f"- Separately, {recon['n_network']} participant(s) had a valid chip read that didn't reach live "
                f"scoring (brief network interruption) but were recovered from backup timing / the local device "
                f"log{bibs('network_bibs')}."
            )
    else:
        lines.append("- Backup-timing coverage not available for this race (no Data Check report provided).")

    if recon["n_unrecovered"]:
        lines.append(f"- **{recon['n_unrecovered']} of those {n_finish_miss} finish misses remain unexplained** -- not covered by backup timing, needs review{bibs('unrecovered_bibs')}.")

    if recon["n_drops"]:
        lines.append(
            f"- Separately, {recon['n_drops']} confirmed drop(s) (started, did not finish) had no finish read, "
            f"as expected -- not counted as a finish miss{bibs('drop_bibs')}."
        )

    lines.append(f"- {len(r.missed_start_only)} result(s) had no chip read at the start line.")
    return lines


def _render_finish_density(report: RaceReport, verbose: bool) -> list[str]:
    """Shared Finish-Line Density content -- like _render_read_reliability,
    kept in one place so detailed/sanitized can't drift apart. Reports both
    the standard 60s window (matches RRTC's runners-per-minute convention)
    and the shorter 15s burst window (catches short clusters -- more typical
    of FSRC's small-field races -- that a 60s window can smooth over)."""
    r = report
    span_sec = (r.classified["finish_time"].max() - r.classified["finish_time"].min()).total_seconds()
    n_finishes = r.classified["finish_time"].notna().sum()
    lines = [f"- Average {n_finishes / span_sec * 60:.2f} finishers/min over the finish window."]
    if verbose:
        lines.append(
            f"- Gap between consecutive finishers (sec): median {r.finish_gap_sec.median():.2f}, "
            f"min {r.finish_gap_sec.min():.2f}, max {r.finish_gap_sec.max():.2f}"
        )
    peak_std = r.density_rolling.loc[r.density_rolling["finishers_in_window"].idxmax()]
    peak_burst = r.density_rolling_burst.loc[r.density_rolling_burst["finishers_in_window"].idxmax()]
    ending = (lambda p: f", ending near {_fmt_ts(p['finish_time'])}") if verbose else (lambda p: "")
    lines.append(f"- Peak density: {peak_std['finishers_in_window']} finishers in a 60s window{ending(peak_std)}.")
    lines.append(f"- Peak burst: {peak_burst['finishers_in_window']} finishers in a 15s window{ending(peak_burst)}.")
    return lines


def _render_mat_diagnostics(report: RaceReport) -> list[str]:
    """Per-mat raw-read diagnostics (see mat_reliability.py) -- detailed
    report only, never sanitized (mat-level equipment detail isn't
    client-facing). De-emphasized to a single reassuring line unless
    mat_reliability_verdict flags a systemic_signal, per Lou's call: this is
    a "worth checking" caveat, not a headline metric.
    """
    v = report.mat_reliability_verdict
    if v is None or v["n_mats"] == 0:
        return []

    lines = ["", "## Raw Read / Antenna Diagnostics"]
    if not v["systemic_signal"]:
        lines.append(
            f"- No antenna anomalies detected: read coverage and signal strength across all {v['n_mats']} mats "
            f"were consistent with each mat's immediate neighbors (some tapering from the middle of the mat "
            f"run toward the edges is normal and not flagged)."
        )
    else:
        lines.append(
            f"- **Possible cabling/power issue**: mat(s) {', '.join(str(m) for m in v['weak_mats'])} read well "
            f"below their immediate neighbors (in tag coverage and/or signal strength) -- worth a physical "
            f"check of that mat/antenna/cable before the next race."
        )
        lines += ["", "Per-mat raw read summary:", "| mat_id | n_reads | unique_tags | reads_per_tag | mean signal | |", "|---|---|---|---|---|---|"]
        for _, row in report.mat_summary.iterrows():
            flag = "**weak**" if row["mat_id"] in v["weak_mats"] else ""
            signal = f"{row['mean_signal_strength']:.1f}" if pd.notna(row["mean_signal_strength"]) else ""
            lines.append(f"| {row['mat_id']} | {row['n_reads']} | {row['n_unique_tags']} | {row['reads_per_tag']:.1f} | {signal} | {flag} |")
    return lines


def _render_field_counts(report: RaceReport) -> list[str]:
    r = report
    lines = [f"- Participants (confirmed by data): {r.n_participants}"]
    if r.n_registered is not None:
        lines.append(f"- Registered: {r.n_registered}")
    if r.n_starters is not None:
        lines.append(f"- Starters: {r.n_starters}")
    if r.n_finishers is not None:
        lines.append(f"- Finishers: {r.n_finishers}")
    return lines


def render_detailed_report(report: RaceReport) -> str:
    r = report
    lines = [
        f"# {r.race_name} — Detailed Timing Report",
        f"_Race date: {r.race_date} | Distance: {r.distance} | Gun time: {_fmt_time(r.gun_time)}_",
        "",
        "## Overview",
        f"- Bib/chip assignments printed: {r.n_bib_chip_entries}",
    ]
    lines += _render_field_counts(r)
    lines.append(f"- Chip-computed finishes: {r.classified['finish_time'].notna().sum()}")
    lines += _render_notes(r.notes + r.detail_notes)

    lines += ["", "## Missed Reads", _MISSED_READ_CAVEAT, ""]
    lines += _render_read_reliability(r, include_bibs=True)
    lines += ["", f"### No chip assigned ({len(r.no_chip_assigned)})"]
    if r.no_chip_assigned.empty:
        lines.append("None.")
    else:
        lines.append("| bib | finish_time |")
        lines.append("|---|---|")
        for _, row in r.no_chip_assigned.iterrows():
            lines.append(f"| {row['bib']} | {_fmt_ts(row['finish_time'])} |")

    lines += ["", f"### Zero reads at all ({len(r.zero_reads)}) -- chip assigned but no start or finish read"]
    if r.zero_reads.empty:
        lines.append("None.")
    else:
        lines.append("| bib |")
        lines.append("|---|")
        for _, row in r.zero_reads.iterrows():
            lines.append(f"| {row['bib']} |")

    lines += ["", f"### Missed start only ({len(r.missed_start_only)}) -- has a finish read, no start read"]
    if r.missed_start_only.empty:
        lines.append("None.")
    else:
        lines.append("| bib | finish_time |")
        lines.append("|---|---|")
        for _, row in r.missed_start_only.iterrows():
            lines.append(f"| {row['bib']} | {_fmt_ts(row['finish_time'])} |")

    lines += ["", f"### Missed finish only ({len(r.missed_finish_only)}) -- has a start read, no finish read"]
    if r.missed_finish_only.empty:
        lines.append("None.")
    else:
        lines.append("| bib | start_time |")
        lines.append("|---|---|")
        for _, row in r.missed_finish_only.iterrows():
            lines.append(f"| {row['bib']} | {_fmt_ts(row['start_time'])} |")

    recon = _reconcile_backup(r)
    if r.backup is not None:
        finish_miss_bibs = r.finish_miss_bibs()
        no_chip_bibs = set(r.no_chip_assigned["bib"])
        lines += ["", f"### Backup timing used ({len(r.backup)})"]
        lines.append("| bib | name | finish_time | reason |")
        lines.append("|---|---|---|---|")
        for _, row in r.backup.iterrows():
            if row["bib"] in finish_miss_bibs:
                reason = "no antenna read at finish"
            elif row["bib"] in no_chip_bibs:
                reason = "no chip assigned"
            else:
                reason = "read existed locally but didn't reach live scoring (network interruption)"
            # finish_time comes from tm-data.csv, not the backup report's own value --
            # the two are the same crossing, just recorded to different precision (tenths
            # vs. hundredths), which read as a data mismatch. tm-data.csv is the reliable,
            # always-available source; the backup report (when supplied) is only used here
            # to confirm which bibs used backup and to look up their name.
            tm_row = r.tm_data[r.tm_data["bib"] == row["bib"]]
            finish_time = _fmt_ts(tm_row["finish_time"].iloc[0]) if not tm_row.empty else _fmt_ts(row["finish_time"])
            lines.append(f"| {row['bib']} | {row['name']} | {finish_time} | {reason} |")

    # Drop reporting doesn't depend on r.backup being supplied -- known_drops
    # is Lou's own manual confirmation, not derived from the backup report
    # (a drop typically has no backup entry either, since there was nothing
    # to recover).
    if recon["n_unrecovered"]:
        lines += ["", f"### Finish misses NOT covered by backup timing ({recon['n_unrecovered']}) -- unexplained, needs review"]
        lines.append(", ".join(str(b) for b in recon["unrecovered_bibs"]))
    if recon["n_drops"]:
        lines += ["", f"### Confirmed drops ({recon['n_drops']}) -- started, did not finish (not counted as a finish miss)"]
        lines.append(", ".join(str(b) for b in recon["drop_bibs"]))

    lines += _render_mat_diagnostics(r)

    lines += ["", "## Finish-to-Bib-Scan Queue Lag"]
    if r.lag is None:
        lines.append("No barcode-scanner.log available for this race.")
    else:
        matched = r.lag.dropna(subset=["scan_time"])
        lines += [
            f"- Finishers with a matched scan: {len(matched)} of {len(r.lag)}",
            f"- Raw lag (sec): median {matched['lag_sec'].median():.2f}, "
            f"90th pct {matched['lag_sec'].quantile(0.90):.2f}, "
            f"range {matched['lag_sec'].min():.2f}-{matched['lag_sec'].max():.2f}",
            f"- Excess lag over baseline (sec): median {matched['excess_lag_sec'].median():.2f}, "
            f"90th pct {matched['excess_lag_sec'].quantile(0.90):.2f}",
        ]
        corr = matched["excess_lag_sec"].corr(matched["finishers_in_prior_window"])
        verdict = "no evidence of a sustained queue" if abs(corr) < 0.2 else "excess lag tracks finisher density -- a queue likely formed"
        lines.append(f"- Excess lag vs. local finisher density correlation: {corr:.3f} ({verdict})")
        lines += ["", "Excess lag histogram (5s bins):"]
        lines.append("```")
        lines.append(lag_histogram(matched, "excess_lag_sec").to_string())
        lines.append("```")

    lines += ["", "## Finish-Line Density"]
    lines += _render_finish_density(r, verbose=True)

    return "\n".join(lines) + "\n"


def render_sanitized_report(report: RaceReport) -> str:
    r = report
    lines = [
        # YAML front matter: sets the page's nav/browser-tab title to the race
        # date rather than the generic "Race Timing Summary" H1 below -- with
        # many races published over time, the date is what distinguishes one
        # from another in a nav list (MkDocs reads `title` from front matter
        # in preference to the first heading; see CLAUDE.md).
        "---",
        f"title: {r.race_date}",
        "---",
        "",
        "# Race Timing Summary",
        f"_Race date: {r.race_date} | Distance: {r.distance}_",
        "",
        "## Overview",
    ]
    lines += _render_field_counts(r)
    lines += _render_notes(r.notes)

    lines += ["", "## Read Reliability"]
    lines += _render_read_reliability(r, include_bibs=False)

    lines += ["", "## Finish-Line Density"]
    lines += _render_finish_density(r, verbose=False)

    return "\n".join(lines) + "\n"


_NOTES_CELL_MAX_LEN = 60


def _summary_notes_cell(report: RaceReport) -> str:
    """Notes cell for the summary table -- short by design (the mkdocs table
    render blows up vertically if this column has to wrap long free text;
    the full sentence is still available on the linked per-race page). Also
    folds in a no-chip-assigned count when nonzero: this stems from a rare
    check-in/print-run process problem, not a chip-timing metric, so it
    doesn't warrant its own permanent column -- surfacing it in Notes only
    when it actually happens is enough."""
    r = report
    notes = list(r.notes)
    if len(r.no_chip_assigned):
        notes = [f"{len(r.no_chip_assigned)} no chip assigned"] + notes
    if not notes:
        return "—"
    text = "; ".join(notes)
    if len(text) > _NOTES_CELL_MAX_LEN:
        text = text[: _NOTES_CELL_MAX_LEN].rstrip() + "…"
    return text


def render_summary_row(report: RaceReport) -> str:
    """A single markdown table row summarizing this race, for the running
    cross-race summary. The Date cell links to that race's sanitized report
    (`<race_date>.md`) -- relies on the summary file and the per-race
    sanitized reports living side by side in the same directory (true both
    of this repo's reports/ and its copy under fsrc-tech's
    docs/race-services/reports/, see CLAUDE.md)."""
    r = report
    n_finish_miss = len(r.genuine_finish_miss_bibs())  # excludes confirmed drops -- see known_drops
    peak_density = r.density_rolling["finishers_in_window"].max()
    peak_burst = r.density_rolling_burst["finishers_in_window"].max()

    return (
        f"| [{r.race_date}]({r.race_date}.md) | {r.distance} | {r.n_participants} | "
        f"{len(r.zero_reads)} | {len(r.missed_start_only)} | {n_finish_miss} | "
        f"{r.pct_read_opportunities_missed():.1f}% | {peak_density} | {peak_burst} | {_summary_notes_cell(r)} |"
    )


_SUMMARY_LEGEND_FILENAME = "SUMMARY-LEGEND.md"

_SUMMARY_HEADER = (
    "# Timing Summary\n\n"
    f"One row per race analyzed, most recent first. See the [column legend]({_SUMMARY_LEGEND_FILENAME}) "
    "for what each column means.\n\n"
    "| Date | Distance | Participants | Zero Reads | Missed Start | Chips Not Read at Finish | "
    "% Missed | Peak (60s) | Peak (15s) | Notes |\n"
    "|---|---|---|---|---|---|---|---|---|---|\n"
)


def render_summary_legend() -> str:
    """The explanatory text formerly embedded as one dense paragraph atop
    SUMMARY.md -- moved to its own linked page (per Lou's call) so the
    summary table itself isn't preceded by a wall of text. Written alongside
    SUMMARY.md by append_summary_row() so it's always present and in sync,
    even though its content doesn't depend on any particular race."""
    return (
        "# Timing Summary — Column Legend\n\n"
        "- **Chips Not Read at Finish** — zero-reads + missed-finish-only bibs "
        "(our own computed count).\n"
        "- **% Missed** — share of all chip read opportunities (start + finish) "
        "that went unread.\n"
        "- **Peak (60s)** — matches the finish-line-timing field's standard "
        "runners-per-minute convention.\n"
        "- **Peak (15s)** — a shorter burst window that catches short clusters "
        "a 60s window can smooth over — more typical of FSRC's small-field races.\n"
        "- **Notes** — kept short here (full detail is on the linked per-race "
        "report); a no-chip-assigned count only appears here when a race "
        "actually had one (rare process problem, not a permanent column).\n\n"
        "See the per-race sanitized report for the recovered-vs-unrecovered "
        "backup-timing breakdown.\n"
    )


_SUMMARY_DATE_RE = re.compile(r"^\| \[(\d{4}-\d{2}-\d{2})\]")


def append_summary_row(report: RaceReport, summary_path: str | Path) -> None:
    """Insert this race's row into the running cross-race summary table,
    sorted by race date descending (most recent race first, so newer races
    don't get buried as the table grows) -- NOT insertion order, which
    silently goes wrong the moment a race is (re-)generated out of
    chronological order (e.g. re-running an earlier race's report after a
    later one has already been added). Re-generating the same race replaces
    its existing row in place rather than appending a duplicate. Creates the
    file (with header) if it doesn't exist yet. Also (re)writes the linked
    column-legend file alongside it (see render_summary_legend()) so it's
    always present and in sync, even on a re-run that doesn't otherwise
    touch SUMMARY.md's header."""
    summary_path = Path(summary_path)
    row = render_summary_row(report) + "\n"

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    (summary_path.parent / _SUMMARY_LEGEND_FILENAME).write_text(render_summary_legend(), encoding="utf-8")

    if not summary_path.exists():
        summary_path.write_text(_SUMMARY_HEADER + row, encoding="utf-8")
        return

    lines = summary_path.read_text(encoding="utf-8").splitlines(keepends=True)
    separator_idx = next(i for i, line in enumerate(lines) if line.startswith("|---"))
    header_lines = lines[: separator_idx + 1]
    existing_rows = [
        line for line in lines[separator_idx + 1 :]
        if _SUMMARY_DATE_RE.match(line) and _SUMMARY_DATE_RE.match(line).group(1) != report.race_date
    ]
    all_rows = existing_rows + [row]
    all_rows.sort(key=lambda line: _SUMMARY_DATE_RE.match(line).group(1), reverse=True)
    summary_path.write_text("".join(header_lines + all_rows), encoding="utf-8")
