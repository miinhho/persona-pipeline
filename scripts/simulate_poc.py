"""Persona simulation PoC — inject one archetype card as a Claude system prompt and run a task.

The point: see whether the segment-conditioned persona meaningfully shapes the response.
If yes, this becomes the basis for a `simulate` stage that fans the same task across
many archetypes and across countries.

Usage examples
--------------
# Pick the largest archetype in Korea, ask it about weekend plans.
python scripts/simulate_poc.py Korea --task "이번 주말에 뭐 하실 거예요?"

# Pick by exact segment_id.
python scripts/simulate_poc.py Korea \\
    --segment-id "수도권|중장년|남자|전문가" \\
    --task "최근 가장 큰 고민이 뭐예요?"

# Pick by NL query (uses the existing rule-based matcher).
python scripts/simulate_poc.py Korea --query "서울 30대 여자 사무직" \\
    --task "주말에 뭘 하면서 시간을 보내세요?"

# No API key → dry-run mode prints the prompts only.
python scripts/simulate_poc.py Korea --task "..." --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make persona_pipeline importable when running the script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl

from persona_pipeline.cli._paths import archetypes_path
from persona_pipeline.mappings import get_mappings
from persona_pipeline.stages.archetype import render_archetype_card
from persona_pipeline.stages.match import match_archetypes
from persona_pipeline.stages.simulate import default_thinking_for


PERSONA_PREAMBLE = (
    "You are role-playing as a single individual whose life context fits the demographic "
    "archetype described below. Speak in the first person, in the voice and worldview that "
    "would feel natural for someone in this segment — vocabulary, concerns, references, "
    "default tone. Stay in character. Never break the fourth wall, never mention that you "
    "are an AI, and never refer to the archetype card itself. If the user writes in Korean, "
    "Japanese, French, Portuguese, etc., respond in that language."
)


def pick_archetype(country: str, segment_id: str | None, query: str | None) -> dict:
    mapping = get_mappings(country)
    df = pl.read_parquet(archetypes_path(country))

    if segment_id:
        match = df.filter(pl.col("segment_id") == segment_id)
        if len(match) == 0:
            raise SystemExit(
                f"segment_id {segment_id!r} not found in {country} archetypes. "
                f"Available: {df['segment_id'].head(5).to_list()} ..."
            )
        return match.row(0, named=True)

    if query:
        results = match_archetypes(query, df, mapping, top_k=1)
        if not results:
            raise SystemExit(f"No archetype matched query {query!r}.")
        return results[0]

    return df.sort("size", descending=True).row(0, named=True)


def build_system_prompt(card: dict) -> str:
    return f"{PERSONA_PREAMBLE}\n\n{render_archetype_card(card)}"


def run_dry(system: str, task: str) -> None:
    print("=== SYSTEM PROMPT ===")
    print(system)
    print()
    print("=== USER TASK ===")
    print(task)


def run_live(system: str, task: str, model: str, max_tokens: int) -> None:
    try:
        import anthropic
    except ImportError:
        raise SystemExit(
            "anthropic SDK not installed. Run: uv pip install anthropic  (or: pip install anthropic)"
        )

    client = anthropic.Anthropic()

    print("=== RESPONSE ===")
    stream_kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
        ],
        "messages": [{"role": "user", "content": task}],
    }
    thinking = default_thinking_for(model)
    if thinking is not None:
        stream_kwargs["thinking"] = thinking

    # Cache the persona system prompt so subsequent calls with the same archetype only pay ~0.1× for that prefix.
    with client.messages.stream(**stream_kwargs) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
        print()

        usage = stream.get_final_message().usage
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        print(
            f"\n-- usage: input={usage.input_tokens}, output={usage.output_tokens}, "
            f"cache_write={cache_write}, cache_read={cache_read}"
        )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Persona simulation PoC — archetype card → Claude system prompt → task response.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("country", help="e.g. Korea, Japan, USA, Singapore, Brazil, France, India")
    ap.add_argument("--segment-id", help="exact segment_id, e.g. '수도권|중장년|남자|전문가'")
    ap.add_argument("--query", help="natural-language query to pick a segment via match stage")
    ap.add_argument("--task", required=True, help="task / question to ask the persona")
    ap.add_argument("--model", default="claude-opus-4-7")
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--dry-run", action="store_true",
                    help="print prompts only, skip LLM call")
    args = ap.parse_args()

    card = pick_archetype(args.country, args.segment_id, args.query)
    system = build_system_prompt(card)

    print(f"# archetype: {card['segment_id']} "
          f"(size={card['size']:,}, share={card['share_pct']:.2f}%)\n")

    if args.dry_run:
        run_dry(system, args.task)
        return
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("(ANTHROPIC_API_KEY not set — falling back to dry-run.)\n")
        run_dry(system, args.task)
        return

    run_live(system, args.task, args.model, args.max_tokens)


if __name__ == "__main__":
    main()
