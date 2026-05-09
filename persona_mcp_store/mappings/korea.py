"""Korea — KSCO 9-group occupation, 6 regions, Korean labels."""
from persona_mcp_store.mappings._base import (
    CountryMappings, REGION, AGE_GEN, SEX, OCCUPATION_GROUP,
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

KSCO_GROUP_DEFINITIONS: dict[str, str] = {
    "관리자": "임원, 팀장, 부서장, 경영자, 사장, 장교 등 조직 관리자.",
    "전문가": "교사, 의사, 간호사, 변호사, 회계사, 엔지니어, 개발자, 연구원, 디자이너, 사회복지사, 강사 등 고숙련 전문직.",
    "사무": "일반 사무, 경리, 총무, 행정, 비서 등 사무 종사자.",
    "서비스": "상담, 안내, 미용, 조리, 음식, 숙박, 여행, 보안, 경비, 경찰, 부동산, 돌봄, 보육 등 대인 서비스직.",
    "판매": "판매, 영업, 매장 종사자, 캐셔, 텔레마케터 등.",
    "농림어업": "농업, 축산, 임업, 어업 종사자.",
    "기능원": "정비, 수리, 조립, 용접, 배관, 금형, 판금, 설치원 등 숙련 기능 종사자.",
    "장치조작": "차량/기계 운전, 조종, 기관사, 운송, 관제사, 장치 조작 종사자.",
    "단순노무": "청소, 포장, 하역, 배달, 택배, 가사, 주차/시설 관리원 등 단순 노무직.",
    "무직": "무직, 비경제활동, 학생, 퇴직자, 주부 등.",
}


MAPPINGS = CountryMappings(
    country="Korea",
    locale="ko",
    hf_split="train",
    axes=[REGION, AGE_GEN, SEX, OCCUPATION_GROUP],
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
    occupation_source_col="occupation",
    occupation_group_definitions=KSCO_GROUP_DEFINITIONS,
    age_gen_labels=["청년", "중장년", "노년"],
)
