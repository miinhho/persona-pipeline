"""France — 13 régions administratives (mapped from 100 départements), native PCS 8-group."""
from persona_mcp_store.mappings._base import (
    CountryMappings, REGION, AGE_GEN, SEX,
)


# 100 départements → 13 régions (2016 reform). DOM is grouped as "Outre-mer".
DEPARTEMENT_TO_REGION: dict[str, str] = {
    # Île-de-France
    "Paris": "Île-de-France", "Hauts-de-Seine": "Île-de-France",
    "Seine-Saint-Denis": "Île-de-France", "Val-de-Marne": "Île-de-France",
    "Yvelines": "Île-de-France", "Seine-et-Marne": "Île-de-France",
    "Essonne": "Île-de-France", "Val-d'Oise": "Île-de-France",
    # Auvergne-Rhône-Alpes
    "Rhône": "Auvergne-Rhône-Alpes", "Isère": "Auvergne-Rhône-Alpes",
    "Loire": "Auvergne-Rhône-Alpes", "Haute-Savoie": "Auvergne-Rhône-Alpes",
    "Puy-de-Dôme": "Auvergne-Rhône-Alpes", "Ain": "Auvergne-Rhône-Alpes",
    "Drôme": "Auvergne-Rhône-Alpes", "Ardèche": "Auvergne-Rhône-Alpes",
    "Allier": "Auvergne-Rhône-Alpes", "Cantal": "Auvergne-Rhône-Alpes",
    "Haute-Loire": "Auvergne-Rhône-Alpes", "Savoie": "Auvergne-Rhône-Alpes",
    # Hauts-de-France
    "Nord": "Hauts-de-France", "Pas-de-Calais": "Hauts-de-France",
    "Somme": "Hauts-de-France", "Oise": "Hauts-de-France",
    "Aisne": "Hauts-de-France",
    # Provence-Alpes-Côte d'Azur
    "Bouches-du-Rhône": "Provence-Alpes-Côte d'Azur",
    "Alpes-Maritimes": "Provence-Alpes-Côte d'Azur",
    "Var": "Provence-Alpes-Côte d'Azur",
    "Vaucluse": "Provence-Alpes-Côte d'Azur",
    "Hautes-Alpes": "Provence-Alpes-Côte d'Azur",
    "Alpes-de-Haute-Provence": "Provence-Alpes-Côte d'Azur",
    # Nouvelle-Aquitaine
    "Gironde": "Nouvelle-Aquitaine", "Pyrénées-Atlantiques": "Nouvelle-Aquitaine",
    "Charente-Maritime": "Nouvelle-Aquitaine", "Dordogne": "Nouvelle-Aquitaine",
    "Landes": "Nouvelle-Aquitaine", "Lot-et-Garonne": "Nouvelle-Aquitaine",
    "Vienne": "Nouvelle-Aquitaine", "Deux-Sèvres": "Nouvelle-Aquitaine",
    "Charente": "Nouvelle-Aquitaine", "Corrèze": "Nouvelle-Aquitaine",
    "Creuse": "Nouvelle-Aquitaine", "Haute-Vienne": "Nouvelle-Aquitaine",
    # Occitanie
    "Haute-Garonne": "Occitanie", "Hérault": "Occitanie",
    "Pyrénées-Orientales": "Occitanie", "Gard": "Occitanie",
    "Tarn": "Occitanie", "Aude": "Occitanie",
    "Aveyron": "Occitanie", "Tarn-et-Garonne": "Occitanie",
    "Lot": "Occitanie", "Lozère": "Occitanie",
    "Hautes-Pyrénées": "Occitanie", "Gers": "Occitanie", "Ariège": "Occitanie",
    # Pays de la Loire
    "Loire-Atlantique": "Pays de la Loire", "Maine-et-Loire": "Pays de la Loire",
    "Sarthe": "Pays de la Loire", "Vendée": "Pays de la Loire",
    "Mayenne": "Pays de la Loire",
    # Bretagne
    "Ille-et-Vilaine": "Bretagne", "Finistère": "Bretagne",
    "Morbihan": "Bretagne", "Côtes-d'Armor": "Bretagne",
    # Normandie
    "Seine-Maritime": "Normandie", "Calvados": "Normandie",
    "Manche": "Normandie", "Eure": "Normandie", "Orne": "Normandie",
    # Grand Est
    "Bas-Rhin": "Grand Est", "Haut-Rhin": "Grand Est",
    "Moselle": "Grand Est", "Meurthe-et-Moselle": "Grand Est",
    "Marne": "Grand Est", "Aube": "Grand Est",
    "Vosges": "Grand Est", "Ardennes": "Grand Est",
    "Haute-Marne": "Grand Est", "Meuse": "Grand Est",
    # Bourgogne-Franche-Comté
    "Côte-d'Or": "Bourgogne-Franche-Comté", "Saône-et-Loire": "Bourgogne-Franche-Comté",
    "Doubs": "Bourgogne-Franche-Comté", "Yonne": "Bourgogne-Franche-Comté",
    "Jura": "Bourgogne-Franche-Comté", "Nièvre": "Bourgogne-Franche-Comté",
    "Haute-Saône": "Bourgogne-Franche-Comté", "Territoire de Belfort": "Bourgogne-Franche-Comté",
    # Centre-Val de Loire
    "Indre-et-Loire": "Centre-Val de Loire", "Loiret": "Centre-Val de Loire",
    "Loir-et-Cher": "Centre-Val de Loire", "Eure-et-Loir": "Centre-Val de Loire",
    "Cher": "Centre-Val de Loire", "Indre": "Centre-Val de Loire",
    # Corse
    "Corse-du-Sud": "Corse", "Haute-Corse": "Corse",
    # DOM (separate régions in reality, grouped here for region-axis purposes).
    "La Réunion": "Outre-mer", "Guadeloupe": "Outre-mer",
    "Martinique": "Outre-mer", "Guyane": "Outre-mer", "Mayotte": "Outre-mer",
}


NATIVE_OCCUPATIONS = [
    "Retraités", "Employés", "Professions intermédiaires",
    "Autres sans activité professionnelle", "Ouvriers",
    "Cadres et professions intellectuelles supérieures",
    "Artisans, commerçants, chefs d'entreprise",
    "Agriculteurs exploitants",
]


MAPPINGS = CountryMappings(
    country="France",
    locale="fr",
    hf_split="train",
    axes=[REGION, AGE_GEN, SEX],
    persona_columns={
        "persona": "[Résumé]",
        "professional_persona": "[Profession]",
        "sports_persona": "[Sports]",
        "arts_persona": "[Arts]",
        "travel_persona": "[Voyage]",
        "culinary_persona": "[Culinaire]",
    },
    region_source_col="departement",
    region_map=DEPARTEMENT_TO_REGION,
    age_gen_labels=["jeune", "adulte", "âgé"],
)
