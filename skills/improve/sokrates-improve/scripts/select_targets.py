#!/usr/bin/env python3
"""Rank improvement targets from a repository's Sokrates analysis.

Deterministic shortlist for the sokrates-improve skill; the agent picks one target and changes the
code, measure.py proves the effect. Kinds:
  units       the most complex / longest units in main code           -> unit:<file>#<name>
  duplicates  the duplicated blocks costing the most lines             -> duplicate:<index>
  hotspots    main files that are big and change often                 -> hotspot:<path>
  findings    AI scanner findings above info that carry a recommendation -> finding:<id>

Every target carries an `effort` (small / medium / large, from how much code it touches); findings are
ordered by priority — the biggest severity for the smallest change first — unless --order severity.

Usage:
  python3 select_targets.py [--sokrates _sokrates] [--kind all|units|duplicates|hotspots|findings]
                            [--top 10] [--json out.json]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sokrates_data import SokratesData, severity_rank, is_test_path  # noqa: E402


def effort_of_lines(lines, files=1):
    """A rough size of the change, from how much code it touches: small (one sitting), medium (an afternoon), large (a real project)."""
    if files <= 2 and lines <= 40:
        return "small"
    if files <= 4 and lines <= 150:
        return "medium"
    return "large"


EFFORT_RANK = {"small": 0, "medium": 1, "large": 2}


def with_effort(target, effort):
    target["effort"] = effort
    target["why"] += f"; effort {effort}"
    return target


def unit_targets(data, main, top):
    units = [u for u in data.units() if u.get("relativeFileName") in main]
    units.sort(key=lambda u: (-int(u.get("mcCabeIndex", 0)), -int(u.get("linesOfCode", 0))))
    out = []
    for u in units[:top]:
        out.append(with_effort({"id": f"unit:{u['relativeFileName']}#{u.get('shortName', '')}", "kind": "unit",
                    "file": u["relativeFileName"], "name": u.get("shortName", ""), "lines": f"{u.get('startLine')}-{u.get('endLine')}",
                    "mcCabe": int(u.get("mcCabeIndex", 0)), "loc": int(u.get("linesOfCode", 0)),
                    "why": f"McCabe {u.get('mcCabeIndex', 0)}, {u.get('linesOfCode', 0)} lines",
                    "action": "extract branches into helpers, replace condition chains with a table or polymorphism, split by responsibility"},
                    effort_of_lines(int(u.get("linesOfCode", 0)))))
    return out


def duplicate_targets(data, main, top):
    dups = data.duplicates()
    scored = []
    for index, d in enumerate(dups):
        files = [f for f in d["files"] if f in main]
        if len(files) < 2:
            continue
        copies = len(d["files"])
        cost = d["blockSize"] * (copies - 1)
        scored.append((cost, index, d, copies))
    scored.sort(key=lambda t: (-t[0], t[1]))
    out = []
    for cost, index, d, copies in scored[:top]:
        places = [f"{b.get('file', {}).get('relativePath', '')}:{b.get('startLine')}-{b.get('endLine')}" for b in d["blocks"]]
        out.append(with_effort({"id": f"duplicate:{index}", "kind": "duplicate", "blockSize": d["blockSize"], "copies": copies,
                    "duplicatedLines": cost, "files": sorted(set(d["files"])), "places": places,
                    "why": f"{d['blockSize']} identical lines in {copies} places ({cost} redundant lines)",
                    "action": "one implementation (function, class, template, data file) called from every copy"},
                    effort_of_lines(d["blockSize"] * copies, len(set(d["files"])))))
    return out


def hotspot_targets(data, main, top):
    history = data.files_with_history()
    max_mccabe, max_unit = {}, {}
    for u in data.units():
        f = u.get("relativeFileName")
        max_mccabe[f] = max(max_mccabe.get(f, 0), int(u.get("mcCabeIndex", 0)))
        max_unit[f] = max(max_unit.get(f, 0), int(u.get("linesOfCode", 0)))
    scored = []
    for path, h in history.items():
        if path not in main or is_test_path(path):
            continue
        commits = h["commits90"] or h["commits"]
        if h["loc"] < 200 or commits == 0:
            continue
        score = h["loc"] * commits * (1 + max_mccabe.get(path, 0) / 25.0)
        scored.append((score, path, h))
    scored.sort(key=lambda t: (-t[0], t[1]))
    out = []
    for score, path, h in scored[:top]:
        out.append(with_effort({"id": f"hotspot:{path}", "kind": "hotspot", "file": path, "loc": h["loc"], "commits": h["commits"],
                    "commits90": h["commits90"], "contributors": h["contributors"], "maxMcCabe": max_mccabe.get(path, 0),
                    "longestUnit": max_unit.get(path, 0), "score": round(score),
                    "why": f"{h['loc']} lines, {h['commits90']} commits in 90 days ({h['commits']} overall), max McCabe {max_mccabe.get(path, 0)}",
                    "action": "split the file along its responsibilities so future changes touch a smaller file"},
                    "large"))
    return out


def finding_effort(finding):
    """From what the evidence cites: how many files and how many lines. A finding with a stated `effort` keeps it."""
    stated = str(finding.get("effort", "")).lower()
    if stated in EFFORT_RANK:
        return stated
    evidence = [e for e in finding.get("evidence") or [] if isinstance(e, dict)]
    files = {e.get("file") for e in evidence if e.get("file")}
    lines = sum(max(1, int(e.get("end_line", 0) or 0) - int(e.get("start_line", 0) or 0) + 1) for e in evidence)
    if not evidence:
        return "large"      # nothing concrete to change at — a design-level finding
    return effort_of_lines(lines, len(files))


def finding_targets(data, top, order="priority"):
    findings = [f for f in data.findings() if severity_rank(f.get("severity")) < 4 and str(f.get("recommendation", "")).strip()]
    for f in findings:
        f["_effort"] = finding_effort(f)
    if order == "severity":
        findings.sort(key=lambda f: (severity_rank(f.get("severity")), EFFORT_RANK[f["_effort"]], f.get("scanner", ""), f.get("id", "")))
    else:   # priority: the biggest severity for the smallest change first
        findings.sort(key=lambda f: (severity_rank(f.get("severity")) + EFFORT_RANK[f["_effort"]], severity_rank(f.get("severity")), f.get("scanner", ""), f.get("id", "")))
    out = []
    for f in findings[:top]:
        evidence = f.get("evidence") or []
        where = [f"{e.get('file')}:{e.get('start_line')}-{e.get('end_line')}" for e in evidence if isinstance(e, dict)]
        out.append(with_effort({"id": f"finding:{f.get('id', '')}", "kind": "finding", "scanner": f.get("scanner"), "severity": f.get("severity"),
                    "confidence": f.get("confidence"), "title": f.get("title", ""), "evidence": where,
                    "why": f"{f.get('severity')} finding of {f.get('scanner')}: {f.get('title', '')}",
                    "action": str(f.get("recommendation", "")).strip()}, f["_effort"]))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sokrates", default="_sokrates", help="the repository's _sokrates folder (default: _sokrates)")
    parser.add_argument("--kind", default="all", choices=["all", "units", "duplicates", "hotspots", "findings"])
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--order", default="priority", choices=["priority", "severity"],
                        help="findings: priority (default) = the biggest severity for the smallest change first; severity = strictly by severity")
    parser.add_argument("--json", help="also write the shortlist as JSON")
    args = parser.parse_args()
    try:
        data = SokratesData(args.sokrates)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    main_paths = data.main_paths()
    kinds = ["units", "duplicates", "hotspots", "findings"] if args.kind == "all" else [args.kind]
    result = {}
    for kind in kinds:
        if kind == "units":
            result[kind] = unit_targets(data, main_paths, args.top)
        elif kind == "duplicates":
            result[kind] = duplicate_targets(data, main_paths, args.top)
        elif kind == "hotspots":
            result[kind] = hotspot_targets(data, main_paths, args.top)
        else:
            result[kind] = finding_targets(data, args.top, args.order)
    for kind, targets in result.items():
        print(f"\n== {kind} ({len(targets)})")
        if not targets:
            print("   none" + (" (no reports/ai-insights findings with a recommendation)" if kind == "findings" else ""))
        for i, t in enumerate(targets, 1):
            print(f"{i:3d}. {t['id']}")
            print(f"     {t['why']}")
            if t["kind"] == "duplicate":
                for place in t["places"][:4]:
                    print(f"       - {place}")
                if len(t["places"]) > 4:
                    print(f"       - … {len(t['places']) - 4} more")
            elif t["kind"] == "finding" and t["evidence"]:
                print(f"       at {', '.join(t['evidence'][:3])}")
            print(f"     -> {t['action']}")
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))
        print(f"\nshortlist written to {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
