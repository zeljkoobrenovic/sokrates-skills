# Illustrators

Optional scripts that add generated visuals to Sokrates AI scanner results. They are not skills; run them after a scan.

## `generate_summary_visuals.py`

Generates one calm, mostly text-free illustration per scanner summary with Google's Gemini image model ("Nano Banana") and shows it at the end of the foldable **Summary** block on each scanner page of the AI Insights Explorer.

```bash
export GEMINI_API_KEY=...          # GOOGLE_API_KEY also accepted
python3 skills/illustrators/generate_summary_visuals.py path/to/_sokrates/findings/ai-insights
```

For every `<scanner>.json` with a `summary` it:

1. builds a prompt from the scanner's motif, the target name and the summary (style: flat vector, blue/teal/green/orange, a few short key words, no numbers, dates or titles),
2. saves the image as `ai-insights/visuals/<scanner>.png` (or `.jpeg`/`.webp`, whatever the model returns),
3. adds `"summary_visual": {"file": "visuals/<scanner>.png", "credit": ..., "generated_at": ..., "prompt": ...}` to the findings JSON,
4. re-renders `index.html` with `sokrates-scan-core/scripts/render_findings.py`.

An image already on disk is kept (the file, not the JSON field, decides); use `--force` to regenerate. Other options: `--dry-run`, `--only <scanner>` (repeatable), `--model`, `--aspect` (default `16:9`), `--sleep`, `--no-render`.

The explorer links the images by relative path (`visuals/...`), so keep the `visuals` folder next to `index.html`. A `summary_visual` whose file is missing is ignored at render time with a warning; findings files without the field render exactly as before.
