"""test_generate - test chip_timing_analysis.report.generate

Focuses on _parse_args' blank/whitespace-only-string handling -- a real
VS Code task gotcha (CLAUDE.md): an optional input whose value ends up as ""
or a lone space must be treated as "not provided", not a literal value (a
literal " " passed to pd.Timestamp() for --gun-time would raise).
"""

from chip_timing_analysis.report.generate import _parse_args


def test_required_race_dir_is_parsed():
    args = _parse_args(["data/2026-05-25-panda-5k"])

    assert args.race_dir == "data/2026-05-25-panda-5k"


def test_optional_fields_default_to_none():
    args = _parse_args(["race_dir"])

    assert args.race_name is None
    assert args.race_date is None
    assert args.distance is None
    assert args.gun_time is None


def test_explicit_value_is_kept():
    args = _parse_args(["race_dir", "--race-name", "Indy 5000"])

    assert args.race_name == "Indy 5000"


def test_blank_string_value_becomes_none():
    args = _parse_args(["race_dir", "--race-name", ""])

    assert args.race_name is None


def test_whitespace_only_value_becomes_none():
    # a VS Code promptString default of " " (not "", to dodge the
    # cancelled-prompt gotcha) must still resolve to "not provided"
    args = _parse_args(["race_dir", "--gun-time", " "])

    assert args.gun_time is None


def test_all_four_optional_string_fields_get_blank_handling():
    args = _parse_args([
        "race_dir",
        "--race-name", " ", "--race-date", " ", "--distance", " ", "--gun-time", " ",
    ])

    assert args.race_name is None
    assert args.race_date is None
    assert args.distance is None
    assert args.gun_time is None


def test_blank_notes_are_dropped_not_kept_as_empty_bullets():
    args = _parse_args(["race_dir", "--note", "  ", "--note", "real note"])

    assert args.notes == ["real note"]


def test_blank_detail_notes_are_dropped():
    args = _parse_args(["race_dir", "--detail-note", " ", "--detail-note", "bib 641 detail"])

    assert args.detail_notes == ["bib 641 detail"]


def test_notes_default_to_empty_list():
    args = _parse_args(["race_dir"])

    assert args.notes == []
    assert args.detail_notes == []


def test_known_drop_and_exclude_bib_are_repeatable_ints():
    args = _parse_args(["race_dir", "--known-drop", "267", "--known-drop", "303", "--exclude-bib", "375"])

    assert args.known_drops == [267, 303]
    assert args.exclude_bibs == [375]


def test_n_registered_starters_finishers_parse_as_ints():
    args = _parse_args(["race_dir", "--n-registered", "141", "--n-starters", "110", "--n-finishers", "109"])

    assert args.n_registered == 141
    assert args.n_starters == 110
    assert args.n_finishers == 109


def test_reports_dir_defaults_to_reports():
    args = _parse_args(["race_dir"])

    assert args.reports_dir == "reports"
