---
name: functionality-scan
description: Defines and describes what the analyzed software actually does, reverse-engineered from the code rather than the README - its purpose and audience, the inventory of user-facing features, the entry points through which functionality is reached (commands, endpoints, UI screens, hooks, config), the end-to-end workflows that connect them, the data the system manages, its integrations, the behaviour that is hidden, dormant or gated, and where the documentation and the code disagree. Use whenever the user asks what a codebase does, what its features are, wants a functional description, feature list, product manual, "what can this software do", a capability inventory for a handover or due diligence, or asks whether the README matches the code. Works best with a Sokrates analysis (_sokrates folder).
---

# Functionality scan

Ask three people what a system does and you get the README's aspiration, the last release's changelog, and one engineer's mental model — none of them the code. This scanner writes the functional description from primary sources: for each thing the software can do, where a user reaches it, what it does, what data it touches, and how it is switched on. The product is the manual a maintainer would sign off on: complete enough for a handover, honest about what is half-built, and explicit where the documentation and the code disagree.

**First read `sokrates-scan-core/SKILL.md`** (sibling skill) — output format, evidence rules, validate/render scripts, `_sokrates` data layout. This file adds only what is specific to describing functionality.

## Scope boundaries with sibling scanners

- `domain-language-scan` names the *concepts* (the nouns) and maps capability families onto components; this scanner describes the *behaviour* (the verbs) — what a user can do, through which surface, with what outcome. In `full-scan` this scanner runs first, so the domain map reuses the feature inventory as its capability list; do not re-derive the glossary here.
- `architecture-scan` explains how the parts are structured. Split on a shared surface such as an RPC protocol: this scanner owns *which methods exist and what they do*; the architecture scan owns how the protocol is versioned, layered and transported. Name the component a feature lives in (`sokrates_refs`), but leave component responsibilities and boundaries to the architecture scan.
- `tech-stack-scan` inventories technologies; an integration is a *feature* here only when it does something for the user (sync to a calendar, deploy to a cloud), not merely when a library is linked.
- `security-scan` (with `architecture-scan`'s security boundaries) and `observability-scan` own security and telemetry behaviour. Mention them inside a feature only where they are user-facing (an approval prompt, an opt-out flag) — citing the approval enum to make a feature description honest is fine; describing the policy model is not.
- `cicd-scan` owns packaging, install channels and containers; here they appear only in `purpose` (how the software is obtained) unless the packaging changes what a user can do.
- `evolution-scan` records deprecations and retired experiments as history; this scanner records their *present* user-facing consequence (still reachable, still documented). Cross-reference rather than duplicate: put the sibling finding's id in `sokrates_refs` as `finding:<id>` — only ids you have actually seen in the sibling file (list them first); never guess an id.
- If sibling findings already exist in `_sokrates/reports/ai-insights/`, read their `summary` and `stats` first and reuse their component names. When a domain map with `capabilities/*` findings already exists, align your feature clusters to its family names and cross-reference them (`finding:<id>`) rather than inventing a competing grouping. For shared data stores, this scanner owns *what is in the store and its lifecycle*; the architecture scan owns the contract and its versioning. Every evidence citation must still be minted from files you read in this run.

## Workflow

The realistic reading strategy for anything beyond a small project is **registration tables, not handlers**: the subcommand enum, the slash-command table, the route or RPC-method macro, the menu definition, the feature-flag registry, the config schema. These few files enumerate the entire functional surface; one load-bearing line from a handler per feature then anchors the behaviour. Do not try to trace every handler end to end — spend that depth on the handful of features every workflow passes through. Sokrates hotspots and churn are weak guides for this scanner (they point at engines, not surfaces); the component list and file inventory are what you need, and `data.zip` can be skipped.

1. Orient per the core skill: `config.json` for components and ignores; sibling scanners' summaries if present. Read the README and user docs *last*, not first — form the picture from code, then compare. Documentation the harness injects before you start (a `CLAUDE.md`, `AGENTS.md`) is documentation too: treat it as claims to be checked, never as ground truth — it is a rich source of gaps.
2. **Find the entry points.** Enumerate every surface from the code that registers it: CLI commands and argument parsers, HTTP/RPC route tables and API schemas, UI screens and menus, message or event handlers, scheduled jobs, plugin or hook registration, configuration keys. Every feature below must hang off at least one entry point, and every *command, route, screen or hook* must be accounted for by some feature or filed as hidden/dormant. Configuration keys are covered by naming them in the surface finding and in the features that consume them — not by one line each. Counting convention, so runs agree: count *registered variants* in the dispatch table (enum variants, route entries); report aliases, platform-gated entries, hidden entries, and legacy/compat duplicates as separate keys rather than folding them in; report the documented count separately when it differs.
3. **Describe each feature.** Pick the 10–20 features that carry the product. For each: entry point, inputs, what it computes or changes, what it persists or sends, what the user gets back, what fails it. Depth is proportional to weight — a feature every workflow passes through gets a read of its handler; a peripheral command gets its doc comment and one decisive line.
4. **Reconstruct the workflows.** Features combine into the sequences users actually perform: setup, the core loop, the exceptional paths (recovery, undo, migration). Describe 3–6 workflows as ordered steps, each step naming the feature it uses and the state it leaves behind. Workflows are where hidden prerequisites surface ("nothing works until X is configured").
5. **Inventory the data.** What the system stores (files, databases, caches, remote state), in what shape, where, with what lifecycle, and which features own it — and what leaves the machine (telemetry, uploads, sync targets; this belongs to `data`, not `integrations`).
6. **Map integrations.** External systems the software talks to *as functionality*: services called, protocols spoken, formats imported and exported, tools driven or driving it. State what each enables and what happens when it is unavailable.
7. **Hunt the hidden and the gaps.** Feature flags and experiments (defaults, who can flip them), undocumented commands and flags, dead or dormant features still wired in, stubs on user-visible paths, and every place the README, help text or docs promise something the code does not do — or the code does something the docs never mention. Each gap cites both sides.
8. Write findings, validate, render, and report per the core workflow. Fields: `scanner: "functionality-scan"`, `scanner_version: "1.0"`.

## Group taxonomy

| group | contents |
|---|---|
| `purpose` | The one-page answer: what the software is, for whom, what problem it solves, what it deliberately is not, and the feature families at a glance. It *names* the product surfaces and how they relate; it does not describe them (that is `entry-points`). One or two findings, the first thing a newcomer reads |
| `features` | The feature inventory: one finding per feature (or tight feature cluster), each with entry point(s), inputs, behaviour, outputs, failure modes, and the component that implements it |
| `entry-points` | The surfaces through which functionality is reached, one finding per surface family (the CLI command set, the HTTP/RPC API, the UI navigation, the hook/plugin protocol, the configuration file): what is exposed, how it is versioned, which entries are undocumented, and — for entries not described as features — a one-line behaviour each |
| `workflows` | End-to-end user journeys as ordered steps, each step tied to a feature, with prerequisites, state left behind and exceptional paths |
| `data` | What the system manages: stores shared across features or with their own lifecycle, and what leaves the system |
| `integrations` | External systems as functionality: what each enables, how it is configured, and the behaviour when it is absent |
| `hidden-and-gaps` | Flags and experiments, undocumented or dormant functionality, stubs on user-visible paths, and documentation-versus-code disagreements in both directions |

Tie-breakers, settled once so runs agree:

- A feature reachable from several surfaces is described once in `features` with all its entry points listed (`attributes.entry_points`, `attributes.surfaces` as lists); each `entry-points` finding just points to it.
- **Flags** mean anything that switches user-visible behaviour: feature-flag registries, experiments, and plain configuration booleans alike (a CLI's `skipX` switches count). When the project has a central feature-flag table, write *one* `hidden-and-gaps` finding for the registry (counts by stage, defaults, how users flip them, stale keys still parsed) and add a `flags` attribute only to the features whose behaviour a flag materially changes. Without a registry: a flag gating a shipped feature is an attribute of that feature; a flag gating unshipped behaviour is its own `hidden-and-gaps` finding.
- **Shipped but off by default** is a `features` finding with `status: shipped-off-by-default`; it becomes `hidden-and-gaps` only when nothing documents how to turn it on.
- **Documented but unimplemented** (a config section nothing reads, a report page nothing fills, a documented option the parser rejects) is one `hidden-and-gaps` finding, not a `features` finding with `status: stub` — `stub` is for functionality that is *registered* on a surface but does nothing.
- **Runtime dependencies of the software's output** (generated reports that load scripts from a CDN, exported files that need an external viewer) are `integrations`: the decisive attribute is what happens when they are unavailable.
- **Deprecated surfaces** are described in `entry-points` (with `status: deprecated`); a separate `hidden-and-gaps` finding exists only if the docs or help text still present the surface as current, or no replacement is named.
- The data a single feature owns lives inside that feature's finding; `data` findings cover shared stores and what leaves the machine.

## What a good finding looks like

A feature finding's evidence is the registration line (the subcommand variant, the route, the menu entry) plus one line from the handler that shows the load-bearing behaviour — two or three citations, not a tour. The description reads like a manual page written by someone who read the implementation: "`codex resume` lists sessions from `~/.codex/sessions`, picks the selected rollout and replays it into a new turn; it fails with `no sessions found` when the directory is empty" — behaviour, location, failure, in that order.

Structured facts go in `attributes`: `entry_points` (list), `surfaces` (list drawn from `cli`, `api`, `ui`, `config`, `env`, `hook`, `job`, `library`, `mcp`), `status` (`shipped`, `shipped-off-by-default`, `experimental`, `deprecated`, `stub`), `flags` (list; keep the project's own flag names, and its own stage vocabulary in `flag_stage` if it has one), `component`.

A workflow finding's description is the numbered sequence; its evidence is the two or three steps where the sequence is actually *decided* in code (the dispatch, the precondition check), not one citation per step — the core evidence cap applies. Inferred ordering is `likely`, not `certain`.

A gap finding cites both sides with the evidence `note` saying which is which: the promise (README line, help text, doc comment) and the code that breaks it — or, for undocumented behaviour, the code and the nearest documentation that should have mentioned it.

Almost everything here is `info` — this scanner's product is a description, not an alarm. Expected shape: 10–20 `features`, and 2–5 each of the other groups; total around 25–40 on a large project. Merge over split, and cluster minor variants (the `--json` output flag of every command) into the feature or surface they belong to.

## Severity calibration

- `medium` — documentation or help text that promises behaviour the code does not implement on a main path (a documented command that is a stub, a described safeguard that is not wired), or a user-visible path that silently does nothing.
- `low` — undocumented user-facing functionality that matters (commands, flags, environment variables users would want to know), dormant features still reachable, experiments on by default without documentation, deprecated surfaces still documented as current.
- `info` — the description itself: purpose, features, entry points, workflows, data, integrations, and documented flags.

When the intent behind a gap is unclear (deliberately unlisted power-user flag vs. forgotten documentation), say so and mark confidence `possible` — reading a design decision as an omission is this scanner's main failure mode.

## Practical notes

- **Before** choosing line numbers, run a small Python script that prints `path:line: text` for the candidate lines and paste from its output into `snippet` — every off-by-one in testing came from counting inside `sed` windows. Prefer lines without escaped quotes (JSON-in-JSON escaping is where citations break). If a cited line is slightly off, the validator reports where the snippet actually is; multi-line snippets tolerate leading-whitespace differences.
- On a re-run, keep the previous `functionality-scan.json` as a diff baseline *outside* the findings folder (a scratch directory) — anything left inside it is picked up by `render`/`merge` as another scanner file. Keep `scanner_version` at `1.0` unless the skill's taxonomy changes; new or changed findings do not bump it.
- After a first successful run on a project that already has a `combined-report.json`, re-run `merge_findings.py` (see the core skill) so the combined report includes this scanner.

## Output

Follow the core workflow: write `_sokrates/reports/ai-insights/functionality-scan.json`, validate until OK, render the explorer, report leading with the purpose statement in one paragraph (what it is, for whom, the five or so feature families) followed by the hidden-and-gaps findings.

Use these `stats` keys where they apply (canonical, counting things in the software, never findings — example numbers fictional): `features_described`, `entry_points_by_surface` (an object, e.g. `{"cli_subcommands": 9, "rpc_methods": 99}` — a single total across surfaces is not meaningful), `surfaces` (the number of distinct values used in `attributes.surfaces` across findings, from the fixed list `cli`, `api`, `ui`, `config`, `env`, `hook`, `job`, `library`, `mcp`; a GUI is its own surface even when it calls the CLI underneath, while an SDK that merely wraps a CLI counts under that CLI), `workflows_described`, `data_stores_found`, `integrations_found`, `flags_found` (config switches included; `flags_by_stage` when the project has stages), `model_tools_found` (agent products only: first-party tool names in the handler specs, excluding tools discovered at runtime from MCP servers), `doc_code_gaps_found` (distinct documentation-versus-code disagreements — the one stat that is allowed to count what the gap findings describe; it may differ from the number of `hidden-and-gaps` findings), e.g. `{"features_described": 9, "entry_points_by_surface": {"cli_subcommands": 9, "rpc_methods": 99}, "surfaces": 9, "workflows_described": 9, "data_stores_found": 9, "integrations_found": 9, "flags_found": 99, "doc_code_gaps_found": 9}`. Omit keys that do not apply (a CLI without flags reports no `flags_found` rather than 0). Add extras freely alongside.
