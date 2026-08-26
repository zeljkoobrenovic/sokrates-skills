# sokrates-skills

Skills for AI coding tools (Claude Code and similar) that work with [Sokrates](https://sokrates.dev) source-code analyses — both **before** an analysis (getting the configuration right) and **after** it (adding the semantic layer that only an AI reader can add).

Sokrates measures: size, complexity, duplication, churn, coupling, contributors. These skills add what the numbers cannot say — what the code *is*, what it depends on, where the real risks are, how it got here — and they make Sokrates itself more useful by configuring it well: meaningful components, features of interest, merged contributor identities, sensible landscapes.

## What is in here

```
skills/
├── scanners/    analysis skills — read a finished _sokrates/ analysis, write verifiable findings,
│                render the AI Insights Explorer (one interactive HTML page per project)
└── config/      configuration skills — create and tune _sokrates/config.json and
                 _sokrates_landscape/ files, each with a checker that simulates Sokrates' rules
```

### Analysis skills (`skills/scanners/`)

| skill | what it finds |
|---|---|
| `sokrates-scan-core` | the shared contract: findings format, evidence rules, validator, explorer renderer, merge/diff tools |
| `full-scan` | orchestrator — runs all scanners in dependency order and merges the results |
| `domain-map-scan` | the domain language: glossary, bounded contexts, capabilities, language drift |
| `architecture-scan` | the implemented architecture: style, components, boundaries, violations, communication, migrations |
| `tech-stack-scan` | languages, frameworks, libraries, build tooling, CI/CD, infrastructure, external services |
| `cicd-scan` | the CI/CD process as a narrative: triggers, build, tests, gates, release, deployment, hygiene |
| `observability-scan` | logging, metrics, tracing, error reporting, health surfaces, telemetry pipeline, blind spots |
| `security-design-scan` | trust boundaries, sandboxing, identity and access, secrets handling, third-party trust, posture |
| `security-scan` | code-level audit: secrets, injection, crypto, unsafe code, input handling, coverage statement |
| `risk-synthesis-scan` | Sokrates hotspots explained: what each risky file does, knowledge risk, change coupling |
| `evolution-scan` | the history as a story: eras, growth, focus shift, people, module lifecycle, trajectory |

Every finding carries file + line + verbatim snippet evidence that a script verifies against the tree — a scan is not finished until validation passes. Results land in `<project>/_sokrates/findings/ai-insights/` as JSON plus `index.html`, the **AI Insights Explorer**: overview, per-scanner pages, cross-scanner attention list, filters, search, evidence citations, deep links.

### Configuration skills (`skills/config/`)

| skill | configures |
|---|---|
| `sokrates-repo-config` | `_sokrates/config.json`: scope, file classification, thresholds, history settings — with a preview that applies the config to the real tree |
| `sokrates-decompositions` | meaningful logical decompositions (components): folder depth, build modules, mixed depth for monorepos, ownership, layers |
| `sokrates-features-of-interest` | concerns / features of interest: debt markers, security-sensitive code, feature flags, domain vocabulary, integrations |
| `sokrates-landscape-config` | `_sokrates_landscape/` files: discovery, filters, tags, teams, embeds — with a checker |
| `sokrates-people-config` | `config-people.json`: contributor identity merging from git history, with a review file for the human decisions |
| `sokrates-virtual-landscapes` | virtual sub-landscapes from the user's grouping or from naming conventions, technology, activity, teams |

The field references under `skills/config/*/references/` were read from the Sokrates Java source, including the places where the documentation and the code disagree.

## Example

**[Live: AI Insights Explorer for openai/codex](https://zeljkoobrenovic.github.io/sokrates-skills/examples/codex/ai-insights/)** — all nine scanners, 191 verified findings (source in `examples/codex/ai-insights/`).

## Install

Link the skills you want into your tool's skills folder (Claude Code shown):

```bash
git clone https://github.com/zeljkoobrenovic/sokrates-skills.git
cd sokrates-skills
for s in skills/scanners/*/ skills/config/*/; do ln -s "$(pwd)/$s" ~/.claude/skills/$(basename "$s"); done
```

Then, in a project that has a Sokrates analysis (`_sokrates/` next to the source), ask your tool for e.g. "run a tech stack scan", "run a full scan", "define better components for this repo", or "merge duplicate contributors in this landscape".

Requirements: Python 3.9+ (standard library only) for the scripts; a Sokrates analysis (`sokrates init` → `sokrates generateReports`) for the scanners; `git-history.txt` (`sokrates extractGitHistory`) for history-based skills.

## Development

New skills follow the loop that produced the existing ones: write the `SKILL.md` against the family conventions in `skills/scanners/sokrates-scan-core/SKILL.md`, run it live on a real codebase with a fresh agent, ask that agent what was unclear or missing, and fold the answers back into the skill and its scripts. See `skills/scanners/README.md` and `skills/config/README.md` for the per-family details.

## License

[MIT](LICENSE)
