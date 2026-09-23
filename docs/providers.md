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
