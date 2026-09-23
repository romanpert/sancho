# Who can change what

This repository is single-maintainer by design. Everything below is configured on GitHub,
not in code, except `CODEOWNERS`, which lives at `.github/CODEOWNERS` and makes the owner a
required reviewer of every path.

## Branch protection, for `main` and again for `dev`

GitHub, **Settings**, **Rules**, **Rulesets**, **New branch ruleset**. One ruleset can target
both branches, which is less to keep in sync than two.

| Setting | Value | Why |
|---|---|---|
| Enforcement status | Active | A ruleset in evaluate mode protects nothing |
| Target branches | `main` and `dev` | Both, or the rule is a detour through `dev` |
| Restrict creations, updates and deletions | On | Nobody creates or deletes these branches |
| Require a pull request before merging | On | No direct pushes, including yours |
| Required approvals | 1 | |
| Require review from Code Owners | On | This is what `CODEOWNERS` is for |
| Dismiss stale approvals on new commits | On | An approval is for the diff that was reviewed |
| Require status checks to pass | On, select the `test` check from `ci.yml` | A red build cannot merge |
| Require branches to be up to date before merging | On | The check ran against what will actually land |
| Block force pushes | On | History on these branches is append-only |
| Require linear history | On, optional | Keeps `git log` readable; use squash or rebase merges |
| Bypass list | Add yourself as **Repository admin**, or leave empty | See the note below |

**On the bypass entry.** With an empty bypass list you cannot merge your own pull request
alone, because you cannot approve it: GitHub does not let an author approve their own PR. For
a solo repository that means every change needs a second account. Adding yourself to the
bypass list keeps the rules on for everyone else and lets you merge your own work. That is
the right setting here, and it is a deliberate trade: the protection is against accident and
against outside contributors, not against yourself.

If a second maintainer ever joins, remove the bypass entry and the rules become real for
everyone, including you.

## The PyPI environment, and the part that will bite

You have configured the `pypi` environment with a required reviewer, administrators allowed
to bypass, and deployment branches limited to `dev` and `main`.

**The release workflow does not run from a branch. It runs from a tag** (`on: push: tags:
v*.*.*`), so at deployment time `github.ref` is `refs/tags/v0.1.0`. With the environment
limited to selected branches only, the deployment is rejected before it starts and the
publish never happens.

Fix it in **Settings**, **Environments**, `pypi`, **Deployment branches and tags**, keep
**Selected branches and tags**, then **Add deployment branch or tag rule**, choose the **Tag**
type and enter:

```
v*
```

Keep the `dev` and `main` branch rules if you want; they do no harm. The tag rule is the one
that matters, and without it `v0.1.0` will fail.

## PyPI trusted publishing

PyPI, **Publishing**, **Add a new pending publisher**:

```
PyPI Project Name:  sanchopanza
Owner:              romanpert
Repository name:    sancho
Workflow name:      release.yml
Environment name:   pypi
```

The environment name must match the `environment: name: pypi` in `release.yml` exactly, or
the OIDC exchange is refused.

## Releasing

```
git tag v0.1.0
git push origin v0.1.0
```

The workflow checks that the tag matches the version in `pyproject.toml`, runs ruff, the test
suite and a replay of the public benches from the recorded fixture, builds, waits for your
approval on the `pypi` environment, publishes with OIDC and cuts a GitHub release. Nothing is
published that has not passed all of that first.
