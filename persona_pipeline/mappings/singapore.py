"""Singapore — city-state, 3 axes (no region). 14 native occupation categories."""
from persona_pipeline.mappings._base import (
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
    occupation_groups=None,
    age_gen_keywords={
        "young": ["young", "youth", "20s", "early 30s"],
        "middle_aged": ["middle", "middle-aged", "30s", "40s", "50s"],
        "elderly": ["elderly", "old", "senior", "60s", "70s", "80s"],
    },
    sex_keywords={
        "Male": ["male", "man", "men", "guy", "boy"],
        "Female": ["female", "woman", "women", "girl", "lady"],
    },
    occupation_keywords={
        occ: [occ, *occ.lower().split()[:2]] for occ in NATIVE_OCCUPATIONS
    },
)
