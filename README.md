# sokrates-skills

Skills for AI coding tools (Claude Code and similar) that work with [Sokrates](https://sokrates.dev) source-code analyses — both **before** an analysis (getting the configuration right) and **after** it (adding the semantic layer that only an AI reader can add).

Sokrates measures: size, complexity, duplication, churn, coupling, contributors. These skills add what the numbers cannot say — what the code *is*, what it depends on, where the real risks are, how it got here — and they make Sokrates itself more useful by configuring it well: meaningful components, features of interest, merged contributor identities, sensible landscapes.

## Start here

One skill, `sokrates`, is the entry point. Ask your agent anything Sokrates-related - "analyze this
repository", "what is this codebase", "is it well tested", "set up a landscape of our repos", "improve the
code where it matters" - and it works out where you are and which skill applies:

```bash
python3 skills/sokrates/scripts/situation.py          # where am I, and what is the next step?
```

prints whether the folder is a repository or a landscape, whether an analysis exists and how old it is,
whether the configuration was tuned, which AI findings exist, how Sokrates can be run on this machine, and
a ranked list of next steps that name the skill or command for each. The other skills are what it routes to.
Its sibling `capabilities.py` probes what the installed Sokrates build can do (commands, flags, the exports in
a `data.zip`) so no skill has to guess from version dates, and `skills/scanners/sokrates-scan-core/scripts/summarize_findings.py`
turns findings into the short Markdown you paste into a pull request or a chat.

## What is in here

```
skills/
├── sokrates/    the entry skill: finds out where you are and routes to the skill that applies
├── scanners/    analysis skills — read a finished _sokrates/ analysis, write verifiable findings,
│                render the AI Insights Explorer (one interactive HTML page per project)
├── config/      configuration skills — create and tune _sokrates/config.json and
│                _sokrates_landscape/ files, each with a checker that simulates Sokrates' rules
└── illustrators/ optional scripts that add generated visuals to scanner results
```

### Analysis skills (`skills/scanners/`)

| skill | what it finds |
|---|---|
| `sokrates-scan-core` | the shared contract: findings format, evidence rules, validator, explorer renderer, merge/diff tools |
| `full-scan` | orchestrator — runs a basic scan (six descriptive scanners), a deep dive (all evaluative scanners or one family: quality, runtime, security), or a full scan, in dependency order, and merges the results |
| `functionality-scan` | what the software does: purpose, features, entry points, workflows, data, integrations, hidden functionality and doc-vs-code gaps |
| `domain-language-scan` | the domain language: glossary, bounded contexts, concepts per capability, language drift |
| `architecture-scan` | the implemented architecture: style, components, boundaries, violations, communication, migrations, security boundaries (trust map, sandboxing, escape hatches) |
| `tech-stack-scan` | languages, frameworks, libraries, build tooling, CI/CD, infrastructure, external services |
| `cicd-scan` | the CI/CD process as a narrative: triggers, build, tests, gates, release, deployment, hygiene |
| `iac-scan` | infrastructure as code: inventory and coverage, containers and dev environments as content, declared resources, environment variants, state and apply path, hardening of the declaration |
| `configuration-scan` | configuration: sources and precedence, settings surface and defaults, secrets plumbing, validation and failure behaviour, feature flags and reload |
| `testing-scan` | test layers, coverage map inferred from references, assertion/mocking/determinism quality, flakiness and skips, infrastructure, gaps |
| `observability-scan` | logging, metrics, tracing, error reporting, health surfaces, telemetry pipeline, blind spots |
| `reliability-scan` | error model, failure handling on load-bearing paths, isolation and blast radius, retries/timeouts, degradation, resource cleanup and shutdown |
| `performance-scan` | workload model and scaling factors, hot-path algorithms and data structures, I/O and memory, parallelism, caching, cost limits, ranked bottlenecks |
| `storage-scan` | data classes and locations, access patterns, schema/format versioning and migrations, integrity and corruption recovery, retention and cleanup |
| `network-scan` | endpoint topology, protocols as used, timeouts/TLS/proxies, endpoint configurability, offline behaviour, data in transit |
| `security-scan` | identity and permission design, secrets by design and in the tree, boundary validation, injection, crypto, unsafe code, third-party and model-output trust, coverage statement |
| `maintainability-scan` | maintainability grades: modularity, reusability, analysability, modifiability, testability — per component, rolled up from Sokrates numbers and sibling findings |
| `risk-synthesis-scan` | Sokrates hotspots explained: what each risky file does, knowledge risk, change coupling |
| `evolution-scan` | the history as a story: eras, growth, focus shift, people, module lifecycle, trajectory |
| `landscape-synthesis-scan` | the portfolio story over a whole landscape: where attention concentrates, findings that recur across repositories (one fix resolving many), scanner coverage gaps, priorities across the estate |

Every finding carries file + line + verbatim snippet evidence that a script verifies against the tree — a scan is not finished until validation passes. Results land in `<project>/_sokrates/reports/ai-insights/` as JSON plus `index.html`, the **AI Insights Explorer**: overview, per-scanner pages, cross-scanner attention list, filters, search, evidence citations, deep links.

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

### Improvement skills (`skills/improve/`)

| skill | does |
| --- | --- |
| `sokrates-improve` | acts on what the analysis found and proves it with the same numbers: ranks targets from the Sokrates data (the most complex units, the costliest duplicated blocks, churn x complexity hotspot files, AI findings with a recommendation), makes one behaviour-preserving change per branch, re-runs Sokrates and reports before/after (and whether a finding is resolved); `select_targets.py` + `measure.py snapshot/compare` |

### Illustrations (`skills/illustrators/`)

`generate_summary_visuals.py` turns each scanner's summary into one calm, mostly visual illustration that tells its story with a few key words — a pipeline for CI/CD, a landscape with glowing hotspots for risks, growth rings for evolution. It uses Google's Gemini image model (`GEMINI_API_KEY`), saves the images in `ai-insights/visuals/`, records them in the findings JSON (`summary_visual`) and re-renders the explorer, which shows each image at the end of the foldable summary block. Optional: without it the explorer looks exactly as before.

## Example

**[Live: AI Insights Explorer for openai/codex](https://zeljkoobrenovic.github.io/sokrates-skills/examples/codex/ai-insights/)** — fifteen scanners, 330 verified findings, each summary illustrated (source in `examples/codex/ai-insights/`).

## Install

Every skill is a folder with a `SKILL.md` (the open [Agent Skills](https://agentskills.io) format), so the same folders work in any tool that supports skills. `install.sh` symlinks all of them into the right places; `git pull` then updates every tool at once.

The shortest way is Sokrates itself (builds since 2026-10-02): it clones this repository into `~/.sokrates/skills/` and
links every skill, and re-running updates.

```bash
sokrates installSkills            # → ~/.claude/skills (Claude Code) and ~/.agents/skills (Codex, Gemini CLI, Cursor, Copilot, …)
sokrates installSkills -project   # → ./.claude/skills and ./.agents/skills of the current project instead (shareable via git)
```

Or from a clone of this repository:

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
3. run the scanners ("run a full scan") — results in `_sokrates/reports/ai-insights/index.html`
4. optionally illustrate the summaries: `GEMINI_API_KEY=... python3 skills/illustrators/generate_summary_visuals.py <project>/_sokrates/reports/ai-insights`
5. regenerate the Sokrates report (`sokrates generateReports`, or `sokrates analyze`): it renders the findings itself, as "AI Insights" and "AI Deep Dives" groups in its sidebar (one page per scanner, plus an overview and the attention items), in the report's style and theme. `ai-insights/index.html` stays the standalone alternative. Sokrates builds from before October 2026 do not render the findings; there, embed the standalone explorer as a tab once:

```bash
java -jar sokrates.jar addCustomTab -label "AI Insights*" -iframeLink "../ai-insights/index.html"
java -jar sokrates.jar generateReports
```

(Newer builds leave such a tab out while they render the findings themselves, so it does not show them twice.)

Requirements: Python 3.9+ (standard library only) for the scripts; a Sokrates analysis (`sokrates init` → `sokrates generateReports`) for the scanners; `git-history.txt` (`sokrates extractGitHistory`) for history-based skills.

## In CI

`examples/ci/github-actions-ai-insights.yml` is a complete workflow: Sokrates analysis with `-dataOnly`, a basic scan
by an agent CLI, validation, the Markdown summary into the job summary, a diff against the previous run's findings
(kept as an artifact) and a failing job when a finding of severity medium or above is new. Resolved and persisting
findings never fail the build - the stable-id contract is what makes the diff meaningful.

## Development

The scripts have a test suite, standard library only like the scripts themselves:

```bash
python3 -m unittest discover -s tests -t . -v
```

It runs every script against `tests/fixtures`: two small repositories analyzed by a real Sokrates run (config,
`data.zip`, git exports, hand-written findings with verifiable evidence) and a landscape over both; see
`tests/fixtures/README.md`. GitHub Actions runs it on every push and pull request. When a script changes what it
reads from Sokrates, rebuild the fixtures with `SOKRATES_JAR=<cli jar> tests/fixtures/make_fixtures.sh`.

New skills follow the loop that produced the existing ones: write the `SKILL.md` against the family conventions in `skills/scanners/sokrates-scan-core/SKILL.md`, run it live on a real codebase with a fresh agent, ask that agent what was unclear or missing, and fold the answers back into the skill and its scripts. See `skills/scanners/README.md` and `skills/config/README.md` for the per-family details.

## License

[MIT](LICENSE)
