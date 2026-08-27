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
| `functionality-scan` | what the software does: purpose, features, entry points, workflows, data, integrations, hidden functionality and doc-vs-code gaps |
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

**[Live: AI Insights Explorer for openai/codex](https://zeljkoobrenovic.github.io/sokrates-skills/examples/codex/ai-insights/)** — nine of the ten scanners, 191 verified findings (source in `examples/codex/ai-insights/`).

## Install

Every skill is a folder with a `SKILL.md` (the open [Agent Skills](https://agentskills.io) format), so the same folders work in any tool that supports skills. `install.sh` symlinks all of them into the right places; `git pull` then updates every tool at once.

```bash
git clone https://github.com/zeljkoobrenovic/sokrates-skills.git
cd sokrates-skills
./install.sh            # → ~/.claude/skills (Claude Code) and ~/.agents/skills (Codex, Gemini CLI, Cursor, Copilot, …)
./install.sh --project  # → ./.claude/skills and ./.agents/skills of the current project instead (shareable via git)
```

| tool | reads skills from | invoke |
|---|---|---|
| **Claude Code** | `~/.claude/skills/` (personal), `.claude/skills/` (project) | automatically when relevant, or `/tech-stack-scan` |
| **OpenAI Codex CLI** | `~/.agents/skills/` (personal), `.agents/skills/` (repository) | automatically, or `$tech-stack-scan` |
| **Gemini CLI** | `~/.gemini/skills/` or `~/.agents/skills/` (user), `.gemini/skills/` or `.agents/skills/` (workspace); also `gemini skills install https://github.com/zeljkoobrenovic/sokrates-skills.git` | the agent activates a matching skill after a confirmation prompt; `gemini skills list --all` |
| **Cursor** | `~/.cursor/skills/` or `~/.agents/skills/` (user), `.cursor/skills/` or `.agents/skills/` (project); `.claude/skills/` is read too | `/` in Agent chat, or automatically |
| **GitHub Copilot** (CLI, VS Code, coding agent) | `~/.copilot/skills/` or `~/.agents/skills/` (personal), `.github/skills/`, `.agents/skills/` or `.claude/skills/` (repository) | automatically; `gh skill` to install from repositories |
| any other Agent-Skills tool | its skills folder — `./install.sh <folder>` | see the tool's docs |

Manual alternative: `ln -s "$(pwd)/skills/scanners/tech-stack-scan" ~/.agents/skills/tech-stack-scan` per skill, or copy the folders.

Typical sequence in a project:

1. `sokrates init`, `sokrates extractGitHistory`, `sokrates generateReports`
2. refine the configuration with the config skills ("check the Sokrates configuration", "define meaningful components", "which features of interest should Sokrates track?", "merge duplicate contributors"), then `sokrates generateReports` again
3. run the scanners ("run a full scan") — results in `_sokrates/findings/ai-insights/index.html`
4. embed the explorer in the main Sokrates report, once, then regenerate to see the new tab:

```bash
java -jar sokrates.jar addCustomTab -label "AI Insights*" -iframeLink "../../findings/ai-insights/index.html"
java -jar sokrates.jar generateReports
```

Requirements: Python 3.9+ (standard library only) for the scripts; a Sokrates analysis (`sokrates init` → `sokrates generateReports`) for the scanners; `git-history.txt` (`sokrates extractGitHistory`) for history-based skills.

## Development

New skills follow the loop that produced the existing ones: write the `SKILL.md` against the family conventions in `skills/scanners/sokrates-scan-core/SKILL.md`, run it live on a real codebase with a fresh agent, ask that agent what was unclear or missing, and fold the answers back into the skill and its scripts. See `skills/scanners/README.md` and `skills/config/README.md` for the per-family details.

## License

[MIT](LICENSE)
