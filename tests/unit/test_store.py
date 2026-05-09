import polars as pl
import pytest

from persona_pipeline import store


@pytest.fixture
def korea_store(tmp_path, monkeypatch):
    rows = []
    specs = [
        ("수도권", "청년", "여자", "사무", 28, 50),
        ("수도권", "중장년", "남자", "관리자", 50, 30),
        ("영남권", "노년", "여자", "무직", 75, 20),
        ("호남권", "중장년", "여자", "서비스", 50, 10),
    ]
    for region, age_gen, sex, occ_grp, age, n in specs:
        for i in range(n):
            rows.append({
                "country": "Korea",
                "uuid": f"{region}-{sex}-{occ_grp}-{i}",
                "region": region, "age_gen": age_gen, "sex": sex,
                "occupation_group": occ_grp, "age": age + i,
                "province": "서울", "occupation": "...",
                "hobbies": ["독서"],
                "persona": f"persona-text-{i}",
                "professional_persona": f"job-text-{i}",
                "sports_persona": "", "arts_persona": "",
                "travel_persona": "", "culinary_persona": "", "family_persona": "",
            })
    df = pl.DataFrame(rows)
    path = tmp_path / "Korea.parquet"
    df.write_parquet(path, compression="zstd")
    monkeypatch.setattr(store, "store_path", lambda c: tmp_path / f"{c}.parquet")
    return path


def test_load_returns_lazyframe(korea_store):
    lf = store.load("Korea")
    assert isinstance(lf, pl.LazyFrame)
    assert lf.collect().height == 110


def test_sample_returns_n_rows_matching_filter(korea_store):
    df = store.sample("Korea", {"region": "수도권"}, n=5)
    assert len(df) == 5
    assert set(df["region"].unique().to_list()) == {"수도권"}


def test_sample_supports_list_filter(korea_store):
    df = store.sample("Korea", {"region": ["수도권", "영남권"]}, n=20)
    assert len(df) == 20
    assert set(df["region"].unique().to_list()) <= {"수도권", "영남권"}


def test_sample_is_deterministic_for_same_seed(korea_store):
    a = store.sample("Korea", {"region": "수도권"}, n=5, seed=42)
    b = store.sample("Korea", {"region": "수도권"}, n=5, seed=42)
    assert a["uuid"].to_list() == b["uuid"].to_list()


def test_sample_differs_across_seeds(korea_store):
    a = store.sample("Korea", {"region": "수도권"}, n=5, seed=1)
    b = store.sample("Korea", {"region": "수도권"}, n=5, seed=2)
    assert a["uuid"].to_list() != b["uuid"].to_list()


def test_sample_with_no_filter_returns_n_rows(korea_store):
    df = store.sample("Korea", filter=None, n=10)
    assert len(df) == 10


def test_sample_caps_at_population_when_n_exceeds(korea_store):
    df = store.sample("Korea", {"region": "호남권"}, n=999)
    assert len(df) == 10  # only 10 호남권 rows in fixture


def test_distribution_groups_and_counts(korea_store):
    df = store.distribution("Korea", group_by=["region"])
    rows = {r["region"]: r["count"] for r in df.iter_rows(named=True)}
    assert rows == {"수도권": 80, "영남권": 20, "호남권": 10}


def test_distribution_sorted_descending(korea_store):
    df = store.distribution("Korea", group_by=["region"])
    counts = df["count"].to_list()
    assert counts == sorted(counts, reverse=True)


def test_distribution_with_filter(korea_store):
    df = store.distribution("Korea", group_by=["sex"], filter={"region": "수도권"})
    rows = {r["sex"]: r["count"] for r in df.iter_rows(named=True)}
    assert rows == {"여자": 50, "남자": 30}


def test_distribution_multiple_group_by(korea_store):
    df = store.distribution("Korea", group_by=["region", "age_gen"])
    assert df.height == 4  # 4 distinct (region, age_gen) pairs in fixture
    assert "count" in df.columns


def test_get_returns_row_dict(korea_store):
    target_uuid = "수도권-여자-사무-3"
    row = store.get("Korea", target_uuid)
    assert row is not None
    assert row["uuid"] == target_uuid
    assert row["region"] == "수도권"
    assert row["sex"] == "여자"
    assert row["occupation_group"] == "사무"


def test_get_returns_none_when_uuid_missing(korea_store):
    assert store.get("Korea", "does-not-exist") is None


@pytest.fixture
def korea_search_store(tmp_path, monkeypatch):
    rows = [
        {"country": "Korea", "uuid": "u1", "region": "수도권", "age_gen": "청년",
         "sex": "남자", "occupation_group": "전문가", "age": 28, "province": "서울",
         "occupation": "개발자", "hobbies": [],
         "persona": "강남에서 일하는 개발자입니다",
         "professional_persona": "백엔드 시니어",
         "sports_persona": "", "arts_persona": "", "travel_persona": "",
         "culinary_persona": "", "family_persona": ""},
        {"country": "Korea", "uuid": "u2", "region": "영남권", "age_gen": "노년",
         "sex": "여자", "occupation_group": "농림어업", "age": 70, "province": "부산",
         "occupation": "농민", "hobbies": [],
         "persona": "어업 종사자입니다",
         "professional_persona": "갈치잡이",
         "sports_persona": "", "arts_persona": "", "travel_persona": "",
         "culinary_persona": "", "family_persona": "강남에 사는 자녀를 둠"},
    ]
    df = pl.DataFrame(rows)
    path = tmp_path / "Korea.parquet"
    df.write_parquet(path, compression="zstd")
    monkeypatch.setattr(store, "store_path", lambda c: tmp_path / f"{c}.parquet")
    return path


def test_search_substring_across_text_columns(korea_search_store):
    df = store.search("Korea", "강남", top_k=10)
    # u1 has '강남' in persona, u2 has '강남' in family_persona
    assert set(df["uuid"].to_list()) == {"u1", "u2"}


def test_search_respects_top_k(korea_search_store):
    df = store.search("Korea", "강남", top_k=1)
    assert df.height == 1


def test_search_with_filter(korea_search_store):
    df = store.search("Korea", "강남", top_k=10, filter={"region": "수도권"})
    assert df["uuid"].to_list() == ["u1"]


def test_search_no_match_returns_empty(korea_search_store):
    df = store.search("Korea", "지구상에없는단어", top_k=10)
    assert df.height == 0
