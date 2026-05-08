"""Rule-based natural-language query → archetype matching, per country."""
from functools import reduce
from operator import add

import polars as pl

from persona_pipeline.mappings import (
    REGION, AGE_GEN, SEX, OCCUPATION_GROUP, CountryMappings,
)


def _extract_axis(query: str, keyword_map: dict[str, list[str]]) -> str | None:
    q_lower = query.lower()
    best_label = None
    best_len = 0
    for label, kws in keyword_map.items():
        for kw in kws:
            if kw.lower() in q_lower and len(kw) > best_len:
                best_label = label
                best_len = len(kw)
    return best_label


_AXIS_TO_FIELD = {
    REGION: "region_keywords",
    AGE_GEN: "age_gen_keywords",
    SEX: "sex_keywords",
    OCCUPATION_GROUP: "occupation_keywords",
}


def parse_query_to_axes(query: str, mapping: CountryMappings) -> dict[str, str | None]:
    return {
        axis: _extract_axis(query, getattr(mapping, _AXIS_TO_FIELD[axis], {}))
        for axis in mapping.axes
    }


def match_archetypes(
    query: str,
    archetypes: pl.DataFrame,
    mapping: CountryMappings,
    top_k: int = 3,
) -> list[dict]:
    axes = parse_query_to_axes(query, mapping)
    matched = {a: v for a, v in axes.items() if v is not None and a in archetypes.columns}

    if not matched:
        return archetypes.sort("size", descending=True).head(top_k).to_dicts()

    score_expr = reduce(add, (
        pl.col(a).cast(pl.Utf8).eq(label).cast(pl.Int32).fill_null(0)
        for a, label in matched.items()
    ))
    df = archetypes.with_columns(score_expr.alias("_score")).filter(pl.col("_score") > 0)

    if len(df) == 0:
        return archetypes.sort("size", descending=True).head(top_k).to_dicts()
    return df.sort(["_score", "size"], descending=[True, True]).head(top_k).to_dicts()
