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
