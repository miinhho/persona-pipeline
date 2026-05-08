import polars as pl

from persona_pipeline.mappings import get_mappings
from persona_pipeline.stages.match import match_archetypes, parse_query_to_axes


def test_korean_query_extracts_all_4_axes():
    axes = parse_query_to_axes("서울 30대 남자 교사", get_mappings("Korea"))
    assert axes == {"region": "수도권", "age_gen": "중장년", "sex": "남자", "occupation_group": "전문가"}


def test_english_query_extracts_axes_for_usa():
    axes = parse_query_to_axes("young software engineer in California", get_mappings("USA"))
    assert axes["region"] == "West"
    assert axes["age_gen"] == "young"
    assert axes["occupation_group"] == "Computer and Mathematical"


def test_partial_query_returns_none_for_unmatched_axes():
    axes = parse_query_to_axes("부산 사람", get_mappings("Korea"))
    assert axes["region"] == "영남권"
    assert axes["age_gen"] is None
    assert axes["sex"] is None


def test_brazil_and_france_sex_keywords_use_native_archetype_labels():
    # regression: previously sex_keywords used English Male/Female labels and didn't match native (Masculino/Homme).
    bra = get_mappings("Brazil")
    fra = get_mappings("France")
    assert "Masculino" in bra.sex_keywords
    assert "Homme" in fra.sex_keywords
    assert parse_query_to_axes("jovem homem", bra)["sex"] == "Masculino"
    assert parse_query_to_axes("jeune homme", fra)["sex"] == "Homme"


def _korea_archetypes():
    return pl.DataFrame([
        {"segment_id": "수도권|청년|남자|전문가", "size": 100, "share_pct": 10.0,
         "mean_age": 27.0, "top_occupation": "전문가", "top_region": "수도권",
         "top_hobbies": "독서", "archetype_text": "...", "country": "Korea",
         "region": "수도권", "age_gen": "청년", "sex": "남자", "occupation_group": "전문가"},
        {"segment_id": "영남권|노년|여자|단순노무", "size": 200, "share_pct": 20.0,
         "mean_age": 70.0, "top_occupation": "단순노무", "top_region": "영남권",
         "top_hobbies": "트로트", "archetype_text": "...", "country": "Korea",
         "region": "영남권", "age_gen": "노년", "sex": "여자", "occupation_group": "단순노무"},
    ])


def test_higher_score_wins_over_size():
    cards = _korea_archetypes()
    results = match_archetypes("서울 청년 남자 교사", cards, get_mappings("Korea"), top_k=1)
    assert results[0]["segment_id"] == "수도권|청년|남자|전문가"


def test_no_keyword_match_falls_back_to_size_descending():
    cards = _korea_archetypes()
    results = match_archetypes("xyz abc", cards, get_mappings("Korea"), top_k=2)
    assert results[0]["segment_id"] == "영남권|노년|여자|단순노무"
