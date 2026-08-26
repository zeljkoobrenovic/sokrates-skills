# Sokrates AI skills

Skills for AI coding tools (Claude Code and similar) that work with [Sokrates](https://sokrates.dev) code analyses. Two families:

| folder | purpose | when |
|---|---|---|
| [`scanners/`](scanners/README.md) | **Analysis skills** — read a finished Sokrates analysis (`_sokrates/`) and add the semantic layer: tech stack, architecture, risks, CI/CD, observability, security, domain map, evolution. Uniform findings JSON + the AI Insights Explorer. | after `sokrates analyze` |
| [`config/`](config/README.md) | **Configuration skills** — create and tune Sokrates configuration: the per-repository `_sokrates/config.json` (source scope, file classification, components, concerns, history settings) and the `_sokrates_landscape/config.json` that combines many repositories into one landscape. | before / between runs |

Install any skill by linking its folder into a skills location, e.g. `ln -s "$(pwd)/skills/scanners/tech-stack-scan" ~/.claude/skills/tech-stack-scan`.
