import pytest

from persona_pipeline.mappings import (
    AGE_GEN, AGE_GEN_BOUNDS, COUNTRIES, OCCUPATION_GROUP, REGION, SEX,
    get_mappings,
)


@pytest.mark.parametrize("country", COUNTRIES)
def test_all_countries_share_minimum_axes(country):
    m = get_mappings(country)
    assert AGE_GEN in m.axes and SEX in m.axes and OCCUPATION_GROUP in m.axes
    assert m.locale and m.hf_split


@pytest.mark.parametrize("country", COUNTRIES)
def test_age_gen_label_count_matches_bounds(country):
    m = get_mappings(country)
    assert len(m.age_gen_keywords) == len(AGE_GEN_BOUNDS)


@pytest.mark.parametrize("country", COUNTRIES)
def test_region_axis_implies_source_col_and_keywords(country):
    m = get_mappings(country)
    if REGION in m.axes:
        assert m.region_source_col is not None
        assert m.region_keywords
    else:
        assert m.region_source_col is None


@pytest.mark.parametrize("country", COUNTRIES)
def test_sex_keyword_labels_match_archetype_output_labels(country):
    # regression: if sex_keywords labels diverge from archetype native sex values, matching scores 0.
    m = get_mappings(country)
    sex_labels = set(m.sex_keywords.keys())
    if m.sex_map:
        assert sex_labels == set(m.sex_map.values())
    assert sex_labels


@pytest.mark.parametrize("country", COUNTRIES)
def test_occupation_keywords_match_definitions_when_set(country):
    m = get_mappings(country)
    if m.occupation_group_definitions is not None:
        # NL-query keyword labels must be a subset of the group labels — anything else is dead code.
        assert set(m.occupation_keywords.keys()) <= set(m.occupation_group_definitions.keys())
