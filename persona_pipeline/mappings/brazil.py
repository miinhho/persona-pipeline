"""Brazil — IBGE 5 regiões, native CBO 11-group occupation column."""
from persona_pipeline.mappings._base import (
    CountryMappings, REGION, AGE_GEN, SEX, OCCUPATION_GROUP,
)


STATE_TO_REGIAO: dict[str, str] = {
    "Acre": "Norte", "Amazonas": "Norte", "Amapá": "Norte",
    "Pará": "Norte", "Rondônia": "Norte", "Roraima": "Norte",
    "Tocantins": "Norte",
    "Alagoas": "Nordeste", "Bahia": "Nordeste", "Ceará": "Nordeste",
    "Maranhão": "Nordeste", "Paraíba": "Nordeste", "Pernambuco": "Nordeste",
    "Piauí": "Nordeste", "Rio Grande do Norte": "Nordeste",
    "Sergipe": "Nordeste",
    "Distrito Federal": "Centro-Oeste", "Goiás": "Centro-Oeste",
    "Mato Grosso": "Centro-Oeste", "Mato Grosso do Sul": "Centro-Oeste",
    "Espírito Santo": "Sudeste", "Minas Gerais": "Sudeste",
    "Rio de Janeiro": "Sudeste", "São Paulo": "Sudeste",
    "Paraná": "Sul", "Rio Grande do Sul": "Sul", "Santa Catarina": "Sul",
}


NATIVE_OCCUPATIONS = [
    "Trabalhador dos serviços, vendedor do comércio ou mercado",
    "Ocupação elementar",
    "Profissional das ciências ou intelectual",
    "Trabalhador qualificado, operário ou artesão da construção, das artes mecânicas ou de outro ofício",
    "Trabalhador de apoio administrativo",
    "Técnico ou profissional de nível médio",
    "Operador de instalação ou máquina ou montador",
    "Trabalhador qualificado da agropecuária, florestal, da caça ou da pesca",
    "Diretor ou gerente",
    "Ocupação mal definida",
    "Membro das forças armadas, policial ou bombeiro militar",
]


MAPPINGS = CountryMappings(
    country="Brazil",
    locale="pt",
    hf_split="train",
    axes=[REGION, AGE_GEN, SEX, OCCUPATION_GROUP],
    persona_columns={
        "persona": "[Resumo]",
        "professional_persona": "[Profissão]",
        "sports_persona": "[Esportes]",
        "arts_persona": "[Artes]",
        "travel_persona": "[Viagem]",
        "culinary_persona": "[Culinária]",
    },
    region_source_col="state",
    region_map=STATE_TO_REGIAO,
    occupation_source_col="occupation",
    occupation_group_definitions=None,
    region_keywords={
        "Norte": ["norte", "amazonas", "pará", "acre"],
        "Nordeste": ["nordeste", "bahia", "ceará", "pernambuco", "salvador", "recife"],
        "Centro-Oeste": ["centro-oeste", "centro oeste", "brasília", "goiás", "goiana"],
        "Sudeste": ["sudeste", "são paulo", "rio de janeiro", "minas gerais", "paulistano", "carioca"],
        "Sul": ["sul", "porto alegre", "curitiba", "florianópolis", "gaúcho", "paranaense"],
    },
    age_gen_keywords={
        "jovem": ["jovem", "juventude", "20 anos", "30 anos"],
        "adulto": ["adulto", "meia-idade", "40 anos", "50 anos"],
        "idoso": ["idoso", "idosa", "velho", "velha", "60 anos", "70 anos"],
    },
    sex_keywords={
        "Masculino": ["homem", "masculino", "rapaz"],
        "Feminino": ["mulher", "feminino", "moça"],
    },
    occupation_keywords={occ: occ.split()[:3] for occ in NATIVE_OCCUPATIONS},
)
