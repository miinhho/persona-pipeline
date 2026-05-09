import pytest

from persona_mcp_store.mappings import (
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
    assert len(m.age_gen_labels) == len(AGE_GEN_BOUNDS)


@pytest.mark.parametrize("country", COUNTRIES)
def test_region_axis_implies_source_col(country):
    m = get_mappings(country)
    if REGION in m.axes:
        assert m.region_source_col is not None
    else:
        assert m.region_source_col is None
