"""Country-agnostic interface."""
from dataclasses import dataclass, field

REGION = "region"
AGE_GEN = "age_gen"
SEX = "sex"

UUID = "uuid"
AGE = "age"
HOBBIES_COL = "hobbies_and_interests_list"

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

    # Order of axes used for store sort + filter pushdown. Some countries
    # differ (Singapore is a city-state, no region axis -> 3 axes).
    axes: list[str]

    persona_columns: dict[str, str]

    # When region_map=None the source column already holds region-level values (e.g. Japan).
    region_source_col: str | None = None
    region_map: dict[str, str] | None = None

    sex_map: dict[str, str] | None = None

    age_gen_labels: list[str] = field(default_factory=list)


