---
name: risk-synthesis-scan
description: Turns Sokrates' quantitative risk signals into explained, actionable findings - reads the codebase's actual hotspot files and says what each one does, why its metrics (complexity, churn, single ownership, change coupling) make it risky, and what to do about it. Use whenever the user asks where the risks in a codebase are, which files need refactoring first, about maintainability, technical debt hotspots, bus factor / knowledge risk, "what should we be worried about", or wants Sokrates results explained or prioritized. Requires a _sokrates analysis.
---

# Risk synthesis scan

Sokrates can say "this file is large, complex, changes constantly, and one person wrote it" — but not what the file *does*, whether the complexity is essential or accidental, or what a fix would look like. This scanner closes that gap: deterministic metrics pick the shortlist, then you read the actual code and explain each risk in words a tech lead can act on.

**First read `sokrates-scan-core/SKILL.md`** (sibling skill) — it defines the output format, evidence rules, validate/render scripts, and the `_sokrates` data layout. This file adds only what is specific to risk synthesis.

## Workflow

1. Orient per the core skill (config.json, unzip `data.zip` to a scratch directory).
2. **Run the selection script** — never eyeball the metrics yourself; the script makes the shortlist deterministic and re-runnable:
   ```bash
   python3 <this-skill-path>/scripts/select_hotspots.py \
       --data <scratch>/sokrates-data --src-root <src-root> --top 10 -o <scratch>/hotspots.json
   ```
   It returns: `hotspots` (files ranked by complexity × recent activity × size, with their most complex units and start lines, plus `coupled_with` links to their shotgun-edit partners and — thanks to `--src-root` — the embedded-test-module boundary and a production-LOC estimate), `knowledge_risk` (top-contributor commit shares and single-owner non-test files with each `owner` and that owner's last commit anywhere in the repo — an owner gone quiet strengthens the finding), and `change_coupling` (cross-folder file pairs that change in the same commits, with a coupling ratio).

   No-history degradation: on a repo without git history the script warns on stderr, sets `stats.history_data: "absent"`, and falls back to a complexity-only ranking (no churn factor). Then scan the hotspots on their complexity merits, state plainly in the summary that churn/ownership/coupling signals are unmeasured and what that does to confidence, and collapse the `knowledge-risk` and `change-coupling` groups into a single `info` finding explaining the gap — never fabricate history-based claims.

   Trust but verify the shortlist data: unit `start_line` values can be off by a few lines or `0` for some languages — locate the unit by searching for its name before citing it. With `--src-root`, units inside an embedded test module are already excluded from `top_units` and the score (`test_units_excluded` says how many); files whose `loc_test_estimate` rivals `loc_production_estimate` owe their bulk to tests, and files flagged `is_test_file: true` are pure test code — judge both on the production part, if any. Coupling pairs marked `same_module_hint: true` are likely one logical module split across files (Rust `#[path]`/`mod.rs` style) — usually an `info` observation, not a boundary problem.
3. **Read the shortlisted code.** For each hotspot file, read at least its flagged units (the script gives you their start lines) plus enough surrounding context to know the file's role. For coupling pairs, read both files. This reading is the entire point of the scanner — a finding that only restates the numbers has no value over the Sokrates report itself.
4. Write findings, validate, render, and report per the core workflow. Scanner id: `risk-synthesis-scan`, version `1.0`. For the findings' `stats`, use the script's `stats` object plus a `shortlist_params` key recording the parameters used (e.g. `"shortlist_params": {"top": 10}`) so a re-run is comparable.

## Group taxonomy

| group | contents |
|---|---|
| `hotspots` | One finding per shortlisted file: what it does, why it keeps changing, whether the complexity is essential (dense domain logic) or accidental (missing abstraction, copy-paste growth), and what a targeted improvement would be |
| `knowledge-risk` | Bus-factor concentration at project level, plus single-owner areas that matter. Cluster related single-owner files into one finding per area/component rather than one per file — a handful of area findings plus, if needed, one catch-all for unrelated peripheral files is the right shape |
| `change-coupling` | One finding per notable coupled pair/cluster: the *semantic reason* they co-change (shared protocol, duplicated logic, leaky boundary, or legitimately cohesive) and whether the boundary should change |

## What a good finding looks like

The description answers four questions in order: *what is this code* (one or two sentences, from actually reading it), *what do the numbers say* (quote the script's values — McCabe, 90-day commits, contributor count — and cite the metrics via `sokrates_refs`, e.g. `metric:mccabe`, `file:<path>`), *why is that risky here specifically* (connect the code's role to the metric — "every new slash command adds an arm to this match" beats "high complexity"), and *what would help* (in `recommendation` — concrete and proportionate: "extract the per-command handlers behind a trait" rather than "refactor this file").

Evidence: cite the signature line of the flagged unit (the script's `start_line` tells you where to look — verify by reading, line numbers in `units.txt` are occasionally off by a few lines) and, when helpful, one line that typifies the problem (a giant match, a copy-pasted block). Metric numbers themselves are not evidence — they go in the description and `sokrates_refs` (see the core skill's evidence rules).

Not every hotspot is a problem. If reading shows the top-ranked file is fine — a well-structured dispatcher, generated-but-tracked code, a test fixture — say so with `severity: info`. A scan whose every finding demands action reads as alarmist and gets ignored; the honest "this one is fine" findings are what make the others credible.

## Severity calibration

Use the core scale, driven by *cost of leaving it alone*:

- `high` — actively churning, hard-to-change code where mistakes are likely and consequential (complex + top-decile recent commits + few owners, in a load-bearing path).
- `medium` — real friction that will keep taxing changes (accidental complexity in active code; a leaky boundary forcing shotgun edits; a critical area only one person knows).
- `low` — worth fixing opportunistically (complex but stable and rarely touched; single-owner code that is small or peripheral).
- `info` — examined and found acceptable, or purely contextual (bus-factor overview when concentration is unremarkable).

For knowledge risk, weigh *recency* heavily: a single-owner file whose owner is still active is `low`–`medium`; the same file when its owner's last commit is months past is a stronger finding.
