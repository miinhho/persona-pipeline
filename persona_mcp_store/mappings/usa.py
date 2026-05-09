"""USA — US Census 4 regions (mapped from 52 states), SOC 22-group occupation."""
from persona_mcp_store.mappings._base import (
    CountryMappings, REGION, AGE_GEN, SEX,
)


# US Census Bureau 4 regions.
STATE_TO_REGION: dict[str, str] = {
    # Northeast
    "CT": "Northeast", "ME": "Northeast", "MA": "Northeast", "NH": "Northeast",
    "NJ": "Northeast", "NY": "Northeast", "PA": "Northeast", "RI": "Northeast",
    "VT": "Northeast",
    # Midwest
    "IL": "Midwest", "IN": "Midwest", "IA": "Midwest", "KS": "Midwest",
    "MI": "Midwest", "MN": "Midwest", "MO": "Midwest", "NE": "Midwest",
    "ND": "Midwest", "OH": "Midwest", "SD": "Midwest", "WI": "Midwest",
    # South
    "AL": "South", "AR": "South", "DE": "South", "FL": "South",
    "GA": "South", "KY": "South", "LA": "South", "MD": "South",
    "MS": "South", "NC": "South", "OK": "South", "SC": "South",
    "TN": "South", "TX": "South", "VA": "South", "WV": "South",
    "DC": "South",
    # West
    "AK": "West", "AZ": "West", "CA": "West", "CO": "West",
    "HI": "West", "ID": "West", "MT": "West", "NV": "West",
    "NM": "West", "OR": "West", "UT": "West", "WA": "West", "WY": "West",
    # Territories — separate but include
    "PR": "Territory", "VI": "Territory", "GU": "Territory",
    "AS": "Territory", "MP": "Territory",
}


# SOC 2018 Major Groups (22 + Military + Not in Workforce). The classifier uses
# these descriptions to bucket the dataset's snake_case occupation strings.
MAPPINGS = CountryMappings(
    country="USA",
    locale="en",
    hf_split="train",
    axes=[REGION, AGE_GEN, SEX],
    persona_columns={
        "persona": "[Summary]",
        "professional_persona": "[Profession]",
        "sports_persona": "[Sports]",
        "arts_persona": "[Arts]",
        "travel_persona": "[Travel]",
        "culinary_persona": "[Culinary]",
    },
    region_source_col="state",
    region_map=STATE_TO_REGION,
    age_gen_labels=["young", "middle_aged", "elderly"],
)
