---
name: sokrates-improve
description: Improves source code where a Sokrates analysis says it matters, and proves the improvement with the same numbers. Picks a target - a long or complex unit, a duplicated block, a churn-times-complexity hotspot file, or an AI scanner finding with a recommendation - makes a behaviour-preserving change on a branch, re-runs Sokrates, and reports before/after metrics (and whether the finding is resolved). Use when the user asks to reduce complexity or duplication, refactor hotspots, "fix the top findings", act on a Sokrates or AI Insights report, or pay down technical debt in a measurable way.
---

# Sokrates improve

The scanners diagnose; this skill acts, and it keeps itself honest the same way the scanners do: every target comes from the Sokrates data with a file and line range, every change is measured by re-running Sokrates, and a change that does not move the number is reverted, not reported. One target per branch, behaviour preserved, tests green.

What moves which number, and what does not (renaming variables does not remove duplication; splitting a function does reduce its complexity): `references/what-moves-the-numbers.md`. Read it before choosing the kind of change.

## Workflow

1. **Have an analysis.** The repository needs `_sokrates/reports/data/data.zip`. If it is missing or older than the code (compare its date with `git log -1`), run `sokrates analyze` in the repository root first (Docker, JAR or alias - see sokrates.dev). AI findings are optional: when `_sokrates/reports/ai-insights/*.json` exist, their recommendations become targets too.
2. **Select targets** - deterministic, from the data, never from a guess:
   ```bash
   python3 <this-skill-path>/scripts/select_targets.py [--sokrates _sokrates] [--kind units|duplicates|hotspots|findings|all] [--top 10] [--json <scratch>/targets.json]
   ```
   It ranks: units by McCabe complexity and size (`unit:` targets), duplicated blocks by lines x copies (`duplicate:`), files by churn x complexity x size (`hotspot:`), and AI findings above info that carry a recommendation (`finding:`). Generated and test code are excluded (Sokrates' own scope classification; a target in `generated` is a configuration problem, see `sokrates-repo-config`, not a refactoring). Show the shortlist to the user and agree on one target unless they already named one.
3. **Snapshot before touching anything:**
   ```bash
   python3 <this-skill-path>/scripts/measure.py snapshot --target <id> -o <scratch>/before.json
   ```
4. **Branch:** `git switch -c sokrates/improve-<short-slug>`. Never work on the default branch.
5. **Change the code**, by the kind of target:
   - `unit:` - extract well-named helpers, replace nested conditionals with guard clauses or a lookup table, split by responsibility. Keep the signature and behaviour; do not "simplify" by deleting branches.
   - `duplicate:` - move the shared lines into one function, class, template or data file and call it from every copy. All copies, not one; a partial de-duplication leaves the block in place.
   - `hotspot:` - the file is big *and* changed often: split it along the seams the units show, so future changes touch a smaller file. Measure by file size and its largest unit.
   - `finding:` - do exactly what the finding's `recommendation` says, at the cited evidence. Read the whole finding first (`ai-insights/<scanner>.json`).
   Respect the repository's conventions and formatter. Do not reformat unrelated code; the diff must read as one change.
6. **Verify behaviour:** run the project's tests (and build, lint, type check) the way its CI does. Red means fix or revert - never report a metric improvement on a broken build.
7. **Re-measure:** re-run Sokrates exactly as for the first snapshot, from the same folder (`sokrates analyze -skipGitHistory -dataOnly` in the repository root: same configuration, the history is unchanged, and the data is all the measurement needs — the HTML reports can wait until the change is accepted), then
   ```bash
   python3 <this-skill-path>/scripts/measure.py snapshot --target <id> -o <scratch>/after.json
   python3 <this-skill-path>/scripts/measure.py compare <scratch>/before.json <scratch>/after.json --markdown
   ```
   `compare` prints the before/after table and a verdict: `improved`, `unchanged` or `worse`, with exit code 0 only for `improved`. For a `finding:` target, re-run that scanner first (its SKILL.md), then compare: resolved means the finding id is gone or downgraded.
8. **Decide.** `improved` and tests green: commit with a message that names the target and the numbers, and report. `unchanged` or `worse`: revert (`git restore . && git clean -fd` on the branch, or drop the branch) and say what you tried and why it did not move the number - that is a useful result too. Never leave a half-done refactoring on the branch.
9. **Report** (and use the same text as the pull request description, `--markdown` gives the table): the target and why it was chosen (its rank and numbers), what changed, the before/after table, the test command and its result, and what the next target would be. Keep the Sokrates commit (`_sokrates/`) out of the change unless the repository tracks it.

## Rules

- **Measured or it did not happen.** No claim of "reduced complexity" without the compare table.
- **One target, one branch, one diff.** Batch nothing; a reviewer must be able to read the change in one sitting.
- **Behaviour first.** Tests decide; when there are no tests around the target, write the characterization tests first and count that as part of the change.
- **Do not game the metric.** Moving code to a generated-looking folder, excluding it in `config.json`, or splitting a function into pieces that only call each other in sequence lowers numbers without improving anything; the reference says what counts as real.
- **Stop when it stops moving.** A target whose number did not move after one honest attempt is reported, not retried with tricks.

## Across many repositories

With the Sokrates CLI, `analyzeLandscape -urls ... -ai <agent>` or `analyzeGitHubOrg -org ... -ai <agent>` runs the agent inside each clone after the analysis; a prompt such as "improve the most complex unit" lets this skill work through an organization, bounded by `-aiMaxRepos` per run and skipped for repositories whose head commit has not moved. The result of each run must still be a branch per repository, pushed for review - never a direct change to a default branch.
