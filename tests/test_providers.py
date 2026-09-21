"""Providers: wire formats, recording and replay, composition. No network."""

from __future__ import annotations

import asyncio

import pytest

from sancho import Answer, Choice, Score, Truth, choice, labelled, score, truth
from sancho.contract import DeciderUnavailable
from sancho.providers import FallbackDecider, FixedDecider, LocalDecider, NullDecider, RoutedDecider
from sancho.providers.fixed import BrokenDecider
from sancho.providers.jev import from_wire, to_wire
from sancho.providers.llm import answers_from, build_schema
from sancho.providers.recorded import RecordedDecider, RecordingDecider, key_of


def test_questions_translate_to_typesafe_wire_format():
    assert to_wire(Choice("q", {"a": "x", "b": "y"})) == {
        "type": "choice",
        "instructions": "q",
        "criteria": {"a": "x", "b": "y"},
    }
    assert to_wire(Score("q", ["low", "high"]))["type"] == "score"
    assert to_wire(Truth("q")) == {"type": "noul", "instructions": "q"}
    assert to_wire(Truth("q", {"true": "t"}))["criteria"] == {"true": "t"}


def test_answers_from_typesafe_derive_confidence_for_noul():
    t = from_wire({"type": "noul", "noul": 0.9})
    assert t.truth == 0.9 and t.confidence == pytest.approx(0.8)
    c = from_wire(
        {"type": "choice", "choice": "a", "confidence": 0.7, "probabilities": {"a": 0.8, "b": 0.2}}
    )
    assert c.choice == "a" and c.probabilities["b"] == 0.2
    assert from_wire({"type": "score"}).empty


def test_answer_factories_follow_the_confidence_convention():
    assert truth(0.9).confidence == pytest.approx(0.8)
    c = choice({"a": 0.7, "b": 0.3})
    assert c.choice == "a" and c.confidence == pytest.approx(0.4)
    s = score([0.1, 0.8, 0.1])
    assert s.score == pytest.approx(1.0) and s.confidence == pytest.approx(0.8)
    lab = labelled("x", ["x", "y", "z"], confidence=0.7)
    assert lab.probabilities["y"] == pytest.approx(0.15)


def test_recording_then_replaying_gives_the_same_answers(tmp_path):
    fixed = FixedDecider({"complexity": Answer("score", 0.9, score=0.3)})
    recorder = RecordingDecider(fixed, tmp_path / "rec.jsonl")
    state, qs = {"task": "t"}, {"complexity": Score("q", ["a", "b", "c"])}
    original = asyncio.run(recorder.decide("routing", state, qs))
    replay = RecordedDecider.from_file(tmp_path / "rec.jsonl")
    again = asyncio.run(replay.decide("routing", state, qs))
    assert again.answers["complexity"].score == original.answers["complexity"].score
    assert key_of("routing", state, qs) in (tmp_path / "rec.jsonl").read_text()
    assert len(replay) == 1


def test_recorded_falls_back_to_the_point_default_then_to_nothing():
    rec = RecordedDecider(
        [
            {
                "point": "citation",
                "default": True,
                "answers": {
                    "relation": {"kind": "choice", "choice": "supports", "confidence": 0.9}
                },
            }
        ]
    )
    qs = {"relation": Choice("q", {"supports": "", "contradicts": ""})}
    assert asyncio.run(rec.decide("citation", {"x": 1}, qs)).answer("relation").choice == "supports"
    assert asyncio.run(rec.decide("search", {"x": 1}, qs)).answer("relation").empty


def test_null_answers_nothing():
    d = asyncio.run(NullDecider().decide("p", {}, {"q": Truth("q")}))
    assert d.answers == {} and not d.failed


def test_fallback_merges_answers_and_raises_only_when_everyone_fails():
    local = LocalDecider({"injection": lambda s, q: truth(0.95)})
    rest = FixedDecider({"relevant": truth(0.8), "injection": truth(0.1)})
    chain = FallbackDecider([local, rest])
    qs = {"injection": Truth("i"), "relevant": Truth("r")}
    d = asyncio.run(chain.decide("triage", {}, qs))
    assert d.answer("injection").truth == 0.95  # local wins its question
    assert d.answer("relevant").truth == 0.8  # the rest comes from the fallback
    assert d.provider == "local+fixed"
    with pytest.raises(DeciderUnavailable):
        asyncio.run(FallbackDecider([BrokenDecider(), BrokenDecider()]).decide("p", {}, qs))


def test_routed_sends_each_point_to_its_provider():
    a = FixedDecider({"dangerous": truth(0.9)})
    b = FixedDecider({"dangerous": truth(0.1)})
    routed = RoutedDecider({"guard": a}, default=b)
    qs = {"dangerous": Truth("d")}
    assert asyncio.run(routed.decide("guard", {}, qs)).answer("dangerous").truth == 0.9
    assert asyncio.run(routed.decide("other", {}, qs)).answer("dangerous").truth == 0.1


def test_local_handlers_may_be_async_and_partial():
    async def slow(state, question):
        return choice({"news": 0.9, "other": 0.1})

    local = LocalDecider({"source_kind": slow})
    qs = {"source_kind": Choice("k", {"news": "", "other": ""}), "relevant": Truth("r")}
    d = asyncio.run(local.decide("triage", {}, qs))
    assert d.answer("source_kind").choice == "news" and d.answer("relevant").empty


def test_llm_schema_and_answer_mapping():
    qs = {
        "complexity": Score("c", ["a", "b", "c"]),
        "injection": Truth("i"),
        "relation": Choice("r", {"supports": "", "contradicts": ""}),
    }
    schema = build_schema(qs)
    assert schema["properties"]["complexity"]["maximum"] == 2
    assert schema["properties"]["relation"]["enum"] == ["supports", "contradicts"]
    assert "confidence" in schema["required"]
    answers = answers_from(
        {"complexity": 1, "injection": True, "relation": "supports", "confidence": 0.8}, qs
    )
    assert answers["complexity"].score == 1.0
    assert answers["injection"].truth == pytest.approx(0.8)
    assert answers["relation"].choice == "supports" and answers["relation"].confidence == 0.8
    assert "relation" not in answers_from({"relation": "nonsense", "confidence": 0.9}, qs)
