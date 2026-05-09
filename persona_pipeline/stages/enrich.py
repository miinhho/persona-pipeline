"""Select demographic columns from raw and derive axes. Text columns are re-read from raw in the archetype stage.

For countries with `occupation_group_definitions`, the occupation_group column is
populated by left-joining a pre-computed `(occupation, occupation_group)` lookup
parquet (see stages/classify_occupation.py). Countries with native categorical
occupation columns (Singapore/Brazil/France) bypass the lookup.
"""
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


def enrich(
    lf: pl.LazyFrame,
    mapping: CountryMappings,
    occupation_lookup: pl.LazyFrame | None = None,
) -> pl.LazyFrame:
    """Build the enriched frame.

    `occupation_lookup` is a (occupation, occupation_group) frame produced by the
    classify_occupation stage. Required when `mapping.occupation_group_definitions`
    is set; ignored otherwise.
    """
    src = mapping.occupation_source_col
    needed = {UUID, AGE, SEX, src}
    if mapping.region_source_col:
        needed.add(mapping.region_source_col)

    new_cols = [_age_gen_expr(mapping)]
    sex = _sex_expr(mapping)
    if sex is not None:
        new_cols.append(sex)
    if REGION in mapping.axes:
        new_cols.append(_region_expr(mapping))

    base = lf.select(list(needed)).with_columns(new_cols)

    if mapping.occupation_group_definitions is None:
        # Native category — source column already holds the group value.
        base = base.with_columns(pl.col(src).alias(OCCUPATION_GROUP))
    else:
        if occupation_lookup is None:
            raise ValueError(
                f"{mapping.country}: occupation_lookup required when occupation_group_definitions is set. "
                f"Run `stage-classify-occupation {mapping.country}` first."
            )
        # Left-join lookup; rows whose occupation isn't in the lookup fall back to "Other".
        lookup = occupation_lookup.select([
            pl.col("occupation").alias(src),
            pl.col("occupation_group").alias(OCCUPATION_GROUP),
        ])
        base = (
            base.join(lookup, on=src, how="left")
            .with_columns(pl.col(OCCUPATION_GROUP).fill_null("Other"))
        )

    final_cols = [UUID, AGE, *mapping.axes, SEGMENT_KEY]
    return base.with_columns(
        pl.concat_str([pl.col(a) for a in mapping.axes], separator=SEGMENT_SEP).alias(SEGMENT_KEY)
    ).select(final_cols)
