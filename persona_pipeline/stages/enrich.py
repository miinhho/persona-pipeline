"""Select demographic columns from raw and derive axes. Text columns are re-read from raw in the archetype stage."""
import polars as pl

from persona_pipeline.mappings import (
    AGE, AGE_GEN, AGE_GEN_BOUNDS, CountryMappings, OCCUPATION_GROUP, REGION,
    SEGMENT_KEY, SEGMENT_SEP, SEX, UUID,
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


def _occupation_group_expr(mapping: CountryMappings) -> pl.Expr:
    src = mapping.occupation_source_col
    if mapping.occupation_groups is None:
        return pl.col(src).alias(OCCUPATION_GROUP)
    expr = pl.lit("Other")
    for group, keywords in reversed(list(mapping.occupation_groups.items())):
        contains_any = pl.lit(False)
        for kw in keywords:
            contains_any = contains_any | pl.col(src).str.contains(kw, literal=True)
        expr = pl.when(contains_any).then(pl.lit(group)).otherwise(expr)
    return expr.alias(OCCUPATION_GROUP)


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


def enrich(lf: pl.LazyFrame, mapping: CountryMappings) -> pl.LazyFrame:
    needed = {UUID, AGE, SEX, mapping.occupation_source_col}
    if mapping.region_source_col:
        needed.add(mapping.region_source_col)

    new_cols = [_age_gen_expr(mapping), _occupation_group_expr(mapping)]
    sex = _sex_expr(mapping)
    if sex is not None:
        new_cols.append(sex)
    if REGION in mapping.axes:
        new_cols.append(_region_expr(mapping))

    final_cols = [UUID, AGE, *mapping.axes, SEGMENT_KEY]
    return (
        lf.select(list(needed))
        .with_columns(new_cols)
        .with_columns(
            pl.concat_str([pl.col(a) for a in mapping.axes], separator=SEGMENT_SEP).alias(SEGMENT_KEY)
        )
        .select(final_cols)
    )
