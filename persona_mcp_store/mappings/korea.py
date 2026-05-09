"""Korea — KSCO 9-group occupation, 6 regions, Korean labels."""
from persona_mcp_store.mappings._base import (
    CountryMappings, REGION, AGE_GEN, SEX,
)


PROVINCE_TO_REGION: dict[str, str] = {
    "서울": "수도권", "경기": "수도권", "인천": "수도권",
    "부산": "영남권", "대구": "영남권", "울산": "영남권",
    "경상남": "영남권", "경상북": "영남권",
    "광주": "호남권", "전북": "호남권", "전라남": "호남권",
    "대전": "충청권", "세종": "충청권",
    "충청북": "충청권", "충청남": "충청권",
    "강원": "강원권",
    "제주": "제주권",
}

MAPPINGS = CountryMappings(
    country="Korea",
    locale="ko",
    hf_split="train",
    axes=[REGION, AGE_GEN, SEX],
    persona_columns={
        "persona": "[요약]",
        "professional_persona": "[직업]",
        "sports_persona": "[스포츠]",
        "arts_persona": "[예술]",
        "travel_persona": "[여행]",
        "culinary_persona": "[음식]",
        "family_persona": "[가족]",
    },
    region_source_col="province",
    region_map=PROVINCE_TO_REGION,
    age_gen_labels=["청년", "중장년", "노년"],
)
