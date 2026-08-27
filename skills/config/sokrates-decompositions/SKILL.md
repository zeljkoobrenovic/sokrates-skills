---
name: sokrates-decompositions
description: Designs meaningful logical decompositions (component structures) for a Sokrates repository analysis - decides what the components of a codebase should be and writes them as logicalDecompositions in _sokrates/config.json - folder-depth, mixed-depth for monorepos with one dominant folder, build-system modules (Cargo, Maven, Gradle, npm workspaces, Bazel, Go, Python, .NET), CODEOWNERS ownership, architectural layers, technology, and several decompositions side by side. Includes a proposal script that measures each candidate on the real tree and emits ready-to-paste config. Use when the user asks for better components, says the Sokrates component view is one big blob or hundreds of fragments, wants components that match teams or modules or layers, or wants dependency/duplication views that mean something.
---

# Sokrates logical decompositions

Every Sokrates view that says something about *structure* — component sizes, dependencies between components, duplication across components, ownership and churn per component, and the `component:<name>` references in every AI scanner finding — depends on the `logicalDecompositions` in `_sokrates/config.json`. The default (folder depth 1) is right for a clean multi-module repository and wrong for almost everything else: one folder holding 95% of the code, or hundreds of fragments, or a `src/` split that mirrors nothing anyone thinks in. This skill produces decompositions that match how the people who work on the code actually divide it.

Field semantics for `logicalDecompositions` (folder depth and prefix stripping, explicit components, `exception` filters, meta rules, `filters` + `includeRemainingFiles`, thresholds) are in `../sokrates-repo-config/references/config-reference.md` — read that section before writing config by hand.

## Workflow

1. **Measure the candidates** — always start here, never guess a depth:
   ```bash
   python3 <this-skill-path>/scripts/propose_decompositions.py <repo>/_sokrates/config.json -o <scratch>/decompositions.json
   ```
   It applies the config's extensions, ignore and scope rules (path rules; content rules are skipped) and size limits to the real tree, then reports for each candidate its components with files, LOC and share, a balance **score** (penalises one dominant component, more than ~25 components, dust below 0.5% LOC, fewer than 4 components), and a ready `config` object:
   - `folder-depth` — depths 1–4 with the recommended one;
   - `mixed-depth` — for monorepos: every top folder holding ≥40% of LOC is opened one level deeper, its tiny children folded into `<folder> (other)` via exception filters, all other top folders kept whole (explicit components, depth 0);
   - `build-modules` — one component per build-system module (Cargo packages, Maven/Gradle modules, npm workspaces, Bazel packages, Go modules, Python packages, .NET projects; test-support crates fold into their parent), nested modules made disjoint with exception filters;
   - `grouped-modules` — when there are more than 25 modules: the same modules grouped mechanically by parent folder (`ext/*`) or shared name prefix (`app-server-*`), with disjoint filters — the starting point you rename and merge with the repository's vocabulary;
   - `ownership` — one component per CODEOWNERS owner;
   - `layers` — recurring architectural folder names (api, domain, service, ui, db, …) across the tree;
   - `technology` — one component per language family.
   The console shows the top rows; the JSON (`-o`) holds every row of every proposal — use it for the grouping work. Scores measure *balance* only (dominant component, dust, count, unassigned share) and are comparable across kinds only in that sense; a high-scoring `layers` proposal made of crate names is still meaningless. If the `.*/_sokrates/.*` ignore rule is missing, add it yourself now — it is one line in `ignore` and every later number depends on it.
2. **Understand what the divisions mean.** Numbers pick the *shape*; you pick the *meaning*. Read the repository's own description of its structure — README, architecture docs, workspace manifests, `CODEOWNERS`, top-level folder names — and, if present, prior scanner findings (`architecture-scan` components and boundaries, `domain-language-scan` bounded contexts) in `_sokrates/findings/ai-insights/`. Decide which vocabulary the components should use: the crates/modules developers name, the products or bounded contexts the business names, the teams that own them, or the layers of the architecture. A decomposition whose names appear nowhere else in the repository is a bad one.
3. **Compose the primary decomposition.** Rules of thumb:
   - Prefer **build modules** when they exist and are not too many (≤ ~40): they are the divisions the compiler already enforces, and dependency analysis between them is meaningful. With more modules, start from `grouped-modules` and **re-group with a real key**: an existing `architecture-scan` component map (its `components` findings usually name 8–15 clusters of modules — the best key when present), the README's architecture section, or the workspace's own folder/prefix conventions. Target 8–20 groups; one component may list many module-dir filters (`.*/codex-rs/core/.*`, `.*/codex-rs/core-plugins/.*`, …).
   - Prefer **mixed-depth** when one folder dominates and its children are the real modules; give the `(other)` component a meaningful name if it has one (e.g. `codex-rs support crates`).
   - Use plain **folder depth** when the score is high (balanced, 5–25 components) and the folder names are the vocabulary people use.
   - Aim for 5–25 components, none above ~40% of LOC, none below ~1% unless it is a genuinely separate thing (a CLI, an SDK). Merge dust into a named group rather than leaving `Unclassified`.
   - Name the decomposition `primary` (Sokrates' default and what other tooling expects), scope `main`.
4. **Add secondary decompositions when they answer a different question** — several may coexist and each gets its own component views: `by-layer` (from the `layers` proposal, with overlap resolved: decide precedence and add `exception` filters, or express it with `metaComponents` `{ "pathPattern": ".*/(api|domain|infra)/.*", "use": "path", "nameOperations": [{"op": "extract", "params": [".*/(api|domain|infra)/.*"]}] }` for name derivation), `by-team` (from `ownership`; later CODEOWNERS rules override earlier ones but Sokrates filters are unordered — keep the specific rules and drop the catch-all, or add exceptions), `by-technology` for polyglot repositories, `by-product` for monorepos that ship several products. Two or three decompositions are plenty; each one costs report size and reader attention.
5. **Verify with the repo-config preview** — mandatory:
   ```bash
   python3 <config-skills-path>/sokrates-repo-config/scripts/preview_config.py <repo>/_sokrates/config.json
   ```
   Check per decomposition: no `Multiple Classifications` (add exception filters), acceptable `Unclassified` (name it or filter it), no dominant component, no regex errors. Iterate until clean.
6. **Write and report.** Edit `logicalDecompositions` in place (replace the default `primary`, append secondaries; never leave the list empty — Sokrates would re-insert the default). Report the component table of each decomposition with LOC shares, the vocabulary source you chose (modules / domains / teams / layers) and why, and the next command (`sokrates generateReports`). If component names changed, note that existing AI scanner findings referencing `component:<old>` need a re-run.

## Patterns worth knowing

- **Disjointness by exception**: a parent-folder component plus child components needs `exception: true` filters for each child on the parent — the script emits these; when hand-writing, copy the pattern. Two recurring shapes:
  - *catch-all inside a folder*: `{"name": "codex-rs support crates", "sourceFileFilters": [{"pathPattern": ".*/codex-rs/.*"}, {"pathPattern": ".*/codex-rs/core/.*", "exception": true}, {"pathPattern": ".*/codex-rs/tui/.*", "exception": true}, …one exception per sibling component…]}`;
  - *everything else*: `{"name": "repo tooling", "sourceFileFilters": [{"pathPattern": ".*"}, {"pathPattern": ".*/codex-rs/.*", "exception": true}, {"pathPattern": ".*/sdk/.*", "exception": true}]}`.
  Inside a decomposition Sokrates applies a component's filters *in order* — put the inclusive filter first and the exceptions after it. Only `name` and `sourceFileFilters` are needed per component; the decomposition-level `dependenciesFinder`/`renderingOptions` boilerplate is optional (defaults apply).
- **A layer view for module repositories**: when the `layers` proposal is folder-name noise, build the layer decomposition from the *dependency direction* instead — group modules into the layers the architecture implies (frontends → API → engine → services → vocabulary/utilities), scoped to the workspace with `filters` + `includeRemainingFiles: false`; Sokrates' component dependency graph then shows every edge that goes the wrong way.
- **Prefix stripping**: Sokrates strips the greatest common folder prefix from folder-based component names, so `src/` alone never becomes the single component; but `src/main/java/com/acme/` style trees need depth 5+ or explicit components — use `minComponentsCount` (raises the depth until N components exist) or explicit filters on the package folders.
- **Generated and vendored code** inside a module inflate its share — classify it as `generated`/ignore in the scope first; decompositions only see `main`.
- **Slices**: `filters` + `includeRemainingFiles: false` analyses one part of a monorepo as if it were the whole (its own component view and dependency graph) — useful as a secondary decomposition for a single product.
- **Dependencies between components** are found by Sokrates' built-in language finders (imports) plus `dependenciesFinder.rules`; components that are not modules (layers, owners) still get dependency edges as long as imports cross them, which is exactly what makes a layer decomposition informative.
