"""Enrich raw Nemotron rows with derived axes and emit the store-shaped LazyFrame.

Output schema (column order): country, uuid, region (if axis), age_gen, sex,
occupation_group, age, province (if exists), occupation (if exists), hobbies,
plus all persona text columns declared in `mapping.persona_columns`.

Hobbies are parsed from the raw `hobbies_and_interests_list` string column
(Python-list literal) into a `list[str]` column.
"""
from __future__ import annotations

import polars as pl

from persona_pipeline.mappings import (
    AGE, AGE_GEN, AGE_GEN_BOUNDS, CountryMappings, HOBBIES_COL,
    OCCUPATION_GROUP, REGION, SEX, UUID,
)


def _age_gen_expr(mapping: CountryMappings) -> pl.Expr:
    labels = list(mapping.age_gen_keywords.keys())
    if len(labels) != len(AGE_GEN_BOUNDS):
        raise ValueError(
            f"{mapping.country}: age_gen_keywords needs {len(AGE_GEN_BOUNDS)} labels, got {labels}"
        )
    young, middle, old = labels
    (_, hi_y), (_, hi_m), _ = AGE_GEN_BOUNDS
    return (
        pl.when(pl.col(AGE) <= hi_y).then(pl.lit(young))
        .when(pl.col(AGE) <= hi_m).then(pl.lit(middle))
        .otherwise(pl.lit(old))
        .alias(AGE_GEN)
    )


def _sex_expr(mapping: CountryMappings) -> pl.Expr | None:
    if mapping.sex_map is None:
        return None
    return pl.col(SEX).replace_strict(mapping.sex_map, default=pl.col(SEX))


def _region_expr(mapping: CountryMappings) -> pl.Expr:
    src = mapping.region_source_col
    if src is None:
        raise ValueError(f"{mapping.country}: region axis declared but region_source_col is None")
    if mapping.region_map is None:
        return pl.col(src).alias(REGION)
    return pl.col(src).replace_strict(mapping.region_map, default="Other").alias(REGION)


def _hobbies_expr() -> pl.Expr:
    return (
        pl.col(HOBBIES_COL)
        .str.strip_chars()
        .str.strip_prefix("[").str.strip_suffix("]")
        .str.replace_all("'", "")
        .str.split(", ")
        .alias("hobbies")
    )


def enrich(
    lf: pl.LazyFrame,
    mapping: CountryMappings,
    occupation_lookup: pl.LazyFrame | None = None,
) -> pl.LazyFrame:
    """Build the enriched LazyFrame to be written as the country store.

    `occupation_lookup` is required when `mapping.occupation_group_definitions` is set
    (Korea/Japan/USA/India). Native-category countries (Singapore/Brazil/France) pass None.
    """
    src = mapping.occupation_source_col
    schema_in = lf.collect_schema().names()

    derived: list[pl.Expr] = [_age_gen_expr(mapping)]
    sex_expr = _sex_expr(mapping)
    if sex_expr is not None:
        derived.append(sex_expr)
    if REGION in mapping.axes:
        derived.append(_region_expr(mapping))
    if HOBBIES_COL in schema_in:
        derived.append(_hobbies_expr())

    base = lf.with_columns(derived)

    if mapping.occupation_group_definitions is None:
        base = base.with_columns(pl.col(src).alias(OCCUPATION_GROUP))
    else:
        if occupation_lookup is None:
            raise ValueError(
                f"{mapping.country}: occupation_lookup required when occupation_group_definitions is set."
            )
        lookup = occupation_lookup.select([
            pl.col("occupation").alias(src),
            pl.col("occupation_group").alias(OCCUPATION_GROUP),
        ])
        base = (
            base.join(lookup, on=src, how="left")
            .with_columns(pl.col(OCCUPATION_GROUP).fill_null("Other"))
        )

    base = base.with_columns(pl.lit(mapping.country).alias("country"))

    schema_now = base.collect_schema().names()
    persona_text_cols = [c for c in mapping.persona_columns if c in schema_now]
    candidate = (
        ["country", UUID, *mapping.axes, AGE]
        + ([mapping.region_source_col]
           if mapping.region_source_col and mapping.region_source_col != REGION
           else [])
        + ([src] if src != OCCUPATION_GROUP else [])
        + (["hobbies"] if "hobbies" in schema_now else [])
        + persona_text_cols
    )
    seen, ordered = set(), []
    for c in candidate:
        if c in schema_now and c not in seen:
            seen.add(c)
            ordered.append(c)
    return base.select(ordered).sort(mapping.axes)
