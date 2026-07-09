"""CLI: generate a race's detailed + sanitized reports and append it to the
running cross-race summary.

Usage:
    python -m chip_timing_analysis.report.generate \\
        <race_dir> <race_name> <race_date> <distance> <gun_time> [note ...]

Each trailing argument after gun_time is a free-text note about an unusual
occurrence at the race (e.g. equipment trouble that didn't affect results) --
included verbatim in the detailed report, the sanitized report, AND the
summary row, so keep these bib/name-free. For notes that need to name a
specific bib/individual, pass detail_notes= when calling generate()/
build_race_report() directly from Python -- those show up only in the
private detailed report.

Example:
    python -m chip_timing_analysis.report.generate \\
        "data/2026-07-04-indy-5000" "Indy 5000" "2026-07-04" "5K" "2026-07-04 08:30:02" \\
        "Brief live-network interruption ~09:05-09:07; did not affect final results, all recovered via backup timing."

Writes:
    <race_dir>/report.md    -- detailed, bib-level (gitignored with the rest of data/)
    reports/<race_date>.md  -- sanitized, aggregate-only, no race name anywhere
                                (not in the filename either -- it's going into git/GitHub)
    reports/SUMMARY.md      -- one row appended for this race
"""

from __future__ import annotations

import sys
from pathlib import Path

from chip_timing_analysis.report.build import build_race_report
from chip_timing_analysis.report.render import render_detailed_report, render_sanitized_report, append_summary_row


def generate(
    race_dir: str,
    race_name: str,
    race_date: str,
    distance: str,
    gun_time: str,
    notes: list[str] | None = None,
    detail_notes: list[str] | None = None,
    reports_dir: str = "reports",
    n_registered: int | None = None,
    n_starters: int | None = None,
    n_finishers: int | None = None,
    known_drops: list[int] | None = None,
) -> None:
    race_dir_path = Path(race_dir)
    report = build_race_report(
        race_dir_path, race_name, race_date, distance, gun_time,
        notes=notes, detail_notes=detail_notes,
        n_registered=n_registered, n_starters=n_starters, n_finishers=n_finishers,
        known_drops=known_drops,
    )

    detailed_path = race_dir_path / "report.md"
    detailed_path.write_text(render_detailed_report(report), encoding="utf-8")
    print(f"wrote {detailed_path}")

    reports_dir_path = Path(reports_dir)
    reports_dir_path.mkdir(parents=True, exist_ok=True)
    # filename is date-only, not the race slug -- this file is git-tracked
    # (going into GitHub), and the race name shouldn't be discoverable just
    # from browsing the repo's file listing.
    sanitized_path = reports_dir_path / f"{race_date}.md"
    sanitized_path.write_text(render_sanitized_report(report), encoding="utf-8")
    print(f"wrote {sanitized_path}")

    summary_path = reports_dir_path / "SUMMARY.md"
    append_summary_row(report, summary_path)
    print(f"appended row to {summary_path}")


if __name__ == "__main__":
    generate(*sys.argv[1:6], notes=sys.argv[6:])
