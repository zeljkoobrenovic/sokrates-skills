---
name: evolution-scan
description: Explains how a codebase evolved over time from its git history - the eras of development and what each was about, how the codebase grew and where the code came from, how the center of activity shifted between areas, who arrived and who left, which parts were born, rewritten or abandoned, what kind of work dominates now (features vs fixes vs refactoring), and where the trajectory points. Use when the user asks about a project's history, timeline, how it got here, growth, momentum, whether it is accelerating or stagnating, contributor turnover, "what changed in the last year", legacy vs. active areas, or wants the story behind the Sokrates churn/age/contributor numbers. Requires a _sokrates analysis with git history (git-history.txt export).
---

# Evolution scan

Sokrates measures churn, file age, and contributor counts as of today. This scanner reads the *history* behind those numbers and tells it as a story: what the project was at each stage, which decisions the commits reveal (rewrites, migrations, abandoned directions), how the team changed, and which way the code is heading. A tech lead should finish the report knowing what "this codebase" meant a year ago, what it means now, and what it is turning into.

**First read `sokrates-scan-core/SKILL.md`** (sibling skill) — output format, evidence rules, validate/render scripts, `_sokrates` data layout. This file adds only what is specific to evolution.

## Workflow

1. Orient per the core skill (config.json, unzip `data.zip` to a scratch directory). Read prior findings if present: `architecture-scan` (components, migrations in progress) and `risk-synthesis-scan` (hotspots, knowledge risk) name the areas whose history matters most; `tech-stack-scan` tells you what the technologies in old commit messages are.
2. **Run the timeline script** — never derive periods, shares, or turnover by hand; the script keeps them deterministic and re-runnable:
   ```bash
   python3 <this-skill-path>/scripts/evolution_timeline.py \
       --src-root <src-root> --data <scratch>/sokrates-data -o <scratch>/evolution.json
   ```
   It reads Sokrates' `git-history.txt` + `git-commits.txt` at the source root (falling back to `zips/git-history.zip` inside `data.zip`) and returns: `stats` (span, commits, authors, busiest period, overall and recent commit themes, 90-day activity trend), `periods` (per month or quarter: commits, authors, new authors, new files, files since gone, lines added/removed, top areas with shares, theme mix, and the **notable commits** — the largest by lines changed, with messages and sample paths), `focus_shift` (share of commits per period for the top areas — the table that shows the center of gravity moving), `areas` (per path-prefix area: commits all-time / 365d / 90d, authors, first and last commit, current size, and flags `emerging`, `accelerating`, `cooling`, `dormant`, `no-history`), `people` (top contributors with tenure, 90-day vs. previous-90-day commits and status active/fading/gone; arrivals in the last year; departures; **fading** major contributors whose 90-day output halved; **rising** ones), and `lifecycle` (files seen vs. current, deletions vs. estimated moves/renames, deletions by area, file-age quantiles, oldest surviving, most committed, most rewritten files). Per period you also get author concentration (`top3_authors_share_pct`), the e-mail-domain mix (in-house vs. community), the count and top three of newly arrived authors, and two notable-commit rankings — by meaningful lines changed (lockfiles, snapshots, fixtures and generated files excluded) and by files touched. `--depth` sets what an "area" is (2 = `codex-rs/core`); `--period` forces month or quarter (auto: months under two years of history).

   No-history degradation: if the script exits 3, no git history export exists. Write a single `info` finding in `trajectory` explaining that evolution cannot be measured, set `stats.history_data: "absent"`, and stop — never reconstruct history from file dates or guesswork.

   Trust but verify the digest — and know its blind spots:
   - **Themes** come from commit-message keywords. `stats.theme_other_pct` tells you how much the vocabulary missed; when `theme_trend_reliable` is false (over 30 % unclassified) do not narrate the theme trend as fact — say the messages are unprefixed imperatives and judge the work mix from the notable commits instead.
   - **Area flags** are threshold heuristics. `not-inventoried` means the area is still committed to but absent from Sokrates' file inventory (usually ignored by `config.json`) — never report it as shrunk or gone. `single-owner` pairs with `emerging`/`accelerating` to answer the medium-severity calibration below; `areas[].top_author_share_pct` is there for every area.
   - **Percentages in `focus_shift` and `top_areas`** are "share of the period's commits that *touch* this area"; a commit touching three areas counts in all three, so shares do not sum to 100. Say "touched by 45 % of commits", never "45 % of the work".
   - **Files gone** are split into `files_deleted` and `files_moved_estimate` (same basename reappearing in the same commit); wholesale renames still inflate deletion counts for the old path, so confirm a "deleted" claim by checking the new location.
   - **Identities** are merged when several e-mails share one author name (`stats.identity_merges` lists them) — mention a merge when it matters ("the maintainer under two addresses"), and treat remaining same-person-different-name cases with suspicion when two "contributors" hand over seamlessly.
   - `people.departures` uses `gone_threshold_days` — the *larger* of 180 days and a quarter of the history; on a young project `fading` is the more telling list. `drive_by_authors_single_commit` qualifies raw author counts — "581 authors" with 329 one-commit authors is a different team than it sounds.
   - Periods flagged `low_sample` (under 10 commits) have meaningless shares and theme mixes — describe them as quiet, not by their percentages.
   - Without `--data`, `files_deleted`, `files_moved_estimate` and `current_files` are null and `dormant`/`not-inventoried` never fire; say so in the summary if you had to run without it.
   The script narrows the reading; the reading is the finding.
3. **Read the history behind the numbers.** For each era you intend to describe, skim that period's notable commits *and open `git-commits.txt`* around them (the file is in the source root — it is citable evidence; it carries no dates, so take dates from the digest's notable commits or grep the sha in `git-history.txt`). Draw era boundaries at the **structural events** the notable commits reveal — an import or deletion of a whole implementation, the birth of the component that becomes the top area, a rewrite landing — not at calendar quarters; when releases or tags exist in `CHANGELOG.md`/release notes use them, but most exports have none, so a one-line pointer changelog is normal and the commit messages are the primary source. For each area you call emerging, dormant, or rewritten, open the current code (or confirm its absence) and find the commit messages that created, replaced, or abandoned it. For people findings, look at what the arriving or departing contributors actually worked on (the script's `top_areas` per author) and whether their areas have other owners now. `CHANGELOG.md`, release notes, ADRs, and `docs/` are first-class sources for *why* things changed — cite them when they exist.
4. Write findings, validate, render the explorer, and report per the core workflow. Scanner id: `evolution-scan`, version `1.0`. For `stats`, use the script's `stats` object (it already carries `history_data: "present"`) plus a `timeline_params` key recording `depth`, `period`, and `top`.

   **Stable ids.** Era slugs are *topical*, never positional or dated: `eras/typescript-cli`, `eras/rust-workspace`, `eras/app-server-platform` — a re-run a quarter later keeps the same eras (their end dates may move) and adds a new one, which the differ then reports as new. The same rule applies to rewrites (`lifecycle/tui-to-tui2`) and people (`people/core-ownership-shift`).

   **Evidence for pure-history facts.** Growth curves, team-size series, velocity comparisons and share tables have no single citable line. Such findings may carry an empty `evidence` array with `confidence: likely` when they are wholly grounded in the digest and cite it via `sokrates_refs` (`metric:commits`, `metric:contributors`, `metric:churn`, `metric:file_age`); do not pad them with the first and last line of `git-commits.txt`. Whenever a claim *can* be pinned to a line — the commit that started a growth burst, the message that announces a rewrite — cite that line and keep `certain`.

## Group taxonomy

| group | contents |
|---|---|
| `eras` | The timeline as chapters: 3–6 eras with their date range, what the project *was* in that era (purpose, shape, main technologies), what the big commits were about, and what closed the era. A long quiet stretch is an era too — describe what maintenance it did and did not do. One finding per era, ordered oldest first, plus at most one finding for a singular turning point that deserves its own entry (a rewrite, a repository merge, a change of ownership); a turning point that *opens* an era is told inside that era's finding, not separately |
| `growth` | How the codebase got its size: growth curve in commits/files/lines per period, where the bulk came from (organic feature work, bulk imports, generated code, vendored trees, test fixtures), and how much of what was ever written is still there (files seen vs. current, most rewritten files) |
| `focus-shift` | Where the center of activity moved: which areas dominated each period and which dominate now, areas that are `emerging` or `accelerating` (with what they are), areas `cooling` or `dormant` (and whether dormant means *finished* or *neglected*) |
| `people` | The team over time: size per period, concentration, arrivals and what they brought, departures and what they left behind (single-owner areas that lost their owner), whether ownership of the core has moved between people |
| `lifecycle` | Births, rewrites, deaths: modules that were created and later replaced (`tui` → `tui2` → …), migrations completed or stalled mid-way (both old and new paths still alive), directories deleted wholesale, the oldest surviving code and whether it still matters |
| `trajectory` | The synthesis: velocity trend (accelerating / steady / decelerating, with the 90-day comparison), what kind of work dominates now versus a year ago (feature vs. fix vs. refactor mix), what the last quarter says about direction, and the risks the trajectory implies — plus the no-history statement when applicable |

Tie-breakers: a rewrite is told once, in `lifecycle` (the mechanics: what replaced what, when, is the old path gone), and referenced from the era it closed or opened; `focus-shift` describes activity *distribution*, not module births; `people` findings are about humans, ownership consequences go in `people` even when the area is also discussed elsewhere; `trajectory` never introduces a new fact, it interprets facts established in the other groups.

## What a good finding looks like

An era finding reads like the opening of a chapter: dates, then *what the project was* in one sentence, *what happened* in three or four (name the largest commits and what they built — "the `app-server` JSON-RPC layer appears in 2025-09 with 962 new files in one month"), and *what it left behind* (a module, a convention, a debt). Quote the script's numbers via `sokrates_refs` (`metric:commits`, `metric:contributors`, `metric:churn`, `metric:file_age`, `component:<name>`); put the numbers in the description, not in evidence.

Evidence for history claims is the history itself: `git-commits.txt:<line>` for the commit message that did the thing, `CHANGELOG.md`/release notes lines, and for "this still exists" / "this is gone" claims the current file (a `mod` declaration, a manifest entry, a README sentence naming the new component); for binary or unreadable survivors (a zip, an image) the `git-history.txt` line that last touched them is the acceptable citation. `git-history.txt` lines are valid evidence too but rarely readable — prefer the message. A finding with only script-derived numbers and no citable line is `possible` (see the core evidence rules).

Not every trend is a problem. A `cooling` area that finished its job is good news; say so with `severity: info`. Reserve `low`–`high` for trajectory facts that call for action: an accelerating area with a single owner, a migration stalled with both halves alive, a departure that orphaned a load-bearing module, velocity collapsing while open scope grows.

## Severity calibration

Use the core scale, driven by *what the trend costs if nobody reacts*:

- `high` — the history shows an active hazard: a half-done rewrite where both generations are load-bearing and diverging; the core's only long-term owners gone in the last year; velocity dropping sharply while the codebase keeps growing.
- `medium` — a trend that will hurt within a few quarters: an emerging area accelerating under one contributor; dormant code that other active areas still depend on; work mix drifting to fixes-only (feature work stopped, maintenance burden rising).
- `low` — worth knowing and cheap to address: stale directories to delete, a completed migration whose old path lingers, a peripheral single-owner departure.
- `info` — chapters of the story, growth facts, and healthy trends.

Weigh *recency* heavily: the last two periods matter more than the first ten, and a claim about "now" must be backed by 90-day figures, not all-time ones.
