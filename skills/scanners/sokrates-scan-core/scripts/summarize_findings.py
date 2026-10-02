#!/usr/bin/env python3
"""Summarize Sokrates AI scanner findings as short Markdown — for a pull request, a wiki page or a chat.

Reads the findings files of an ai-insights folder (or explicit JSON files), and writes: one badge line
with the severity counts, the findings above info ranked by severity (title, scanner, first evidence
location, the recommendation when there is one), and a table with one row per scanner. The explorer
(render_findings.py) is the place to browse; this is the text to paste.

Usage:
  python3 summarize_findings.py <findings-or-ai-insights-dir | scanner.json ...> [--top 10] [-o summary.md]
  python3 summarize_findings.py <dir> --badge        # only the one-line badge, e.g. for a README
"""

import argparse
import json
import sys
from pathlib import Path

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
CONFIDENCE_ORDER = {"certain": 0, "likely": 1, "possible": 2}
INSIGHTS_DIR_NAME = "ai-insights"


def resolve_inputs(inputs):
    first = Path(inputs[0])
    if len(inputs) == 1 and first.is_dir():
        target = first / INSIGHTS_DIR_NAME if (first / INSIGHTS_DIR_NAME).is_dir() and first.name != INSIGHTS_DIR_NAME else first
        return sorted(target.glob("*.json"))
    return [Path(p) for p in inputs]


def load_docs(paths):
    docs = []
    for path in paths:
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or "scanner" not in doc or "findings" not in doc or doc.get("scanner") == "combined":
            continue
        docs.append(doc)
    return docs


def severity_counts(findings):
    counts = {s: 0 for s in SEVERITY_ORDER}
    for f in findings:
        counts[str(f.get("severity", "info")).lower() if str(f.get("severity", "info")).lower() in counts else "info"] += 1
    return counts


def badge(counts, scanners):
    parts = [f"{n} {s}" for s, n in counts.items() if n and s != "info"]
    text = " · ".join(parts) if parts else "nothing above info"
    return f"AI insights: {text} ({counts['info']} informational) from {scanners} scanner{'s' if scanners != 1 else ''}"


def first_location(finding):
    for e in finding.get("evidence") or []:
        if isinstance(e, dict) and e.get("file"):
            return f"`{e['file']}:{e.get('start_line')}`"
    return ""


def shorten(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def render(docs, top):
    findings = [dict(f, _scanner=doc.get("scanner")) for doc in docs for f in doc.get("findings") or [] if isinstance(f, dict)]
    counts = severity_counts(findings)
    target = next((doc.get("target", {}).get("name") for doc in docs if isinstance(doc.get("target"), dict) and doc["target"].get("name")), "")
    latest = max((str(doc.get("analyzed_at") or "") for doc in docs), default="")
    lines = [f"# AI insights{' — ' + target if target else ''}", "",
             f"**{badge(counts, len(docs))}**" + (f", analyzed {latest[:10]}" if latest else ""), ""]
    attention = [f for f in findings if str(f.get("severity", "info")).lower() != "info"]
    # a stable sort: within one severity and confidence the scanner's own order is kept (scanners order findings deliberately)
    attention.sort(key=lambda f: (SEVERITY_ORDER.get(str(f.get("severity")).lower(), 4), CONFIDENCE_ORDER.get(str(f.get("confidence")).lower(), 2)))
    if attention:
        lines.append(f"## Needs attention ({min(top, len(attention))} of {len(attention)})")
        lines.append("")
        for f in attention[:top]:
            where = first_location(f)
            rec = shorten(f.get("recommendation", ""), 200)
            lines.append(f"- **{shorten(f.get('title', f.get('id', '')), 120)}** — {f.get('severity')}, {f.get('_scanner')}" +
                         (f", {where}" if where else "") + (f". {rec}" if rec else ""))
        lines.append("")
    lines.append("## Scanners")
    lines.append("")
    lines.append("| scanner | findings | above info | analyzed |")
    lines.append("| --- | ---: | ---: | --- |")
    for doc in sorted(docs, key=lambda d: d.get("scanner", "")):
        fs = [f for f in doc.get("findings") or [] if isinstance(f, dict)]
        above = sum(1 for f in fs if str(f.get("severity", "info")).lower() != "info")
        lines.append(f"| {doc.get('scanner')} | {len(fs)} | {above} | {str(doc.get('analyzed_at') or '')[:10]} |")
    lines.append("")
    return "\n".join(lines), counts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="findings dir, ai-insights dir, or findings JSON files")
    ap.add_argument("--top", type=int, default=10, help="findings above info to list (default 10)")
    ap.add_argument("--badge", action="store_true", help="print only the one-line badge")
    ap.add_argument("-o", "--output", help="write the Markdown here instead of stdout")
    args = ap.parse_args()
    docs = load_docs(resolve_inputs(args.inputs))
    if not docs:
        print("error: no findings files among the inputs", file=sys.stderr)
        return 1
    text, counts = render(docs, args.top)
    if args.badge:
        print(badge(counts, len(docs)))
        return 0
    if args.output:
        Path(args.output).write_text(text)
        print(f"wrote {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
