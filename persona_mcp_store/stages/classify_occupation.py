"""LLM-as-classifier for free-text occupation strings.

Distinct occupation values from the raw dataset are sent to a small Claude model
along with the country's group definitions. The result — a `(occupation, group)`
parquet — is a permanent data asset checked into the repo. enrich() reads it as
a lookup join, so there are no keyword tables to maintain.

Uses the Message Batches API: it bypasses per-minute rate limits (this is a
one-time bulk job, not interactive) and gets 50% off list price. Polls every
15 seconds; most batches finish in <5 minutes.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import polars as pl

from persona_mcp_store.mappings import CountryMappings

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_POLL_INTERVAL = 15.0  # seconds
OTHER_LABEL = "Other"


def _build_system(mapping: CountryMappings) -> str:
    items = "\n".join(
        f"- {label}: {desc}" for label, desc in (mapping.occupation_group_definitions or {}).items()
    )
    return (
        f"You classify free-text occupation strings from the {mapping.country} dataset "
        f"(language: {mapping.locale}) into exactly ONE of the official categories below.\n\n"
        f"Categories (label: description):\n{items}\n"
        f"- {OTHER_LABEL}: anything that does not clearly fit any category above\n\n"
        f"Reply with the label string only. Use {OTHER_LABEL} only as a last resort."
    )


@dataclass
class _ClassifierConfig:
    system: str
    enum_values: list[str]
    schema: dict[str, Any]
    model: str


def _make_config(mapping: CountryMappings, model: str) -> _ClassifierConfig:
    if mapping.occupation_group_definitions is None:
        raise ValueError(
            f"{mapping.country}: occupation_group_definitions is None — country uses native category"
        )
    enum_values = list(mapping.occupation_group_definitions.keys()) + [OTHER_LABEL]
    schema = {
        "type": "object",
        "properties": {"group": {"type": "string", "enum": enum_values}},
        "required": ["group"],
        "additionalProperties": False,
    }
    return _ClassifierConfig(
        system=_build_system(mapping),
        enum_values=enum_values,
        schema=schema,
        model=model,
    )


def _unique_occupations(raw: pl.LazyFrame, src: str) -> list[str]:
    return (
        raw.select(src)
        .unique()
        .filter(pl.col(src).is_not_null() & (pl.col(src).cast(pl.Utf8).str.len_chars() > 0))
        .collect()[src]
        .to_list()
    )


def _parse_message(msg, enum_values: list[str]) -> tuple[str, str | None]:
    """Return (group, error). On any parse problem, group is OTHER_LABEL with error reason."""
    text = next((b.text for b in msg.content if getattr(b, "type", None) == "text"), "")
    try:
        group = json.loads(text)["group"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return OTHER_LABEL, f"unparseable: {text[:80]}"
    if group not in enum_values:
        return OTHER_LABEL, f"out-of-enum: {group!r}"
    return group, None


def classify_occupations(
    raw: pl.LazyFrame,
    mapping: CountryMappings,
    model: str = DEFAULT_MODEL,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    client=None,
    progress=print,
) -> pl.DataFrame:
    """Classify all unique occupation values via the Batches API.

    Returns a DataFrame with columns (occupation, occupation_group, error).
    `progress` is called with status strings; pass `lambda *_: None` to silence.
    """
    cfg = _make_config(mapping, model)
    src = mapping.occupation_source_col
    unique_vals = _unique_occupations(raw, src)

    if not unique_vals:
        return pl.DataFrame(schema={"occupation": pl.Utf8, "occupation_group": pl.Utf8, "error": pl.Utf8})

    if client is None:
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError(
                "anthropic SDK not installed. Install with: pip install 'persona-mcp-store[sim]'"
            ) from e
        client = anthropic.Anthropic()

    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    requests = [
        Request(
            custom_id=f"occ-{i}",
            params=MessageCreateParamsNonStreaming(
                model=cfg.model,
                max_tokens=64,
                system=[
                    {"type": "text", "text": cfg.system, "cache_control": {"type": "ephemeral"}},
                ],
                messages=[{"role": "user", "content": occ}],
                output_config={"format": {"type": "json_schema", "schema": cfg.schema}},
            ),
        )
        for i, occ in enumerate(unique_vals)
    ]

    progress(f"submitting batch: {len(requests):,} requests")
    batch = client.messages.batches.create(requests=requests)
    progress(f"batch_id={batch.id} status={batch.processing_status}")

    while batch.processing_status != "ended":
        time.sleep(poll_interval)
        batch = client.messages.batches.retrieve(batch.id)
        c = batch.request_counts
        progress(
            f"  status={batch.processing_status} "
            f"processing={c.processing} succeeded={c.succeeded} errored={c.errored}"
        )

    custom_id_to_result: dict[str, Any] = {}
    for result in client.messages.batches.results(batch.id):
        custom_id_to_result[result.custom_id] = result

    rows = []
    for i, occ in enumerate(unique_vals):
        result = custom_id_to_result.get(f"occ-{i}")
        if result is None:
            rows.append({"occupation": occ, "occupation_group": OTHER_LABEL, "error": "missing-result"})
            continue
        if result.result.type != "succeeded":
            err = getattr(result.result, "error", None)
            err_type = getattr(err, "type", str(result.result.type))
            rows.append({"occupation": occ, "occupation_group": OTHER_LABEL, "error": str(err_type)})
            continue
        group, err = _parse_message(result.result.message, cfg.enum_values)
        rows.append({"occupation": occ, "occupation_group": group, "error": err})

    return pl.DataFrame(
        rows, schema={"occupation": pl.Utf8, "occupation_group": pl.Utf8, "error": pl.Utf8}
    )
