"""Download all 7 Nemotron-Personas datasets and generate schema analysis.

Saves per-country raw to data/raw/{country}/personas.parquet and writes a
combined report at data/analysis/all_countries_schema.md.
"""

import json
from pathlib import Path
from typing import cast

import polars as pl
from datasets import get_dataset_split_names, load_dataset


def pick_split(splits: list[str]) -> str:
    """Pick a split: prefer 'train', fall back to en_*/*_en for multilingual datasets, else the first."""
    if "train" in splits:
        return "train"
    for s in splits:
        sl = s.lower()
        if sl.startswith("en_") or sl.endswith("_en") or sl == "en":
            return s
    return splits[0]


COUNTRIES = ["USA", "Japan", "India", "Singapore", "Brazil", "France", "Korea"]
RAW_DIR = Path("data/raw")
ANALYSIS_DIR = Path("data/analysis")
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)


def download(country: str) -> Path:
    out = RAW_DIR / country / "personas.parquet"
    if out.exists():
        print(f"[{country}] cached: {out}")
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    repo = f"nvidia/Nemotron-Personas-{country}"
    splits = get_dataset_split_names(repo)
    split = pick_split(splits)
    print(f"[{country}] splits={splits} → using '{split}'", flush=True)
    ds = load_dataset(repo, split=split)
    df = cast(pl.DataFrame, pl.from_arrow(ds.data.table))
    df.write_parquet(out, compression="zstd")
    print(f"[{country}] {len(df):,} rows → {out}", flush=True)
    return out


def analyze(country: str, path: Path) -> dict:
    df = pl.read_parquet(path)
    info = {
        "country": country,
        "rows": len(df),
        "columns": [],
    }
    for col in df.columns:
        dtype = str(df[col].dtype)
        col_info = {
            "name": col,
            "dtype": dtype,
            "null_pct": float(df[col].null_count() / len(df) * 100),
        }
        # Demographic / categorical columns: unique value distribution.
        if dtype == "String":
            n_unique = df[col].n_unique()
            col_info["n_unique"] = n_unique
            if n_unique <= 50:
                top = df[col].value_counts(sort=True).head(50)
                col_info["values"] = [
                    {"value": r[col], "count": r["count"]} for r in top.iter_rows(named=True)
                ]
            elif n_unique <= 500:
                top = df[col].value_counts(sort=True).head(20)
                col_info["values_top20"] = [
                    {"value": r[col], "count": r["count"]} for r in top.iter_rows(named=True)
                ]
            else:
                col_info["values_sample"] = df[col].drop_nulls().head(5).to_list()
        elif dtype.startswith("Int") or dtype.startswith("Float"):
            col_info["min"] = float(df[col].min()) if df[col].null_count() < len(df) else None
            col_info["max"] = float(df[col].max()) if df[col].null_count() < len(df) else None
            col_info["mean"] = float(df[col].mean()) if df[col].null_count() < len(df) else None
        info["columns"].append(col_info)
    return info


def render_md(all_info: list[dict]) -> str:
    out = ["# Nemotron-Personas 7-country schema analysis\n"]

    out.append("## Summary\n")
    out.append("| country | rows | columns |\n|---|---|---|\n")
    for info in all_info:
        out.append(f"| {info['country']} | {info['rows']:,} | {len(info['columns'])} |\n")
    out.append("\n")

    col_sets = {info["country"]: {c["name"] for c in info["columns"]} for info in all_info}
    common = set.intersection(*col_sets.values())
    out.append("## Common columns (all countries)\n")
    out.append(", ".join(sorted(common)) + "\n\n")

    out.append("## Country-specific columns\n")
    for c, cols in col_sets.items():
        unique = cols - common
        if unique:
            out.append(f"- **{c}**: {', '.join(sorted(unique))}\n")
    out.append("\n")

    for info in all_info:
        out.append(f"## {info['country']} ({info['rows']:,} rows)\n\n")
        for col in info["columns"]:
            out.append(f"### `{col['name']}` ({col['dtype']}, null {col['null_pct']:.1f}%)\n")
            if "values" in col:
                out.append(f"unique: {col['n_unique']}\n\n")
                for v in col["values"]:
                    out.append(f"- `{v['value']}` ({v['count']:,})\n")
            elif "values_top20" in col:
                out.append(f"unique: {col['n_unique']} (top 20)\n\n")
                for v in col["values_top20"]:
                    out.append(f"- `{v['value']}` ({v['count']:,})\n")
            elif "values_sample" in col:
                out.append(f"unique: {col['n_unique']} (sample 5)\n\n")
                for v in col["values_sample"]:
                    out.append(f"- `{str(v)[:200]}`\n")
            elif "min" in col:
                out.append(f"min={col['min']}, max={col['max']}, mean={col['mean']:.2f}\n")
            out.append("\n")

    return "".join(out)


def main():
    all_info = []
    for c in COUNTRIES:
        path = download(c)
        info = analyze(c, path)
        all_info.append(info)
        # Per-country JSON.
        (ANALYSIS_DIR / f"{c}_schema.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2, default=str)
        )
        print(f"[{c}] analyzed", flush=True)

    md = render_md(all_info)
    out_md = ANALYSIS_DIR / "all_countries_schema.md"
    out_md.write_text(md, encoding="utf-8")
    print("\n=== analysis done ===")
    print(f"report: {out_md}")
    print(f"json: {ANALYSIS_DIR}/*_schema.json")


if __name__ == "__main__":
    main()
