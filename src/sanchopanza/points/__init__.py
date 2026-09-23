"""Decision points: the questions each one asks and the pure policy that acts on them.

Every module here follows the same shape:

    state, questions = <point>.questions(...)     # minimal state, closed questions
    result = <point>.decide(decision, thresholds)  # pure, testable with a table of cases

Question texts are the ones measured in docs/paper.md, verbatim. Instructions are in
English on purpose (the primary training language of the decision models measured);
the content under evaluation can be in any language and stays as it is.

Three rules from the measurements, applied in every point:
- The decider reads; it does not predict. Ask about what is in the text.
- What code can decide, code decides (literal quote match, token overlap, deny-lists,
  transitive reduction). The model only covers what code cannot.
- Include `other` / `none` when the option list may not be exhaustive.
"""

from . import citation, entities, guard, injection, plan, review, routing, search, tools, triage

__all__ = [
    "citation",
    "entities",
    "guard",
    "injection",
    "plan",
    "review",
    "routing",
    "search",
    "tools",
    "triage",
]
