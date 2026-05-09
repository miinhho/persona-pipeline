# persona-pipeline

Multi-country archetype pipeline over Nemotron-Personas (USA / Japan / India / Singapore / Brazil / France / Korea, ~1M personas each). Builds demographic segment archetypes and matches natural-language queries against them.

## Quick start

```bash
make download COUNTRY=Korea          # HF Nemotron-Personas-Korea
make build COUNTRY=Korea             # enrich → partition
make archetype COUNTRY=Korea         # archetype cards
make match COUNTRY=Korea Q='서울 30대 남자 PM'

make build-all                       # all 7 countries sequentially
```

## Pipeline

```
raw (HF dataset)
  ↓ enrich     select demographic columns + derive axes (region/age_gen/sex/occupation_group) + segment_key
  ↓ partition  segment_id + per-segment cascading backoff (L0 → L1 → L2)
  ↓ archetype  per-segment stats + 5 uniformly-random persona samples
  ↓ match      NL query → axis match (substring + fuzzy fallback) → top-K archetypes
```

## Country mappings

`persona_pipeline/mappings/{korea,japan,...}.py` — per-country rules in a `CountryMappings` dataclass:
- `axes`: order of axes that compose segment_id (Singapore has no region axis -> 3 axes)
- `region_source_col` + `region_map`: native administrative division → regional grouping (Japan exposes a native `region` column, no map needed)
- `occupation_groups`: keyword rules to bucket free-text occupation into a category (USA SOC / Korea KSCO / India NCO / Japan JSOC; Singapore / Brazil / France use the dataset's native category column)
- `*_keywords`: locale keywords used to extract axis labels from a natural-language query

## Layout

```
persona_pipeline/
├── _config.py           constants (BATCH_SIZE, SAMPLES_PER_SEGMENT, ...)
├── mappings/            per-country rules + axis name constants
├── stages/              enrich, partition, archetype, match
├── validate.py          stage invariants
├── io.py                atomic parquet write + HF download
└── cli/                 Typer commands

tests/                   pytest
```
