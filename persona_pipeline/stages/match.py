"""Rule-based natural-language query → archetype matching, per country."""
import difflib
import re
from functools import reduce
from operator import add

import polars as pl

from persona_pipeline.mappings import (
    REGION, AGE_GEN, SEX, OCCUPATION_GROUP, CountryMappings,
)

FUZZY_CUTOFF = 0.75
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _extract_axis(query: str, keyword_map: dict[str, list[str]]) -> str | None:
    if not keyword_map:
        return None
    q_lower = query.lower()

    best_label: str | None = None
    best_len = 0
    for label, kws in keyword_map.items():
        for kw in kws:
            kw_lower = kw.lower()
            if kw_lower and kw_lower in q_lower and len(kw_lower) > best_len:
                best_label = label
                best_len = len(kw_lower)
    if best_label is not None:
        return best_label

    # Fuzzy fallback: per query token, find the closest keyword across all labels.
    # Picks the highest-scoring (token, keyword) pair to avoid an early-token false positive.
    flat = [(label, kw.lower()) for label, kws in keyword_map.items() for kw in kws if kw]
    if not flat:
        return None
    candidates = [kw for _, kw in flat]
    tokens = _TOKEN_RE.findall(q_lower)

    best_ratio = 0.0
    best_fuzzy: str | None = None
    for token in tokens:
        if len(token) < 2:
            continue
        match = difflib.get_close_matches(token, candidates, n=1, cutoff=FUZZY_CUTOFF)
        if not match:
            continue
        ratio = difflib.SequenceMatcher(None, token, match[0]).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_fuzzy = next(label for label, kw in flat if kw == match[0])
    return best_fuzzy


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
