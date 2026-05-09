"""India — 6 zones (mapped from 36 states/UTs), NCO 10-group occupation. Uses en_IN split only."""
from persona_mcp_store.mappings._base import (
    CountryMappings, REGION, AGE_GEN, SEX,
)


# Census of India / RBI zoning — 36 states/UTs grouped into 6 zones.
STATE_TO_ZONE: dict[str, str] = {
    # North
    "Delhi": "North", "Haryana": "North", "Himachal Pradesh": "North",
    "Jammu and Kashmir": "North", "Ladakh": "North", "Punjab": "North",
    "Rajasthan": "North", "Uttarakhand": "North", "Chandigarh": "North",
    # South
    "Andhra Pradesh": "South", "Karnataka": "South", "Kerala": "South",
    "Tamil Nadu": "South", "Telangana": "South",
    "Puducherry": "South", "Lakshadweep": "South",
    "Andaman and Nicobar Islands": "South",
    # East
    "Bihar": "East", "Jharkhand": "East", "Odisha": "East",
    "West Bengal": "East",
    # West
    "Goa": "West", "Gujarat": "West", "Maharashtra": "West",
    "Dadra and Nagar Haveli and Daman and Diu": "West",
    # Central
    "Chhattisgarh": "Central", "Madhya Pradesh": "Central",
    "Uttar Pradesh": "Central",
    # Northeast
    "Arunachal Pradesh": "Northeast", "Assam": "Northeast",
    "Manipur": "Northeast", "Meghalaya": "Northeast",
    "Mizoram": "Northeast", "Nagaland": "Northeast",
    "Sikkim": "Northeast", "Tripura": "Northeast",
}


# NCO-2015 / ISCO-08 compatible 10 major groups + Not in Workforce. The dataset's
# free-text occupation strings often look like "Building Construction Labourers, Other"
# or "Market-Oriented Crop and Animal Producers, Other" — the classifier maps these
# to the appropriate group using the descriptions below.
MAPPINGS = CountryMappings(
    country="India",
    locale="en",
    hf_split="en_IN",
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
    region_map=STATE_TO_ZONE,
    age_gen_labels=["young", "middle_aged", "elderly"],
)
