---
name: sokrates-improve
description: Improves source code where a Sokrates analysis says it matters and proves it with the same numbers: picks a target (a complex or long unit, a duplicated block, a churn-times-complexity hotspot, or an AI finding with a recommendation), makes one behaviour-preserving change on a branch, re-measures, and reports before/after; across a landscape it ranks targets of every repository together. Use to reduce complexity or duplication, refactor hotspots, fix the top findings, or pay down debt measurably.
---

# Sokrates improve

The scanners diagnose; this skill acts, and it keeps itself honest the same way the scanners do: every target comes from the Sokrates data with a file and line range, every change is measured by re-running Sokrates, and a change that does not move the number is reverted, not reported. One target per branch, behaviour preserved, tests green.

What moves which number, and what does not (renaming variables does not remove duplication; splitting a function does reduce its complexity): `references/what-moves-the-numbers.md`. Read it before choosing the kind of change.

## Workflow

1. **Have an analysis.** The repository needs `_sokrates/reports/data/data.zip`. If it is missing or older than the code (compare its date with `git log -1`), run `sokrates analyze` in the repository root first (Docker, JAR or alias - see sokrates.dev). AI findings are optional: when `_sokrates/reports/ai-insights/*.json` exist, their recommendations become targets too.
2. **Select targets** - deterministic, from the data, never from a guess. For a whole landscape ("which repository should we improve first?"), `select_targets.py --landscape <root>` ranks the targets of every repository analysis under the root together, each naming its `repo` and `analysis` folder; pick the repository, then continue below in its checkout (an analysis kept without source needs `sokrates analyzeGitRepo -url …`, which reuses its config, or a clone). For one repository:
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
   - `hotspot:` - the file is big *and* changed often: split it along the seams the units show, so future changes touch a smaller file. A good split moves one cohesive block - a tab, a section, an aggregation, a command - into a class of its own that receives what it needs through its constructor (the report, the folder, the data, a callback for the one thing it must ask the origin for) rather than reaching back into the origin; the origin keeps the orchestration and calls the new class; a serialized shape stays as it was (a delegating getter, or an unwrapped nested object, keeps the JSON flat). The extracted class starts with only the imports it uses. What is not a split: a second file that holds half the methods and calls the first for every field, or a move that copies the code. `references/what-moves-the-numbers.md` has the checklist; `measure.py compare` lists the files that are new in the folder and the hotspot's lines including them, so a move shows as lines that left and a copy as lines that doubled.
   - `finding:` - do exactly what the finding's `recommendation` says, at the cited evidence. Read the whole finding first (`ai-insights/<scanner>.json`).
   Respect the repository's conventions and formatter. Do not reformat unrelated code; the diff must read as one change.
6. **Verify behaviour,** twice. Run the project's tests (and build, lint, type check) the way its CI does; red means fix or revert - never report a metric improvement on a broken build. Then prove it on the outputs: a refactoring that moves code verbatim rarely breaks a test, and the tests only cover the cases someone thought of. Build the program as it was before the change, generate its outputs on a fixed input (a fixture, a sample repository, the project's own data), repeat with the changed code into a second folder, and diff the two:
   ```bash
   python3 <this-skill-path>/scripts/diff_outputs.py <scratch>/outputs-before <scratch>/outputs-after
   ```
   It compares every file, masks timestamps and timings, reads JSON as canonical and opens zips and the archives Sokrates embeds in its HTML entry by entry, so a changed number in one chart is named rather than hidden. Then run `python3 <this-skill-path>/scripts/check_imports.py` (no arguments: the files the branch changed or added) - a class extracted from a bigger file inherits that file's import list, and the cleanup belongs in the same change; it exits 1 while anything is flagged. Exit code 0 means equivalent; anything it prints is a behaviour change to explain or to fix. The full recipe (keeping the old build, choosing the input, what to ignore) is in `references/proving-behaviour.md`. Where the code produces no files - a library, a parser - add characterization tests around the target before changing it, or dump the structure it builds and diff that.
7. **Re-measure:** re-run Sokrates exactly as for the first snapshot, from the same folder (`sokrates analyze -skipGitHistory -dataOnly` in the repository root: same configuration, the history is unchanged, and the data is all the measurement needs — the HTML reports can wait until the change is accepted), then
   ```bash
   python3 <this-skill-path>/scripts/measure.py snapshot --target <id> -o <scratch>/after.json
   python3 <this-skill-path>/scripts/measure.py compare <scratch>/before.json <scratch>/after.json --markdown
   ```
   `compare` prints the before/after table and a verdict: `improved`, `unchanged` or `worse`, with exit code 0 only for `improved`. For a `unit:` target the table also shows the helpers that are new in the file and the unit's McCabe and size *including* them: extracting a helper moves decisions, it does not remove them, and the table says which of the two happened. When a unit got shorter but not simpler, `compare` reminds you that Sokrates counts `&&`, `||` and `?:` as decisions too. A unit id from `select_targets.py` ends in `@<start line>`, which picks the right overload for the first snapshot; `--like` then finds the same overload by its parameter count after the lines have shifted. A bare `#<name>` that matches several overloads measures the most complex one and warns. For a `finding:` target do **not** re-run the whole scanner: run scan-core's `recheck_findings.py <ai-insights>/<scanner>.json --ids <finding id> --fix-lines` first. `intact` means the cited code did not change and the finding stands (verdict `unchanged`, nothing more to run); `moved` means only line numbers drifted (fixed in place); `gone` means the cited code changed, and `recheck_findings.py --prompt` prints the brief for a scoped agent re-check of exactly those ids (minutes, not an hour) that removes, downgrades or keeps the finding and refreshes the file's summary and stats. `compare` reports `needs re-check` (exit 3) while that judgment is pending; after it, compare again: resolved means the finding id is gone or downgraded.
8. **Decide.** `improved` and tests green: commit with a message that names the target and the numbers - pasted from `measure.py compare --for-commit`, never typed from memory (a number written before the measurement is the one way the report lies) - and report. `unchanged` or `worse`: revert (`git restore . && git clean -fd` on the branch, or drop the branch) and say what you tried and why it did not move the number - that is a useful result too. Never leave a half-done refactoring on the branch.
9. **Report** (and use the same text as the pull request description, `--markdown` gives the table): the target and why it was chosen (its rank and numbers), what changed, the before/after table, the test command and its result, and what the next target would be. Keep the Sokrates commit (`_sokrates/`) out of the change unless the repository tracks it.

## Rules

- **Measured or it did not happen.** No claim of "reduced complexity" without the compare table.
- **One target, one branch, one diff.** Batch nothing; a reviewer must be able to read the change in one sitting.
- **Behaviour first.** Tests decide; when there are no tests around the target, write the characterization tests first and count that as part of the change.
- **Do not game the metric.** Moving code to a generated-looking folder, excluding it in `config.json`, or splitting a function into pieces that only call each other in sequence lowers numbers without improving anything; the reference says what counts as real.
- **Stop when it stops moving.** A target whose number did not move after one honest attempt is reported, not retried with tricks.

## Across many repositories

With the Sokrates CLI, `analyzeLandscape -urls ... -ai <agent>` or `analyzeGitHubOrg -org ... -ai <agent>` runs the agent inside each clone after the analysis; a prompt such as "improve the most complex unit" lets this skill work through an organization, bounded by `-aiMaxRepos` per run and skipped for repositories whose head commit has not moved. The result of each run must still be a branch per repository, pushed for review - never a direct change to a default branch.
