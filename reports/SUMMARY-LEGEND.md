# Timing Summary — Column Legend

- **Zero Reads** — chip assigned, but no read at either start or finish (a subset of both Missed Start and Missed Finish below).
- **Missed Start** — Zero Reads + missed-start-only bibs (our own computed count). A runner whose chip was read crossing the start after the start window closed (a late start) is not counted.
- **Missed Finish** — Zero Reads + missed-finish-only bibs (our own computed count).
- **% Missed** — share of all chip read opportunities (start + finish) that went unread.
- **Start Peak (1s)** — most start crossings read within any one second, the load on the start mats at the busiest moment.
- **Finish Peak (60s)** — most finishers within any 60s window; matches the finish-line-timing field's standard runners-per-minute convention.
- **Finish Peak (15s)** — a shorter burst window that catches short clusters a 60s window can smooth over — more typical of FSRC's small-field races.
- **Finish Peak (5s)** — groups finishing together, for dense finishes.
- **Notes** — kept short here (full detail is on the linked per-race report); a no-chip-assigned count only appears here when a race actually had one (rare process problem, not a permanent column).
- **n/a** — the race was not chip timed (Time Machine only), so the chip read and start columns don't apply; Participants is the finisher count.

See the per-race sanitized report for the recovered-vs-unrecovered backup-timing breakdown.
