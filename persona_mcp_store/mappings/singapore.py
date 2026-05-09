"""Singapore — city-state, 3 axes (no region). 14 native occupation categories."""
from persona_mcp_store.mappings._base import (
    CountryMappings, AGE_GEN, SEX, OCCUPATION_GROUP,
)


NATIVE_OCCUPATIONS = [
    "Retired", "Associate Professional or Technician", "Professional",
    "Homemaker", "Senior Official or Manager", "Unemployed",
    "Clerical Worker", "Service or Sales Worker", "Student",
    "Plant or Machine Operator or Assembler",
    "Production Craftsman or Related Worker", "National Service",
    "Cleaner, Labourer or Related Worker", "Agricultural or Fishery Worker",
]


MAPPINGS = CountryMappings(
    country="Singapore",
    locale="en",
    hf_split="train",
    axes=[AGE_GEN, SEX, OCCUPATION_GROUP],
    persona_columns={
        "persona": "[Summary]",
        "professional_persona": "[Profession]",
        "sports_persona": "[Sports]",
        "arts_persona": "[Arts]",
        "travel_persona": "[Travel]",
        "culinary_persona": "[Culinary]",
    },
    occupation_source_col="occupation",
    occupation_group_definitions=None,
    age_gen_labels=["young", "middle_aged", "elderly"],
)
