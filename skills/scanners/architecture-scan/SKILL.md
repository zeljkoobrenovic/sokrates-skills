---
name: architecture-scan
description: Infers a codebase's actual architecture from its code - the overall style and shape, what each major component is responsible for, the load-bearing boundaries and contracts between them, dependency direction and where it is violated, how parts communicate at runtime, and which architectural migrations are visibly in progress. Use whenever the user asks how a codebase is structured or organized, wants an architecture overview/diagram input/onboarding map, asks what depends on what, whether the architecture is clean or eroding, where a new feature should live, or wants Sokrates' component decomposition explained and judged. Works best with a Sokrates analysis (_sokrates folder).
---

# Architecture scan

Every codebase has two architectures: the one in people's heads (READMEs, directory names, crate boundaries) and the one the imports actually implement. This scanner reads both and reports the real one — each component's actual responsibility, the contracts between them, the direction dependencies flow, and the places where the implemented structure deviates from the evident intent. The output is the onboarding document and review baseline the repo doesn't have: not a box diagram, but the reasons the boxes are shaped the way they are.

**First read `sokrates-scan-core/SKILL.md`** (sibling skill) — it defines the output format, evidence rules, validate/render scripts, and the `_sokrates` data layout. This file adds only what is specific to architecture scanning.

## Scope boundaries with sibling scanners

- `risk-synthesis-scan` explains *churn-weighted* coupling and hotspot risk; this scanner judges structure regardless of churn — a clean-but-never-touched layering violation belongs here, a hot file's refactor priority belongs there. Reference its coupling findings rather than re-deriving them.
- `tech-stack-scan` names the technologies; this scanner explains the *roles* they play in the structure (that Tokio exists is stack; that the system is organized as async actors over channels is architecture).
- Security boundaries are **this scanner's** `security-boundaries` group: where untrusted data enters, the process/sandbox/privilege structure and network confinement of executed code, and their escape hatches — as *structure*. What crosses them and whether the crossings are checked (auth, validation, injection, secrets) is `security-scan`'s; it reads this group first. `reliability-scan` reads the same boundaries as failure boundaries and references them.
- You may reference prior-scan findings in descriptions, but never copy their evidence blocks — every citation must be minted from files you read in this run.

## Workflow

1. Orient per the core skill. Read `config.json`'s `logicalDecompositions` — Sokrates' component split is your starting hypothesis, not your conclusion; part of this scan's value is saying where that split matches reality and where it doesn't. Prior findings (`_sokrates/findings/ai-insights/*.json`) supply the tech skeleton.
2. **Extract the cheap structure first.** Workspace manifests are a free dependency graph: Cargo workspace members and their inter-crate `dependencies`, package.json workspaces, Bazel deps — and the parent/root manifest's *own* dependency block (inherited dependencies every module gets are a hub). Build the component-level directed graph from manifests before reading any code, and compute its shape (layers? hub-and-spoke? cycles?). Directory naming and README/docs architecture statements give you the *stated* design to compare against.
3. **Assign responsibilities by reading entry points.** For each major component, read its `lib.rs`/`index`/`__init__` exports and one or two central types — enough to state its responsibility in one sentence that its author would accept. Components too small or auxiliary to matter get clustered, not skipped silently.
4. **Read the boundary artifacts.** The contracts between components are where architecture lives: protocol/API crates, trait/interface definitions at seams, event/message type definitions, generated bindings. For each load-bearing boundary, note what crosses it, in which direction, and what guarantees the contract encodes (versioning, compatibility, who may break whom).
5. **Hunt deviations.** With the graph and the stated design in hand, look for: dependency cycles (manifest-level and, where suspicious, import-level), skip-layer imports (UI reaching into storage), grab-bag modules that belong to no layer, duplicated concepts on both sides of a boundary, and "everyone depends on it" hubs whose surface doesn't justify it. Each deviation finding states the evident *intent* it violates — a violation is only a violation relative to a rule the codebase itself implies.
6. **Map the security boundaries.** Using the component graph and the entry points: where does untrusted data enter (network, model output, user files, plugins/extensions, IPC, CLI), what sits on each side, which boundaries are enforced by *structure* — separate processes, OS sandboxes (seccomp/Landlock/bubblewrap/App Sandbox), workers, privilege separation, network confinement (egress proxies, allowlists) — and what escape hatches (flags, env vars, config) relax them. Read the sandbox/policy setup code and the process-spawn sites; record each boundary's default (confined or open when unconfigured) and its bypass surface. One overview finding plus separate findings only for the two or three boundaries with their own story. On a plain codebase (one process, one OS user, nothing executed) the group is `trust-map` plus one finding per boundary whose default is *open* (a report that loads code from a CDN, a plugin dir loaded without checks); "no sandbox" is not a finding. `open-defaults` is for open defaults of boundaries that have their own mechanism finding; when the only open default *is* the network boundary, `network-confinement` carries it and `open-defaults` is not written. The `sokrates_refs` link to `security-scan` is the whole hand-off — no "whether X is checked is security-scan's" sentence per finding. Escape hatches are design facts; a boundary whose default silently disables it is a finding here (`medium`–`high` per calibration), whereas a crossing that is unchecked is `security-scan`'s. Cite the type-selection function, the default value of the level/mode enum, and the spawn-time injection (env, args) — those three lines are usually the whole boundary. Compensating checks in callers (an approval prompt, a patch-safety assessment) are crossings: mention them and reference `security-scan`, but they lower the *confidence* of the open-default finding, not its severity. Third-party code launched *outside* the sandbox by default (an MCP server with `sandbox: None`) is an open default here; what it is allowed to do is `security-scan/third-party-trust`.
7. **Synthesize style and evolution.** One finding names the overall style(s) and how the layers compose; evolution findings capture visible migrations (parallel v1/v2 structures, deprecated paths still wired in, extension points prepared but unused). Inferences about direction are `likely`/`possible` — confidence rates the claim, not the citations.
8. Write findings, validate, render; re-run the merge script if a `combined-report.json` exists. Report per the core workflow. Fields: `scanner: "architecture-scan"`, `scanner_version: "1.1"`.

## Group taxonomy

| group | contents |
|---|---|
| `style` | The shape narrative: overall style(s), layer composition, what the structure optimizes for — one synthesis finding, plus separate findings only for style aspects with their own story |
| `components` | The real component map: responsibility statements for major components/clusters, and the verdict on Sokrates' decomposition (where it matches, where it misleads) |
| `boundaries` | Load-bearing contracts between components: protocol layers, seam traits/interfaces, dependency-direction rules the code implies, versioning/compatibility guarantees |
| `violations` | Deviations from the evident intent: cycles, skip-layer imports, grab-bag modules, duplicated concepts across a boundary, unjustified hubs — each stated relative to the rule it breaks |
| `communication` | How parts talk at runtime: channels/events/actors, IPC and RPC between processes, sync vs. async seams, backpressure and ordering assumptions |
| `evolution` | Architecture in motion: migrations in progress, deprecated-but-wired paths, parallel old/new structures, extension points and plugin surfaces |
| `security-boundaries` | The trust structure: where untrusted data enters and what sits on each side (`trust-map`, one overview), process/sandbox/privilege boundaries and their mechanisms (`sandbox-<mechanism>` or `process-isolation`), network confinement of executed code (`network-confinement`), escape hatches and their gating (`escape-hatches`), and boundaries whose default is open (`open-defaults`) — as structure; crossings are judged by `security-scan` |

Tie-breakers (they keep ids stable across independent runs):

- A violating dependency goes to `violations` even when discovered while mapping a boundary; the boundary's own finding stays clean. `style` holds only synthesis.
- A component whose *shape* breaks an evident rule (a god-crate the repo's own docs warn against) goes to `violations`; its responsibility statement stays in the `components` map.
- A contract that is *intended but weak* (a hand-mirrored schema, an unversioned seam) stays in `boundaries` — `violations` is for crossings and shapes that break a rule, not for contracts whose mechanism is merely fragile.
- When a deviation is also a migration frontier (a skip-layer import that exists because the migration isn't finished), the dependency files under `violations`; the `evolution` finding tells the migration story and cross-references it rather than re-describing the edge.
- A trust boundary that coincides with an architectural boundary: the *contract* stays in `boundaries`, the *channel* stays in `communication`, and the trust structure (what is confined, what is open) is written once in `security-boundaries` — three findings that reference each other, none restating the others.
- Cycles: count production-graph and test-only (dev-dependency) cycles separately — Cargo dev-dependencies legally create cycles, so a manifest pass must split them. Test-only cycles are normally `info`; the `cycles_found` stat counts *production* cycles, with test-only ones noted in an extra key.

## Stable ids

Slugs are **component, contract, mechanism or edge names, never consequences or adjectives**. Fixed slugs (use only when the subject exists; `<component>` is the Sokrates component or the crate/package name in kebab-case, whichever the description uses):

| group | fixed slugs |
|---|---|
| `style` | `overview` (the one synthesis), `layering` (only when the layer composition needs its own finding) |
| `components` | `<component>` (one per major component or cluster, e.g. `core`, `protocol`, `frontends`), `sokrates-decomposition` (the verdict on the configured components) |
| `boundaries` | `<contract-crate-or-seam>` (e.g. `app-server-protocol`, `exec-server-protocol`, `extension-api`), `dependency-direction` (the implied rule set, one finding) |
| `violations` | `cycles` (production; test-only cycles inside `attributes`), `<from>-to-<to>` for a skip-layer or inverted edge (e.g. `protocol-to-services`, `tui-to-executor`), `<component>-hub` for an unjustified hub, `<component>-grab-bag` |
| `communication` | `<mechanism>` (e.g. `session-actor-channels`, `process-rpc`, `events`) |
| `evolution` | `<migration>` named by its target (e.g. `api-v2`, `sqlite-state`, `thread-rename`), `deprecated-paths`, `extension-points` |
| `security-boundaries` | `trust-map`, `sandbox-<mechanism>` (one per mechanism when each has its own story) or `sandbox-layers` (one finding when the OS-specific mechanisms are described together), `process-isolation` (worker/child processes that are not a sandbox), `network-confinement`, `escape-hatches`, `open-defaults` |

Project-specific findings get a free slug naming the crate, seam or edge, never the consequence (`core-god-crate` → `core-hub`). A contract finding stays in `boundaries` even when the seam is also a trust boundary — the `security-boundaries` finding references it. Several mechanisms sharing a slug are listed in `attributes`.

## What a good finding looks like

A component finding answers: what it is responsible for (one sentence from reading, not from its name), what it depends on and what depends on it (the graph position), and what would break if it were replaced. A boundary finding cites the contract artifact itself (the trait, the protocol type, the manifest dependency line) — one line of the seam usually beats three lines of a consumer. A violation finding cites both ends: the rule's evidence (the layering the manifests imply, the doc that states it) and the breach (the import that crosses it), with the evidence `note` saying which is which.

Absences are evidenced by the nearest delimiting positive fact. Strengths are findings — a boundary that has held cleanly under churn deserves an `info` entry; it is the baseline that makes the violations meaningful. Expect roughly 14–24 findings (this scanner's taxonomy is broad, so it sits at the high end of the family's usual band; `security-boundaries` adds 2–5 on a security-conscious codebase and one `trust-map` finding on a plain one); merge over split, cluster minor components rather than enumerating them, and cluster minor boundary crates into one finding.

## Severity calibration

Descriptive structure findings are `info`. Raise severity only for structural defects, driven by the cost of building on top of them:

- `high` — a security boundary whose default *silently* disables it in real deployments (escape hatch on by default, sandbox that no-ops when a dependency is missing); erosion that actively misleads or blocks: a dependency cycle among core components, a boundary so leaky that its contract no longer constrains anything, two sources of truth for a central concept.
- `medium` — a single-wall trust boundary where depth is warranted; a *deliberate, documented* open default with the confined mode available (present the trade-off); a documented open default with *no* confined mode is `medium` when user content or secrets cross it, `low` otherwise; deviations that tax every change in an area: systematic skip-layer access, a hub module everything imports for unrelated reasons, duplicated domain concepts drifting apart across a boundary.
- `low` — contained drift: a single skip-layer import, a deprecated path still wired but isolated, naming that misstates a component's real role. Meta-findings about the *analysis setup* rather than the code (a Sokrates decomposition that misleads, missing components in config.json) are also `low` with a recommendation — they are defects in the lens, not the building.
- `info` — the map itself: style, responsibilities, healthy boundaries, evolution observations.

When unsure whether a structure is intent or accident, say so in the description and keep severity low — misdiagnosed intent is this scanner's main failure mode.

## Output

Follow the core workflow: write `_sokrates/findings/ai-insights/architecture-scan.json`, validate until OK, render the explorer, report leading with the style narrative (the architecture in three sentences) and any above-info findings.

Use these `stats` keys where they apply (canonical, counting things in the structure, never findings — the example numbers are fictional): `components_mapped` (major components/clusters given responsibility statements), `boundaries_traced` (contracts read at the artifact level), `violations_found` (distinct deviations, not findings about them), `cycles_found` (*production* dependency cycles; report test-only cycles under an extra key like `test_only_cycles`), `trust_boundaries_mapped` (entry points where untrusted data enters, as listed in `trust-map`), `escape_hatches` (distinct *user-reachable* switches — CLI flags, config keys, env vars — that *relax a boundary*; behaviour-steering switches that relax nothing are not counted), e.g. `{"components_mapped": 99, "boundaries_traced": 99, "violations_found": 99, "cycles_found": 99}`. Add extras freely alongside.
