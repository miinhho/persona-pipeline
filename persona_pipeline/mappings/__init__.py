"""country key → CountryMappings dispatcher."""
from persona_pipeline.mappings._base import (
    AGE,
    AGE_GEN,
    AGE_GEN_BOUNDS,
    CountryMappings,
    HOBBIES_COL,
    OCCUPATION_GROUP,
    REGION,
    SEGMENT_ID,
    SEGMENT_KEY,
    SEGMENT_SEP,
    SEX,
    UUID,
    backoff_axes,
    parse_segment,
)
from persona_pipeline.mappings import (
    brazil, france, india, japan, korea, singapore, usa,
)

_REGISTRY: dict[str, CountryMappings] = {
    "Korea": korea.MAPPINGS,
    "Japan": japan.MAPPINGS,
    "Singapore": singapore.MAPPINGS,
    "Brazil": brazil.MAPPINGS,
    "France": france.MAPPINGS,
    "USA": usa.MAPPINGS,
    "India": india.MAPPINGS,
}

COUNTRIES: list[str] = list(_REGISTRY.keys())


def get_mappings(country: str) -> CountryMappings:
    if country not in _REGISTRY:
        raise KeyError(f"Unknown country '{country}'. Choose from {COUNTRIES}")
    return _REGISTRY[country]


__all__ = [
    "AGE",
    "AGE_GEN",
    "AGE_GEN_BOUNDS",
    "COUNTRIES",
    "CountryMappings",
    "HOBBIES_COL",
    "OCCUPATION_GROUP",
    "REGION",
    "SEGMENT_ID",
    "SEGMENT_KEY",
    "SEGMENT_SEP",
    "SEX",
    "UUID",
    "backoff_axes",
    "get_mappings",
    "parse_segment",
]
