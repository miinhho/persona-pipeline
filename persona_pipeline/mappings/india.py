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


# NCO-2015 / ISCO-08 compatible 10 major groups + Not in Workforce. The dataset's
# free-text occupation strings often look like "Building Construction Labourers, Other"
# or "Market-Oriented Crop and Animal Producers, Other" — the classifier maps these
# to the appropriate group using the descriptions below.
NCO_GROUP_DEFINITIONS: dict[str, str] = {
    "Managers": "Managers, directors, executives, officials, heads, chiefs, supervisors at any level.",
    "Professionals": "Engineers, doctors, scientists, teachers, professors, lawyers, accountants, architects, software developers, designers, consultants — high-skill professional occupations.",
    "Technicians and Associate Professionals": "Technicians, draftsmen, nurses, pharmacists, lab technicians, paramedics, computer operators, mid-skill technical workers.",
    "Clerical Support Workers": "Clerks, secretaries, receptionists, data-entry, typists, office assistants, customer-service reps in clerical roles.",
    "Service and Sales Workers": "Shop attendants, salespersons, market vendors, stall sellers, telemarketers, advertising sales agents, waiters, cooks, barbers, hairdressers, security/police/firefighters, hospitality workers.",
    "Skilled Agricultural Workers": "Farmers, market-oriented crop/animal producers, horticulturists, fishermen, shepherds, plantation workers.",
    "Craft and Related Trades Workers": "Carpenters, masons, tailors, weavers, electricians, plumbers, welders, mechanics, well-diggers and other skilled trades.",
    "Plant and Machine Operators and Assemblers": "Machine/plant operators, drivers, conductors, pilots, assemblers, machinists, packing/filling machine tenders.",
    "Elementary Occupations": "Labourers, construction/maintenance labourers, domestic helpers, cleaners, sweepers, porters, loaders, hawkers, rickshaw pullers, helpers, packers — unskilled physical work.",
    "Armed Forces": "Army, navy, air force, soldiers, military officers.",
    "Not in Workforce": "No occupation, retired, homemakers, students, unemployed.",
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
    occupation_group_definitions=NCO_GROUP_DEFINITIONS,
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
    occupation_keywords={
        "Managers": ["manager", "director", "executive", "supervisor"],
        "Professionals": ["engineer", "doctor", "scientist", "teacher", "lawyer", "accountant", "architect", "developer"],
        "Technicians and Associate Professionals": ["technician", "nurse", "pharmacist"],
        "Clerical Support Workers": ["clerk", "secretary", "receptionist"],
        "Service and Sales Workers": ["sales", "cashier", "vendor", "waiter", "barber"],
        "Skilled Agricultural Workers": ["farmer", "agricultural", "fisherman"],
        "Craft and Related Trades Workers": ["carpenter", "mason", "electrician", "plumber", "welder", "mechanic"],
        "Plant and Machine Operators and Assemblers": ["operator", "driver", "pilot"],
        "Elementary Occupations": ["labourer", "laborer", "cleaner", "porter", "helper"],
        "Armed Forces": ["army", "navy", "air force", "soldier"],
        "Not in Workforce": ["unemployed", "homemaker", "retired", "student"],
    },
)
