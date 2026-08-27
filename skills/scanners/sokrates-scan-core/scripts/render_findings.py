#!/usr/bin/env python3
"""Render Sokrates AI scanner findings as an interactive HTML explorer.

Reads every findings JSON in the ai-insights folder, embeds them into the
explorer template (templates/insights-explorer.html) and writes a single
self-contained index.html next to the JSON files. The explorer is static:
it works from file:// and needs no server, so it must be regenerated after
any scanner writes or changes a findings file.

Usage:
  python3 render_findings.py <findings-or-ai-insights-dir> [-o index.html] [--template path]
  python3 render_findings.py <scanner.json> [...]                  (explicit files)

Given `_sokrates/findings/`, the script descends into its `ai-insights/`
subfolder (creating the explorer there); given the `ai-insights/` folder
itself, it uses it directly. A previous combined-report.json is skipped —
the explorer builds its own cross-scanner views.
"""

import argparse
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "insights-explorer.html"
DEFAULT_ICONS = Path(__file__).resolve().parent.parent / "templates" / "icons"
DEFAULT_SCANNERS_META = Path(__file__).resolve().parent.parent / "templates" / "scanners.json"
INSIGHTS_DIR_NAME = "ai-insights"


def load_docs(paths):
    docs, skipped = [], []
    for path in sorted(paths):
        try:
            doc = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            skipped.append((path, "unreadable or not JSON"))
            continue
        if not isinstance(doc, dict) or "scanner" not in doc or "findings" not in doc:
            skipped.append((path, "not a findings file"))
            continue
        if doc.get("scanner") == "combined":
            skipped.append((path, "combined output (explorer merges itself)"))
            continue
        doc["_file"] = path.name
        attach_visual(doc, path.parent)
        docs.append(doc)
    docs.sort(key=lambda d: d.get("scanner", ""))
    return docs, skipped


def attach_visual(doc, base_dir: Path):
    """Resolve an optional summary_visual (see generate_summary_visuals.py) to a src the
    explorer can show: the relative path when the file exists next to the JSON, else dropped."""
    visual = doc.get("summary_visual")
    if not isinstance(visual, dict) or not visual.get("file"):
        return
    rel = str(visual["file"])
    if not (base_dir / rel).is_file():
        print(f"warning: {doc['_file']}: summary visual {rel} not found, skipping", file=sys.stderr)
        doc.pop("summary_visual", None)
        return
    visual["src"] = rel.replace("\\", "/")


def resolve_inputs(inputs):
    """Return (json paths, output dir) for a directory or explicit files."""
    first = Path(inputs[0])
    if len(inputs) == 1 and first.is_dir():
        target = first
        if first.name != INSIGHTS_DIR_NAME and (first / INSIGHTS_DIR_NAME).is_dir():
            target = first / INSIGHTS_DIR_NAME
        elif first.name != INSIGHTS_DIR_NAME and not list(first.glob("*.json")):
            target = first / INSIGHTS_DIR_NAME
        return list(target.glob("*.json")), target
    paths = [Path(p) for p in inputs]
    return paths, paths[0].parent


def embed_json(docs) -> str:
    # `</script` inside a string would terminate the script block; escape it.
    text = json.dumps(docs, ensure_ascii=False, separators=(",", ":"))
    return text.replace("</", "<\\/")


def load_icons(icons_dir: Path) -> dict:
    """scanner id -> data URI, for every <scanner>.png in the icons folder."""
    icons = {}
    if icons_dir and icons_dir.is_dir():
        for png in sorted(icons_dir.glob("*.png")):
            icons[png.stem] = "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode("ascii")
    return icons


def load_scanners_meta(path: Path) -> list:
    """Display metadata (name, order, emoji, description, group explanations) per scanner."""
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"warning: cannot read scanner metadata {path}: {e}", file=sys.stderr)
        return []
    return doc.get("scanners", []) if isinstance(doc, dict) else []


def render(docs, template_text: str, icons: dict, scanners_meta: list) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Plain replacement of literal tokens; the template contains other `${` in JS.
    return (template_text.replace("${data}", embed_json(docs))
            .replace("${icons}", json.dumps(icons))
            .replace("${scanners}", embed_json(scanners_meta))
            .replace("${generatedAt}", generated))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="findings dir, ai-insights dir, or findings JSON files")
    ap.add_argument("-o", "--output", help="output HTML path (default: <ai-insights>/index.html)")
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE), help="explorer template path")
    ap.add_argument("--icons", default=str(DEFAULT_ICONS), help="folder with <scanner>.png icons to embed")
    ap.add_argument("--scanners-meta", default=str(DEFAULT_SCANNERS_META),
                    help="scanners.json with display names, order, descriptions and group explanations")
    args = ap.parse_args()

    paths, out_dir = resolve_inputs(args.inputs)
    docs, skipped = load_docs(paths)
    for path, reason in skipped:
        print(f"note: skipped {path.name} ({reason})", file=sys.stderr)
    if not docs:
        print(f"error: no findings files found in {out_dir}", file=sys.stderr)
        return 2

    template_path = Path(args.template)
    try:
        template_text = template_path.read_text()
    except OSError as e:
        print(f"error: cannot read template {template_path}: {e}", file=sys.stderr)
        return 2
    for token in ("${data}", "${icons}", "${scanners}", "${generatedAt}"):
        if token not in template_text:
            print(f"error: template lacks placeholder {token}", file=sys.stderr)
            return 2

    out_path = Path(args.output) if args.output else out_dir / "index.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    icons = load_icons(Path(args.icons))
    out_path.write_text(render(docs, template_text, icons, load_scanners_meta(Path(args.scanners_meta))))
    total = sum(len(d.get("findings", [])) for d in docs)
    print(f"wrote {out_path} ({len(docs)} scanners, {total} findings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
