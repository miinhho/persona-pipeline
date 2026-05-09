"""Country-agnostic interface."""
from dataclasses import dataclass, field

REGION = "region"
AGE_GEN = "age_gen"
SEX = "sex"
OCCUPATION_GROUP = "occupation_group"

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

    # When occupation_group_definitions=None the source column already holds the categorical
    # group (Singapore / Brazil / France). Otherwise an LLM-as-classifier (see
    # stages/classify_occupation.py) maps the free-text source column to one of these labels;
    # the mapping is stored as a parquet asset and replayed via lookup join in enrich.
    # The dict is `{label: short description for the classifier}` — categories are defined
    # once here, never duplicated as keyword lists.
    occupation_source_col: str = "occupation"
    occupation_group_definitions: dict[str, str] | None = None

    age_gen_labels: list[str] = field(default_factory=list)


