---
name: maintainability-scan
description: Grades a codebase's maintainability along the five ISO/IEC 25010 sub-characteristics - modularity (change impact radius between components), reusability (which assets can be used elsewhere and which are trapped or copy-pasted), analysability (can a newcomer find the part to change and see a change's consequences - naming, module size, documentation, dead code, coupling visibility), modifiability (where changes are expensive - complexity, size, duplication, temporal coupling, single ownership, hardcoded vs configured behaviour, fix-heavy churn), and testability (seams, injectability, global state, and the testing scanner's verdict) - as evidenced grades per sub-characteristic and per component, rolled up from Sokrates' metrics and the other scanners' findings plus targeted reading. Use whenever the user asks how maintainable a codebase is, for a maintainability/technical-debt assessment, an ISO 25010 quality evaluation, whether the code is easy to change or understand, where maintenance effort goes, or wants Sokrates' size/complexity/duplication/coupling numbers turned into a judgement. Requires a _sokrates analysis; strongest after the other scanners have run.
---

# Maintainability scan

Sokrates measures the raw material of maintainability — size, complexity, duplication, coupling, churn, ownership — and the other scanners explain individual parts of it. This scanner turns those into the judgement a quality standard asks for: per ISO/IEC 25010 sub-characteristic, **how maintainable is this system, where exactly is it not, and what drives that** — graded, evidenced, and diffable across runs. It is the family's roll-up scanner: most of its evidence anchors are Sokrates numbers and sibling findings; its own reading is targeted at what nobody else covers (reusability, analysability).

**First read `sokrates-scan-core/SKILL.md`** (sibling skill) — output format, evidence rules, validate/render scripts, `_sokrates` layout. This file adds only what is specific to maintainability scanning.

## The one question

*If a competent newcomer had to make a typical change here, how long until they find the place, how much else moves, and how would they know it worked?* Ask it per component; the five sub-characteristics are the five parts of the answer.

## The roll-up evidence contract (this scanner's exception)

Every other scanner restates nothing. This one *may* cite a sibling finding as the primary anchor of a graded finding — restating-with-a-grade is its job — under two conditions: every finding still carries **at least one fresh file/line citation of its own** (the validator needs something to check; a manifest line, the biggest unit's signature, a duplicated block, the config key that makes behaviour configurable), and every number comes from Sokrates via `metric:` refs or from the script, never re-counted by hand. Sibling findings are referenced as `sokrates_refs: ["finding:<scanner>/<group>/<slug>"]` — only ids that exist (`grep -h '"id"' _sokrates/findings/ai-insights/*.json --exclude=combined-report.json`). Never copy a sibling's evidence block.

**Grades, not scores.** Each sub-characteristic and each major component gets one of `strong` / `adequate` / `weak` / `poor`, with the two or three drivers stated. No index, no percentage, no weighted formula — an invented number would read as a measurement, and the family's credibility rests on not faking one.

## Scope and boundaries with sibling scanners

- **`risk-synthesis-scan`** explains individual hotspots, knowledge risk and change coupling at file level. This scanner grades at system and component level and references those explanations; it never re-narrates a hotspot.
- **`architecture-scan`** owns the component map, boundaries, violations and cycles. `modularity` grades what that structure *costs a change* and references the violations; it does not re-map.
- **`testing-scan`** owns the tests. `testability` here is the *design's* testability (seams, injectability, global state, construction of collaborators) plus a one-line roll-up of testing-scan's coverage verdict — reference, do not re-grade the tests.
- **`domain-language-scan`** owns naming drift; `analysability/naming` references it and adds only the size/depth/documentation side.
- **`evolution-scan`** owns the history narrative; `modifiability/fix-heavy-areas` uses commit-message keywords from `git-commits.txt` as a number, referencing evolution's work-mix finding when present.
- **`reliability-scan`** / **`performance-scan`** own their qualities; a tolerant convention or a hot loop is cited here only as a modifiability driver.

## Workflow

1. **Orient per the core skill.** Read the sibling findings that carry maintainability evidence: `architecture-scan` (components, violations, cycles, decomposition verdict), `risk-synthesis-scan` (all groups), `testing-scan` (coverage grades, determinism), `domain-language-scan` (language-drift), `evolution-scan` (work mix, trajectory), `functionality-scan` (feature list, for "typical change" scenarios). Read `_sokrates/config.json` for the components and any concerns that track debt (`technical debt`, `deprecated`, `TODOs`).
2. **Compute the roll-up with the script.**
   ```bash
   python3 <this-skill-path>/scripts/compute_maintainability.py <unzipped-data-dir> [--commits <path>/git-commits.txt] --json <scratch>/maintainability.json
   ```
   From `data.zip` it derives, per component and for the system: size and complexity distribution (share of LOC in high/very-high-risk files and units), duplication share and **cross-component** duplication (the reuse-by-copy signal), component dependency fan-in/fan-out and cycles where Sokrates extracted dependencies (it says explicitly when it did not — Rust and some languages have none), temporal-coupling density (file pairs co-changing across components), ownership concentration (files with one contributor, top-contributor share), documentation footprint (doc files and their freshness vs code), dead-code hints (files unchanged for years in components that churn), TODO/deprecated concern counts, and — with `git-commits.txt` — the fix-vs-feature share of commit messages per component. It prints the table and writes every number with its provenance; **copy its `stats`, do not recompute.** The "typical change" scenarios it suggests (the most co-changing cross-component file pairs) are the reading leads for step 4.
3. **Read for reusability and analysability** — the two sub-characteristics nobody else covers. Reusability: which components are libraries in fact (no product-type imports, own manifest, used by more than one consumer) and which are trapped (a `utils` that imports product types, a shared crate that depends back on the app); where the same capability was copied instead of reused (the cross-component duplicate pairs — read two). Analysability: pick three files a newcomer would need for a typical change (from the scenarios) and record what stands in the way — file length, nesting depth, naming that misstates the role, missing module docs, indirection layers, generated-vs-hand-written confusion; then the documentation side (README/ADR/docs freshness vs code churn, doc comments on public surfaces) and dead code (unreferenced modules, feature-gated-forever paths — cite the manifest or the gate).
4. **Trace two typical changes end to end.** Take the two cross-component scenarios the script ranks highest (or two features from functionality-scan) and list the files a change touches, the components crossed, the tests that would catch a mistake (from testing-scan), the config that could avoid the change. This is the concrete evidence for `modularity`, `modifiability` and `testability` verdicts — the numbers say *where*, the traces say *why*.
5. **Grade.** Per sub-characteristic one system verdict (`<sub>/verdict`) with components graded in `attributes.components`, plus separate findings only where one place drives the grade (`modifiability/hotspot-cluster-<component>`, `reusability/trapped-<component>`, `analysability/oversized-<component>`). Each grade names its drivers with `metric:` refs and `finding:` refs and cites one fresh line. Where Sokrates data is missing for a driver (no dependency extraction), say so in the finding and lower confidence rather than guessing.
6. **Synthesize the posture.** One `maintainability-posture/posture` finding, `severity: info`, `confidence: likely`: the five grades in one sentence each, the component that costs the most maintenance effort and why, the trajectory (improving or eroding, from evolution-scan and churn), and the three highest-leverage changes as `finding:` refs to the findings that carry the recommendations.
7. Write findings, validate, render; re-run the merge script if a `combined-report.json` exists. Report per the core workflow. Scanner id: `maintainability-scan`, version `1.0`.

## Group taxonomy (ISO/IEC 25010)

| group | contents |
|---|---|
| `modularity` | Change impact radius: component coupling (fan-in/out, cycles), cross-component temporal coupling, boundary leaks — what a change in one component does to others |
| `reusability` | Which assets are reusable in fact (libraries with no product coupling, shared utilities with one owner) and which are trapped or copy-pasted (cross-component duplication, utilities depending on the product) |
| `analysability` | Can the part to change be found and its consequences seen: naming and module size/depth, documentation footprint and freshness, dead and dormant code, visibility of coupling, generated-vs-hand-written clarity |
| `modifiability` | Where changes are expensive: complexity/size/duplication concentration, hotspot clusters, single ownership, hardcoded vs configured behaviour, fix-heavy churn, shotgun-surgery shapes |
| `testability` | The design's testability: seams and injectable collaborators, global state, construction of dependencies, test-hostile patterns — with testing-scan's coverage verdict rolled up by reference |
| `maintainability-posture` | The synthesis (one finding, `info`, id `maintainability-posture/posture`): the five grades, the costliest component, the trajectory, the highest-leverage changes |

**Precedence**: a duplicated block across components → `reusability` (copy instead of reuse); within one component → `modifiability` driver; a dependency cycle → `modularity` (architecture owns the finding, this one grades it); single ownership → `modifiability` (risk-synthesis owns the knowledge-risk narrative); global state → `testability` (reliability owns its failure consequence); a misleading name → `analysability` (domain-language owns the drift narrative); a fix-heavy area → `modifiability/fix-heavy-areas`, its history story → evolution.

## Stable ids

| group | fixed slugs |
|---|---|
| `modularity` | `verdict`, `coupling-<component>` (one per component whose coupling drives the grade), `cross-component-cochange` |
| `reusability` | `verdict`, `libraries-in-fact`, `trapped-<component>`, `copy-instead-of-reuse` |
| `analysability` | `verdict`, `naming`, `module-size`, `documentation`, `dead-code`, `oversized-<component>` |
| `modifiability` | `verdict`, `hotspot-cluster-<component>`, `ownership`, `configurability`, `fix-heavy-areas`, `duplication` |
| `testability` | `verdict`, `seams`, `global-state`, `construction` |
| `maintainability-posture` | `posture` |

`<component>` is the Sokrates component name in kebab-case. `verdict` findings are always written (five of them); the others only when a driver earns its own finding. Grades live in `attributes.grade` (system) and `attributes.components` (object component → grade) so a re-run diffs the grade, not the prose.

## What a good finding looks like

A verdict finding states the grade, the two or three drivers with their numbers (`"41% of main LOC sits in very-high-risk files (metric:file_size)"`, `"7 of 12 cross-component co-change pairs involve `core`"`), the sibling findings that explain them, and one fresh citation (the largest unit's signature, the `Cargo.toml` line that makes a crate depend back on the app, the copied block). A component-specific finding says what a change there costs and what would shrink it. Expect 10–14 findings; five verdicts plus posture are mandatory, the rest earned.

## Severity calibration

Verdicts are `info` regardless of grade — the grade *is* the message and the attention list should not fill with five entries per run. Raise severity only on component-specific findings that call for action:

- `high` — a component graded `poor` on two or more sub-characteristics that is also the most-changed area (churn in the top quartile): every change there is expensive, risky and hard to verify.
- `medium` — a `poor` grade with one driver that has a clear fix (a trapped utility crate, a copy-instead-of-reuse pair on a hot path, an oversized module a newcomer must read, single ownership of a hot component).
- `low` — `weak` grades with contained drivers, documentation drift, dead code, configurability gaps off the hot path.
- Confidence: `certain` when the drivers are Sokrates numbers plus a read citation; `likely` when a driver is inferred (dead code from age alone, reusability from manifests without reading consumers); `possible` when Sokrates data for a driver is missing.

## Output

Follow the core workflow: write `_sokrates/findings/ai-insights/maintainability-scan.json`, validate until OK, render the explorer, re-merge if a combined report exists, report leading with the five grades in one line and the costliest component.

`stats` — copy the script's `stats` object verbatim (it carries `provenance` per number) and add:

- `grades` — `{"modularity": "adequate", "reusability": "weak", "analysability": "adequate", "modifiability": "weak", "testability": "strong"}`
- `component_grades` — object: component → the five grades
- `costliest_component` — name and the one-line reason
- `scenarios_traced` — the two typical changes, each as `{"change": "...", "files": n, "components": n, "tests": "..."}`
- `data_gaps` — list of drivers Sokrates could not supply (e.g. `"component dependencies (no extraction for Rust)"`)
