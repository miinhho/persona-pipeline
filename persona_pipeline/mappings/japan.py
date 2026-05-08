"""Japan — native region column (8 areas), JSOC 11-group, 男/女, no family_persona column."""
from persona_pipeline.mappings._base import (
    CountryMappings, REGION, AGE_GEN, SEX, OCCUPATION_GROUP,
)


OCCUPATION_GROUPS: dict[str, list[str]] = {
    "管理職": ["管理職", "経営", "役員", "代表", "社長", "部長", "課長"],
    "専門・技術職": ["医師", "看護", "教員", "教師", "教授", "研究", "技術", "エンジニア",
                  "開発", "プログラマ", "デザイナ", "弁護士", "会計士", "薬剤"],
    "事務職": ["事務", "経理", "総務", "人事", "秘書"],
    "販売職": ["販売", "営業", "店員", "販売員"],
    "サービス職": ["サービス", "介護", "美容", "理容", "調理", "ホテル", "旅館", "観光"],
    "保安職": ["警察", "消防", "警備", "自衛"],
    "農林漁業": ["農業", "畜産", "林業", "漁業", "養殖"],
    "生産工程": ["製造", "生産", "工場", "組立", "加工", "建設", "鉄鋼", "機械器具"],
    "輸送・機械運転": ["運転", "操縦", "運輸", "輸送", "鉄道", "航空"],
    "建設・採掘": ["建設", "土木", "採掘", "建築"],
    "運搬・清掃": ["運搬", "清掃", "包装", "配達", "倉庫"],
    "無職・引退": ["無職", "引退", "退職", "学生"],
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
    occupation_groups=OCCUPATION_GROUPS,
    region_keywords={
        "関東地方": ["関東", "東京", "神奈川", "埼玉", "千葉", "茨城", "栃木", "群馬"],
        "近畿地方": ["近畿", "関西", "大阪", "京都", "兵庫", "奈良", "滋賀", "和歌山"],
        "中部地方": ["中部", "愛知", "静岡", "岐阜", "三重", "新潟", "富山", "石川", "福井", "山梨", "長野"],
        "九州地方": ["九州", "福岡", "佐賀", "長崎", "熊本", "大分", "宮崎", "鹿児島", "沖縄"],
        "東北地方": ["東北", "青森", "岩手", "宮城", "秋田", "山形", "福島"],
        "中国地方": ["中国地方", "広島", "岡山", "山口", "鳥取", "島根"],
        "北海道地方": ["北海道"],
        "四国地方": ["四国", "愛媛", "香川", "徳島", "高知"],
    },
    age_gen_keywords={
        "若年": ["若年", "若い", "青年", "20代", "30代前半"],
        "中高年": ["中高年", "中年", "壮年", "30代", "40代", "50代", "60代前半"],
        "高齢": ["高齢", "老年", "60代", "70代", "80代", "シニア"],
    },
    sex_keywords={
        "男": ["男", "男性", "オス"],
        "女": ["女", "女性", "メス"],
    },
    occupation_keywords={k: [k, *v[:3]] for k, v in OCCUPATION_GROUPS.items()},
)
