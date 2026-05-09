import asyncio
import json
from unittest.mock import MagicMock

import polars as pl
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from persona_pipeline import mcp_server, store
from persona_pipeline.mcp_server import _observe, _validate_axis_names


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


def test_observe_logs_start_and_finish_when_ctx_provided():
    ctx = MagicMock()
    with _observe(ctx, "myop", x=1, y="a"):
        pass
    # Two info calls: start with params, finish with elapsed_ms
    assert ctx.info.call_count == 2
    start_msg = ctx.info.call_args_list[0].args[0]
    finish_msg = ctx.info.call_args_list[1].args[0]
    assert "myop" in start_msg and "x=1" in start_msg and "y='a'" in start_msg
    assert "myop" in finish_msg and "ms" in finish_msg


def test_observe_silent_when_ctx_is_none():
    # Must not raise; must not require ctx methods
    with _observe(None, "myop", x=1):
        pass


def test_observe_logs_error_on_unexpected_exception():
    ctx = MagicMock()
    with pytest.raises(ValueError):
        with _observe(ctx, "myop"):
            raise ValueError("boom")
    ctx.error.assert_called_once()
    err_msg = ctx.error.call_args.args[0]
    assert "ValueError" in err_msg and "boom" in err_msg


def test_observe_does_not_log_error_on_tool_error():
    ctx = MagicMock()
    with pytest.raises(ToolError):
        with _observe(ctx, "myop"):
            raise ToolError("user-facing")
    ctx.error.assert_not_called()


def test_validate_axis_names_passes_when_all_valid():
    # Korea has 4 axes; no exception expected
    _validate_axis_names("Korea", ["region", "sex"], purpose="filter axis")


def test_validate_axis_names_raises_tool_error_when_unknown():
    with pytest.raises(ToolError) as exc_info:
        _validate_axis_names("Korea", ["region", "foo"], purpose="filter axis")
    msg = str(exc_info.value)
    assert "filter axis" in msg
    assert "foo" in msg
    assert "personas://catalog/Korea" in msg
    # Lists the valid axes for the country
    for axis in ["region", "age_gen", "sex", "occupation_group"]:
        assert axis in msg


def test_validate_axis_names_singapore_rejects_region():
    # Singapore has no region axis (city-state); region must be rejected
    with pytest.raises(ToolError) as exc_info:
        _validate_axis_names("Singapore", ["region"], purpose="filter axis")
    assert "region" in str(exc_info.value)
    assert "Singapore" in str(exc_info.value)


def test_sample_personas_invalid_axis_value_raises_tool_error(korea_store):
    """Passing region=['서울'] (real provinces, not the region axis label '수도권')
    must raise ToolError instead of returning [] silently."""
    store.write_catalog("Korea")  # ensure sidecar is on disk for this fixture
    with pytest.raises(ToolError) as exc_info:
        mcp_server.sample_personas(country="Korea", n=1, region=["서울"])
    msg = str(exc_info.value)
    assert "region" in msg and "서울" in msg
    assert "수도권" in msg  # one of the valid values listed
    assert "personas://catalog/Korea" in msg


def test_validate_axis_values_passes_when_all_valid(korea_store):
    store.write_catalog("Korea")
    # 수도권 is a real region in the fixture; should not raise
    out = mcp_server.sample_personas(country="Korea", n=1, region=["수도권"])
    assert len(out) == 1


def test_validate_axis_values_skips_when_no_catalog(korea_store, monkeypatch):
    """Defensive: if catalog sidecar is missing, fall through silently (don't block
    the tool because of a missing sidecar — the country store still works)."""
    monkeypatch.setattr(store, "load_catalog", lambda c: None)
    # Even with a non-catalogued value, this should not raise (catalog absent)
    out = mcp_server.sample_personas(country="Korea", n=1, region=["수도권"])
    assert len(out) == 1


def test_unknown_country_lists_built_countries(korea_store, monkeypatch, tmp_path):
    """country-not-found error includes the list of currently-built countries."""
    store.write_catalog("Korea")
    # Point store_path elsewhere so France lookup fails but Korea's catalog stays under tmp_path
    real_store_path = store.store_path
    monkeypatch.setattr(
        store, "store_path",
        lambda c: real_store_path("Korea") if c == "Korea" else tmp_path / f"{c}.parquet",
    )
    with pytest.raises(ToolError) as exc_info:
        mcp_server.sample_personas(country="France", n=1)
    msg = str(exc_info.value)
    assert "not built" in msg
    assert "Currently built" in msg
    assert "Korea" in msg


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
    with pytest.raises(ToolError) as exc_info:
        mcp_server.persona_distribution(country="Korea", group_by=["foo"])
    msg = str(exc_info.value)
    assert "group_by axis" in msg
    assert "foo" in msg
    assert "personas://catalog/Korea" in msg


def test_sample_personas_default_ctx_none_still_works(korea_store):
    # Regression: existing tests pass ctx implicitly as None
    out = mcp_server.sample_personas(country="Korea", n=1)
    assert len(out) == 1


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
    payload = json.loads(mcp_server.catalog())
    assert isinstance(payload, list)
    countries = [c["country"] for c in payload]
    assert "Korea" in countries
    korea = next(c for c in payload if c["country"] == "Korea")
    assert korea["n_personas"] == 110
    assert set(korea["axes"]) == {"region", "age_gen", "sex", "occupation_group"}


def test_catalog_resource_returns_empty_list_when_no_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "store_path", lambda c: tmp_path / f"{c}.parquet")
    payload = json.loads(mcp_server.catalog())
    assert payload == []


def test_country_catalog_resource_returns_axes_and_counts(korea_with_catalog):
    payload = json.loads(mcp_server.country_catalog("Korea"))
    assert payload["country"] == "Korea"
    assert payload["n_personas"] == 110
    assert payload["axes"]["region"]["수도권"] == 80
    assert "schema" in payload and "uuid" in payload["schema"]


def test_country_catalog_resource_unknown_country_raises_value_error():
    with pytest.raises(ValueError, match="unknown country"):
        mcp_server.country_catalog("Atlantis")


def test_search_personas_empty_result_warns(korea_store):
    ctx = MagicMock()
    out = mcp_server.search_personas(
        country="Korea", query="지구상에없는단어", top_k=10, ctx=ctx
    )
    assert out == []
    ctx.warning.assert_called_once()
    warn_msg = ctx.warning.call_args.args[0]
    assert "no matches" in warn_msg.lower()


def test_sample_personas_n_zero_raises_validation_through_mcp_path(korea_store):
    """
    Field(ge=1) enforcement only fires when invoked through the FastMCP call path
    (it runs Pydantic model_validate on the tool args). Calling the function
    directly bypasses validation. This test exercises the real path.
    """
    async def _call():
        return await mcp_server.mcp.call_tool(
            "sample_personas", {"country": "Korea", "n": 0}
        )

    with pytest.raises(Exception) as exc_info:
        asyncio.run(_call())
    msg = str(exc_info.value).lower()
    # Pydantic v2 message contains "greater than or equal to 1"; FastMCP may wrap it
    assert any(s in msg for s in (
        "greater than or equal to 1",
        "input should be",
        "ge=1",
        "validation",
    )), f"unexpected error message: {exc_info.value!r}"
