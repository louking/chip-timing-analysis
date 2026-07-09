"""Markdown rendering for RaceReport: a detailed local report (bib-level
detail, stays out of git via data/<race>/ -- gitignored), a sanitized report
(aggregate-only, safe for fsrc-tech), and a row for the cross-race running
summary table.
"""

from __future__ import annotations

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


_MISSED_READ_CAVEAT = (
    "If missed reads cluster in time or on specific mats, that points to a systemic "
    "equipment issue (e.g. antenna positioning) rather than isolated incidents (e.g. a "
    "damaged or missing chip) -- worth checking the raw per-mat reads before concluding "
    "which it is."
)


def _reconcile_backup(report: RaceReport) -> dict:
    """Split finish misses into "recovered via backup" vs. "not covered by
    backup at all". The latter is further split using RaceReport.known_drops:
    a confirmed legitimate DNF (e.g. Indy bib 658 -- started, never finished,
    genuinely nothing to record) vs. a finish miss that's still unexplained
    and should be flagged as needing review. When we have RDS's own backup
    report, also split recovered cases into "no read at all" vs. "had a valid
    read that didn't reach live scoring" (network interruption).
    """
    finish_miss_bibs = report.finish_miss_bibs()
    known_drop_bibs = set(report.known_drops)

    if report.backup is None:
        unrecovered_bibs = sorted(finish_miss_bibs)
        base = {"available": False, "n_backup": None, "n_zero_read": len(finish_miss_bibs), "n_network": None, "network_bibs": []}
    else:
        backup_bibs = set(report.backup["bib"])
        network_bibs = sorted(backup_bibs - finish_miss_bibs)
        unrecovered_bibs = sorted(finish_miss_bibs - backup_bibs)
        base = {
            "available": True,
            "n_backup": len(backup_bibs),
            "n_zero_read": len(finish_miss_bibs & backup_bibs),
            "n_network": len(network_bibs),
            "network_bibs": network_bibs,
        }

    review_bibs = sorted(set(unrecovered_bibs) - known_drop_bibs)
    drop_bibs = sorted(set(unrecovered_bibs) & known_drop_bibs)
    return {
        **base,
        "n_unrecovered": len(unrecovered_bibs),
        "unrecovered_bibs": unrecovered_bibs,
        "n_review": len(review_bibs),
        "review_bibs": review_bibs,
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
    n_finish_miss = len(r.finish_miss_bibs())

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
        lines.append(f"- Of those {n_finish_miss} finish misses, {recon['n_unrecovered']} were NOT covered by backup timing at all:")
        if recon["n_drops"]:
            lines.append(f"  - {recon['n_drops']} confirmed as a drop (started, did not finish) -- expected, not a data issue{bibs('drop_bibs')}.")
        if recon["n_review"]:
            lines.append(f"  - **{recon['n_review']} remain unexplained** -- needs review{bibs('review_bibs')}.")

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
        f"_Race date: {r.race_date} | Distance: {r.distance} | Gun time: {r.gun_time}_",
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
        lines += ["", f"### Backup timing used ({len(r.backup)})"]
        lines.append("| bib | name | finish_time | reason |")
        lines.append("|---|---|---|---|")
        for _, row in r.backup.iterrows():
            reason = "no antenna read at finish" if row["bib"] in finish_miss_bibs else "read existed locally but didn't reach live scoring (network interruption)"
            # finish_time comes from tm-data.csv, not the backup report's own value --
            # the two are the same crossing, just recorded to different precision (tenths
            # vs. hundredths), which read as a data mismatch. tm-data.csv is the reliable,
            # always-available source; the backup report (when supplied) is only used here
            # to confirm which bibs used backup and to look up their name.
            tm_row = r.tm_data[r.tm_data["bib"] == row["bib"]]
            finish_time = _fmt_ts(tm_row["finish_time"].iloc[0]) if not tm_row.empty else _fmt_ts(row["finish_time"])
            lines.append(f"| {row['bib']} | {row['name']} | {finish_time} | {reason} |")
        if recon["n_unrecovered"]:
            lines += ["", f"### NOT covered by backup timing ({recon['n_unrecovered']}) -- no finish read and no backup entry either"]
            if recon["n_drops"]:
                lines.append(f"- Confirmed drops (started, did not finish): {', '.join(str(b) for b in recon['drop_bibs'])}")
            if recon["n_review"]:
                lines.append(f"- **Needs review** (unexplained): {', '.join(str(b) for b in recon['review_bibs'])}")

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


def render_summary_row(report: RaceReport) -> str:
    """A single markdown table row summarizing this race, for the running
    cross-race summary."""
    r = report
    n_finish_miss = len(r.finish_miss_bibs())
    peak_density = r.density_rolling["finishers_in_window"].max()
    peak_burst = r.density_rolling_burst["finishers_in_window"].max()
    notes_cell = "; ".join(r.notes) if r.notes else "—"

    return (
        f"| {r.race_date} | {r.distance} | {r.n_participants} | {len(r.no_chip_assigned)} | "
        f"{len(r.zero_reads)} | {len(r.missed_start_only)} | {n_finish_miss} | "
        f"{r.pct_read_opportunities_missed():.1f}% | {peak_density} | {peak_burst} | {notes_cell} |"
    )


_SUMMARY_HEADER = (
    "# Running Timing Summary\n\n"
    "One row per race analyzed. \"Chips Not Read at Finish\" = zero-reads + missed-finish-only "
    "bibs (our own computed count). \"% Missed\" = share of all chip read opportunities "
    "(start + finish) that went unread. \"Peak (60s)\" matches the finish-line-timing field's "
    "standard runners-per-minute convention; \"Peak (15s)\" is a shorter burst window that "
    "catches short clusters a 60s window can smooth over -- more typical of FSRC's small-field "
    "races. See the per-race sanitized report for the recovered-vs-unrecovered backup-timing "
    "breakdown.\n\n"
    "| Date | Distance | Participants | No Chip | Zero Reads | Missed Start | Chips Not Read at Finish | "
    "% Missed | Peak (60s) | Peak (15s) | Notes |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|\n"
)


def append_summary_row(report: RaceReport, summary_path: str | Path) -> None:
    """Append this race's row to the running cross-race summary table,
    creating the file (with header) if it doesn't exist yet."""
    summary_path = Path(summary_path)
    if not summary_path.exists():
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(_SUMMARY_HEADER, encoding="utf-8")

    with summary_path.open("a", encoding="utf-8") as f:
        f.write(render_summary_row(report) + "\n")
