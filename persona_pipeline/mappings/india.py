"""India — 6 zones (mapped from 36 states/UTs), NCO 10-group occupation. Uses en_IN split only."""
from persona_pipeline.mappings._base import (
    CountryMappings, REGION, AGE_GEN, SEX, OCCUPATION_GROUP,
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


# NCO-2015 / ISCO-08 compatible 10 major groups. Substring-matched against free-text occupation.
NCO_GROUPS: dict[str, list[str]] = {
    "Managers": ["manager", "director", "executive", "official", "head of",
                 "chief", "supervisor"],
    "Professionals": ["engineer", "doctor", "physician", "scientist", "researcher",
                      "teacher", "professor", "lawyer", "advocate", "accountant",
                      "architect", "developer", "programmer", "software",
                      "designer", "consultant"],
    "Technicians and Associate Professionals": ["technician", "associate professional",
                                                 "operator computer", "draftsman",
                                                 "paramedic", "nurse", "pharmacist"],
    "Clerical Support Workers": ["clerk", "secretary", "data entry", "receptionist",
                                  "typist", "office assistant"],
    "Service and Sales Workers": ["sales", "cashier", "shopkeeper", "vendor",
                                   "waiter", "cook", "chef", "barber", "hairdresser",
                                   "police", "security", "firefighter"],
    "Skilled Agricultural Workers": ["farmer", "agricultural", "horticulture",
                                      "fisherman", "shepherd", "plantation"],
    "Craft and Related Trades Workers": ["carpenter", "mason", "tailor", "weaver",
                                          "blacksmith", "goldsmith", "potter",
                                          "cobbler", "electrician", "plumber",
                                          "welder", "mechanic"],
    "Plant and Machine Operators and Assemblers": ["operator", "machine operator",
                                                    "driver", "conductor", "pilot",
                                                    "assembler", "machinist"],
    "Elementary Occupations": ["labourer", "laborer", "domestic", "cleaner",
                                "sweeper", "porter", "hawker", "rickshaw",
                                "construction worker", "helper"],
    "Armed Forces": ["army", "navy", "air force", "armed forces", "soldier",
                     "officer (army"],
    "Not in Workforce": ["no occupation", "retired", "homemaker", "housewife",
                         "student", "unemployed"],
}


MAPPINGS = CountryMappings(
    country="India",
    locale="en",
    hf_split="en_IN",
    axes=[REGION, AGE_GEN, SEX, OCCUPATION_GROUP],
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
    occupation_source_col="occupation",
    occupation_groups=NCO_GROUPS,
    region_keywords={
        "North": ["north", "delhi", "punjab", "rajasthan", "haryana", "northern"],
        "South": ["south", "tamil", "kerala", "karnataka", "andhra", "telangana",
                  "bangalore", "chennai", "hyderabad", "southern"],
        "East": ["east", "bihar", "bengal", "odisha", "kolkata", "eastern"],
        "West": ["west", "gujarat", "maharashtra", "mumbai", "pune", "goa", "western"],
        "Central": ["central", "uttar pradesh", "madhya pradesh", "chhattisgarh"],
        "Northeast": ["northeast", "assam", "manipur", "meghalaya", "nagaland",
                      "sikkim", "tripura"],
    },
    age_gen_keywords={
        "young": ["young", "youth", "20s", "early 30s"],
        "middle_aged": ["middle", "middle-aged", "30s", "40s", "50s"],
        "elderly": ["elderly", "old", "senior", "60s", "70s", "80s"],
    },
    sex_keywords={
        "Male": ["male", "man", "men", "boy"],
        "Female": ["female", "woman", "women", "girl", "lady"],
    },
    occupation_keywords={k: v[:5] for k, v in NCO_GROUPS.items()},
)
