"""Build archetype cards per segment_id (single-pass polars join + uniform random sampling)."""
import ast
from collections import Counter
from pathlib import Path

import polars as pl

from persona_pipeline._config import HOBBIES_PARSE_CAP_PER_SEGMENT, SAMPLES_PER_SEGMENT
from persona_pipeline.mappings import (
    AGE, CountryMappings, HOBBIES_COL, OCCUPATION_GROUP, REGION, SEGMENT_ID, UUID,
    parse_segment,
)


def _parse_hobbies(raw: str) -> list[str]:
    """Nemotron's hobbies_and_interests_list is a Python list literal serialized as a string."""
    s = raw.strip()
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, (list, tuple)):
                return [str(h).strip() for h in parsed if str(h).strip()]
        except (ValueError, SyntaxError):
            pass
    return [h.strip() for h in s.split(",") if h.strip()]


def _top_hobbies(hobby_raws: list[str | None], k: int = 5) -> list[str]:
    counter: Counter = Counter()
    for raw in hobby_raws:
        if not raw:
            continue
        for hobby in _parse_hobbies(str(raw)):
            counter[hobby] += 1
    return [h for h, _ in counter.most_common(k)]


def _build_sample_profile(persona_data: dict[str, str | None], mapping: CountryMappings) -> str:
    parts = []
    for col, header in mapping.persona_columns.items():
        text = persona_data.get(col)
        if text:
            parts.append(f"{header}\n{text}")
    return "\n\n".join(parts)


def render_archetype_card(card: dict, max_chars: int = 300) -> str:
    """Render a single archetype row dict to the markdown card displayed by the match CLI."""
    hobbies = card.get("top_hobbies") or []
    if isinstance(hobbies, str):
        hobbies = [h.strip() for h in hobbies.split(",") if h.strip()]
    samples = card.get("samples") or []
    samples_block = "\n\n".join(f"[#{i+1}]\n{s[:max_chars]}" for i, s in enumerate(samples))
    return (
        f"# Archetype: {card['segment_id']}\n"
        f"- size: {card['size']:,} ({card['share_pct']:.2f}%)\n"
        f"- mean_age: {card['mean_age']:.1f}\n"
        f"- top_occupation: {card.get('top_occupation') or ''}\n"
        f"- top_region: {card.get('top_region') or ''}\n"
        f"- top_hobbies: {', '.join(hobbies) if hobbies else '(none)'}\n\n"
        f"## representative personas\n"
        f"{samples_block}"
    )


def synthesize_archetypes(
    partition_path: Path | str,
    raw_path: Path | str,
    mapping: CountryMappings,
) -> pl.DataFrame:
    has_region = REGION in mapping.axes
    has_occ = OCCUPATION_GROUP in mapping.axes

    p = pl.scan_parquet(str(partition_path)).select([UUID, SEGMENT_ID, AGE, *mapping.axes])

    raw_lf = pl.scan_parquet(str(raw_path))
    raw_schema = raw_lf.collect_schema().names()
    has_hobbies = HOBBIES_COL in raw_schema
    persona_cols = [c for c in mapping.persona_columns if c in raw_schema]

    raw_select = [UUID, *([HOBBIES_COL] if has_hobbies else []), *persona_cols]
    r = raw_lf.select(raw_select)

    # Hash(uuid) gives a deterministic uniform-random ordering per uuid — sort_by + head(k)
    # is equivalent to taking k uniformly-random rows per segment.
    joined = (
        p.join(r, on=UUID, how="left")
        .with_columns(pl.col(UUID).hash(seed=0xA5A5A5A5).alias("_rand"))
    )

    agg: list[pl.Expr] = [
        pl.len().alias("size"),
        pl.col(AGE).mean().alias("mean_age"),
    ]
    if has_occ:
        agg.append(
            pl.col(OCCUPATION_GROUP).drop_nulls().mode().first().alias("top_occupation")
        )
    if has_region:
        agg.append(
            pl.col(REGION).drop_nulls().mode().first().alias("top_region")
        )
    if has_hobbies:
        agg.append(
            pl.col(HOBBIES_COL).sort_by("_rand").head(HOBBIES_PARSE_CAP_PER_SEGMENT)
            .alias("_hobby_raws")
        )
    for col in persona_cols:
        agg.append(
            pl.col(col).sort_by("_rand").head(SAMPLES_PER_SEGMENT).alias(f"_s_{col}")
        )

    grouped = joined.group_by(SEGMENT_ID).agg(agg).collect()

    total_n = int(grouped["size"].sum()) if len(grouped) else 0
    records: list[dict] = []
    for row in grouped.iter_rows(named=True):
        sid = row[SEGMENT_ID]
        size = row["size"]

        sample_lists = [row[f"_s_{c}"] for c in persona_cols]
        n_samples = min(SAMPLES_PER_SEGMENT, max((len(s) for s in sample_lists), default=0))
        samples: list[str] = []
        for i in range(n_samples):
            persona_data: dict[str, str | None] = {}
            for c, vals in zip(persona_cols, sample_lists):
                persona_data[c] = vals[i] if i < len(vals) else None
            text = _build_sample_profile(persona_data, mapping)
            if text:
                samples.append(text)

        top_hobbies_list = _top_hobbies(row["_hobby_raws"]) if has_hobbies else []

        rec: dict = {
            "country": mapping.country,
            "segment_id": sid,
            "size": size,
            "share_pct": (size / total_n * 100) if total_n else 0.0,
            "mean_age": float(row["mean_age"]) if row["mean_age"] is not None else 0.0,
            "top_occupation": row.get("top_occupation") or "",
            "top_region": row.get("top_region") or "",
            "top_hobbies": top_hobbies_list,
            "samples": samples,
        }
        rec.update(parse_segment(sid, mapping.axes))
        records.append(rec)

    if not records:
        return pl.DataFrame()
    return pl.DataFrame(records).sort("size", descending=True)
