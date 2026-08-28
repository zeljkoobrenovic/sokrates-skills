---
name: domain-language-scan
description: Writes down a codebase's domain language - the core concepts (glossary with code-anchored definitions), which components own which concepts (bounded contexts), which concepts each product capability rides on, and where the ubiquitous language drifts (one concept under two names, one name meaning two things, renames caught mid-flight). Use whenever the user asks what the domain concepts/entities of a codebase mean, wants a glossary, domain model, ubiquitous language, concept map, or onboarding vocabulary, or wants naming consistency reviewed. For what the software does (features, entry points, workflows) use functionality-scan instead. Works best with a Sokrates analysis (_sokrates folder).
---

# Domain language scan

Every codebase speaks a language — Thread, Turn, Session, Rollout, whatever its nouns are — and newcomers spend their first weeks reverse-engineering it. This scanner writes that language down from primary sources: for each core concept, what the *code* says it is (the defining type, its doc comment, its relationships), which component owns it, which product capability it serves — and where the language has drifted, because synonyms, homonyms, and half-finished renames are where newcomers and LLMs alike misread a system.

**First read `sokrates-scan-core/SKILL.md`** (sibling skill) — output format, evidence rules, validate/render scripts, `_sokrates` data layout. This file adds only what is specific to the domain language.

## Scope boundaries with sibling scanners

- `architecture-scan` maps components and their *structural* responsibilities; this scanner maps *meaning* — the concepts those components own and the vocabulary they share. Where an architecture finding already names a migration (a rename mid-flight), reference it and add the language consequences rather than re-deriving the migration.
- `functionality-scan` describes what the software *does* (features, entry points, workflows). When its findings exist, take the capability families from its `features` and `purpose` findings and only add the concept layer; do not re-inventory commands or endpoints here.
- `tech-stack-scan` explains technologies; a technology term is domain vocabulary only when the codebase gives it a project-specific meaning (a "Skill" here is not the dictionary word).
- You may reference prior-scan findings in descriptions, but every evidence citation must be minted from files you read in this run.

## Workflow

1. Orient per the core skill. Component names in `config.json`, crate/package names, and prior scans' vocabulary are your candidate-concept list; so are the nouns that dominate protocol/API type names.
2. **Harvest the vocabulary.** From type and module names across the protocol/API layer (the wire types are where the team commits to names publicly), list the recurring nouns. Rank by centrality: how many types/modules embed the noun, whether it appears in persistence and on the wire, whether the docs lead with it. Pick the 8–15 concepts that carry the system.
3. **Define each concept from primary sources.** For each: read the defining type (struct/class/interface) and its doc comment, note its identity (id type), lifecycle (who creates/destroys it), key relationships (owns/belongs-to), and where it lives (component, persistence). The definition you write must be one a maintainer would sign off on — and it must come from the defining code, not from the README's aspiration. Note explicitly when README and code disagree.
4. **Draw the contexts.** Group concepts by the component that owns their definition; note concepts shared across contexts and which side holds the canonical definition (the protocol crate? the storage layer?). A concept with two independent definitions in two contexts is either a deliberate context boundary (fine — say what translates between them) or drift (a `language-drift` finding).
5. **Map capabilities to concepts.** For each major capability family (from `functionality-scan` when present, otherwise from the user-facing surface), name the concepts it rides on and where their definitions live. This is the "to change X, these are the nouns you touch" table — keep it to the concept layer; the feature inventory itself is `functionality-scan`'s.
6. **Hunt language drift.** Synonym pairs (two names, one concept — especially old/new names from renames), homonyms (one name, two meanings in different areas), concepts whose name misleads about their behavior, and terms used in code but never defined anywhere. Each drift finding names the canonical term the codebase itself seems to be converging on, when one is visible.
7. Write findings, validate, render, and report per the core workflow. Fields: `scanner: "domain-language-scan"`, `scanner_version: "1.0"`.

## Group taxonomy

| group | contents |
|---|---|
| `glossary` | The core concepts: one finding per major concept (or per tight concept cluster — e.g. a parent and its line items), each with a code-anchored definition, identity, lifecycle, and owning component |
| `bounded-contexts` | The context map: which components own which vocabulary, where concepts are shared vs. translated, which definition is canonical |
| `capabilities` | Capability family → concepts mapping: which nouns each family of functionality rides on and where their definitions live. Aim for 3–6 family findings — a family is roughly what one team would own (thread lifecycle, extensibility, safety), not one entry per CLI subcommand; cross-reference `functionality-scan` findings with `finding:<id>` where they exist |
| `language-drift` | Synonyms, homonyms, misleading names, undefined jargon, renames mid-flight — each with the visible canonical direction |

Tie-breakers: a concept's definition lives in `glossary` even when its ownership is contested — the contest itself is a `bounded-contexts` or `language-drift` finding referencing the glossary entry. To avoid double-booking content: the glossary entry states the competing meanings *neutrally in one sentence each* and points to the drift finding; the drift finding carries the collision evidence and the judgment. A rename in progress is `language-drift` here even if `architecture-scan` files it under evolution; cross-reference rather than duplicate the story.

Layered type families — the same concept re-declared per layer (wire type, API type, runtime type, persistence type), the dominant pattern in wire-heavy codebases — get *one* clustered glossary entry that names each layer's declaration and what changes between layers; count each layer-spanning concept once in `concepts_defined`.

## What a good finding looks like

A glossary finding's evidence is the defining line (the struct declaration, the doc comment above it) — one or two citations, not every usage. The description carries the definition, relationships, and lifecycle in three or four sentences a newcomer can absorb. A drift finding cites both sides (the two names' defining or typical-use lines) with the evidence `note` saying which is which. Absences (a central term never defined, a capability with no owning component) are evidenced by the nearest delimiting positive fact.

Almost everything here is `info` — this scanner's product is a map, not an alarm. Expect roughly 12–20 findings, dominated by `glossary` and `capabilities`; merge over split, and cluster satellite concepts under the concept they orbit.

## Severity calibration

- `medium` — drift that actively causes defects or misintegration: one name bound to two incompatible meanings on a public API surface; documentation defining a concept contrary to the code. Escape clause: drift the team visibly *manages* (an acknowledged rename with compat shims and a stated direction) rates `low` — keep `medium` only when the confusion is live on user-facing surfaces beyond the acknowledged migration.
- `low` — friction drift: synonym pairs still both live in code, misleading names on load-bearing types, central jargon defined nowhere. Vocabulary documented only *outside* the repo (docs that are stubs pointing to an external site) is a `low` drift finding — the in-repo language has no in-repo definition, which is the newcomer's actual problem.
- `info` — the map itself: glossary entries, context boundaries, capability mappings, and completed renames worth recording.

When unsure whether two names are drift or a deliberate context translation, present both readings and mark confidence `possible` — misdiagnosed intent is this scanner's main failure mode too.

## Output

Follow the core workflow: write `_sokrates/reports/ai-insights/domain-language-scan.json`, validate until OK, render the explorer, report leading with the vocabulary in one paragraph (the system's ten nouns and how they relate) and any drift findings.

Use these `stats` keys where they apply (canonical, counting things in the domain, never findings — example numbers fictional): `concepts_defined` (distinct concepts, counted inside clustered entries too), `contexts_mapped`, `capability_families_mapped` (families, i.e. `capabilities` findings' subjects — not CLI subcommands), `drift_pairs_found`, e.g. `{"concepts_defined": 99, "contexts_mapped": 9, "capability_families_mapped": 9, "drift_pairs_found": 9}`. Add extras freely alongside.
