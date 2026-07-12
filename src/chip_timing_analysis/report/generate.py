"""CLI: generate a race's detailed + sanitized reports and append it to the
running cross-race summary.

Usage:
    python -m chip_timing_analysis.report.generate \\
        <race_dir> \\
        [--race-name NAME] [--race-date YYYY-MM-DD] [--distance 5K|10K|10M] \\
        [--gun-time "YYYY-MM-DD HH:MM:SS"] \\
        [--note TEXT ...] [--detail-note TEXT ...] \\
        [--n-registered N] [--n-starters N] [--n-finishers N] \\
        [--known-drop BIB ...] [--exclude-bib BIB ...] \\
        [--reports-dir DIR]

--race-name/--race-date/--distance/--gun-time are only required when race_dir
has no RDS full-database-export zip (see CLAUDE.md / parsers/rdgo_export.py)
-- when one is present, any left unset are derived from it (race_name from
the export's own race name, race_date from the gun time's date, distance
from each scored_event's Gap Factor, gun_time from its GUNTIME marker). Pass
any of them explicitly to override the derived value.

--note is a free-text note about an unusual occurrence at the race (e.g.
equipment trouble that didn't affect results) -- included verbatim in the
detailed report, the sanitized report, AND the summary row, so keep these
bib/name-free. Repeat --note for multiple. --detail-note can name specific
bibs/individuals and is shown ONLY in the private detailed report (repeat
for multiple).

--known-drop / --exclude-bib take a single bib number each and may be
repeated for multiple bibs. See RaceReport/build_race_report() docstrings
for the distinction: a known drop started but didn't finish (real DNF); an
excluded bib is removed from the participant universe entirely (e.g. a
chip cross-reference that was a data-entry error, never really issued).

Example (zip present -- race_name/race_date/distance/gun_time all derived):
    python -m chip_timing_analysis.report.generate "data/2026-05-25-panda-5k" \\
        --n-registered 300 --known-drop 267 --known-drop 303 --known-drop 333

Example (no zip -- CSV path, everything explicit):
    python -m chip_timing_analysis.report.generate \\
        "data/2026-07-04-indy-5000" \\
        --race-name "Indy 5000" --race-date "2026-07-04" --distance "5K" \\
        --gun-time "2026-07-04 08:30:02" \\
        --note "Brief live-network interruption ~09:05-09:07; did not affect final results, all recovered via backup timing." \\
        --n-registered 141 --n-starters 110 --n-finishers 109

Writes:
    <race_dir>/report.md    -- detailed, bib-level (gitignored with the rest of data/)
    reports/<race_date>.md  -- sanitized, aggregate-only, no race name anywhere
                                (not in the filename either -- it's going into git/GitHub)
    reports/SUMMARY.md      -- one row appended for this race
"""

from __future__ import annotations

import argparse
from pathlib import Path

from chip_timing_analysis.report.build import build_race_report
from chip_timing_analysis.report.render import render_detailed_report, render_sanitized_report, append_summary_row


def generate(
    race_dir: str,
    race_name: str | None = None,
    race_date: str | None = None,
    distance: str | None = None,
    gun_time: str | None = None,
    notes: list[str] | None = None,
    detail_notes: list[str] | None = None,
    reports_dir: str = "reports",
    n_registered: int | None = None,
    n_starters: int | None = None,
    n_finishers: int | None = None,
    known_drops: list[int] | None = None,
    exclude_bibs: list[int] | None = None,
) -> None:
    race_dir_path = Path(race_dir)
    report = build_race_report(
        race_dir_path, race_name, race_date, distance, gun_time,
        notes=notes, detail_notes=detail_notes,
        n_registered=n_registered, n_starters=n_starters, n_finishers=n_finishers,
        known_drops=known_drops, exclude_bibs=exclude_bibs,
    )

    detailed_path = race_dir_path / "report.md"
    detailed_path.write_text(render_detailed_report(report), encoding="utf-8")
    print(f"wrote {detailed_path}")

    reports_dir_path = Path(reports_dir)
    reports_dir_path.mkdir(parents=True, exist_ok=True)
    # filename is date-only, not the race slug -- this file is git-tracked
    # (going into GitHub), and the race name shouldn't be discoverable just
    # from browsing the repo's file listing. Uses report.race_date (the
    # resolved value) rather than the race_date argument, which may have
    # been None and derived from the RDS export inside build_race_report().
    sanitized_path = reports_dir_path / f"{report.race_date}.md"
    sanitized_path.write_text(render_sanitized_report(report), encoding="utf-8")
    print(f"wrote {sanitized_path}")

    summary_path = reports_dir_path / "SUMMARY.md"
    append_summary_row(report, summary_path)
    print(f"appended row to {summary_path}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a race's detailed + sanitized reports and append it to the running cross-race summary.",
    )
    parser.add_argument("race_dir")
    parser.add_argument(
        "--race-name", default=None,
        help="Required only when race_dir has no RDS export zip (otherwise derived from it).",
    )
    parser.add_argument(
        "--race-date", default=None,
        help="Required only when race_dir has no RDS export zip (otherwise derived from gun_time's date).",
    )
    parser.add_argument(
        "--distance", default=None,
        help="Required only when race_dir has no RDS export zip (otherwise derived from the export's Gap Factor).",
    )
    parser.add_argument(
        "--gun-time", default=None,
        help="Required only when race_dir has no RDS export zip.",
    )
    parser.add_argument(
        "--note", dest="notes", action="append", default=[],
        help="Bib/name-free note, shown in all three outputs. Repeatable.",
    )
    parser.add_argument(
        "--detail-note", dest="detail_notes", action="append", default=[],
        help="Note that may name bibs/individuals, shown only in the private detailed report. Repeatable.",
    )
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--n-registered", type=int, default=None)
    parser.add_argument("--n-starters", type=int, default=None)
    parser.add_argument("--n-finishers", type=int, default=None)
    parser.add_argument(
        "--known-drop", dest="known_drops", type=int, action="append", default=[],
        help="Bib confirmed as a legitimate DNF (started, didn't finish). Repeatable.",
    )
    parser.add_argument(
        "--exclude-bib", dest="exclude_bibs", type=int, action="append", default=[],
        help="Bib to remove from the participant universe entirely (e.g. data-entry error). Repeatable.",
    )
    args = parser.parse_args(argv)
    # Blank strings (e.g. an unfilled VS Code task input, which passes ""
    # rather than omitting the flag) mean "not provided" here, not a literal
    # empty value -- gun_time="" would fail pd.Timestamp(), and a blank note
    # would show up as an empty bullet in the reports. race_name/race_date/
    # distance similarly fall through to build_race_report()'s own
    # None-means-derive-from-the-RDS-export handling.
    for attr in ("race_name", "race_date", "distance", "gun_time"):
        if getattr(args, attr) == "":
            setattr(args, attr, None)
    args.notes = [n for n in args.notes if n.strip()]
    args.detail_notes = [n for n in args.detail_notes if n.strip()]
    return args


if __name__ == "__main__":
    args = _parse_args()
    generate(
        args.race_dir, args.race_name, args.race_date, args.distance,
        gun_time=args.gun_time,
        notes=args.notes,
        detail_notes=args.detail_notes,
        reports_dir=args.reports_dir,
        n_registered=args.n_registered,
        n_starters=args.n_starters,
        n_finishers=args.n_finishers,
        known_drops=args.known_drops,
        exclude_bibs=args.exclude_bibs,
    )
