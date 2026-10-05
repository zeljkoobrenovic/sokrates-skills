# Scanner icons

One PNG per scanner, named `<scanner-id>.png` (e.g. `cicd-scan.png`). `render_findings.py`
embeds every file in this folder into the explorer as a data URI; a scanner without a PNG falls
back to an emoji. Recommended: square, transparent background, 128–256 px. The current files are
generated placeholders — replace them with real artwork.

Sokrates bundles a copy of this folder and of `../scanners.json` (in its repository:
`reports/src/main/resources/ai-insights/`) to render the findings in its own report; when adding or
renaming a scanner, update that copy too.
