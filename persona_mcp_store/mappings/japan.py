"""Japan — native region column (8 areas), JSOC 11-group, 男/女, no family_persona column."""
from persona_mcp_store.mappings._base import (
    CountryMappings, REGION, AGE_GEN, SEX, OCCUPATION_GROUP,
)


# Note: the Japan dataset's `occupation` column is industry × company-size text
# ("小売業 大手", "金融業 中堅") rather than a job title. The classifier uses these
# definitions to infer the most likely JSOC group from that signal.
JSOC_GROUP_DEFINITIONS: dict[str, str] = {
    "管理職": "経営者、役員、部長、課長などの組織管理者。経営層を含む大企業や公的機関での管理職。",
    "専門・技術職": "医師、看護師、教員、研究者、エンジニア、デザイナーなど高度専門・技術職。金融・保険・診療所などの専門業務もここに含む。",
    "事務職": "一般事務、経理、総務、人事、秘書など。公務員(地方/国家)、卸売業・金融業の事務系業務はここに分類。",
    "販売職": "販売員、営業、店員、レジ係。小売業の現場業務を含む。",
    "サービス職": "介護、美容、調理、宿泊、観光、飲食などの対人サービス。",
    "保安職": "警察、消防、警備、自衛官。",
    "農林漁業": "農業、畜産、林業、漁業、養殖の従事者。",
    "生産工程": "製造、生産、加工、組立など工場内の作業。製造業の現場業務はここに分類。",
    "輸送・機械運転": "車両・機械の運転、運輸、鉄道、航空、操縦。郵便・運送業の配達員もここ。",
    "建設・採掘": "建設、土木、採掘、建築などの作業員。",
    "運搬・清掃": "運搬、清掃、包装、配達、倉庫業務。",
    "無職・引退": "無職、退職者、学生、家事従事者。",
}


MAPPINGS = CountryMappings(
    country="Japan",
    locale="ja",
    hf_split="train",
    axes=[REGION, AGE_GEN, SEX, OCCUPATION_GROUP],
    persona_columns={
        "persona": "[要約]",
        "professional_persona": "[職業]",
        "sports_persona": "[スポーツ]",
        "arts_persona": "[芸術]",
        "travel_persona": "[旅行]",
        "culinary_persona": "[料理]",
    },
    region_source_col="region",
    region_map=None,
    sex_map={"男": "男", "女": "女"},
    occupation_source_col="occupation",
    occupation_group_definitions=JSOC_GROUP_DEFINITIONS,
    age_gen_labels=["若年", "中高年", "高齢"],
)
