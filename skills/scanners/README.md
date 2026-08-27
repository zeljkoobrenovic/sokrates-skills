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
| `full-scan` | ✅ | Orchestrator: runs all ten scanners in dependency order (waves), merges into the combined report, diffs against previous results on re-runs |
| `functionality-scan` | ✅ | What the software does, from the code: purpose and audience, feature inventory with entry points and behaviour, surfaces (CLI/API/UI/config/hooks), end-to-end workflows, data managed, integrations, hidden/dormant functionality and doc-vs-code gaps |
| `tech-stack-scan` | ✅ | Languages, frameworks, libraries, build tooling, CI/CD, infrastructure, databases, external services, protocols |
| `risk-synthesis-scan` | ✅ | Narrative explanation of Sokrates hotspots: what each risky file does and why it's risky, knowledge risk (bus factor, single-owner areas), change coupling explained |
| `cicd-scan` | ✅ | The CI/CD process as a narrative: triggers, build, test gates, quality gates, release and publishing, deployment/install channels, pipeline hygiene risks |
| `observability-scan` | ✅ | How the code observes itself: logging, metrics, tracing, error reporting, health surfaces, where telemetry flows, and what monitoring the emitted signals can (and cannot) support |
| `security-design-scan` | ✅ | The security architecture as implemented: trust boundaries, sandboxing/isolation, identity and access design, secrets handling, third-party/runtime trust, posture synthesis and gaps |
| `architecture-scan` | ✅ | The implemented architecture: style, component responsibilities, load-bearing boundaries and contracts, dependency-direction violations, runtime communication, migrations in progress |
| `security-scan` | ✅ | Code-level security audit: secrets in the tree, injection-prone construction, crypto fitness, unsafe-code hygiene, input handling — with an explicit clean-coverage statement (design-level review is `security-design-scan`) |
| `domain-language-scan` | ✅ | The domain language: code-anchored concept glossary, bounded contexts and canonical definitions, concepts per capability family, language drift (synonyms, homonyms, renames mid-flight) |
| `evolution-scan` | ✅ | The codebase's history as a story: eras of development, growth and where the code came from, how the center of activity shifted between areas, contributor arrivals and departures, module births/rewrites/deaths, and the velocity and work-mix trajectory |

## Usage

Point an AI tool with these skills at a project containing a `_sokrates` analysis and ask, e.g., "run a tech stack scan". Output lands in `<project>/_sokrates/findings/ai-insights/` — open `index.html` there to browse.

To make the skills available in Claude Code, link or copy them into a skills location, e.g.:

```bash
for s in skills/scanners/*/; do ln -s "$(pwd)/$s" ~/.claude/skills/$(basename "$s"); done
```
