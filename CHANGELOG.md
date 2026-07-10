# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/) (`version` in `pyproject.toml` is
the source of truth — bump it by hand and tag the commit `vX.Y.Z`).

## [Unreleased]

### Added
- Per-mat raw-read diagnostics (`analysis/mat_reliability.py`), surfaced in the detailed report only: flags an antenna reading weakly (low signal strength) or being missed almost entirely relative to its immediate neighbors, a possible sign of a cabling/power problem worth a physical check.
- Running summary table (`reports/SUMMARY.md`)'s Date column now links each row to that race's sanitized report; documented the manual workflow for publishing sanitized reports/summary into the fsrc-tech wiki (`docs/race-services/reports/`).
- Sanitized per-race report (`reports/<race_date>.md`) now opens with a `title` front-matter block so its wiki nav entry shows the race date rather than a generic heading. Running summary retitled "Timing Summary", now lists most recent race first, drops the "No Chip" column (folded into the Notes cell only when nonzero), and truncates the Notes cell to keep mkdocs-material's table from wrapping long text into tall rows.

### Fixed
- `RaceReport.genuine_finish_miss_bibs()` now excludes confirmed drops (`known_drops`) from the "chips not read at finish" headline count and `pct_read_opportunities_missed()` — a confirmed drop (started, did not finish) was never going to have a finish read, so it isn't a chip-reading miss. Previously counted as a subset of "unrecovered finish misses"; now reported as a fully separate line/section. On the Indy 5000 this changed the headline from 4 to 3 finish misses (2.3% → 1.8% missed).

## [0.1.0] - 2026-07-09

Initial release. Parsers for Trident raw/filtered read logs, bib/chip
assignments, tmtility data export, barcode-scanner log, and RDS backup-time-
selected report. Start/finish classification against the RDS gun-time/gap-
factor theory, finish-to-bib-scan queue lag, and finish-line density
analysis. Per-race report builder and renderer (detailed + sanitized +
running summary), validated end-to-end against the Indy 5000 race.
