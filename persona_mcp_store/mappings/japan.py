"""Japan — native region column (8 areas), JSOC 11-group, 男/女, no family_persona column."""
from persona_mcp_store.mappings._base import (
    CountryMappings, REGION, AGE_GEN, SEX,
)


# Note: the Japan dataset's `occupation` column is industry × company-size text
# ("小売業 大手", "金融業 中堅") rather than a job title. The classifier uses these
# definitions to infer the most likely JSOC group from that signal.
MAPPINGS = CountryMappings(
    country="Japan",
    locale="ja",
    hf_split="train",
    axes=[REGION, AGE_GEN, SEX],
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
    age_gen_labels=["若年", "中高年", "高齢"],
)
