# Sokrates AI scanner skills (`skills/scanners/`)

Skills that let AI coding tools (Claude Code and similar) produce additional semantic insights for codebases analyzed with [Sokrates](https://sokrates.dev). Sokrates provides the quantitative layer (size, complexity, duplication, churn, coupling, contributors); these scanners add the layer only an AI reader can: what the code means, what it depends on, and where the real risks are.

## Design

All scanners share one contract, defined in **`sokrates-scan-core`**:

- **Uniform output** — every scanner writes `_sokrates/findings/ai-insights/<scanner>.json`: grouped findings, each with severity, confidence, and evidence (file + line range + verbatim fragment). Schema: `sokrates-scan-core/schema/findings.schema.json`.
- **Verifiable evidence** — `scripts/validate_findings.py` mechanically checks each cited snippet against the actual file. A scan is not done until validation passes; this is the guard against hallucinated findings.
- **Sokrates-aware** — scanners read the existing `_sokrates` data first (components, hotspots, file inventories) and spend AI effort where the numbers point, citing back via `sokrates_refs`.
- **Uniform reports** — `scripts/render_findings.py` builds the **AI Insights Explorer** (`ai-insights/index.html`, from `templates/insights-explorer.html`): one self-contained interactive HTML page embedding all scanners' findings — overview, per-scanner pages, cross-scanner attention list, filters, search, evidence citations, deep links. No markdown reports.
- **Composable & diffable** — `scripts/merge_findings.py` rolls all scanners of a project into one machine-readable `combined-report.json` (a schema-conformant findings document the validator and differ accept); `scripts/diff_findings.py` compares two runs of a scanner via the stable-id contract (new / resolved / persisting, CI-friendly exit code).

## Scanners

| skill | status | what it finds |
|---|---|---|
| `sokrates-scan-core` | ✅ | (shared foundation, not a scanner) |
| `full-scan` | ✅ | Orchestrator: runs all fifteen scanners in dependency order (waves), merges into the combined report, diffs against previous results on re-runs |
| `functionality-scan` | ✅ | What the software does, from the code: purpose and audience, feature inventory with entry points and behaviour, surfaces (CLI/API/UI/config/hooks), end-to-end workflows, data managed, integrations, hidden/dormant functionality and doc-vs-code gaps |
| `tech-stack-scan` | ✅ | Languages, frameworks, libraries, build tooling, CI/CD, infrastructure, databases, external services, protocols |
| `risk-synthesis-scan` | ✅ | Narrative explanation of Sokrates hotspots: what each risky file does and why it's risky, knowledge risk (bus factor, single-owner areas), change coupling explained |
| `cicd-scan` | ✅ | The CI/CD process as a narrative: triggers, build, test gates, quality gates, release and publishing, deployment/install channels, pipeline hygiene risks |
| `testing-scan` | ✅ | The tests as a system: layers as implemented, coverage map inferred from what tests reference, test quality (assertions, mocking, determinism, flakiness, skips), test infrastructure, gaps on load-bearing paths |
| `observability-scan` | ✅ | How the code observes itself: logging, metrics, tracing, error reporting, health surfaces, where telemetry flows, and what monitoring the emitted signals can (and cannot) support |
| `reliability-scan` | ✅ | How the code behaves when things go wrong: error model, handling on load-bearing paths (swallowed, catch-all, panics), failure isolation and blast radius, retries/timeouts/circuit breakers, degradation and fallbacks, resource cleanup and shutdown, posture per failure source |
| `performance-scan` | ✅ | Static performance review: workload model and scaling factors, algorithmic/data-structure choices on hot paths, I/O and memory, parallelism and contention, caching and recomputation, cost limits — ranked likely bottlenecks and highest-leverage optimizations |
| `storage-scan` | ✅ | How persistent data is handled: data classes and where they live, access patterns (ORM/SQL, transactions, locking, streaming), schema/format ownership and migrations, integrity and corruption recovery, lifecycle (retention, cleanup, backup) |
| `network-scan` | ✅ | Connectivity behaviour: endpoint topology (listens/connects, defaults), protocols as used, connection management (timeouts, TLS, proxies, reconnection), endpoint configurability, offline behaviour, data in transit |
| `architecture-scan` | ✅ | The implemented architecture: style, component responsibilities, load-bearing boundaries and contracts, dependency-direction violations, runtime communication, migrations in progress, security boundaries as structure (trust map, sandboxing, network confinement, escape hatches) |
| `security-scan` | ✅ | Security review, design first and code second: identity and permission design, secrets by design and in the tree, boundary validation and injection-prone construction, crypto fitness, unsafe/native/dynamic code, third-party and model-output trust — with a posture stating what was swept clean and what was not covered (trust boundaries and sandboxing as structure live in `architecture-scan`) |
| `domain-language-scan` | ✅ | The domain language: code-anchored concept glossary, bounded contexts and canonical definitions, concepts per capability family, language drift (synonyms, homonyms, renames mid-flight) |
| `maintainability-scan` | ✅ | Maintainability grades — modularity, reusability, analysability, modifiability, testability — per sub-characteristic and per component, rolled up from Sokrates numbers and the other scanners' findings (runs last) |
| `evolution-scan` | ✅ | The codebase's history as a story: eras of development, growth and where the code came from, how the center of activity shifted between areas, contributor arrivals and departures, module births/rewrites/deaths, and the velocity and work-mix trajectory |

## Usage

Point an AI tool with these skills at a project containing a `_sokrates` analysis and ask, e.g., "run a tech stack scan". Output lands in `<project>/_sokrates/findings/ai-insights/` — open `index.html` there to browse.

To make the skills available in Claude Code, link or copy them into a skills location, e.g.:

```bash
for s in skills/scanners/*/; do ln -s "$(pwd)/$s" ~/.claude/skills/$(basename "$s"); done
```
