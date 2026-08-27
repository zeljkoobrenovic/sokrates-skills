# Reading a Sokrates analysis

A guide to the machine-readable data Sokrates leaves behind, and which parts are worth a scanner's attention.

## config.json (analysis root)

Read this first. Key fields:

- `metadata.name` — project name; use it for `target.name` in findings.
- `srcRoot` — source root *relative to the config file* (often `..`, meaning the analysis root sits inside the project). Evidence paths in findings are relative to this resolved directory.
- `extensions` — file extensions Sokrates considered source.
- `ignore[]` — path/content patterns excluded from analysis (vendored code, binaries, caches, generated files). Respect these: scanning vendored code wastes effort and pollutes findings. Exception: dependency manifests and lock files may be *listed* in ignores but are still legitimate evidence for tech-stack-style scanners.
- `logicalDecompositions[]` (or `components`) — how the project is split into components; use component names in `sokrates_refs`.
- `concerns`, `controls`, `goals` — cross-cutting concerns and quality goals the analysis tracks.

## reports/data/data.zip

The bulk of the analysis. Unzip to a scratch directory (it can be tens of MB; do not unzip into the project):

```bash
unzip -o _sokrates/reports/data/data.zip -d <scratchpad>/sokrates-data
```

Useful entries, roughly in order of value to scanners:

| Entry | What it gives you |
|---|---|
| `text/mainFiles.txt` | Every main source file with line counts — the cheap way to get the full inventory without walking the tree |
| `text/mainFilesWithHistory.txt` | Same plus first/last change dates — age and activity per file |
| `text/aspect_component_primary_<name>.txt` | Files per component — scope a scan to one component |
| `files.json` | Per-file records (path, lines of code, extension, component) |
| `units.json` / `text/units.txt` | Units (functions/methods) with size and McCabe complexity — the complexity hotspot source. Records use `relativeFileName`, `shortName`, `linesOfCode`, `mcCabeIndex`. **Capped at the top 10,000 units** on large codebases — it is the largest/most complex slice, not the full inventory |
| `executionTimes.txt` / `executionTimes.json` | Sokrates' own stage stopwatch for this analysis (per stage, ms) — the only measured timing a scanner gets; look for analogous self-timing artifacts in the target itself (benchmarks, profiler output, CI timing logs) |
| `duplicates.json` | Duplicated blocks with file/line ranges |
| `contributors.json` / `text/contributors.txt` | Commit counts and dates per contributor email — knowledge-risk input |
| `text/temporal_dependencies_different_folders*.txt` | Folder pairs that change in the same commits — hidden coupling |
| `mainFiles.json`, `testFilesPaths.json`, `buildAndDeploymentFiles.json`, `generatedFilesPaths.json`, `otherFilesPaths.json` | The main/test/build/generated/other split — e.g. build files are prime tech-stack evidence |
| `text/aspect_concern_*` | Files matching each configured concern (e.g. TODOs), including matched text |
| `analysisResults.json` | Everything in one large document (metrics included); prefer the focused files above — this one is several MB |

## Using the data well

- **Prioritize by hotspot, not alphabetically.** Big + complex + recently churned + few contributors = where a deep read pays off. All four signals are in the files above.
- **Scope by component** when the project is large: pick components from config.json, get their file lists from the `aspect_component_*` text files.
- **Cross-reference instead of recomputing.** Don't count lines, find duplicates, or measure complexity yourself — cite Sokrates via `sokrates_refs` and spend AI effort on what the numbers can't say.
- **Check freshness.** Compare the analysis timestamp (file dates in the zip) against the working tree; note in your scan summary if the analysis looks stale.
