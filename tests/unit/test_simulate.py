"""Simulate-stage tests with a fake AsyncAnthropic client."""
from __future__ import annotations

from dataclasses import dataclass

import polars as pl
import pytest

from persona_pipeline.stages.simulate import (
    PERSONA_PREAMBLE, build_system_prompt, run_simulation,
)


def _card(segment_id: str = "수도권|중장년|남자", size: int = 1000) -> dict:
    return {
        "country": "Korea",
        "segment_id": segment_id,
        "size": size,
        "share_pct": 12.5,
        "mean_age": 49.7,
        "top_occupation": "전문가",
        "top_region": "수도권",
        "top_hobbies": ["산책", "독서"],
        "samples": ["[요약]\n홍길동 씨는 …"],
    }


def _cards_df(*cards) -> pl.DataFrame:
    return pl.DataFrame(list(cards))


# --- Fake AsyncAnthropic ----------------------------------------------------

@dataclass
class _FakeBlock:
    type: str
    text: str


@dataclass
class _FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class _FakeMessage:
    content: list
    usage: _FakeUsage


class _FakeStream:
    def __init__(self, message: _FakeMessage):
        self._message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get_final_message(self):
        return self._message


class _FakeMessages:
    def __init__(self, responses: list, recorded_calls: list):
        self._responses = list(responses)
        self._recorded = recorded_calls

    def stream(self, **kwargs):
        self._recorded.append(kwargs)
        next_resp = self._responses.pop(0)
        if isinstance(next_resp, Exception):
            raise next_resp
        return _FakeStream(next_resp)


class _FakeClient:
    def __init__(self, responses: list):
        self.calls: list[dict] = []
        self.messages = _FakeMessages(responses, self.calls)


def _ok_message(text: str, **usage_kwargs) -> _FakeMessage:
    return _FakeMessage(
        content=[_FakeBlock(type="text", text=text)],
        usage=_FakeUsage(**usage_kwargs),
    )


# --- Tests ------------------------------------------------------------------

def test_build_system_prompt_includes_preamble_and_card():
    s = build_system_prompt(_card())
    assert PERSONA_PREAMBLE in s
    assert "수도권|중장년|남자" in s
    assert "[요약]" in s


def test_run_simulation_collects_response_and_usage():
    cards = _cards_df(_card("수도권|청년|남자", 100), _card("영남권|노년|여자", 200))
    client = _FakeClient([
        _ok_message("응답1", input_tokens=10, output_tokens=20, cache_read_input_tokens=5),
        _ok_message("응답2", input_tokens=12, output_tokens=22, cache_creation_input_tokens=8),
    ])

    df = run_simulation(cards, "Korea", "주말 계획?", client=client, concurrency=2)

    assert df.shape[0] == 2
    expected = {"country", "segment_id", "size", "task", "model", "response",
                "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "error"}
    assert expected.issubset(set(df.columns))

    by_seg = {r["segment_id"]: r for r in df.iter_rows(named=True)}
    assert by_seg["수도권|청년|남자"]["response"] == "응답1"
    assert by_seg["수도권|청년|남자"]["cache_read_tokens"] == 5
    assert by_seg["영남권|노년|여자"]["response"] == "응답2"
    assert by_seg["영남권|노년|여자"]["cache_write_tokens"] == 8
    assert by_seg["수도권|청년|남자"]["error"] is None


def test_run_simulation_isolates_per_segment_failures():
    cards = _cards_df(_card("a|b|c", 50), _card("d|e|f", 60))
    client = _FakeClient([
        _ok_message("ok", input_tokens=1, output_tokens=2),
        RuntimeError("boom"),
    ])

    df = run_simulation(cards, "Korea", "?", client=client, concurrency=1)

    by_seg = {r["segment_id"]: r for r in df.iter_rows(named=True)}
    assert by_seg["a|b|c"]["error"] is None
    assert by_seg["a|b|c"]["response"] == "ok"
    assert by_seg["d|e|f"]["error"] is not None
    assert "boom" in by_seg["d|e|f"]["error"]
    assert by_seg["d|e|f"]["response"] == ""


def test_run_simulation_passes_cache_control_on_system_prompt():
    cards = _cards_df(_card("x|y|z", 1))
    client = _FakeClient([_ok_message("ok")])

    run_simulation(cards, "Korea", "?", client=client)

    assert len(client.calls) == 1
    sys_param = client.calls[0]["system"]
    assert isinstance(sys_param, list) and len(sys_param) == 1
    assert sys_param[0]["cache_control"] == {"type": "ephemeral"}
    assert client.calls[0]["thinking"] == {"type": "adaptive"}
    assert client.calls[0]["model"] == "claude-opus-4-7"
