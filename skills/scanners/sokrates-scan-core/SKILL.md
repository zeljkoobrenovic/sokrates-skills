---
name: sokrates-scan-core
description: Shared foundation for all Sokrates AI scanner skills. Defines the common findings output format (grouped findings with file/line evidence), the evidence rules that keep scanners honest, how to read an existing Sokrates analysis (_sokrates folder), and the validate/render scripts every scanner must run. Load this whenever you are running any *-scan skill on a codebase with a Sokrates analysis, writing a new scanner skill, or asked to validate/render/merge scanner findings files.
---

# Sokrates scan core

Sokrates (sokrates.dev) produces a quantitative analysis of a codebase: file inventory, components, duplication, unit size, complexity, churn, contributors, temporal coupling. AI scanner skills add the *semantic* layer on top — what the code means, which technologies it uses, where the real risks are.

This skill is the contract all scanners share. It exists so that:

- every scanner produces the **same output shape**, so reports, diffs, and dashboards can be built once;
- every finding carries **verifiable evidence** (file + line + verbatim fragment), so a script — not trust — decides whether a finding is grounded;
- scanners **build on the Sokrates data** instead of re-deriving what it already measured.

## Where things live

For a project analyzed by Sokrates, expect this layout (the analysis root may also sit next to the source instead of inside it):

```
<project>/
├── ... source code ...
└── _sokrates/
    ├── config.json          # project name, srcRoot, extensions, ignores, components
    ├── findings/
    │   └── ai-insights/     # <- scanner output goes here (JSON per scanner + index.html explorer)
    └── reports/
        ├── data/data.zip    # machine-readable analysis (json + text exports)
        └── html/            # human reports
```

Scanners write one file per run into `_sokrates/findings/ai-insights/`:

- `<scanner-name>.json` — the findings, conforming to `schema/findings.schema.json`

and then regenerate the shared **`index.html`** in the same folder — the AI Insights Explorer, a self-contained interactive HTML page (built from `templates/insights-explorer.html`) that embeds every scanner's JSON in the folder: overview tiles, per-scanner pages, cross-scanner attention list, severity/confidence/group filters, full-text search, evidence citations, deep links per finding. It is the human-facing report; **no markdown reports are produced** (never hand-write one either).

## Scanner workflow (every scanner follows this)

1. **Orient with Sokrates data first.** Read `_sokrates/config.json` for the project name, `srcRoot`, extensions, ignore rules, and logical components. Use ignore rules to skip vendored/generated code. See `references/sokrates-data-guide.md` for what else is available (hotspots, churn, contributors) and how to unzip `data.zip` — spend your reading budget where Sokrates points.
2. **Scan.** Do the scanner-specific work (its own SKILL.md defines it). While scanning, record evidence *as you read it*: exact file path, line numbers, verbatim fragment. Never reconstruct evidence from memory afterwards — that is how hallucinated line numbers happen.
3. **Write findings JSON** to `_sokrates/findings/ai-insights/<scanner>.json` following the format below (create the folder if missing).
4. **Validate** (mandatory — a scan is not finished until this passes):
   ```bash
   python3 <core-skill-path>/scripts/validate_findings.py _sokrates/findings/ai-insights/<scanner>.json
   ```
   (The validator resolves the source root from `target.src_root` in the file; `--src-root` overrides it.)
   On errors, fix the findings: re-read the file to correct line numbers/snippets, or if the evidence cannot be located, downgrade the finding to `confidence: possible` with empty evidence, or drop it. Re-run until it reports OK.
5. **Render** the explorer (regenerates `index.html` from *all* JSON files in the folder, so other scanners' results stay included):
   ```bash
   python3 <core-skill-path>/scripts/render_findings.py _sokrates/findings/ai-insights/
   ```
   The page is static and embeds the data, so it must be re-rendered after every change to any findings file.
6. **Report to the user**: lead with the summary and attention items (severity above info), mention the validation result ("N/N findings verified"), the findings file path, and the explorer path (`_sokrates/findings/ai-insights/index.html`, open in a browser). If the project's Sokrates report does not yet embed the explorer, mention the one-time command that adds it as a tab of the main report: `java -jar sokrates.jar addCustomTab -label "AI Insights*" -iframeLink "../../findings/ai-insights/index.html"` (run in the project folder; the tab then follows every re-render). Older Sokrates builds lack `addCustomTab` — if you have verified the installed CLI does not offer it, skip the suggestion rather than recommend a command you know is missing.

### Composing and comparing runs

Two more scripts operate on finished findings files; run them when asked for a combined report or a re-scan comparison (they need no LLM judgment — never hand-write their output):

- **Merge** — one roll-up across all scanners of a project:
  ```bash
  python3 <core-skill-path>/scripts/merge_findings.py _sokrates/findings/ai-insights/ [-o combined-report.json]
  ```
  Writes `combined-report.json` — a findings document with `scanner: "combined"` concatenating all findings, so the standard tooling composes (validate re-verifies every citation in one pass; diff compares two merged runs). Merged findings keep their original `<source-scanner>/<group>/<slug>` ids — the validator accepts that for `scanner: "combined"` only. Re-merging a directory skips a previous combined output, and the explorer skips it too (it builds its own cross-scanner views from the individual files), so the combined JSON is purely a machine artifact.
- **Diff** — compare two runs of the *same* scanner; relies on the stable-id contract, which is why ids must derive from the subject, not wording. When a previous findings file exists, preserve it before overwriting (e.g. rename with its `analyzed_at` date), then compare:
  ```bash
  python3 <core-skill-path>/scripts/diff_findings.py old.json new.json [-o diff.txt]
  ```
  Reports new / resolved / persisting findings and severity/confidence changes; exit code 1 when anything changed (usable as a CI gate), 0 when identical. Include the diff summary when reporting to the user — "2 new, 1 resolved since 2026-08-24" is often the headline.

## Findings format

Full schema: `schema/findings.schema.json`. Shape:

```json
{
  "scanner": "tech-stack-scan",
  "scanner_version": "1.0",
  "analyzed_at": "2026-08-24T10:00:00Z",
  "target": { "name": "Codex", "src_root": "../..", "commit": "abc123..." },
  "summary": "One-paragraph narrative of what the scan found.",
  "stats": { "any_scanner_specific": "aggregates" },
  "findings": [
    {
      "id": "tech-stack-scan/frameworks/tokio",
      "group": "frameworks",
      "title": "Tokio async runtime",
      "description": "Self-contained explanation of what was found and why it matters.",
      "severity": "info",
      "confidence": "certain",
      "evidence": [
        { "file": "codex-rs/Cargo.toml", "start_line": 24, "end_line": 24,
          "snippet": "tokio = { version = \"1\", features = [\"full\"] }",
          "note": "workspace dependency declaration" }
      ],
      "recommendation": "Only when severity is above info.",
      "tags": ["rust", "async"],
      "sokrates_refs": ["component:codex_rs"],
      "attributes": { "version": "1.x" }
    }
  ]
}
```

### Field semantics

- **summary / description / recommendation** — plain prose, one idea per sentence (the explorer renders each sentence as a bullet). Mark the two or three *key phrases* of a paragraph with `**double asterisks**` and identifiers with `` `backticks` ``; the explorer renders these as bold / inline code (no other markdown is interpreted). Quantities ("168 findings", "42%") are emphasised automatically.

- **target.src_root** — path to the analyzed source root, *relative to the directory containing the findings file*. From `_sokrates/findings/ai-insights/` with the analysis inside the project, that is `../../..`. Everything in `evidence[].file` is relative to this root; the validator resolves it the same way. (Note: this is not the same as `srcRoot` in Sokrates' config.json, which is relative to the config file.)
- **analyzed_at** — ISO-8601, UTC. A date-only value like `2026-08-24` is acceptable when the exact time doesn't matter.
- **id** — `<scanner>/<group>/<slug>`, stable across runs of the same scanner on the same project. Stable ids make re-runs diffable (new / resolved / persisting). Derive the slug from the *subject* (e.g. the library name), never from wording or position.
- **group** — the clustering key for reports. Each scanner defines its own group taxonomy in its SKILL.md; stick to it rather than inventing groups per run.
- **severity** — `info` means "neutral fact worth knowing" (most inventory findings). Reserve `low`–`critical` for things that call for action; then also fill `recommendation`.
- **confidence** — `certain`: directly evidenced (declared in a manifest, unambiguous in code). `likely`: strong indirect signals. `possible`: inference. A finding without evidence must be `possible` — *unless* it is wholly grounded in Sokrates data via `sokrates_refs` (a bus-factor overview, a duplication statistic); such pure-metric findings carry the confidence the data supports.
- **evidence** — 1–3 *representative* citations per finding, each ≤ 5 lines. One finding per subject with representative evidence, not one finding per occurrence. `file` is relative to `target.src_root`.
- **sokrates_refs** — link findings back into the Sokrates world where natural: `component:<name>`, `file:<path>`, `concern:<name>`, `metric:<name>`. Canonical metric names (snake_case; use these rather than inventing variants, so refs compare across scanners and runs): `metric:loc`, `metric:mccabe`, `metric:unit_size`, `metric:duplication`, `metric:churn`, `metric:commits`, `metric:commits_30d`, `metric:commits_90d`, `metric:commits_365d`, `metric:contributors`, `metric:contributor_share`, `metric:temporal_coupling`, `metric:file_age`, `metric:hotspot_score`.

### Evidence rules (the honesty contract)

Every claim a reader might act on needs evidence they can jump to. The validator mechanically checks that each snippet occurs at the cited lines of the cited file — treat a validation failure as "this finding may be hallucinated", not as a formality. If you find yourself unable to cite evidence for a finding, that is information: mark it `possible` or drop it.

Practical notes on snippets:

- **Prefer single-line snippets.** A multi-line snippet must be verbatim and contiguous — it has to include *everything* between the first and last cited line (comment prefixes included), which is easy to get wrong. Two single-line evidence entries beat one fragile multi-line one.
- **Numbers from Sokrates metrics** (line counts, percentages, complexity scores) cannot be file/line evidence. Put them in the description, reference them via `sokrates_refs` (`metric:...`), and cite something real in the tree as evidence (a manifest, a toolchain file) — or mark the finding `possible`.

## Severity calibration across scanners

So reports compose, all scanners use the same scale: `critical` = actively dangerous or broken (leaked secret, known-exploited dependency); `high` = significant risk needing near-term action; `medium` = should be addressed, not urgent; `low` = worth knowing, minor; `info` = inventory/observation. When unsure between two levels, pick the lower one — inflated severity erodes trust in the whole report.
