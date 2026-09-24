# A generative verifier as a control on a compositional judgment

The same frontier model answers each point twice: once in a single word, once after working the answer out in two sentences. The compositional point and the control differ in whether the judgment requires tracing an artefact between two objects.

| Point | Shape | Arm | n | Correct | Cost per judgment | Output tokens |
|---|---|---|---|---|---|---|
| dependency | compositional | evaluator | 20 | 19/20 | 28 millionths | 0 |
| dependency | compositional | direct | 20 | 20/20 | 3102 millionths | 98 |
| dependency | compositional | reasoning | 20 | 20/20 | 5906 millionths | 2,117 |
| recall | control | evaluator | 36 | 36/36 | 28 millionths | 0 |
| recall | control | direct | 36 | 36/36 | 2773 millionths | 124 |
| recall | control | reasoning | 36 | 36/36 | 4670 millionths | 2,452 |

## What moved

- **dependency** (compositional): reasoning changed 0 decisions out of 20, at 1.9x the cost per judgment.
  **Ceiling: the direct arm already scored 20/20, so no gain was detectable on this point.** The comparison bounds what reasoning costs, not what it buys; testing the hypothesis needs cases the cheaper arm gets wrong.
- **recall** (control): reasoning changed 0 decisions out of 36, at 1.7x the cost per judgment.
  **Ceiling: the direct arm already scored 36/36, so no gain was detectable on this point.** The comparison bounds what reasoning costs, not what it buys; testing the hypothesis needs cases the cheaper arm gets wrong.
