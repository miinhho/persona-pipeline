"""Build archetype cards per segment_id (partition cache + raw 2-source PyArrow chunked scan)."""
import ast
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl
import pyarrow.dataset as ds

from persona_pipeline._config import (
    BATCH_SIZE, HOBBIES_PARSE_CAP_PER_SEGMENT, SAMPLES_PER_SEGMENT,
)
from persona_pipeline.mappings import (
    AGE, CountryMappings, HOBBIES_COL, OCCUPATION_GROUP, REGION, SEGMENT_ID, UUID,
    parse_segment,
)


@dataclass
class SegmentAccum:
    size: int = 0
    age_sum: float = 0.0
    occ: Counter = field(default_factory=Counter)
    region: Counter = field(default_factory=Counter)
    hobbies: Counter = field(default_factory=Counter)
    samples: list[str] = field(default_factory=list)
    hobbies_parsed: int = 0


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


def _build_archetype_text(segment_id: str, stats: dict, samples: list[str]) -> str:
    hobbies = ", ".join(stats["top_hobbies"]) if stats["top_hobbies"] else "(none)"
    samples_block = "\n\n".join(f"[#{i+1}]\n{s[:300]}" for i, s in enumerate(samples))
    return (
        f"# Archetype: {segment_id}\n"
        f"- size: {stats['size']:,} ({stats['share_pct']:.2f}%)\n"
        f"- mean_age: {stats['mean_age']:.1f}\n"
        f"- top_occupation: {stats['top_occupation']}\n"
        f"- top_region: {stats['top_region']}\n"
        f"- top_hobbies: {hobbies}\n\n"
        f"## representative personas\n"
        f"{samples_block}"
    )


def _build_sample_profile(persona_data: dict[str, list], i: int, mapping: CountryMappings) -> str:
    parts = []
    for col, header in mapping.persona_columns.items():
        if col not in persona_data:
            continue
        text = persona_data[col][i] or ""
        parts.append(f"{header}\n{text}")
    return "\n\n".join(parts)


def _scan_partition_cache(
    partition_path: Path | str,
    mapping: CountryMappings,
) -> tuple[dict[str, SegmentAccum], dict[str, str]]:
    has_region = REGION in mapping.axes
    has_occ = OCCUPATION_GROUP in mapping.axes
    p_columns = [UUID, SEGMENT_ID, AGE, *mapping.axes]
    dataset = ds.dataset(str(partition_path), format="parquet")

    segs: dict[str, SegmentAccum] = {}
    uuid_to_seg: dict[str, str] = {}

    for batch in dataset.scanner(columns=p_columns, batch_size=BATCH_SIZE).to_batches():
        uuids = batch.column(UUID).to_pylist()
        sids = batch.column(SEGMENT_ID).to_pylist()
        ages = batch.column(AGE).to_pylist()
        occs = batch.column(OCCUPATION_GROUP).to_pylist() if has_occ else None
        regs = batch.column(REGION).to_pylist() if has_region else None

        for i, sid in enumerate(sids):
            uuid_to_seg[uuids[i]] = sid
            seg = segs.get(sid)
            if seg is None:
                seg = SegmentAccum()
                segs[sid] = seg
            seg.size += 1
            if ages[i] is not None:
                seg.age_sum += ages[i]
            if occs and occs[i]:
                seg.occ[occs[i]] += 1
            if has_region and regs and regs[i]:
                seg.region[regs[i]] += 1

    return segs, uuid_to_seg


def _scan_raw_for_samples_and_hobbies(
    raw_path: Path | str,
    mapping: CountryMappings,
    segs: dict[str, SegmentAccum],
    uuid_to_seg: dict[str, str],
) -> None:
    """Mutate segs in place — adds per-segment hobbies counter and sample profile_text."""
    raw_dataset = ds.dataset(str(raw_path), format="parquet")
    raw_schema = set(raw_dataset.schema.names)
    has_hobbies = HOBBIES_COL in raw_schema
    persona_cols = [c for c in mapping.persona_columns if c in raw_schema]

    raw_columns = [UUID]
    if has_hobbies:
        raw_columns.append(HOBBIES_COL)
    raw_columns.extend(persona_cols)

    for batch in raw_dataset.scanner(columns=raw_columns, batch_size=BATCH_SIZE).to_batches():
        uuids = batch.column(UUID).to_pylist()
        hobs = batch.column(HOBBIES_COL).to_pylist() if has_hobbies else []
        persona_data = {c: batch.column(c).to_pylist() for c in persona_cols}

        for i, uuid in enumerate(uuids):
            sid = uuid_to_seg.get(uuid)
            if sid is None:
                continue
            seg = segs[sid]
            hobby_raw = hobs[i] if hobs else None
            if hobby_raw and seg.hobbies_parsed < HOBBIES_PARSE_CAP_PER_SEGMENT:
                for hobby in _parse_hobbies(str(hobby_raw)):
                    seg.hobbies[hobby] += 1
                seg.hobbies_parsed += 1
            if len(seg.samples) < SAMPLES_PER_SEGMENT:
                seg.samples.append(_build_sample_profile(persona_data, i, mapping))


def synthesize_archetypes(
    partition_path: Path | str,
    raw_path: Path | str,
    mapping: CountryMappings,
) -> pl.DataFrame:
    has_region = REGION in mapping.axes

    segs, uuid_to_seg = _scan_partition_cache(partition_path, mapping)
    _scan_raw_for_samples_and_hobbies(raw_path, mapping, segs, uuid_to_seg)

    total_n = sum(s.size for s in segs.values())
    records = []
    for sid, seg in sorted(segs.items(), key=lambda kv: kv[1].size, reverse=True):
        top_occ = seg.occ.most_common(1)[0][0] if seg.occ else ""
        top_reg = seg.region.most_common(1)[0][0] if has_region and seg.region else ""
        top_hobbies_list = [h for h, _ in seg.hobbies.most_common(5)]
        stats = {
            "size": seg.size,
            "share_pct": seg.size / total_n * 100,
            "mean_age": seg.age_sum / seg.size if seg.size else 0.0,
            "top_occupation": top_occ,
            "top_region": top_reg,
            "top_hobbies": top_hobbies_list,
        }
        rec: dict = {
            "country": mapping.country,
            "segment_id": sid,
            **{k: v for k, v in stats.items() if k != "top_hobbies"},
            "top_hobbies": ",".join(top_hobbies_list),
            "archetype_text": _build_archetype_text(sid, stats, seg.samples),
        }
        rec.update(parse_segment(sid, mapping.axes))
        records.append(rec)

    return pl.DataFrame(records).sort("size", descending=True)
