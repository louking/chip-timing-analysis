# Data layout

```
data/
  logs/                              # shared, long-lived tmtility app logs -- NOT per-race
    barcode-scanner.log              # these are the connector service's own logs, span months;
    tm-reader.log                    # parsers narrow to a race's window via start/end params

  <date>-<race-slug>/                # one directory per race, e.g. 2026-07-04-indy-5000
    r_*.log, f_*.log, s_*.log        # raw Trident Time Machine exports, directly at race root
    tm-data.csv                      # tmtility data export -- structured input to RaceDay Scoring
    bib-chip.csv                     # bib<->chip/tag assignment list
    backup-time-selected.csv         # RDS "Backup Time Selected" Data Check report (optional)
    time-machine-used.csv            # RDS "Time Machine - Used" Data Check report (optional)
```

See `data/_example-race/` for the empty template layout, and `data/2026-07-04-indy-5000/` for a populated real example.

Race data itself is gitignored by default (see `.gitignore`) — only this README and the example template are tracked. `data/logs/` is likewise gitignored (it's under `/data/*`), even though it isn't itself a race directory.
