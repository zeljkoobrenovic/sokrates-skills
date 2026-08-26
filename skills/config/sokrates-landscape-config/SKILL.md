---
name: sokrates-landscape-config
description: Creates and tunes a Sokrates landscape - the _sokrates_landscape/config.json (plus config-tags.json, config-teams.json, config-people.json) that combines many repository analyses into one landscape report - covering folder layout and discovery, repository filters and thresholds, virtual sub-landscapes by repository-name patterns, repository tags, contributor identity merging, bots and ignored accounts, teams, and report embeds. Includes a checker that previews discovery, tag/virtual-landscape/team matching and the contributor pipeline before running updateLandscape. Use when the user wants to set up or fix a Sokrates landscape, organise many repositories into groups, define teams, merge contributor identities, tag repositories, or asks why a repository or contributor is missing from a landscape.
---

# Sokrates landscape configuration

A landscape aggregates repository analyses (each a `_sokrates/reports/data/data.zip`) into one portfolio report: repositories, technologies, contributors, teams, trends. What makes a landscape useful is configuration Sokrates cannot infer: how repositories group into sub-landscapes, which tags mean something in this organisation, who the *people* are behind the e-mail addresses, and which accounts are bots. This skill sets those up and verifies them before `updateLandscape` runs.

Field reference (read from the Java model, incl. the differences from the docs): `references/landscape-reference.md`.

## Workflow

1. **Get the layout right.** Repository analyses must sit *under* the analysis root as `<anything>/<repo>/_sokrates/reports/data/data.zip` (any nesting; a nested `_sokrates_landscape/` makes a folder sub-landscape). The landscape lives in `<root>/_sokrates_landscape/`. If repositories are still unanalysed, that is repository-config work first (`sokrates-repo-config`), then `sokrates generateReports` in each — the landscape reads their `metadata.name`, so make sure names are set and unique.
2. **Bootstrap.** If `_sokrates_landscape/config.json` does not exist, run `sokrates updateLandscape -analysisRoot <root>` once (it creates `config.json`, default `config-tags.json`, empty `config-teams.json`/`config-people.json`, and `info.json`) — or write the files by hand from the reference and let the first run normalise them. Never edit `info.json`; never store anything in `landscapes/` or `contributors/` (wiped each run).
3. **Check** — before and after every edit:
   ```bash
   python3 <this-skill-path>/scripts/check_landscape.py <root> [--conf <root>/_sokrates_landscape/config.json] [--json <scratch>/landscape.json]
   ```
   It re-implements discovery and matching: which repositories are found (and which are skipped as duplicate or blank names), which the thresholds exclude and why, which tags each repository gets, virtual-landscape membership, and the contributor pipeline (ignore → transform → people → threshold → bots → teams) with merged identities, active contributors without a team, alias candidates, and unused people/teams/tags. It flags regexes that do not compile (Sokrates treats them as non-matching silently), legacy and ghost keys, and empty virtual landscapes. `FAILED` = do not run Sokrates yet.
4. **Decide the portfolio shape.**
   - *Folder sub-landscapes* when the repositories already live in meaningful folders (per team/product): a `_sokrates_landscape/` in each folder, generated deepest-first with `-recursive`.
   - *Virtual landscapes* when grouping is by naming convention or cuts across folders: `virtualLandscapes.landscapes[]` with `includeRepoNamePatterns` — **case-sensitive, full-string** regexes on `metadata.name` (`.*-service` not `-service`). A repository may be in several; the Remainder collects the rest — name it (`remainderLandscapeMetadata`) so it reads well. Nest for a hierarchy.
   - Filters: `repositoryThresholdLocMain` / `repositoryThresholdContributors` / `ignoreRepositoriesLastUpdatedBefore` to drop toy and dead repositories; `ignoreExtensions` and `mergeExtensions` (`yml`→`yaml`) to keep the technology view honest.
5. **People before teams.** Run `sokrates updateLandscapePeopleConfigByUserName -analysisRoot <root>` to generate `config-people.json` merging identities that share a user name; then hand-fix what it cannot know (same person, different names), add `userName`, `links`, `image`. Use `transformContributorEmails` for systematic normalisation (strip `+id` GitHub noreply prefixes, unify domains) — it runs before people matching. Put CI and service accounts in `bots` (they get their own tab) or `ignoreContributors` (they vanish); set `contributorThresholdCommits` to drop drive-bys if wanted; `anonymizeContributors` for external audiences. Templates: `contributorAvatarLinkTemplate: "https://avatars.githubusercontent.com/${contributorid}"` works when ids are GitHub logins.
6. **Teams.** `config-teams.json`: first matching team wins, matching is case-insensitive full-string on the *canonical* email (after people merge) or user name — literal emails and domain patterns (`.*@payments[.]example[.]com`) both work. The checker lists active contributors that fall into "Undefined Team" — resolve those; inactive unmatched contributors are dropped from teams silently.
7. **Tags.** Keep the default CI/CD and build-tool groups; add organisation-specific groups — by name pattern (`patterns`), by dominant technology (`mainExtensions`), by presence of a technology (`anyExtensions`), or by files (`pathPatterns`, one matching file tags the repository). Add the "ui tech" group (react/vue/android) by hand — Sokrates builds it but never writes it. Give tags `imageLink`s for the visual matrix.
8. **Presentation.** `metadata`, `parentUrl`/`breadcrumbs` for a hierarchy of landscapes, `iFrames*`/`customTabs` for dashboards, `commitsMaxYears` to the organisation's real age, `contributorsListLimit` for very large orgs.
9. **Re-check, run, verify.** `sokrates updateLandscape -analysisRoot <root> [-recursive]`, then compare the report's repository and contributor counts with the checker's numbers; diff the rewritten companion files against your versioned copies (Sokrates normalises them on every run).

## Rules of thumb

- Name-based matching (tags `patterns`, virtual landscapes) is case-sensitive; people/team/bot matching is not. Compile-check every regex with the checker.
- `repositoryThresholdContributors` never excludes a repository with zero contributors (no git history) — use the LOC threshold or fix the repository's history export instead.
- The landscape only knows what the repository analyses exported: wrong scopes or components in a repository are fixed in *its* config, then re-analysed, not in the landscape.
- Keep `config*.json` under version control; treat the on-disk copies after a run as generated.
- `repositoriesShortListLimit` does nothing; `showExtensionsOnFirstTab` and other keys not in the reference are ignored.
