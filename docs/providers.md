# Providers: any decision model behind one contract

```python
class Decider(Protocol):
    name: str
    async def decide(self, point: str, state: State, questions: Mapping[str, Question]) -> Decision: ...
```

`state` is the minimal text (or JSON) the decision needs. `questions` map a key to a
`Choice`, `Score` or `Truth`. The `Decision` carries an `Answer` per key with `confidence`
and, depending on the kind, `choice` + `probabilities`, `score`, or `truth`. Raise
`DeciderUnavailable` when you cannot answer; never invent answers. Leave a question out of
`answers` when you cannot answer just that one; the policy uses its default for it.

Confidence convention: for `Truth`, `confidence = |2p - 1|` (use `sanchopanza.answers.truth`).
For `Choice`, the provider's own confidence if it has one, else top minus runner-up
(`answers.choice`). For `Score`, the provider's confidence or the modal mass (`answers.score`).

## Built in

| Name | Class | What it is for | Confidence is |
|---|---|---|---|
| `jev` | `JevDecider` | TypeSafe Jev over HTTP; the model the paper measures | a property of the output distribution |
| `recorded` | `RecordedDecider` | replay of real decisions; tests, dry runs, CI | recorded |
| `null` | `NullDecider` | no provider; every policy uses its default | none |
| `llm` | `LLMDecider` | any LLM forced into a JSON schema; the paper's baseline | **self-reported**, and measured not to separate errors |
| `local` | `LocalDecider` | your classifiers, embeddings, vision models | whatever you compute |
| | `FallbackDecider` | first provider that answers each question wins | merged |
| | `RoutedDecider` | one provider per decision point | per point |
| | `RecordingDecider` | wraps a real provider and writes a fixture | passthrough |

`sanchopanza.providers.create(name, **kwargs)` instantiates by name, including providers other
packages register under the `sanchopanza.providers` entry-point group.

## Writing one

A provider for a hosted decision API is `jev.py` with another URL and mapping: about 150
lines, most of them error handling. A provider for a local model is shorter:

```python
from sanchopanza import answers
from sanchopanza.providers import LocalDecider

def injection(state, question):
    p = clf.predict_proba([state["text"]])[0][1]
    return answers.truth(p)

def source_kind(state, question):
    probs = vision_model(state["screenshot"])            # a softmax over the option names
    return answers.choice(dict(zip(question.options, probs)))

decider = LocalDecider({"injection": injection, "source_kind": source_kind}, model="onprem-v3")
```

Handlers are keyed by question key (`injection`, `relevant`, `complexity`, ...) or `"*"` for
a catch-all. They receive the state and the `Question` object, so a generic handler can
inspect `question.options` or `question.levels`. Sync or async both work.

For an LLM you do not have a completer for, write `async def complete(system, user, schema)
-> (payload, tokens_in, tokens_out)` and pass it to `LLMDecider`. Two are included:
`anthropic_completer` (tool-forced) and `openai_completer` (json_schema).

## Mixing

```python
squire = Squire(FallbackDecider([
    LocalDecider({"injection": onprem_injection}),   # this question never leaves the building
    create("jev"),                                    # the rest goes to the hosted model
]))

squire = Squire(RoutedDecider(
    {"guard": LocalDecider(...), "entity": create("jev")},
    default=LLMDecider(anthropic_completer(key, "claude-haiku-4-5-20251001")),
))
```

`FallbackDecider` merges answers question by question and raises only when every provider
raised. `RoutedDecider` picks by decision point. Both are `Decider`s themselves, so they nest.

## Data handling

The state is text you choose. The points trim it (`text.truncate`) and send only the fields
the question needs: a task, a query and its predecessors, a page excerpt, a claim and a
section, a command and a description of the environment. Nothing else. If your data cannot
leave a jurisdiction, keep that point on a `LocalDecider` via `RoutedDecider`, or
pseudonymize in the harness before the state is built. The benches in this repository were
pseudonymized that way before publication.

## The path from hosted to local

The paper's argument for the contract: a hosted decision model starts with zero labelled
data; the journal records every decision with its probabilities and outcome; once there are
labels, a small supervised model behind the same contract can replace it where it wins, on
your hardware, in ten milliseconds. Nothing above `Decider` changes. That is what "plug and
play" means here.

## Beyond text: attachments

`state` may carry a `sanchopanza.media.Attachment` at any depth, and the questions do not
change. That is not a guess about the future: *Visual Jev* (arXiv 2609.25845, 2026-09-22,
independent of TypeSafe) scores Choice, Score and Noul questions over an image from raw
logits with no autoregressive generation, at 5.7 ms amortized per question when 32 questions
share one image. The shape of this contract already fits it.

```python
from sanchopanza import answers, image, attachments_in
from sanchopanza.providers import LocalDecider, RoutedDecider, create

def shows_an_error_state(state, question):
    shot = attachments_in(state)
    return answers.truth(my_classifier(shot[0].path)) if shot else None

vision = LocalDecider({"error_state": shows_an_error_state})
decider = RoutedDecider({"screenshot": vision}, default=create("jev"))
```

**What does not exist, as of 2026-09-24.** No vendor sells a calibrated, non-generative
decision model that reads an image. TypeSafe's own documentation is explicit about the model
this package was built against: *"Jev accepts text only. State must be a string, JSON object,
or array of text values. Images, audio, and video are not supported (yet)."* The managed
image classifiers are not substitutes for a calibrated decider and it is worth knowing why:

| | Score it returns | Calibration published |
|---|---|---|
| AWS Rekognition moderation | confidence 0-100, documented as "confidence that the label has been correctly identified" | none |
| Azure AI Content Safety, image | an ordinal severity in {0, 2, 4, 6} - how bad, not how likely | none |
| Google Vision SafeSearch | a six-value likelihood bucket, "intended to give clients highly stable results across model upgrades" | none, and not expressible |
| OpenAI `omni-moderation-latest` | scores in [0, 1], documented as confidence, with a warning that they "may need recalibration over time" | none |

Two of the four cannot emit a continuous score at all. Widening the survey to the
specialists does not help: across **seven vendors** - those four plus Hive, Clarifai and
Sightengine - **not one publishes an expected calibration error, a reliability diagram or a
Brier score**. The nearest thing to an operating point anyone gives is Hive's recommended
threshold of 0.9, which is a suggestion and not a calibration claim, and Sightengine's
"99.2 % F1" comes with no test set, no date and no threshold, which makes it unusable for
setting one. The pattern worth remembering: **no vendor publishes both a performance number
and the threshold it was measured at**, which is exactly the pair you would need.

Self-hosted models do better. ShieldGemma 2 publishes per-policy precision, recall and F1 and
returns the probability of the `Yes` token. So calibration over images is something you fit
and measure, not something you buy, exactly as it was for text.

**Three rules the survey argues for, and the package enforces the first.**

1. **A text-only provider refuses an attachment; it never drops it.** `JevDecider` raises
   `DeciderUnavailable`, the squire turns that into the harness default and journals the
   reason. Sending the state with the image removed would answer a question about something
   the model never saw, and fail-open would then treat that answer as real.
2. **Ask every question about one image in a single call.** One question about a 1080p
   screenshot on a small hosted vision model is roughly 60x the cost of a text decision here;
   eight questions grouped over a 768px image is roughly 4.5x. Resize before sending, and use
   `hints` to say so.
3. **An image in the context is attack surface this layer cannot screen.** No production
   prompt-injection classifier accepts an image: Prompt Guard 2, Azure Prompt Shields and
   Model Armor are text-in, and the best image-accepting detector in the literature reaches a
   true-positive rate of 0.38 at a false-positive rate of 0.002. Image-borne injection against
   a shipping browser agent has been demonstrated. The `injection` question here reads text;
   it does not see pixels.
