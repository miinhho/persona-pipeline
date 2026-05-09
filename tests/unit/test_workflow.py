import polars as pl

from persona_pipeline.mappings import get_mappings
from persona_pipeline.stages.archetype import render_archetype_card, synthesize_archetypes
from persona_pipeline.stages.enrich import enrich
from persona_pipeline.stages.match import match_archetypes
from persona_pipeline.stages.partition import partition

KOREA = get_mappings("Korea")


def _korea_synthetic_raw():
    rows = []
    specs = [
        ("서울", "남자", "초등학교 교사", 30, 10),
        ("서울", "여자", "회계 사무원", 35, 8),
        ("부산", "남자", "음식점 조리원", 60, 7),
        ("제주", "여자", "농업 종사원", 70, 5),
    ]
    for province, sex, occ, age_base, n in specs:
        for i in range(n):
            rows.append({
                "uuid": f"{province}-{sex}-{i}",
                "age": age_base + i,
                "sex": sex,
                "province": province,
                "occupation": occ,
                "persona": f"{province} {sex} 요약 텍스트 " * 5,
                "professional_persona": f"{occ} 직업 텍스트 " * 5,
                "sports_persona": "스포츠 " * 10,
                "arts_persona": "예술 " * 10,
                "travel_persona": "여행 " * 10,
                "culinary_persona": "음식 " * 10,
                "family_persona": "가족 " * 10,
                "hobbies_and_interests_list": "['독서', '산책']",
            })
    return rows


def _run_workflow(tmp_path, mapping, raw_rows, min_size):
    raw = tmp_path / "raw.parquet"
    enriched = tmp_path / "enriched.parquet"
    partitioned = tmp_path / "partitioned.parquet"
    pl.DataFrame(raw_rows).write_parquet(raw)
    enrich(pl.scan_parquet(raw), mapping).sink_parquet(enriched)
    partition(enriched, partitioned, mapping, min_size=min_size)
    return synthesize_archetypes(partitioned, raw, mapping)


def test_workflow_produces_archetype_with_required_fields(tmp_path):
    cards = _run_workflow(tmp_path, KOREA, _korea_synthetic_raw(), min_size=1)
    expected = {"country", "segment_id", "size", "share_pct", "mean_age",
                "top_occupation", "top_region", "top_hobbies", "samples",
                *KOREA.axes}
    assert expected.issubset(set(cards.columns))
    assert "archetype_text" not in cards.columns


def test_workflow_share_pct_sums_to_100_and_size_covers_all_rows(tmp_path):
    raw_rows = _korea_synthetic_raw()
    cards = _run_workflow(tmp_path, KOREA, raw_rows, min_size=1)
    assert abs(float(cards["share_pct"].sum()) - 100.0) < 0.01
    assert cards["size"].sum() == len(raw_rows)


def test_workflow_samples_capped_per_segment_and_render_includes_persona_sections(tmp_path):
    cards = _run_workflow(tmp_path, KOREA, _korea_synthetic_raw(), min_size=1)
    samples_lists = cards["samples"].to_list()
    assert all(len(s) <= 5 for s in samples_lists)
    assert any(len(s) >= 1 for s in samples_lists)
    text = render_archetype_card(cards.row(0, named=True))
    assert "[요약]" in text
    assert "[직업]" in text


def test_workflow_match_returns_ranked_archetypes(tmp_path):
    cards = _run_workflow(tmp_path, KOREA, _korea_synthetic_raw(), min_size=1)
    results = match_archetypes("서울 30대 남자 교사", cards, KOREA, top_k=3)
    assert len(results) >= 1
    top = results[0]
    assert top["region"] == "수도권" or top["sex"] == "남자"
