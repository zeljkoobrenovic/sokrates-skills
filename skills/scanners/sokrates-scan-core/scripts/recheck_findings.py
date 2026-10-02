#!/usr/bin/env python3
"""Re-check findings against the current tree without re-running the scanner.

After code changed (a fix, a refactoring, an improve-skill run), each finding's cited evidence is in one
of three states:
  intact   every snippet is still at its cited lines — the code the finding describes has not changed,
           so the finding stands; no scanner or agent is needed to say so
  moved    the snippets are still in the file, at other lines — only line numbers drifted;
           --fix-lines rewrites them in place and the finding stands
  gone     a snippet (or its file) is no longer there — the cited code changed; whether the finding is
           resolved, partly resolved or merely reworded needs judgment: that is the scoped re-check
           an agent runs on exactly these ids (--prompt prints the brief for it)

Usage:
  python3 recheck_findings.py <findings.json | ai-insights dir> [--ids ID ...] [--src-root <path>]
                              [--fix-lines] [--prompt] [--json out.json]

Exit codes: 0 = nothing gone (after --fix-lines nothing to do), 1 = some findings need the scoped re-check,
2 = bad invocation. Standard library only.
"""

import argparse
import json
import re
import sys
from pathlib import Path

EVIDENCE_KEYS = ("file", "start_line", "end_line", "snippet")


def norm(text):
    return re.sub(r"\s+", " ", text).strip()


def load_lines(src_root, cache, rel):
    if rel not in cache:
        try:
            cache[rel] = [ln.rstrip("\r") for ln in (src_root / rel).read_text(errors="replace").split("\n")]
        except OSError:
            cache[rel] = None
    return cache[rel]


def locate(lines, snippet, start, end):
    """Where the snippet is now: ("intact", start, end), ("moved", new_start, new_end) or ("gone", None, None)."""
    wanted = norm(snippet)
    span = max(0, end - start)
    if 1 <= start <= end <= len(lines) and wanted in norm(" ".join(lines[start - 1:end])):
        return "intact", start, end
    first = norm(snippet.strip().splitlines()[0]) if snippet.strip() else ""
    if not first:
        return "gone", None, None
    for n, line in enumerate(lines, 1):
        if first in norm(line) and wanted in norm(" ".join(lines[n - 1:n + span])):
            return "moved", n, n + span
    return "gone", None, None


def recheck_doc(doc, src_root, ids, fix_lines):
    cache = {}
    results = []
    changed = 0
    for finding in doc.get("findings") or []:
        if not isinstance(finding, dict) or (ids and finding.get("id") not in ids):
            continue
        states, details = [], []
        for ev in finding.get("evidence") or []:
            if not isinstance(ev, dict) or any(k not in ev for k in EVIDENCE_KEYS):
                continue
            lines = load_lines(src_root, cache, ev["file"])
            if lines is None:
                states.append("gone")
                details.append(f"{ev['file']}: file not found")
                continue
            state, start, end = locate(lines, str(ev["snippet"]), int(ev["start_line"]), int(ev["end_line"]))
            states.append(state)
            if state == "moved":
                details.append(f"{ev['file']}: {ev['start_line']}-{ev['end_line']} -> {start}-{end}")
                if fix_lines:
                    ev["start_line"], ev["end_line"] = start, end
                    changed += 1
            elif state == "gone":
                details.append(f"{ev['file']}:{ev['start_line']}-{ev['end_line']}: snippet no longer in the file")
        overall = "no-evidence" if not states else ("gone" if "gone" in states else ("moved" if "moved" in states else "intact"))
        results.append({"id": finding.get("id"), "severity": finding.get("severity"), "state": overall, "details": details})
    return results, changed


def prompt_for(doc_path, ids):
    ids_text = "\n".join(f"  - {i}" for i in ids)
    return f"""Re-check mode (sokrates-scan-core): the code cited by these findings in {doc_path} changed.
Load the sokrates-scan-core skill and the scanner's skill named in the file, then re-verify ONLY these findings:
{ids_text}
For each one, read the cited files as they are now and decide: resolved (the recommendation is implemented or
the described situation no longer exists) -> remove the finding; partly resolved -> keep its id, lower the
severity, rewrite description and evidence against the current code; unresolved -> keep it, with evidence
pointing at the current lines. Do not touch other findings. Then refresh the file's `summary` and `stats` so
they describe the findings that remain, update `analyzed_at`, run validate_findings.py (must pass) and
render_findings.py. Do not modify source files. Finish with one line per id: resolved / partly / unresolved, and why."""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="a findings file, or an ai-insights folder (every scanner file in it)")
    ap.add_argument("--ids", nargs="*", default=[], help="only these finding ids (default: all)")
    ap.add_argument("--src-root", help="directory the evidence paths are relative to (default: target.src_root of each file)")
    ap.add_argument("--fix-lines", action="store_true", help="rewrite the line numbers of moved evidence in place")
    ap.add_argument("--prompt", action="store_true", help="print the brief for the scoped agent re-check of the findings whose evidence is gone")
    ap.add_argument("--json", help="write the per-finding states here")
    args = ap.parse_args()
    target = Path(args.target)
    if target.is_dir():
        paths = sorted(p for p in target.glob("*.json") if p.name != "combined-report.json")
    elif target.is_file():
        paths = [target]
    else:
        print(f"error: {target} does not exist", file=sys.stderr)
        return 2
    ids = set(args.ids)
    report = []
    gone_total = 0
    for path in paths:
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError) as e:
            print(f"note: skipped {path.name} ({e})", file=sys.stderr)
            continue
        if not isinstance(doc, dict) or "findings" not in doc or doc.get("scanner") == "combined":
            continue
        if args.src_root:
            src_root = Path(args.src_root)
        else:
            declared = doc.get("target", {}).get("src_root") if isinstance(doc.get("target"), dict) else None
            if not declared:
                print(f"error: {path.name}: no --src-root given and no target.src_root in the file", file=sys.stderr)
                return 2
            src_root = (path.parent / declared).resolve()
        if not src_root.is_dir():
            print(f"error: src root is not a directory: {src_root}", file=sys.stderr)
            return 2
        results, changed = recheck_doc(doc, src_root, ids, args.fix_lines)
        if changed:
            path.write_text(json.dumps(doc, indent=2) + "\n")
        gone = [r["id"] for r in results if r["state"] == "gone"]
        gone_total += len(gone)
        counts = {s: sum(1 for r in results if r["state"] == s) for s in ("intact", "moved", "gone", "no-evidence")}
        print(f"{path.name}: {len(results)} findings — {counts['intact']} intact, {counts['moved']} moved, {counts['gone']} gone, {counts['no-evidence']} without evidence"
              + (f"; {changed} evidence line ranges rewritten" if changed else ""))
        for r in results:
            if r["state"] in ("moved", "gone"):
                print(f"  {r['state']:<6} {r['id']}")
                for d in r["details"]:
                    print(f"         {d}")
        if gone and args.prompt:
            print("\n" + prompt_for(path, gone) + "\n")
        report.append({"file": str(path), "results": results, "evidence_lines_rewritten": changed})
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))
    if gone_total:
        print(f"\n{gone_total} finding(s) cite code that changed — run the scoped re-check (--prompt prints the brief) before calling them resolved.")
    return 1 if gone_total else 0


if __name__ == "__main__":
    sys.exit(main())
