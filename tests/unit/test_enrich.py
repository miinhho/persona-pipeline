import polars as pl

from persona_mcp_store.mappings import get_mappings
from persona_mcp_store.stages.enrich import enrich

KOREA = get_mappings("Korea")
PERSONA_TEXT_COLS = list(KOREA.persona_columns.keys())  # 7 fields for Korea


def _korea_synthetic_raw() -> pl.LazyFrame:
    rows = [
        {"uuid": "a", "age": 30, "sex": "남자", "province": "서울",
         "occupation": "초등학교 교사", "hobbies_and_interests_list": "['독서']",
         **{c: f"{c} 텍스트" for c in PERSONA_TEXT_COLS}},
        {"uuid": "b", "age": 70, "sex": "여자", "province": "제주",
         "occupation": "농업 종사원", "hobbies_and_interests_list": "['산책', '명상']",
         **{c: f"{c} 텍스트" for c in PERSONA_TEXT_COLS}},
    ]
    return pl.LazyFrame(rows)


def test_enrich_output_contains_country_axes_and_raw_text():
    df = enrich(_korea_synthetic_raw(), KOREA).collect()
    expected = {
        "country", "uuid", "age", "sex", "province", "occupation", "hobbies",
        "region", "age_gen",
        *PERSONA_TEXT_COLS,
    }
    assert expected.issubset(set(df.columns))
    assert df["country"].unique().to_list() == ["Korea"]


def test_enrich_does_not_emit_legacy_columns():
    df = enrich(_korea_synthetic_raw(), KOREA).collect()
    for legacy in ("segment_key", "segment_id", "occupation_group"):
        assert legacy not in df.columns


def test_enrich_axes_resolved_correctly():
    df = enrich(_korea_synthetic_raw(), KOREA).collect()
    by_uuid = {r["uuid"]: r for r in df.iter_rows(named=True)}
    assert by_uuid["a"]["region"] == "수도권"
    assert by_uuid["a"]["age_gen"] == "청년"
    assert by_uuid["b"]["region"] == "제주권"
    assert by_uuid["b"]["age_gen"] == "노년"


def test_enrich_preserves_raw_occupation_text():
    df = enrich(_korea_synthetic_raw(), KOREA).collect()
    by_uuid = {r["uuid"]: r for r in df.iter_rows(named=True)}
    assert by_uuid["a"]["occupation"] == "초등학교 교사"
    assert by_uuid["b"]["occupation"] == "농업 종사원"


def test_enrich_hobbies_parsed_to_list():
    df = enrich(_korea_synthetic_raw(), KOREA).collect()
    assert df.schema["hobbies"] == pl.List(pl.Utf8)
    assert df.filter(pl.col("uuid") == "a")["hobbies"].to_list()[0] == ["독서"]
    assert df.filter(pl.col("uuid") == "b")["hobbies"].to_list()[0] == ["산책", "명상"]


def test_enrich_sorted_by_axes():
    df = enrich(_korea_synthetic_raw(), KOREA).collect()
    sorted_df = df.sort(KOREA.axes)
    assert df["uuid"].to_list() == sorted_df["uuid"].to_list()


def test_enrich_singapore_has_no_region_axis():
    sg = get_mappings("Singapore")
    sg_persona_cols = list(sg.persona_columns.keys())
    rows = [
        {"uuid": "sg-1", "age": 35, "sex": "Male", "occupation": "Professional",
         **{c: f"{c}-text" for c in sg_persona_cols}},
        {"uuid": "sg-2", "age": 70, "sex": "Female", "occupation": "Retired",
         **{c: f"{c}-text" for c in sg_persona_cols}},
    ]
    df = enrich(pl.LazyFrame(rows), sg).collect()

    assert df["country"].unique().to_list() == ["Singapore"]
    assert "region" not in df.columns
    assert set(sg.axes) == {"age_gen", "sex"}
    # Raw occupation text preserved
    by_uuid = {r["uuid"]: r["occupation"] for r in df.iter_rows(named=True)}
    assert by_uuid["sg-1"] == "Professional"
    assert by_uuid["sg-2"] == "Retired"
