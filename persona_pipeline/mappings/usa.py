"""USA — US Census 4 regions (mapped from 52 states), SOC 22-group occupation."""
from persona_pipeline.mappings._base import (
    CountryMappings, REGION, AGE_GEN, SEX, OCCUPATION_GROUP,
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
SOC_GROUP_DEFINITIONS: dict[str, str] = {
    "Management": "Managers, executives, CEOs, CFOs, directors, supervisors, administrators, legislators.",
    "Business and Financial": "Analysts, accountants, auditors, financial advisors, buyers, loan officers, tax preparers, HR, fundraisers.",
    "Computer and Mathematical": "Software developers, programmers, data scientists, web developers, network admins, mathematicians, statisticians, actuaries.",
    "Architecture and Engineering": "Architects, engineers (mechanical, electrical, civil, etc.), drafters, surveyors.",
    "Life, Physical, and Social Science": "Scientists, biologists, chemists, physicists, geologists, psychologists, sociologists, researchers.",
    "Community and Social Service": "Social workers, counselors, clergy, community/social-human service workers.",
    "Legal": "Lawyers, judges, paralegals, law clerks.",
    "Education": "Teachers, professors, instructors, tutors, librarians, school workers (kindergarten through postsecondary).",
    "Arts, Design, Entertainment, Sports, and Media": "Artists, designers, musicians, actors, writers, editors, photographers, athletes, dancers, reporters, broadcast/media workers.",
    "Healthcare Practitioners": "Physicians, nurses, pharmacists, dentists, veterinarians, therapists, surgeons.",
    "Healthcare Support": "Nursing assistants, home-health aides, medical assistants, orderlies, phlebotomists, therapy assistants.",
    "Protective Service": "Police, firefighters, security guards, correctional officers, detectives.",
    "Food Preparation and Serving": "Cooks, chefs, waiters, bartenders, fast-food workers, hosts, dishwashers, counter workers.",
    "Building and Grounds Cleaning": "Janitors, cleaners, groundskeepers, housekeeping, landscaping, pest control.",
    "Personal Care and Service": "Barbers, hairdressers, childcare workers, fitness instructors, personal-care aides, funeral workers, tour guides.",
    "Sales": "Sales reps, cashiers, retail clerks, telemarketers, real-estate agents, wholesale and insurance sales.",
    "Office and Administrative Support": "Clerks, secretaries, receptionists, data-entry, billing, shipping, dispatchers, administrative assistants.",
    "Farming, Fishing, and Forestry": "Farmers, ranchers, fishers, foresters, agricultural workers, loggers.",
    "Construction and Extraction": "Construction workers, carpenters, electricians, plumbers, masons, roofers, painters, miners, pipefitters.",
    "Installation, Maintenance, and Repair": "Mechanics, repair workers, installers, maintenance workers, repair technicians.",
    "Production": "Assemblers, machinists, welders, production operators, fabricators, tool & die makers.",
    "Transportation and Material Moving": "Drivers (truck/taxi/bus), pilots, transport workers, delivery, couriers, warehouse workers, laborers, freight handlers.",
    "Military": "Military personnel, armed forces, soldiers, marines, navy, air force, national guard.",
    "Not in Workforce": "Not in workforce, unemployed, homemakers, retirees, students.",
}


MAPPINGS = CountryMappings(
    country="USA",
    locale="en",
    hf_split="train",
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
    region_map=STATE_TO_REGION,
    occupation_source_col="occupation",
    occupation_group_definitions=SOC_GROUP_DEFINITIONS,
    region_keywords={
        "Northeast": ["northeast", "new york", "boston", "philadelphia",
                      "ny", "nj", "ma", "ct", "pa"],
        "Midwest": ["midwest", "chicago", "detroit", "minneapolis", "il", "mi",
                    "oh", "wi", "mn", "in"],
        "South": ["south", "southern", "texas", "florida", "atlanta", "dallas",
                  "houston", "miami", "tx", "fl", "ga", "nc", "va", "dc"],
        "West": ["west", "california", "los angeles", "san francisco", "seattle",
                 "denver", "ca", "wa", "or", "co", "az", "nv"],
        "Territory": ["puerto rico", "guam", "virgin islands", "samoa"],
    },
    age_gen_keywords={
        "young": ["young", "youth", "youthful", "20s", "early 30s", "millennial"],
        "middle_aged": ["middle", "middle-aged", "30s", "40s", "50s", "midlife"],
        "elderly": ["elderly", "old", "senior", "60s", "70s", "80s", "retiree", "boomer"],
    },
    sex_keywords={
        "Male": ["male", "man", "men", "guy", "boy"],
        "Female": ["female", "woman", "women", "girl", "lady"],
    },
    occupation_keywords={
        # Natural-language queries don't use snake_case, so keywords are space-separated.
        "Management": ["manager", "executive", "ceo", "director", "supervisor"],
        "Business and Financial": ["analyst", "accountant", "financial"],
        "Computer and Mathematical": ["software", "programmer", "developer", "engineer software", "data scientist"],
        "Architecture and Engineering": ["architect", "engineer"],
        "Life, Physical, and Social Science": ["scientist", "researcher"],
        "Community and Social Service": ["social worker", "counselor"],
        "Legal": ["lawyer", "attorney", "paralegal"],
        "Education": ["teacher", "professor", "tutor", "librarian"],
        "Arts, Design, Entertainment, Sports, and Media": ["artist", "designer", "musician", "writer", "athlete"],
        "Healthcare Practitioners": ["doctor", "nurse", "pharmacist", "physician", "therapist"],
        "Healthcare Support": ["nursing assistant", "medical assistant"],
        "Protective Service": ["police", "firefighter", "security guard"],
        "Food Preparation and Serving": ["cook", "chef", "waiter", "bartender"],
        "Building and Grounds Cleaning": ["janitor", "cleaner"],
        "Personal Care and Service": ["barber", "hairdresser"],
        "Sales": ["sales", "cashier", "retail"],
        "Office and Administrative Support": ["clerk", "secretary", "receptionist", "office worker"],
        "Farming, Fishing, and Forestry": ["farmer", "rancher", "fisher"],
        "Construction and Extraction": ["construction worker", "carpenter", "electrician", "plumber"],
        "Installation, Maintenance, and Repair": ["mechanic", "technician"],
        "Production": ["assembler", "welder", "factory worker"],
        "Transportation and Material Moving": ["driver", "truck driver", "delivery", "warehouse"],
        "Military": ["soldier", "marine", "military"],
        "Not in Workforce": ["unemployed", "homemaker", "retired", "student"],
    },
)
