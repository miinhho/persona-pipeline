import polars as pl
import pytest

from persona_pipeline import mcp_server, store


@pytest.fixture
def korea_store(tmp_path, monkeypatch):
    rows = []
    for i in range(20):
        rows.append({
            "country": "Korea", "uuid": f"k-{i}",
            "region": "수도권" if i < 10 else "영남권",
            "age_gen": "청년" if i % 2 == 0 else "중장년",
            "sex": "여자" if i % 3 == 0 else "남자",
            "occupation_group": "사무",
            "age": 30 + i, "province": "서울", "occupation": "사무원",
            "hobbies": ["독서"],
            "persona": f"persona {i}", "professional_persona": "",
            "sports_persona": "", "arts_persona": "",
            "travel_persona": "", "culinary_persona": "", "family_persona": "",
        })
    pl.DataFrame(rows).write_parquet(tmp_path / "Korea.parquet", compression="zstd")
    monkeypatch.setattr(store, "store_path", lambda c: tmp_path / f"{c}.parquet")


def test_sample_personas_returns_dicts_with_filters(korea_store):
    out = mcp_server.sample_personas(country="Korea", n=3, region=["수도권"])
    assert len(out) == 3
    for p in out:
        assert p["region"] == "수도권"
        assert "persona" in p  # raw text passed through


def test_sample_personas_no_axis_filter(korea_store):
    out = mcp_server.sample_personas(country="Korea", n=5)
    assert len(out) == 5


def test_sample_personas_combines_axis_filters(korea_store):
    out = mcp_server.sample_personas(
        country="Korea", n=10,
        region=["수도권"], age_gen=["청년"], sex=["여자"],
    )
    for p in out:
        assert p["region"] == "수도권"
        assert p["age_gen"] == "청년"
        assert p["sex"] == "여자"


def test_search_personas_returns_matching_substring(korea_store):
    out = mcp_server.search_personas(country="Korea", query="persona 5", top_k=10)
    assert len(out) == 1
    assert out[0]["uuid"] == "k-5"


def test_persona_distribution_by_region(korea_store):
    out = mcp_server.persona_distribution(country="Korea", group_by=["region"])
    rows = {r["region"]: r["count"] for r in out}
    assert rows == {"수도권": 10, "영남권": 10}


def test_get_persona_returns_dict(korea_store):
    out = mcp_server.get_persona(country="Korea", uuid="k-7")
    assert out is not None
    assert out["uuid"] == "k-7"


def test_get_persona_returns_none_when_missing(korea_store):
    assert mcp_server.get_persona(country="Korea", uuid="nope") is None
