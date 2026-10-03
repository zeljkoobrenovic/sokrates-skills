# Proving a refactoring on its outputs

Tests prove the cases someone thought of. A refactoring that moves code verbatim - a helper extracted, a block moved to
its own class, a chain turned into a table - rarely breaks one, and that is exactly when a retyped literal, a dropped
clause or a reordered side effect slips through. The proof that catches those is cheaper and stronger: the program
produces the same outputs from the same input before and after the change.

## The recipe

1. **Keep the build from before the change.** Before touching the code, build the program and copy the artifact
   aside (`cp target/app.jar <scratch>/app-before.jar`), or keep a `git worktree add <scratch>/before <default branch>`
   and build there. Never trust a comparison whose "before" was produced by the changed code - if the build failed
   silently and the old artifact was reused, both folders come from the same code and the diff proves nothing.
   Check that the artifact actually contains the new classes before trusting the "after" run.
2. **Choose a fixed input** that exercises the code you change: a test fixture, a sample project, the repository's own
   data. Smaller is faster, but it must reach the changed code; for a report renderer that means an input that has
   the thing being rendered (history, duplicates, more than one component).
3. **Generate twice**, same command, same input, into two folders: `<scratch>/outputs-before` with the kept build,
   `<scratch>/outputs-after` with the changed one.
4. **Diff with `scripts/diff_outputs.py before after`.** It masks timestamps and timings, compares JSON as canonical
   (key order and the usual volatile keys ignored), opens zips entry by entry and extracts the archives Sokrates embeds
   in its HTML (`SOKRATES_ARCHIVE`), so a difference is named by file and entry. Exit code 0 is the proof. Add
   `--ignore <name>` for a file that is volatile by design (a log, an execution-stats file) and `--volatile-key <key>`
   for a JSON field that carries a time or a counter.
5. **Explain every line it prints.** A difference is either a behaviour change you intended (then say so in the
   report, with the entry it names) or a mistake to fix before measuring. An analysis-time metric is the only
   difference a Sokrates report should show after a pure refactoring.

## When there are no outputs

A library, a parser, an analyzer: dump the structure it builds (its JSON serialization, a `toString`, a table of the
units it extracts) from a fixed input, before and after, and diff that. For a configuration or convention table, dump
the table (every entry in order) from both builds - 500 identical lines in the same order is a proof; the tests
covering three of them are not.

## What it does not prove

Behaviour the input does not exercise, concurrency, and anything keyed on the current date. Say in the report what
input the proof used, so a reviewer knows what it covered.
