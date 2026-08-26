---
name: sokrates-virtual-landscapes
description: Defines virtual landscapes for a Sokrates landscape - the virtualLandscapes section of _sokrates_landscape/config.json that groups repositories into sub-landscapes by repository-name patterns - from the user's own grouping (products, teams, org units) or from what the repository analyses reveal (naming conventions, folders, main technology, activity, contributor domains, shared committers, tags), with nesting. Includes a proposal script that measures every candidate grouping (members, LOC shares, coverage, remainder) and emits paste-ready config, and validates a user-supplied grouping. Use when the user wants to split a large landscape into meaningful sub-landscapes, group repositories by product/team/technology/platform, asks how to organise many repositories in Sokrates, or wants an "active vs dormant" or "in-house vs community" view.
---

# Sokrates virtual landscapes

A landscape with a hundred repositories is a list; a landscape split into a dozen meaningful sub-landscapes is a map. Sokrates has two ways to split: **folder sub-landscapes** (a `_sokrates_landscape/` inside a folder of analyses — no config, but the folder structure must already be right) and **virtual landscapes** (`virtualLandscapes` in `config.json`: named groups defined by regexes on repository names, nestable, regenerated on every `updateLandscape` under `_sokrates_landscape/landscapes/<name>/`). This skill designs the virtual ones — from the organisation's own vocabulary when the user provides it, and from evidence in the analyses when they don't.

Semantics (from the Sokrates source, reference: `../sokrates-landscape-config/references/landscape-reference.md`): a repository belongs to a virtual landscape when `includeRepoNamePatterns` is non-empty **and** its `metadata.name` (from the repository's `_sokrates/config.json`, not the folder) fully matches any include pattern **and** matches no exclude pattern; matching is **case-sensitive** (prefix a pattern with `(?i)` to relax it); a repository may be in several landscapes; those in none go to the Remainder (`remainderLandscapeMetadata.name`); nesting is unlimited; an invalid regex silently matches nothing; `landscapes/` is wiped and regenerated on every run.

## Workflow

1. **Ask what the map is for** — or infer it from the request: by product line, by team/org unit, by platform/technology, by lifecycle (active vs archived), by customer, by compliance scope. If the user names the groups, that vocabulary wins; the analyses are then used to check coverage, not to invent groups.
2. **Measure the candidates** (and the user's grouping, if given):
   ```bash
   python3 <this-skill-path>/scripts/propose_virtual_landscapes.py <analysis-root> [--groups <scratch>/groups.json] -o <scratch>/virtual.json
   ```
   `groups.json` is either a flat map `{"Platform": ["core-.*", "(?i).*-infra"], "Mobile": {"include": ["ios-.*"], "exclude": ["ios-legacy"]}}` (regexes or exact names) or a real `virtualLandscapes` object with nesting — the latter is what you finally paste, so measure that shape last. Landscape thresholds from the existing `config.json` (`repositoryThresholdLocMain`, `repositoryThresholdContributors`, `ignoreRepositoriesLastUpdatedBefore`, duplicate names) are applied first so counts match what Sokrates will show; an existing `virtualLandscapes` is measured as proposal `existing`. The script discovers every repository analysis under the root, extracts name, **description** (the GitHub description Sokrates carries in `analysisResults.metadata` — the primary signal for *what the software is*; the JSON `repository_table` has it for every repository, and the console prints it for everything left in the remainder), links, folder, main LOC, dominant technology, tags, contributors (count, e-mail domains, top committers) and latest commit, and reports for each proposal its landscapes with members, LOC share, **coverage** (% of repositories placed) and the **remainder**:
   - `user` — your grouping measured: empty groups, repositories in several groups, unmatched names (case!);
   - `organisations` (for `org / repo` names) and `naming` — shared prefixes, suffixes, dotted extensions (`*.gl`) and tokens of the repository part of the name as real regex patterns — the only kind that classifies *future* repositories automatically; product families usually appear as suffix/extension conventions, org prefixes are just the folders again;
   - `folders`, `technology`, `activity` (active / fading / dormant by latest commit), `size`, `organisation` (dominant contributor e-mail domain), `teams` (repositories sharing their main committers), `tags` (Sokrates tag rules that fired) — all as explicit name lists, i.e. snapshots that need regenerating when repositories come and go.
3. **Compose the landscapes.** Rules of thumb:
   - Prefer **patterns** over name lists: if a proposal's groups coincide with a naming convention (`payments-*`, `*-service`, an org prefix), write the regex; keep explicit lists only for the exceptions (`excludeRepoNamePatterns`) or for one-off views.
   - 5–15 top-level landscapes; a landscape with one repository is noise, one with 60 % of the LOC needs nesting (`virtualLandscapes` inside it — e.g. org → product → component libraries).
   - A repository may legitimately be in two landscapes (a shared library under both products that use it) — but say so, and keep the Remainder small and named honestly (`Other repositories`, `Unassigned — please classify`).
   - Snapshot views (activity, size, technology) are best as a *second* grouping alongside the structural one, or replaced by landscape filters (`ignoreRepositoriesLastUpdatedBefore`, `repositoryThresholdLocMain`) and tags, which Sokrates maintains itself.
   - When folders already encode the structure, propose folder sub-landscapes instead (`sokrates-landscape-config` skill) — they need no configuration and survive renames. The script warns when folder sub-landscapes **already exist**: then the virtual landscapes must offer a *different* cut (by product family, not by org/folder again).
   - Every nested level has its own remainder (`<parent>/Remainder` in the checker) — name it via the nested `remainderLandscapeMetadata` or extend the nested patterns until it is empty; the script warns about non-empty nested remainders.
   - Repositories excluded by the landscape thresholds never appear in any landscape; if one belongs to a family anyway, lower the threshold rather than listing it.
   - Name landscapes the way the organisation does (products, teams, platforms), give each a `description`, and keep names stable: the generated sub-landscape URLs (`landscapes/<name>/`) are what people bookmark.
4. **Re-measure the final grouping** with `--groups` until coverage, overlaps and remainder are what you intend; every pattern compiles; names match case-sensitively.
5. **Write and verify.** Put the `virtualLandscapes` object into `_sokrates_landscape/config.json` (merge with existing settings; keep `remainderLandscapeMetadata`), then run the landscape checker, which re-evaluates membership exactly as Sokrates will:
   ```bash
   python3 <config-skills-path>/sokrates-landscape-config/scripts/check_landscape.py <analysis-root>
   ```
6. **Report**: the landscape table (name, description, repositories, LOC share, pattern or list, nesting), overlaps and remainder (with the descriptions of what stayed unclassified), which proposals you rejected and why, and the next command — `sokrates updateLandscape -analysisRoot <root>` (add `-recursive` when folder sub-landscapes exist).

## Patterns

- **Org / product / library hierarchy**: top level from the name prefix (`(?i)payments[-_/ ].*`), nested level from the second token (`(?i)payments[-_/ ]api.*`, `…-web.*`), libraries as a nested `Shared libraries` with explicit names and `excludeRepoNamePatterns` on the products.
- **In-house vs community** for open-source portfolios: the `organisation` proposal's domain groups turned into two landscapes with explicit lists, refreshed by re-running the script.
- **Lifecycle view without maintenance**: instead of an `Archived` virtual landscape, set `ignoreRepositoriesLastUpdatedBefore` on the main landscape and create a second landscape folder (a separate `_sokrates_landscape/` with a different config over the same analyses) for the archive.
- **Names with `org / repo` form** (GitHub exports): tokens split on `/` and spaces too, so `(?i)uber[-_./ ].*` catches `uber / x`, `uber-go / y`, `uber-web / z`; tighten with `(?i)uber / .*` when the org alone is meant.
