"""Attachments: the state may carry one, and a text-only provider must say so.

The rule these tests defend is not obvious and it is the whole point of the module: a
provider that cannot read an attachment **refuses**, it does not quietly send the state with
the attachment removed. Dropping it produces a confident answer to a question about
something the model never saw, and the squire's fail-open then treats that answer as real.
Refusing turns into the harness default and a journal entry, which is the correct outcome.

No test here calls a paid provider.
"""

from __future__ import annotations

import asyncio

import pytest

from sanchopanza import Attachment, DeciderUnavailable, attachments_in, image, without_attachments
from sanchopanza.points import triage
from sanchopanza.providers import FallbackDecider, FixedDecider, LocalDecider, create
from sanchopanza.providers.jev import JevDecider

from .helpers import squire, thresholds, yes


def test_an_attachment_needs_a_media_type_and_somewhere_to_find_the_bytes():
    with pytest.raises(ValueError):
        Attachment(media_type="png", url="https://x.test/a.png")
    with pytest.raises(ValueError):
        Attachment(media_type="image/png")


def test_the_four_ways_to_name_the_bytes_all_work():
    for kwargs in (
        {"data": b"x"},
        {"path": "a.png"},
        {"url": "https://x.test/a.png"},
        {"ref": "f1"},
    ):
        assert image(**kwargs).is_image


def test_attachments_are_found_at_any_depth():
    shot = image(path="shot.png")
    state = {"purpose": "p", "pages": [{"title": "t", "capture": shot}, "plain text"]}
    assert attachments_in(state) == (shot,)
    assert attachments_in("just text") == ()
    assert attachments_in(shot) == (shot,)


def test_describing_a_state_leaves_the_text_alone():
    state = {"purpose": "p", "capture": image(url="https://x.test/a.png")}
    flat = without_attachments(state)
    assert flat["purpose"] == "p"
    assert flat["capture"] == "[image/png: https://x.test/a.png]"


# --- the refusal ---------------------------------------------------------------------------


def test_a_text_only_provider_refuses_loudly():
    """Its own documentation says images are not supported, so it must not pretend."""
    jev = JevDecider(api_key="not-used-in-this-test")
    with pytest.raises(DeciderUnavailable) as raised:
        asyncio.run(jev.decide("triage", {"capture": image(path="a.png")}, {}))
    assert "text only" in str(raised.value) and "image/png" in str(raised.value)


def test_the_refusal_becomes_the_harness_default_and_is_journalled():
    """Fail-open still holds: the agent carries on, and the reason is written down."""

    class TextOnly:
        name = "text-only"
        accepts_attachments = False

        async def decide(self, point, state, questions):
            if attachments_in(state):
                raise DeciderUnavailable("text only")
            return await FixedDecider({}).decide(point, state, questions)

    sq, _ = squire(TextOnly())
    decision = asyncio.run(
        sq.decide("triage", {"capture": image(path="a.png")}, {"relevant": yes(0.5)})
    )
    assert decision.failed and decision.error == "text only"
    assert triage.decide(decision, thresholds()).keep  # the default: in doubt a page enters


def test_providers_declare_whether_they_can_read_an_attachment():
    assert create("null").accepts_attachments is True
    assert create("jev", api_key="x").accepts_attachments is False
    assert LocalDecider({}).accepts_attachments is True


def test_one_capable_link_makes_the_chain_capable():
    chain = FallbackDecider([create("jev", api_key="x"), LocalDecider({})])
    assert chain.accepts_attachments is True


def test_a_local_vision_handler_answers_about_the_attachment_today():
    """The path that works right now: a model of your own behind the same contract."""
    from sanchopanza import answers

    def looks_like_a_receipt(state, question):
        shot = attachments_in(state)
        return answers.truth(0.93) if shot and shot[0].is_image else None

    squire_, journal = squire(LocalDecider({"is_receipt": looks_like_a_receipt}))
    decision = asyncio.run(
        squire_.decide("vision", {"capture": image(path="a.png")}, {"is_receipt": yes(0.5)})
    )
    assert decision.answer("is_receipt").truth == pytest.approx(0.93)
