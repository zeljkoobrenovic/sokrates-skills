# What moves the numbers

How Sokrates computes the metrics this skill targets, so a change is chosen that actually moves them - and so the agent recognises changes that only look like improvements.

## Lines of code

Counted after cleaning: blank lines and comments are removed (language-aware). Reformatting, re-wrapping and comments do not change LOC; removing code or moving it to another file does. Per file (`files.json`, `text/aspect_main.txt`) and per unit (`units.json`).

## Units: size and conditional complexity

A unit is a function, method or procedure as the language analyzer finds it (`units.json`: `relativeFileName`, `shortName`, `startLine`, `endLine`, `linesOfCode`, `mcCabeIndex`). Risk categories: unit size 1-20 / 21-50 / 51-100 / 101+ lines; conditional complexity (McCabe) 1-5 / 6-10 / 11-25 / 26+.

McCabe counts decision points: each `if`, `else if`, loop, `case`, `catch`, `&&`, `||`, ternary adds one. What lowers it for a unit:

- extracting a block of branches into its own function (the complexity moves with it - the total stays, the maximum per unit drops, which is the point);
  `measure.py compare` shows this: next to the unit's own numbers it lists the helpers that are new in the file and the unit's McCabe and size including them, so a reviewer sees whether decisions were removed or redistributed;
- not ternaries or boolean operators in place of nested `if`s: `?:`, `&&` and `||` count as decisions exactly like `if` (Java, C-style languages: ` if `, ` while `, ` for `, ` case `, ` catch `, `&&`, `||`, ` ? `), so flattening nesting that way leaves the number where it was or raises it;
- replacing a chain of `if`/`else if` on one value with a lookup table or polymorphism;
- early returns that remove nesting only help when they remove branches, not when they only re-indent;
- deleting dead branches.

What does not: renaming, reordering, comments, splitting a long straight-line function without branches (that lowers unit *size*, which may be the goal for a `unit:` target chosen by size).

Matching after a change: units are matched by file and name, not by line numbers (those shift), and overloads by their parameter count (`select_targets.py` ids end in `@<start line>`, which the first snapshot turns into the parameter count `--like` reuses); a leading folder on the exported path (it depends on how Sokrates was invoked) is tolerated. A renamed unit is reported as "not found"; mention the rename in the report and re-run `select_targets.py` to see the new names. `units.json` holds at most 10,000 units, so in a very large analysis a small unit can fall out of the export - that is also a sign the scope is too wide.

## Same scope, or no comparison

`measure.py compare` warns when the main lines of code moved by more than 10% between the snapshots: the two analyses did not see the same files, and nothing in the table is comparable. The usual causes are a `config.json` that does not ignore `_sokrates/` itself (the second run then analyzes the first run's reports), or Sokrates started from a different folder or with a different `-confFile` path. Take both snapshots with the same command run from the same folder - `sokrates analyze -skipGitHistory` in the repository root is the safe choice.

## Duplication

Sokrates reports blocks of **6 or more identical cleaned lines** that occur in two or more places (`duplicates.json`: each entry has a `blockSize` and the `duplicatedFileBlocks` with file and lines). Cleaning removes blank lines, comments and the usual noise such as imports before comparing, so:

- renaming variables, re-commenting, or reformatting leaves the duplication exactly as it was;
- changing one copy slightly splits a long block into two shorter ones and can *increase* the number of duplicates while reducing duplicated lines - compare looks at duplicated lines for the files involved, not at the block count;
- the real fix is one implementation called from every former copy: a shared function, base class, template, macro, or data file; or deleting copies that are not needed.

Duplication inside generated code is a scoping problem: classify the folder as `generated` in `config.json` (the `sokrates-repo-config` skill) rather than refactoring generated files, which the generator will overwrite.

## Hotspots

A hotspot is a file that is both large and frequently changed: `text/mainFilesWithHistory.txt` gives per file the lines of code, the number of commits (overall, 30 and 90 days), contributors and churn; `units.json` gives its largest and most complex units. The score used by `select_targets.py` is lines x commits in the last 90 days (falling back to all-time commits), weighted by the file's maximum unit complexity. Splitting the file along responsibilities is what helps: later changes then touch a smaller file. Moving code around without reducing the file does not.

## AI findings

A finding (`_sokrates/reports/ai-insights/<scanner>.json`) with severity above `info` carries a `recommendation` and evidence (file, line range, snippet). It is resolved when, after the change and a re-run of that scanner, the finding id is no longer reported or its severity went down; `measure.py compare` checks exactly that. The scanner's SKILL.md says how to re-run it; `diff_findings.py` in `sokrates-scan-core` compares whole runs.

## Scope matters

All of the above is computed on the `main` scope. Test, generated, build and other files are classified by `config.json`; a target the selector marks as outside `main` is skipped on purpose. Changing `config.json` to make a number disappear is not an improvement and must never be part of an improve branch.
