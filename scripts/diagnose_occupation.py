"""Diagnose occupation classification quality per country.

For countries with keyword-based `occupation_groups` (Korea/Japan/USA/India),
print the post-enrich distribution and the top free-text values that fall into
'Other' so you can spot which keyword set needs boosting.

Singapore / Brazil / France use the dataset's native category column
(`occupation_groups=None`) and are skipped — those countries don't have
this problem by design.

Usage:
    python scripts/diagnose_occupation.py                 # all countries
    python scripts/diagnose_occupation.py Korea Japan     # subset
    python scripts/diagnose_occupation.py --top-other 30  # show more samples
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

# Make persona_pipeline importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl

from persona_pipeline.cli._paths import raw_path
from persona_pipeline.mappings import COUNTRIES, get_mappings


def _classify(text: str | None, groups: dict[str, list[str]]) -> str:
    if not text:
        return "Other"
    for group, keywords in groups.items():
        if any(kw in text for kw in keywords):
            return group
    return "Other"


def diagnose(country: str, top_other: int) -> None:
    mapping = get_mappings(country)
    if mapping.occupation_groups is None:
        print(f"\n## {country} — uses native occupation category (no keywords needed), skip")
        return

    rp = raw_path(country)
    if not Path(rp).exists():
        print(f"\n## {country} — raw not downloaded ({rp}), skip")
        return

    src = mapping.occupation_source_col
    df = pl.read_parquet(rp).select([src])
    total = len(df)
    n_unique = df[src].n_unique()

    print(f"\n## {country}  (source: {src!r}, {total:,} rows, {n_unique:,} unique values)")

    groups = [_classify(o, mapping.occupation_groups) for o in df[src].to_list()]
    dist = Counter(groups)
    print(f"   distribution:")
    for g, n in sorted(dist.items(), key=lambda kv: -kv[1]):
        marker = " ←" if g == "Other" else ""
        print(f"     {g:30s} {n:>9,} ({n/total*100:>5.2f}%){marker}")

    other_share = dist.get("Other", 0) / total * 100
    if other_share >= 5 and top_other > 0:
        print(f"   top {top_other} unmatched values (keyword gaps):")
        other_samples = [o for o, g in zip(df[src].to_list(), groups) if g == "Other"]
        for occ, n in Counter(other_samples).most_common(top_other):
            print(f"     {n:>6,}  {occ}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("countries", nargs="*", help="default: all 7")
    ap.add_argument("--top-other", type=int, default=15, help="how many 'Other' samples to show")
    args = ap.parse_args()

    countries = args.countries or COUNTRIES
    for c in countries:
        diagnose(c, top_other=args.top_other)


if __name__ == "__main__":
    main()
