# Examples

## `codex/` — OpenAI Codex, all nine scanners

The AI Insights Explorer for [openai/codex](https://github.com/openai/codex) as analysed on 2026-08-25
(Rust workspace, ~800k main LOC, 9,545 commits): open `codex/ai-insights/index.html` in a browser.

- `index.html` — the self-contained explorer (all findings embedded, works from `file://`)
- `<scanner>-scan.json` — the findings of each scanner, in the shared format defined by
  `skills/scanners/sokrates-scan-core/schema/findings.schema.json`; 191 findings in total,
  every evidence citation verified against the source tree at analysis time

The evidence paths (`target.src_root`) point at the Codex checkout the analysis was made on and do
not resolve inside this repository; clone Codex next to it to re-validate with `validate_findings.py`.
