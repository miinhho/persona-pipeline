import polars as pl

from persona_pipeline.mappings import SEGMENT_KEY, SEGMENT_SEP, get_mappings
from persona_pipeline.stages.enrich import enrich


def _korea_row(**overrides):
    base = {
        "uuid": "u1", "age": 35, "sex": "남자", "province": "서울",
        "occupation": "초등학교 교사", "education_level": "대학교(4년제)",
        "professional_persona": "직업 텍스트 " * 50,
    }
    base.update(overrides)
    return base


def _enrich(country, rows, lookup=None):
    """Tests don't care about classifier quality — auto-build a lookup that maps every
    raw occupation to the first defined group, unless the test explicitly passes its own."""
    mapping = get_mappings(country)
    if mapping.occupation_group_definitions is not None and lookup is None:
        first_group = next(iter(mapping.occupation_group_definitions))
        occs = sorted({r.get("occupation", "") for r in rows if r.get("occupation")})
        lookup = pl.LazyFrame({
            "occupation": occs,
            "occupation_group": [first_group] * len(occs),
        })
    return enrich(pl.LazyFrame(rows), mapping, occupation_lookup=lookup).collect()


def test_text_columns_not_carried_through_to_cache():
    out = _enrich("Korea", [_korea_row()])
    assert set(out.columns) == {"uuid", "age", "region", "age_gen", "sex", "occupation_group", SEGMENT_KEY}


def test_segment_key_axes_order_matches_mapping():
    out = _enrich("Korea", [_korea_row()])
    mapping = get_mappings("Korea")
    parts = out[SEGMENT_KEY][0].split(SEGMENT_SEP)
    assert len(parts) == len(mapping.axes)
    for axis, part in zip(mapping.axes, parts):
        assert out[axis][0] == part


def test_age_gen_transitions_at_34_to_35_and_64_to_65():
    boundary_ages = [34, 35, 64, 65]
    for country, sex_val, region_kw, occ in [
        ("Korea", "남자", ("province", "서울"), "교사"),
        ("Japan", "男", ("region", "関東地方"), "教師"),
    ]:
        rows = [{"uuid": f"u{a}", "age": a, "sex": sex_val, region_kw[0]: region_kw[1], "occupation": occ}
                for a in boundary_ages]
        groups = _enrich(country, rows)["age_gen"].to_list()
        assert groups[0] != groups[1], country
        assert groups[2] != groups[3], country


def test_unmapped_region_falls_back_to_other():
    out = _enrich("Korea", [_korea_row(province="북한")])
    assert out["region"][0] == "Other"


def test_occupation_not_in_lookup_falls_back_to_other():
    # Empty lookup → enrich's left-join produces null → fill_null("Other").
    empty_lookup = pl.LazyFrame({"occupation": ["다른 직업"], "occupation_group": ["전문가"]})
    out = _enrich("Korea", [_korea_row(occupation="외계인 통역사")], lookup=empty_lookup)
    assert out["occupation_group"][0] == "Other"


def test_singapore_3_axes_drops_region_from_output():
    out = _enrich("Singapore", [{"uuid": "u1", "age": 40, "sex": "Male", "occupation": "Professional"}])
    assert "region" not in out.columns
    assert len(out[SEGMENT_KEY][0].split(SEGMENT_SEP)) == 3


def test_japan_sex_passes_through_native_label():
    out = _enrich("Japan", [
        {"uuid": "u1", "age": 30, "sex": "男", "region": "関東地方", "occupation": "教師"},
        {"uuid": "u2", "age": 30, "sex": "女", "region": "関東地方", "occupation": "教師"},
    ])
    assert out["sex"].to_list() == ["男", "女"]


def test_row_count_preserved():
    rows = [
        {"uuid": f"u{i}", "age": 20 + i, "sex": "남자", "province": "서울", "occupation": "교사"}
        for i in range(50)
    ]
    out = _enrich("Korea", rows)
    assert len(out) == 50
    assert out["uuid"].n_unique() == 50
