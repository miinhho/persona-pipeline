"""Country-agnostic interface + segment_id encoding utilities."""
from dataclasses import dataclass, field

REGION = "region"
AGE_GEN = "age_gen"
SEX = "sex"
OCCUPATION_GROUP = "occupation_group"

UUID = "uuid"
AGE = "age"
SEGMENT_ID = "segment_id"
SEGMENT_KEY = "segment_key"
HOBBIES_COL = "hobbies_and_interests_list"

# axis values may contain underscores, so "_" is unsafe as separator.
SEGMENT_SEP = "|"

# Same boundaries across countries; only the labels differ per locale.
AGE_GEN_BOUNDS: list[tuple[int, int]] = [
    (0, 34),
    (35, 64),
    (65, 200),
]


@dataclass(frozen=True)
class CountryMappings:
    country: str
    locale: str
    hf_split: str

    # Order of axes that compose segment_id. Some countries differ
    # (Singapore is a city-state, no region axis -> 3 axes).
    axes: list[str]

    persona_columns: dict[str, str]

    # When region_map=None the source column already holds region-level values (e.g. Japan).
    region_source_col: str | None = None
    region_map: dict[str, str] | None = None

    sex_map: dict[str, str] | None = None

    # When occupation_group_definitions=None the source column already holds the categorical
    # group (Singapore / Brazil / France). Otherwise an LLM-as-classifier (see
    # stages/classify_occupation.py) maps the free-text source column to one of these labels;
    # the mapping is stored as a parquet asset and replayed via lookup join in enrich.
    # The dict is `{label: short description for the classifier}` — categories are defined
    # once here, never duplicated as keyword lists.
    occupation_source_col: str = "occupation"
    occupation_group_definitions: dict[str, str] | None = None

    region_keywords: dict[str, list[str]] = field(default_factory=dict)
    age_gen_keywords: dict[str, list[str]] = field(default_factory=dict)
    sex_keywords: dict[str, list[str]] = field(default_factory=dict)
    occupation_keywords: dict[str, list[str]] = field(default_factory=dict)


# Backoff: L0 = axes, L1 = axes[:-1], L2 = axes[1:-1] (or axes[:-1] when len(axes) < 3).

def backoff_axes(axes: list[str], level: int) -> list[str]:
    if level == 0:
        return list(axes)
    if level == 1:
        return list(axes[:-1])
    if level == 2:
        return list(axes[1:-1]) if len(axes) >= 3 else list(axes[:-1])
    raise ValueError(f"backoff level must be 0/1/2, got {level}")


def parse_segment(segment_id: str, axes: list[str]) -> dict[str, str | None]:
    """Map segment_id parts to axes. Backed-off segments leave some axes as None."""
    parts = segment_id.split(SEGMENT_SEP)
    out: dict[str, str | None] = {a: None for a in axes}
    for level in (0, 1, 2):
        active = backoff_axes(axes, level)
        if len(parts) == len(active):
            for a, v in zip(active, parts):
                out[a] = v
            return out
    return out
