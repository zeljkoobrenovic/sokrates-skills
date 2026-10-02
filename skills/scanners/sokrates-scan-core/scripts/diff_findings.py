#!/usr/bin/env python3
"""Diff two runs of the same Sokrates AI scanner: new / resolved / persisting.

Relies on the stable-id contract (<scanner>/<group>/<slug> stays constant for
the same logical finding across runs). Reports findings that appeared,
disappeared, persisted, and — among persisting ones — severity or confidence
changes. Exits 1 if anything changed (usable as a CI signal), 0 if identical.

Usage:
  python3 diff_findings.py <old.json> <new.json> [-o diff.txt] [--fail-on low|medium|high|critical]

Without -o, prints the diff to stdout. --fail-on <severity> is the CI gate: exit 3 when a NEW
finding, or a persisting one whose severity rose, is at that severity or above; resolved and
unchanged findings never fail a build. Exit codes: 0 identical, 1 changed, 2 bad input, 3 gate fired.
"""

import argparse
import json
import sys
from pathlib import Path

# Deliberately duplicated across render/merge/diff: each script stays a single
# standalone file that can be copied or invoked in isolation.
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
SEVERITY_BADGE = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "info": "⚪"}


def load(path: Path) -> dict:
    doc = json.loads(path.read_text())
    if "scanner" not in doc or "findings" not in doc:
        raise ValueError(f"{path} is not a findings file")
    return doc


def by_id(doc):
    result = {}
    for f in doc.get("findings", []):
        fid = f.get("id", "")
        if fid in result:
            print(f"warning: duplicate id {fid}", file=sys.stderr)
        result[fid] = f
    return result


def line(f, prefix=""):
    badge = SEVERITY_BADGE.get(f.get("severity"), "")
    return f"- {prefix}{badge} **{f.get('severity')}** `{f.get('id')}` — {f.get('title')}"


def render(old_doc, new_doc) -> tuple[str, bool]:
    old, new = by_id(old_doc), by_id(new_doc)
    new_ids = [i for i in new if i not in old]
    resolved_ids = [i for i in old if i not in new]
    persisting_ids = [i for i in new if i in old]

    changed = []
    for i in persisting_ids:
        deltas = []
        for field in ("severity", "confidence"):
            if old[i].get(field) != new[i].get(field):
                deltas.append(f"{field} {old[i].get(field)} → {new[i].get(field)}")
        if deltas:
            changed.append((i, deltas))

    out = [f"# Findings diff — {new_doc.get('scanner')} on "
           f"{new_doc.get('target', {}).get('name', '?')}", ""]
    out.append(f"old: {old_doc.get('analyzed_at')} ({len(old)} findings) → "
               f"new: {new_doc.get('analyzed_at')} ({len(new)} findings)")
    if old_doc.get("scanner") != new_doc.get("scanner"):
        out.append("")
        out.append(f"**warning:** comparing different scanners "
                   f"(`{old_doc.get('scanner')}` vs `{new_doc.get('scanner')}`)")
    out.append("")
    out.append(f"**{len(new_ids)} new · {len(resolved_ids)} resolved · "
               f"{len(persisting_ids)} persisting ({len(changed)} changed)**")
    out.append("")

    if new_ids:
        out.append("## New")
        out.append("")
        for i in sorted(new_ids, key=lambda i: (SEVERITY_ORDER.get(new[i].get("severity"), 9), i)):
            out.append(line(new[i]))
        out.append("")
    if resolved_ids:
        out.append("## Resolved")
        out.append("")
        for i in sorted(resolved_ids, key=lambda i: (SEVERITY_ORDER.get(old[i].get("severity"), 9), i)):
            out.append(line(old[i]))
        out.append("")
    if changed:
        out.append("## Changed (persisting)")
        out.append("")
        for i, deltas in sorted(changed):
            out.append(line(new[i]) + f" ({'; '.join(deltas)})")
        out.append("")
    if not (new_ids or resolved_ids or changed):
        out.append("No changes: every finding persists with the same severity and confidence.")
        out.append("")

    has_changes = bool(new_ids or resolved_ids or changed)
    return "\n".join(out), has_changes


def gate(old_doc, new_doc, threshold_name):
    """The findings that trip a --fail-on gate: new at or above the threshold, or persisting with a severity that rose to it."""
    threshold = SEVERITY_ORDER[threshold_name]
    old_by, new_by = by_id(old_doc), by_id(new_doc)
    tripped = []
    for fid, f in new_by.items():
        sev = SEVERITY_ORDER.get(str(f.get("severity", "info")).lower(), 4)
        if sev > threshold:
            continue
        if fid not in old_by:
            tripped.append(f"new {f.get('severity')}: {fid}")
        elif SEVERITY_ORDER.get(str(old_by[fid].get("severity", "info")).lower(), 4) > sev:
            tripped.append(f"{old_by[fid].get('severity')} -> {f.get('severity')}: {fid}")
    return tripped


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("-o", "--output", help="Write the (markdown-formatted) text here instead of stdout")
    ap.add_argument("--fail-on", choices=["low", "medium", "high", "critical"],
                    help="exit 3 when a new finding, or a persisting one whose severity rose, is at this severity or above (a CI gate)")
    args = ap.parse_args()
    try:
        old_doc, new_doc = load(Path(args.old)), load(Path(args.new))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    text, has_changes = render(old_doc, new_doc)
    if args.output:
        Path(args.output).write_text(text)
        print(f"wrote {args.output}")
    else:
        print(text)
    if args.fail_on:
        tripped = gate(old_doc, new_doc, args.fail_on)
        if tripped:
            print(f"\nGATE: {len(tripped)} finding(s) at {args.fail_on} or above are new or escalated:", file=sys.stderr)
            for t in tripped:
                print(f"  {t}", file=sys.stderr)
            return 3
    return 1 if has_changes else 0


if __name__ == "__main__":
    sys.exit(main())
