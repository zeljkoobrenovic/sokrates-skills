---
name: cicd-scan
description: Reconstructs a codebase's CI/CD process as an evidence-backed narrative - what triggers a build, how the code is built and tested, which quality gates guard merges, how releases are versioned and published, where artifacts get deployed and how users receive them - plus hygiene risks in the pipeline itself (unpinned actions, missing gates, secret exposure). Use whenever the user asks how a project is built/tested/deployed/released, wants the CI/CD or release process explained or documented, asks "what happens when I push / tag / merge", or wants a pipeline audit. Works best with a Sokrates analysis (_sokrates folder) but degrades gracefully without one.
---

# CI/CD process scan

Config files say what steps exist; they don't say what the *process* is. This scanner reads the pipeline definitions, build files, and release scripts and reconstructs the lifecycle a change actually goes through — "a PR triggers X, a merge to main additionally Y, a tag starting with `v` releases Z to W" — in words a new team member or an auditor can follow. Inventorying the *tools* (which CI provider, which build system) is `tech-stack-scan`'s job; this scanner explains the *flow* and judges its hygiene.

**First read `sokrates-scan-core/SKILL.md`** (sibling skill) — it defines the output format, evidence rules, validate/render scripts, and the `_sokrates` data layout. This file adds only what is specific to CI/CD scanning.

## Workflow

1. Orient per the core skill. The extracted data's build/deployment index (`buildAndDeploymentFilesPaths.json` for paths, `buildAndDeploymentFiles.json` for per-file records) lists build files and scripts — but CI workflow files are often *missing* from it (Sokrates ignore rules frequently exclude `.github/`). Treat the index as a supplement: always glob `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, etc. directly.
2. **Map the trigger surface first.** List every pipeline entry point and its trigger before reading any steps: each CI workflow's `on:`/trigger block, scheduled jobs, manual dispatches, tag patterns, path filters. The trigger surface is the skeleton every other finding hangs on.
3. **Trace each lifecycle stage** (see taxonomy). For each, read the relevant workflow jobs and the scripts they shell out to — a workflow step that runs `./scripts/release.sh` is only understood by reading `release.sh`. Reusable-workflow composition (`uses: ./.github/workflows/...`, `workflow_call`) is part of the pipeline definition itself — follow those chains freely to their leaves; the "one level of indirection" budget refers to leaving workflow-land into scripts and programs. Note in the finding when you stopped following.
4. **Distinguish declared from inferred.** "This workflow uploads to crates.io" is `certain` (the step is right there). "Deploys probably happen from a separate private repo" is an inference — mark it `possible` and say what signal suggests it. Absences are findings too: no deploy step in any workflow is worth a finding *saying* deployment happens elsewhere.
5. Write findings, validate, render, and report per the core workflow. Scanner id: `cicd-scan`, version `1.0`.

## Group taxonomy

| group | contents |
|---|---|
| `triggers` | The pipeline entry-point map: what runs on PR, push, tag, schedule, manual dispatch; path filters and concurrency rules. Usually one overview finding plus one per unusual trigger worth explaining |
| `build` | How source becomes artifacts, per ecosystem: build commands, cross-compilation/target matrix, caching strategy, reproducibility measures (lockfile enforcement, pinned toolchains, hermetic builds) |
| `testing` | Test *execution* in the pipeline: which suites run when (PR vs post-merge vs nightly), on what OS/version matrix, with what caching and sharding, and what a green PR proves. The tests themselves — layers, coverage, quality, flakiness — are `testing-scan`'s; reference its findings rather than describing suites |
| `quality-gates` | Non-test merge gates: lint/format/typecheck jobs, security and license scanning, codegen-freshness checks, required reviews, merge queues |
| `release` | How a release is cut: version bumping, changelog, tagging convention, artifact publishing (registries, package managers), signing/notarization/provenance |
| `deployment` | Where artifacts go and how users get them: deploy targets, environments and promotion, install channels (curl-script, package manager, auto-update), rollback story |
| `pipeline-hygiene` | The pipeline's own security and reliability posture — risks (unpinned third-party actions/images, over-broad credentials or `pull_request_target` misuse, secrets that could leak into logs or forks, missing gates on the release path, jobs that can't fail) *and* notable strengths (all actions SHA-pinned, credentials never persisted) |

A publish target like npm sits in two groups by design: the *act* of publishing (the job, its credentials, signing) is `release`; the *consumption channel map* (every way users receive the software, including that npm package) is `deployment`. Describe the mechanics once, in `release`, and let `deployment` reference them.

## What a good finding looks like

Each process finding answers: *what happens* (the flow, named triggers and steps — "on a `rust-v*` tag, workflow X builds N targets and uploads to Y"), *where that's defined* (evidence: the trigger line, the key step — cite the workflow/script lines you actually read), and *what's notable* (the judgment: a gap, a strength, an inference about the parts you can't see). A finding that paraphrases one workflow's step list adds nothing; the value is in connecting files into a flow and naming what's missing.

Aggregate by lifecycle stage, not by file: twelve workflow files that together form "the PR gate" are one `testing`/`quality-gates` story, not twelve findings. Per-file findings are only warranted for the odd one out. For a repo with a real pipeline expect roughly 10–20 findings overall; prefer merging over splitting when in doubt.

**Evidencing an absence.** The evidence contract only lets you cite lines that exist, so an absence finding cites the nearest *positive* fact that delimits it: "the release path runs no tests" is evidenced by the release workflow's `needs:` list (which visibly lacks a test job); "no workflow deploys the server" by the closest deploy-like step that exists (a webhook call, a docs mention). Say in the evidence `note` what the citation delimits.

## Severity calibration

Process descriptions are `info`. Raise severity only for pipeline defects:

- `high` — the release path lacks an integrity control it clearly should have (unsigned artifacts users curl into a shell, publish jobs runnable from unreviewed code, plaintext secrets in the repo).
- `medium` — hygiene issues with real attack or breakage surface: third-party actions pinned to mutable tags on jobs with secrets, no test gate before publish, `pull_request_target` with checkout of PR code.
- `low` — friction and drift risks: near-duplicate workflow blocks maintained by hand, caching that likely masks stale builds, gates that only warn.
- `info` — the process narrative itself, including well-done aspects worth stating (a strong finding of "this is solid, here's why" makes the criticism credible).

State absences at the severity of their consequence, but only when the absence is verifiable from the repo (e.g. "no workflow deploys the server component — deployment must live elsewhere" is `info`; "tests never run on Windows despite Windows-specific code paths" might be `medium`).

## Output

Follow the core workflow: write `_sokrates/findings/ai-insights/cicd-scan.json`, validate until OK, render the explorer, report leading with the one-paragraph lifecycle narrative and any above-info findings.

Use these `stats` keys where they apply (canonical, so re-runs compare): `workflows`, `scheduled`, `tag_trigger_families`, `publish_targets` (list), e.g. `{"workflows": 27, "scheduled": 2, "tag_trigger_families": 4, "publish_targets": ["npm", "R2", "WinGet"]}`. Do not count jobs — matrix expansion makes the number ill-defined and expensive; add other extras freely alongside.
