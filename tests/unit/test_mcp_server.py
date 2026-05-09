import polars as pl
import pytest
from mcp.server.fastmcp.exceptions import ToolError

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


def test_unknown_country_raises_tool_error(korea_store, monkeypatch, tmp_path):
    # Unknown country name (not in mappings registry)
    with pytest.raises(ToolError, match="unknown country"):
        mcp_server.sample_personas(country="Atlantis", n=1)

    # Valid country whose store parquet has not been built
    # Monkeypatch store_path to point to a non-existent file for France
    monkeypatch.setattr(store, "store_path", lambda c: tmp_path / f"{c}.parquet")
    with pytest.raises(ToolError, match="not built"):
        mcp_server.sample_personas(country="France", n=1)


from unittest.mock import MagicMock
from mcp.server.fastmcp.exceptions import ToolError as _ToolError

from persona_pipeline.mcp_server import _observe as _observe_for_test  # noqa: E402


def test_observe_logs_start_and_finish_when_ctx_provided():
    ctx = MagicMock()
    with _observe_for_test(ctx, "myop", x=1, y="a"):
        pass
    # Two info calls: start with params, finish with elapsed_ms
    assert ctx.info.call_count == 2
    start_msg = ctx.info.call_args_list[0].args[0]
    finish_msg = ctx.info.call_args_list[1].args[0]
    assert "myop" in start_msg and "x=1" in start_msg and "y='a'" in start_msg
    assert "myop" in finish_msg and "ms" in finish_msg


def test_observe_silent_when_ctx_is_none():
    # Must not raise; must not require ctx methods
    with _observe_for_test(None, "myop", x=1):
        pass


def test_observe_logs_error_on_unexpected_exception():
    ctx = MagicMock()
    with pytest.raises(ValueError):
        with _observe_for_test(ctx, "myop"):
            raise ValueError("boom")
    ctx.error.assert_called_once()
    err_msg = ctx.error.call_args.args[0]
    assert "ValueError" in err_msg and "boom" in err_msg


def test_observe_does_not_log_error_on_tool_error():
    ctx = MagicMock()
    with pytest.raises(_ToolError):
        with _observe_for_test(ctx, "myop"):
            raise _ToolError("user-facing")
    ctx.error.assert_not_called()


from persona_pipeline.mcp_server import _validate_axis_names as _validate_for_test  # noqa: E402


def test_validate_axis_names_passes_when_all_valid():
    # Korea has 4 axes; no exception expected
    _validate_for_test("Korea", ["region", "sex"], purpose="filter axis")


def test_validate_axis_names_raises_tool_error_when_unknown():
    with pytest.raises(_ToolError) as exc_info:
        _validate_for_test("Korea", ["region", "foo"], purpose="filter axis")
    msg = str(exc_info.value)
    assert "filter axis" in msg
    assert "foo" in msg
    assert "personas://catalog/Korea" in msg
    # Lists the valid axes for the country
    for axis in ["region", "age_gen", "sex", "occupation_group"]:
        assert axis in msg


def test_validate_axis_names_singapore_rejects_region():
    # Singapore has no region axis (city-state); region must be rejected
    with pytest.raises(_ToolError) as exc_info:
        _validate_for_test("Singapore", ["region"], purpose="filter axis")
    assert "region" in str(exc_info.value)
    assert "Singapore" in str(exc_info.value)


def test_sample_personas_with_ctx_logs_two_info_calls(korea_store):
    ctx = MagicMock()
    out = mcp_server.sample_personas(country="Korea", n=2, ctx=ctx)
    assert len(out) == 2
    # Two info calls (start + finish)
    assert ctx.info.call_count >= 2
    start_msg = ctx.info.call_args_list[0].args[0]
    assert "sample_personas" in start_msg


def test_sample_personas_empty_filter_result_warns(korea_store):
    # Filter to a region that doesn't exist in the fixture; expect zero rows + warning
    ctx = MagicMock()
    out = mcp_server.sample_personas(
        country="Korea", n=5, region=["존재하지않는지역"], ctx=ctx
    )
    assert out == []
    ctx.warning.assert_called_once()
    warn_msg = ctx.warning.call_args.args[0]
    assert "empty" in warn_msg.lower()


def test_persona_distribution_unknown_group_by_raises_tool_error(korea_store):
    with pytest.raises(_ToolError) as exc_info:
        mcp_server.persona_distribution(country="Korea", group_by=["foo"])
    msg = str(exc_info.value)
    assert "group_by axis" in msg
    assert "foo" in msg
    assert "personas://catalog/Korea" in msg


def test_sample_personas_default_ctx_none_still_works(korea_store):
    # Regression: existing tests pass ctx implicitly as None
    out = mcp_server.sample_personas(country="Korea", n=1)
    assert len(out) == 1


import json as _json


@pytest.fixture
def korea_with_catalog(tmp_path, monkeypatch):
    """Standalone fixture: 110 rows (80 수도권, 30 영남권), writes catalog sidecar."""
    monkeypatch.setattr(store, "store_path", lambda c: tmp_path / f"{c}.parquet")
    rows = []
    for i in range(110):
        rows.append({
            "country": "Korea", "uuid": f"kc-{i}",
            "region": "수도권" if i < 80 else "영남권",
            "age_gen": "청년" if i % 2 == 0 else "중장년",
            "sex": "여자" if i % 3 == 0 else "남자",
            "occupation_group": "사무",
            "age": 30 + (i % 50), "province": "서울", "occupation": "사무원",
            "hobbies": ["독서"],
            "persona": f"persona {i}", "professional_persona": "",
            "sports_persona": "", "arts_persona": "",
            "travel_persona": "", "culinary_persona": "", "family_persona": "",
        })
    pl.DataFrame(rows).write_parquet(tmp_path / "Korea.parquet", compression="zstd")
    store.write_catalog("Korea")


def test_catalog_resource_lists_built_countries(korea_with_catalog):
    payload = _json.loads(mcp_server.catalog())
    assert isinstance(payload, list)
    countries = [c["country"] for c in payload]
    assert "Korea" in countries
    korea = next(c for c in payload if c["country"] == "Korea")
    assert korea["n_personas"] == 110
    assert set(korea["axes"]) == {"region", "age_gen", "sex", "occupation_group"}


def test_catalog_resource_returns_empty_list_when_no_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "store_path", lambda c: tmp_path / f"{c}.parquet")
    payload = _json.loads(mcp_server.catalog())
    assert payload == []


def test_country_catalog_resource_returns_axes_and_counts(korea_with_catalog):
    payload = _json.loads(mcp_server.country_catalog("Korea"))
    assert payload["country"] == "Korea"
    assert payload["n_personas"] == 110
    assert payload["axes"]["region"]["수도권"] == 80
    assert "schema" in payload and "uuid" in payload["schema"]


def test_country_catalog_resource_unknown_country_raises_value_error():
    with pytest.raises(ValueError, match="unknown country"):
        mcp_server.country_catalog("Atlantis")
