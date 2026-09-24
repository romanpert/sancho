"""Attachments: how a non-text thing gets into a decision's state.

**What exists, as of 2026-09-24.** No vendor sells a calibrated, non-generative decision
model that takes an image. TypeSafe's own documentation is explicit about the model this
package was built against: *"Jev accepts text only. State must be a string, JSON object, or
array of text values. Images, audio, and video are not supported (yet)."* Everything else on
offer is a ranking score that is not a probability, an uncalibrated vendor confidence, or a
generative model coaxed into a schema, whose self-reported confidence is not usable as a
decision score (Qwen3-VL-4B baseline ECE 0.42 on visual reasoning).

**Why this module exists anyway.** The shape is proven. *Visual Jev* (arXiv 2609.25845,
2026-09-22, independent of TypeSafe) scores Choice, Score and Noul questions over an image
from raw logits with no autoregressive generation, at 5.7 ms amortized per question when 32
questions share one image. The questions did not have to change. So the only thing standing
between this package and a multimodal decider is **the type of `state`**, and that is what
this module widens. A local vision model behind `LocalDecider` works today.

**The economics are the design.** Against 29 millionths of a dollar for a text decision, one
question about a 1080p screenshot on a small hosted VLM is about 60x that. Eight questions
grouped into one call about a 768px image is about 4.5x. So `Attachment` carries hints for
resizing, and every decision point that grows an image should ask all of its questions in one
call, which the contract already does.

**One safety fact that does not have a workaround yet.** No production prompt-injection
classifier accepts an image: Prompt Guard 2, Azure Prompt Shields and Model Armor are all
text-in, and the best image-accepting detector in the literature reaches a true-positive rate
of 0.38 at a false-positive rate of 0.002. Image-borne injection against a shipping browser
agent has been demonstrated (faint text invisible to a human, read by the OCR path). The
`injection` question in this package reads text; it does not see pixels. An attachment that
reaches a model's context is attack surface this layer cannot screen, and the harness must
know that.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Attachment:
    """A non-text part of a state, named by media type rather than by kind.

    Four ways to say where the bytes are, because every provider prefers a different one and
    converting eagerly throws away both cost levers (a provider that can fetch a URL itself
    should not be handed base64, and an already-uploaded file should not be re-sent):

    - `data`: the bytes, inline.
    - `path`: a local file the provider reads.
    - `url`: the provider decides whether to forward the link or download it.
    - `ref`: an identifier the provider already holds from an earlier upload.

    `hints` carries provider-specific knobs (a maximum side, a detail level) so that they
    stay out of the contract. One class keyed by `media_type` rather than `Image` / `Audio`
    / `Document`, so that nothing here changes when the next modality arrives.
    """

    media_type: str
    data: bytes | None = None
    path: str | None = None
    url: str | None = None
    ref: str | None = None
    hints: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.media_type or "/" not in self.media_type:
            raise ValueError("media_type must be a media type such as 'image/png'")
        if not any((self.data, self.path, self.url, self.ref)):
            raise ValueError("an attachment needs one of data, path, url or ref")

    @property
    def is_image(self) -> bool:
        return self.media_type.startswith("image/")

    def describe(self) -> str:
        """A short text stand-in, for logs and for text-only providers to refuse against."""
        where = "inline" if self.data is not None else (self.path or self.url or self.ref or "?")
        return f"[{self.media_type}: {where}]"


def image(
    *,
    data: bytes | None = None,
    path: str | None = None,
    url: str | None = None,
    ref: str | None = None,
    media_type: str = "image/png",
    **hints: Any,
) -> Attachment:
    """`Attachment` for the common case, so a caller never has to spell the media type."""
    return Attachment(media_type=media_type, data=data, path=path, url=url, ref=ref, hints=hints)


def attachments_in(state: Any) -> tuple[Attachment, ...]:
    """Every attachment anywhere in a state, so a provider can find them before deciding.

    A state is text, a mapping or a sequence, and an attachment may sit at any depth. A
    text-only provider calls this to refuse loudly; a multimodal one calls it to collect what
    it has to upload.
    """
    if isinstance(state, Attachment):
        return (state,)
    if isinstance(state, Mapping):
        found: list[Attachment] = []
        for value in state.values():
            found.extend(attachments_in(value))
        return tuple(found)
    if isinstance(state, (list, tuple)):
        found = []
        for value in state:
            found.extend(attachments_in(value))
        return tuple(found)
    return ()


def without_attachments(state: Any) -> Any:
    """The same state with every attachment replaced by its short description.

    What a text-only provider would send if the caller told it to carry on regardless. It is
    not the default: silently dropping the thing the question is about produces a confident
    answer to a question nobody asked, which is worse than no answer at all.
    """
    if isinstance(state, Attachment):
        return state.describe()
    if isinstance(state, Mapping):
        return {key: without_attachments(value) for key, value in state.items()}
    if isinstance(state, (list, tuple)):
        return [without_attachments(value) for value in state]
    return state
