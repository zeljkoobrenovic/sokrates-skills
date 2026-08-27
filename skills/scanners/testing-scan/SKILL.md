---
name: testing-scan
description: Reads a codebase's tests as a system - the test model as implemented (unit/integration/end-to-end/snapshot/property/fuzz split, frameworks, where tests live, test-to-main ratio per component), the coverage map inferred from what the tests reference (which components, features and paths are well tested, thinly tested or untested - without a coverage tool), test quality (assertion strength, mocking discipline, fixtures and test data, determinism, flakiness markers, skipped and ignored tests, duplication), the test infrastructure (harnesses, golden files, mock servers, containers, generated tests, how to run them locally), and the gaps on load-bearing paths - synthesized into a testing posture. Use whenever the user asks how well a project is tested, what the tests cover, whether tests are trustworthy or flaky, what kinds of tests exist, how to run them, where test coverage is missing, or wants a test strategy/quality review. Works best with a Sokrates analysis (_sokrates folder - the test scope and per-component file lists are the starting inventory) but degrades gracefully without one.
---

# Testing scan

Tests are the executable statement of what a team promised itself would keep working. This scanner reads that statement — what kinds of tests exist and where, what they actually exercise, how much they can be trusted, and which load-bearing code has no promise attached at all. It infers coverage from what the tests *reference*, not from a coverage tool; say so in the summary.

**First read `sokrates-scan-core/SKILL.md`** (sibling skill) — output format, evidence rules, validate/render scripts, `_sokrates` layout. This file adds only what is specific to testing scanning.

## The one question

*If this component broke, which test would fail — and would anyone believe it?* Ask it per component and per load-bearing path.

## Scope and boundaries with sibling scanners

- **`cicd-scan`** (`testing`, `quality-gates`) owns *when and where tests run in the pipeline*: what a PR must pass, the OS/version matrix, post-merge and nightly runs. Reference its findings for gating; this scanner owns the tests themselves. Do not re-describe workflow files.
- **`functionality-scan`** (`features`) is the list of promises; the `coverage-map` maps tests onto it by reference to its feature ids.
- **`risk-synthesis-scan`** (`hotspots`) names the files where an untested change costs most; `gaps` cross-references them.
- **`reliability-scan`** owns failure handling; `gaps/error-paths` here says only whether those paths have tests, with references.
- **`architecture-scan`** names the components; use its names and the Sokrates `aspect_component_*` file lists for the per-component ratio.
- **`tech-stack-scan`** names the test frameworks; do not re-inventory, describe how they are used.

**Cross-referencing.** List existing ids first (`grep -h '"id"' _sokrates/findings/ai-insights/*.json --exclude=combined-report.json`) and reference siblings as `sokrates_refs: ["finding:<scanner>/<group>/<slug>"]` — only ids you saw. Never copy another scanner's evidence blocks.

## Workflow

1. **Orient per the core skill.** Sokrates' `test` scope is the starting inventory: `testFilesPaths.json` / `text/aspect_test.txt` (test files with LOC), `text/testFilesWithHistory.txt` (age, churn, contributors per test file), `text/aspect_component_*` (main files per component, for the ratio). **Sokrates classifies by path**, so tests that live inside main files — Rust `#[cfg(test)]` modules, Python doctests, Go example tests in non-`_test` files — are invisible to it; the script below measures them. Read `cicd-scan/testing` for how tests are gated and `functionality-scan/features` for the promise list. Also `metrics.txt` in `data.zip` (`TEST_VS_MAIN_LINES_OF_CODE_PERCENTAGE`, per-extension test/main splits) and `text/testFilesWithHistory.txt` (column 4, days since first update — sort by it for the newest tests per component). Sokrates has **no duplication data for the test scope**; do not cite `metric:duplication` for tests. Check the build files for a coverage tool (JaCoCo, `cargo-llvm-cov`, `coverage.py`, `nyc`/`c8`) and state in the posture whether one exists — this scan never runs the suite and never claims a percentage. **Do not run the tests.**
2. **Count with the script, then find the test infrastructure.** Run
   ```bash
   python3 <this-skill-path>/scripts/count_test_sites.py <src-root> --json <scratch>/test-counts.json
   ```
   It reports, per ecosystem: test files and LOC by path *and* inline test modules (Rust `#[cfg(test)]` LOC per crate), frameworks and runners used, test functions, assertions and assertion density, mocks/fakes/spies, snapshot/golden files, property and fuzz tests, skipped/ignored/flaky-marked tests, sleeps/time/randomness/network in tests, test-only helpers, and test LOC per top-level folder — facts to copy into `stats`, leads to read. From its top files locate: the shared harness/fixtures (`conftest.py`, `test_support`, `TestUtils`, `*_helpers`), the mock servers and recorded fixtures, the golden/snapshot directories, the e2e/integration runner, and the biggest test files. Outline the harness API (`pub fn`, constructors, skip macros) rather than reading thousands of wrapper lines; read a *sample* of ordinary tests per component (3–5 each: the largest *with test functions* — the script's largest-files list already excludes fixture classes — and the newest by `testFilesWithHistory.txt`) — outline the rest. With a Sokrates analysis, run it with `--components-dir <unzipped data.zip>` — it maps every test file and inline module to the Sokrates component whose directories it lives under and prints main/test/inline LOC and test-function counts per component: that table *is* `ratio-by-component` and, at scale, most of the coverage grading. Then run it again with `--refs-file` on the load-bearing main files (hotspot files from `risk-synthesis-scan` evidence, the entry points named by architecture/reliability findings, and each `aspect_component_*.txt` list for the ratio): it prints how many test files reference each — the table that grounds `coverage-map` and `gaps`.
3. **Build the test model.** The layers as implemented: unit, integration (what boundary they cross — real DB? real filesystem? in-process server?), end-to-end (real binary? real network?), snapshot/golden, property-based, fuzz, benchmarks-as-tests, doc tests. Frameworks and runners per layer (reference `tech-stack-scan`'s framework finding; `test-model/frameworks` exists only when tech-stack has none), where each lives, and the ratio of test to main LOC per component. Two LOC sources exist — Sokrates (`metric:loc`, all extensions in scope, so HTML templates count as main) and the script (code files only); state both when they differ by more than a few points and say which the grade uses. This is the `test-model/layers` finding plus `test-model/ratio-by-component`; every run command (one test, the suite, the slow tier) lives in `test-model/run-commands` — the sole home, `test-infrastructure/harness` is for shared code, not commands.
4. **Infer the coverage map.** For each component (and each major feature from functionality-scan): which tests reference it (imports, paths, command names, endpoint names), at which layer, and how deeply (happy path only? error paths? edge cases?). Grade it `well`, `thin`, `untested` with the evidence being the tests that exist (or the absence — cite the component's main entry file and say no test references it). Rule of thumb: `untested` = no test references any of its files; `thin` = tests exist but the component's largest or hottest files have none, or only snapshot/smoke tests touch it; `well` = its load-bearing files each have referencing tests at more than one layer or with error-path cases; `adequate` = a suite exists and the ratio is healthy but you did not read enough to say more — use it honestly at scale instead of inflating to `well`. Above ~100k test LOC the grade comes from the inventory (the component table, which hotspot has a `*_tests.rs` sibling or inline module, which suite modules exist); reads are reserved for the thin and suspect components and the quality findings. Do not claim percentages; say "no test imports `X`" or "the only tests of `Y` are snapshot tests". A per-feature verdict (`feature-<feature>`) is written only when features and components diverge (a feature spanning several components, or one component serving several features); in a modular monolith the component verdicts suffice.
5. **Judge test quality.** Assertion strength (asserting on outputs vs "does not throw"; snapshot-only suites; assertion density), mocking discipline (what is mocked — the boundary or the thing under test; mock-heavy suites that test the mocks), fixtures and test data (shared builders vs copy-paste, recorded fixtures and how they are refreshed), determinism (sleeps, wall-clock, randomness without seed, real network, order dependence, shared global state), flakiness markers (`retry`, `flaky`, `#[ignore]`, `skip`, `xfail`, `@Disabled`, `it.skip`) and their reasons, skipped tests that hide failures, test duplication (Sokrates duplication in the test scope, `metric:duplication`), test runtime hints (huge suites, per-test containers).
6. **Read the infrastructure.** Harnesses and base classes, fake/mock servers, containers or services needed, golden-file update commands, generated tests, test-only feature flags and build profiles, how a developer runs one test, the whole suite, and the slow tier; what CI runs that a developer cannot (reference cicd-scan).
7. **Find the gaps.** Load-bearing code with no test reference: Sokrates hotspots (`risk-synthesis-scan`) and the main loop / persistence writer / external-call wrapper named by architecture and reliability findings; error paths never exercised (`reliability-scan/handling`); features in functionality-scan's inventory with no test; whole layers missing (no integration tests at all; e2e only manual). Each gap is evidenced by the untested file and the nearest existing test file of that component (a directory cannot be cited). When every hotspot has a direct test, that positive verdict goes into `well-tested.attributes.hotspots_with_tests` — `gaps/hotspots` is written only for uncovered ones. `coverage-map/thin-<component>` is the *component verdict*; `gaps/*` names the *files and paths* — a thin component's untested hotspot file appears in `gaps/hotspots` with the component finding referenced, never in both narratives. `missing-layer-<layer>` is written only when the missing layer would cover something `main-loop`/`persistence`/`external-calls` do not already name (for a batch CLI, an absent e2e layer and an untested main loop are one finding: `main-loop`). Client-side code shipped inside templates or assets with no test runner at all is `gaps/untested-<artifact>` (e.g. `untested-report-templates`).
8. **Synthesize the posture.** One `testing-posture/posture` finding, `severity: info`, `confidence: likely`: the pyramid shape, what a green run does and does not prove, the most trusted and least trusted suites, and the three highest-leverage changes as `finding:` refs. Evidence cites the harness or the runner configuration.
9. Write findings, validate, render; re-run the merge script if a `combined-report.json` exists. Report per the core workflow. Scanner id: `testing-scan`, version `1.1`.

## Group taxonomy

| group | contents |
|---|---|
| `test-model` | The layers as implemented (unit/integration/e2e/snapshot/property/fuzz/doc), frameworks and runners per layer, where tests live, test-to-main ratio per component, how each layer is run |
| `coverage-map` | Per component and per major feature: which tests reference it, at which layer, how deeply; the well-tested, thin and untested areas — inferred from references, not measured |
| `test-quality` | Assertion strength, mocking discipline, fixtures and test data, determinism (sleeps, clock, randomness, network, order, shared state), flakiness and skip markers with reasons, duplication, runtime |
| `test-infrastructure` | Harnesses and base classes, mock servers and recorded fixtures, golden/snapshot management, containers and services, generated tests, test-only flags and profiles, local run commands |
| `gaps` | Untested load-bearing paths (hotspots, main loop, persistence, external calls), error paths without tests, features without tests, missing layers |
| `testing-posture` | The synthesis (one finding, `info`, id `testing-posture/posture`) |

**Precedence**: a skipped/ignored test → `test-quality/skipped-tests` (its subject's missing coverage is mentioned there, not duplicated in `gaps`); an `#[ignore = "flaky"]` or skip-for-flakiness → `flakiness` wins, listed in `skipped-tests.attributes`; a mock server that lives in the shared support crate → `harness` (`mock-servers` only when it is a separate artifact); env vars that select what runs → `run-commands`, not `test-flags`; a snapshot-only suite → `test-quality/assertion-strength`, its subject's shallow coverage → `coverage-map` (one mention, reference the quality finding); a mock server → `test-infrastructure`, over-mocking → `test-quality/mocking`; a component with tests only in another layer → `coverage-map`, not `gaps` (`gaps` is for *no* test); a flaky marker → `test-quality/flakiness`, the sleep that causes it → same finding.

## Stable ids

Slugs are **layer, component, mechanism or artifact names, never consequences**. Fixed slugs (use only when the subject exists; `<component>` is the architecture/Sokrates component name in kebab-case, `<feature>` the functionality-scan feature slug):

| group | fixed slugs |
|---|---|
| `test-model` | `layers`, `ratio-by-component`, `inline-tests` (tests inside main files, when they are a material share), `frameworks` (only when tech-stack-scan has no framework finding), `run-commands` |
| `coverage-map` | `well-tested` (one finding, components in `attributes`), `thin-<component>`, `untested-<component>`, `feature-<feature>` (only for a headline feature whose coverage deserves its own verdict) |
| `test-quality` | `assertion-strength`, `mocking`, `fixtures-and-data`, `determinism`, `flakiness`, `skipped-tests`, `duplication`, `runtime` |
| `test-infrastructure` | `harness` (shared support code, including in-crate mock servers), `mock-servers` (separate artifacts only), `golden-files`, `containers-and-services`, `generated-tests`, `test-flags` (build profiles and features only) |
| `gaps` | `hotspots`, `main-loop`, `persistence`, `external-calls`, `error-paths`, `missing-layer-<layer>` (e.g. `missing-layer-integration`), `untested-<artifact>` |
| `testing-posture` | `posture` |

Project-specific findings get a free slug naming the suite or artifact (`test-infrastructure/wiremock-recordings`), never the consequence. Several mechanisms sharing a slug are listed in `attributes`. `coverage-map` findings carry `attributes.tests` (the test files or modules that ground the verdict) so a re-run can see what changed.

## What a good finding looks like

Evidence is the test function that proves the layer exists, the `assert` (or its absence) in a representative test, the `#[ignore]`/`skip` line with its reason, the `sleep` in the flaky test, the harness constructor, the golden-file directory listing entry, the mock-server setup — and for gaps, the untested entry point. Descriptions speak per component or suite: "the `core` crate has 612 inline test functions against 42k LOC, mostly unit; the session loop is exercised only through `tests/suite/*` end-to-end runs behind a mock model server". Numbers from Sokrates (test LOC, ratios, duplication) go in the description with `metric:` refs — they are not file/line evidence.

One finding per layer, component, mechanism or gap — not per test file. Expected on every project: `layers`, `ratio-by-component`, `run-commands`, `well-tested`, `assertion-strength`, `determinism`, `hotspots`, `posture`; everything else only when the subject exists (a `test-quality` slot with nothing to say — no mocks, no flaky markers — is a sentence in the posture, not a finding). That lands at 12–20 findings for a mid-size to large codebase, fewer for a small one; roughly half `info` (the model, the infrastructure, the well-tested map).

## Severity calibration

- `high` — a load-bearing path (main loop, persistence writer, security boundary, payment/auth flow) with *no* test at any layer **and** whose parts are untested too; an entire language or runtime shipped in the repo (client-side code in templates, an SDK) with no test runner at all when it carries a headline feature; a suite that is green while asserting nothing (assertions stripped, snapshot suites that auto-accept); skipped tests that hide a known failing behaviour on a shipped path.
- `medium` — skipped tests whose skip reason says the behaviour is known-incorrect on a shipped path (`high` when the path is load-bearing); orchestration untested while its parts are (the main loop has no test but every stage does); a whole layer missing where the system's risk demands it (no integration tests for a system whose bugs are integration bugs); flaky tests retried or ignored without tracking; tests that depend on real network or wall-clock on the default path; a component with heavy churn and only thin tests (cross-reference hotspots); over-mocking that tests the mocks.
- `low` — thin coverage on a stable component, duplication in tests, slow suites without a fast tier, golden files updated by hand with no review guidance, fixtures copy-pasted, test-only helpers that drifted from production behaviour.
- `info` — the model, the infrastructure, the well-tested map, the run commands.
- Mitigations lower a finding one rung: the untested path is exercised by an e2e or manual QA suite documented in the repo, the component is small and stable, the flakiness is tracked in an issue linked from the test, the self-skipping tests demonstrably run on a CI matrix leg (reference `cicd-scan`).

## Output

Follow the core workflow: write `_sokrates/findings/ai-insights/testing-scan.json`, validate until OK, render the explorer, re-merge if a combined report exists, report leading with the posture summary (what a green run proves and the biggest gap, in two sentences) and any above-info findings.

`stats` — copy the script's **facts** under its own keys (zeros included; omit keys whose shape does not exist in the ecosystem; a fact key you verified as false positives is omitted and named in `count_notes`), add `count_rule`, and on top:

- `test_loc`, `main_loc`, `test_ratio` — the script's numbers; `test_ratio` is `{"path_based": 0.31, "inline": 0.12, "total": 0.43}` for ecosystems with inline tests and a plain number otherwise; add `sokrates_test_ratio` when Sokrates' scope-based figure differs materially
- `layers` — object: layer → `{"framework": "...", "runner": "...", "tests": n}` where `tests` is given only when countable (annotated test functions for unit; files for other layers, stated as such)
- `framework_split` — e.g. `{"junit4_files": 116, "junit5_files": 61}` when more than one framework generation coexists
- `coverage_tool` — the configured tool or `none`
- `test_files_created_last_240d` — from `testFilesWithHistory.txt`
- `ratio_by_component` — the script's `by_component` table (main, test, inline LOC and test functions per Sokrates component)
- `coverage_grades` — object: component → `well` | `adequate` | `thin` | `untested`
- `skipped_tests`, `flaky_markers`, `sleep_in_tests`, `network_in_tests`, `tier_markers` — from the script
- `test_references` — the `--refs-file` table for the load-bearing files: `{"<path>": n}`
- `run_commands` — list of the commands a developer uses (unit, whole suite, slow tier)
