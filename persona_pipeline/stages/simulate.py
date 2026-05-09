"""LLM persona simulation — fan a single task across many archetypes for one country.

Each archetype card becomes a Claude system prompt; the same task is sent as the
user message. Calls run concurrently under an asyncio Semaphore. Per-segment
try/except keeps one failure from poisoning the run — failed rows carry an `error`
string instead of a response.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass

import polars as pl

from persona_pipeline.stages.archetype import render_archetype_card

PERSONA_PREAMBLE = (
    "You are role-playing as a single individual whose life context fits the demographic "
    "archetype described below. Speak in the first person, in the voice and worldview that "
    "would feel natural for someone in this segment — vocabulary, concerns, references, "
    "default tone. Stay in character. Never break the fourth wall, never mention that you "
    "are an AI, and never refer to the archetype card itself. If the user writes in Korean, "
    "Japanese, French, Portuguese, etc., respond in that language."
)

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_CONCURRENCY = 4

# Models that accept `thinking: {type: "adaptive"}`. Sonnet 4.5 / Haiku 4.5 / older
# return 400 ("adaptive thinking is not supported on this model"); for those we omit
# the thinking parameter entirely.
_ADAPTIVE_THINKING_MODELS: frozenset[str] = frozenset({
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
})


def default_thinking_for(model: str) -> dict | None:
    return {"type": "adaptive"} if model in _ADAPTIVE_THINKING_MODELS else None


@dataclass
class SimulationResult:
    country: str
    segment_id: str
    size: int
    task: str
    model: str
    response: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    error: str | None = None


def build_system_prompt(card: dict) -> str:
    return f"{PERSONA_PREAMBLE}\n\n{render_archetype_card(card)}"


async def _simulate_one(
    client,
    card: dict,
    task: str,
    country: str,
    model: str,
    max_tokens: int,
    sem: asyncio.Semaphore,
    thinking: dict | None,
) -> SimulationResult:
    base = SimulationResult(
        country=country,
        segment_id=card["segment_id"],
        size=int(card["size"]),
        task=task,
        model=model,
        response="",
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
    system = build_system_prompt(card)
    stream_kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
        ],
        "messages": [{"role": "user", "content": task}],
    }
    if thinking is not None:
        stream_kwargs["thinking"] = thinking

    async with sem:
        try:
            async with client.messages.stream(**stream_kwargs) as stream:
                msg = await stream.get_final_message()
        except Exception as exc:  # network, rate-limit, refusal, etc. — isolate
            base.error = f"{type(exc).__name__}: {exc}"
            return base

    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    u = msg.usage
    base.response = text
    base.input_tokens = int(getattr(u, "input_tokens", 0) or 0)
    base.output_tokens = int(getattr(u, "output_tokens", 0) or 0)
    base.cache_read_tokens = int(getattr(u, "cache_read_input_tokens", 0) or 0)
    base.cache_write_tokens = int(getattr(u, "cache_creation_input_tokens", 0) or 0)
    return base


async def run_simulation_async(
    cards: pl.DataFrame,
    country: str,
    task: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    concurrency: int = DEFAULT_CONCURRENCY,
    thinking: dict | None | str = "auto",
    client=None,
) -> pl.DataFrame:
    """Fan a single task across `cards` rows. `client` is an injection point for tests.

    `thinking`: "auto" picks adaptive when supported by `model`, off otherwise.
    Pass a dict (e.g. `{"type": "adaptive"}`) or `None` to override.
    """
    if thinking == "auto":
        thinking = default_thinking_for(model)

    if client is None:
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError(
                "anthropic SDK not installed. Install with: pip install 'persona-pipeline[sim]'"
            ) from e
        client = anthropic.AsyncAnthropic()

    sem = asyncio.Semaphore(concurrency)
    coros = [
        _simulate_one(client, row, task, country, model, max_tokens, sem, thinking)
        for row in cards.iter_rows(named=True)
    ]
    results = await asyncio.gather(*coros)
    return pl.DataFrame([asdict(r) for r in results])


def run_simulation(
    cards: pl.DataFrame,
    country: str,
    task: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    concurrency: int = DEFAULT_CONCURRENCY,
    thinking: dict | None | str = "auto",
    client=None,
) -> pl.DataFrame:
    return asyncio.run(
        run_simulation_async(
            cards, country, task,
            model=model, max_tokens=max_tokens, concurrency=concurrency,
            thinking=thinking, client=client,
        )
    )
