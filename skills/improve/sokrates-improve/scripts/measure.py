#!/usr/bin/env python3
"""Measure an improvement target before and after a change, from the Sokrates analysis.

  snapshot  --target <id> [--sokrates _sokrates] -o before.json
            the target's numbers now, plus the repository totals; after the change (and
            `sokrates generateReports`) take a second snapshot with the same --target, or with
            --like before.json to reuse the target definition (a duplicate:<index> changes index
            between runs; --like keeps the files it referred to).
  compare   before.json after.json [--markdown]
            the before/after table and the verdict: improved / unchanged / worse / not found.
            Exit code 0 = improved, 1 = unchanged or worse, 2 = target not found after the change.

Target ids come from select_targets.py: unit:<file>#<name>, duplicate:<index>, hotspot:<path>,
finding:<finding id>.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sokrates_data import SokratesData, severity_rank  # noqa: E402


def totals(data):
    units = data.units()
    dup_lines = sum(d["blockSize"] * (len(d["files"]) - 1) for d in data.duplicates())
    metrics = data.metrics()
    return {
        "mainLinesOfCode": metrics.get("LINES_OF_CODE_MAIN"),
        "units": len(units),
        "unitsOver100Lines": sum(1 for u in units if int(u.get("linesOfCode", 0)) > 100),
        "unitsMcCabeOver25": sum(1 for u in units if int(u.get("mcCabeIndex", 0)) > 25),
        "unitsMcCabeOver10": sum(1 for u in units if int(u.get("mcCabeIndex", 0)) > 10),
        "duplicatedLines": dup_lines,
    }


def same_file(exported, wanted):
    """Exported paths may carry a leading folder (e.g. the repository folder) depending on how Sokrates was invoked."""
    return exported == wanted or exported.endswith("/" + wanted) or wanted.endswith("/" + exported)


def measure_unit(data, file, name):
    candidates = [u for u in data.units() if same_file(u.get("relativeFileName", ""), file) and u.get("shortName") == name]
    if not candidates:
        return {"found": False}
    u = max(candidates, key=lambda x: (int(x.get("mcCabeIndex", 0)), int(x.get("linesOfCode", 0))))
    return {"found": True, "mcCabe": int(u.get("mcCabeIndex", 0)), "loc": int(u.get("linesOfCode", 0)),
            "lines": f"{u.get('startLine')}-{u.get('endLine')}", "unitsInFile": len([x for x in data.units() if x.get("relativeFileName") == file])}


def measure_duplicate_files(data, files):
    files = set(files)
    lines, blocks = 0, 0
    for d in data.duplicates():
        if any(f in files for f in d["files"]):
            lines += d["blockSize"] * (len(d["files"]) - 1)
            blocks += 1
    return {"found": True, "duplicatedLines": lines, "duplicateBlocks": blocks, "files": sorted(files)}


def measure_hotspot(data, path):
    h = data.files_with_history().get(path)
    units = [u for u in data.units() if u.get("relativeFileName") == path]
    loc = h["loc"] if h else next((int(f.get("linesOfCode", 0)) for f in data.json("files.json", []) if f.get("relativePath") == path), None)
    if loc is None:
        return {"found": False}
    return {"found": True, "loc": loc, "units": len(units),
            "maxMcCabe": max([int(u.get("mcCabeIndex", 0)) for u in units] or [0]),
            "longestUnit": max([int(u.get("linesOfCode", 0)) for u in units] or [0]),
            "commits90": h["commits90"] if h else None}


def measure_finding(data, finding_id):
    for f in data.findings():
        if f.get("id") == finding_id:
            return {"found": True, "present": True, "severity": f.get("severity"), "confidence": f.get("confidence"), "title": f.get("title", "")}
    return {"found": True, "present": False}


def parse_target(target):
    kind, _, rest = target.partition(":")
    if kind == "unit":
        file, _, name = rest.rpartition("#")
        return {"kind": "unit", "file": file, "name": name}
    if kind == "duplicate":
        return {"kind": "duplicate", "index": int(rest)}
    if kind == "hotspot":
        return {"kind": "hotspot", "file": rest}
    if kind == "finding":
        return {"kind": "finding", "id": rest}
    raise ValueError(f"unknown target '{target}' (expected unit:, duplicate:, hotspot: or finding:)")


def snapshot(args):
    data = SokratesData(args.sokrates)
    if args.like:
        before = json.loads(Path(args.like).read_text())
        spec, target_id = before["spec"], before["target"]
    else:
        spec, target_id = parse_target(args.target), args.target
    kind = spec["kind"]
    if kind == "unit":
        measured = measure_unit(data, spec["file"], spec["name"])
    elif kind == "duplicate":
        if "files" not in spec:
            dups = data.duplicates()
            if spec["index"] >= len(dups):
                print(f"ERROR: duplicate index {spec['index']} is out of range ({len(dups)} duplicates)", file=sys.stderr)
                return 1
            spec["files"] = sorted(set(dups[spec["index"]]["files"]))
        measured = measure_duplicate_files(data, spec["files"])
    elif kind == "hotspot":
        measured = measure_hotspot(data, spec["file"])
    else:
        measured = measure_finding(data, spec["id"])
    out = {"target": target_id, "spec": spec, "takenAt": time.strftime("%Y-%m-%d %H:%M:%S"),
           "analysisAt": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(data.analyzed_at())),
           "measured": measured, "totals": totals(data)}
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"{target_id}: {json.dumps(measured)}")
    print(f"totals: {json.dumps(out['totals'])}")
    print(f"written to {args.out}")
    return 0 if measured.get("found") else 2


def verdict(kind, b, a):
    if not a.get("found"):
        return "not found"
    if kind == "unit":
        if a["mcCabe"] < b["mcCabe"] and a["loc"] <= b["loc"] * 1.1:
            return "improved"
        if a["loc"] < b["loc"] and a["mcCabe"] <= b["mcCabe"]:
            return "improved"
        if a["mcCabe"] > b["mcCabe"] or a["loc"] > b["loc"]:
            return "worse"
        return "unchanged"
    if kind == "duplicate":
        if a["duplicatedLines"] < b["duplicatedLines"]:
            return "improved"
        return "worse" if a["duplicatedLines"] > b["duplicatedLines"] else "unchanged"
    if kind == "hotspot":
        better = (a["loc"] < b["loc"] and a["maxMcCabe"] <= b["maxMcCabe"]) or (a["maxMcCabe"] < b["maxMcCabe"] and a["loc"] <= b["loc"])
        worse = a["loc"] > b["loc"] and a["maxMcCabe"] >= b["maxMcCabe"]
        return "improved" if better else ("worse" if worse else "unchanged")
    if kind == "finding":
        if not b.get("present"):
            return "unchanged"
        if not a.get("present"):
            return "improved"
        return "improved" if severity_rank(a.get("severity")) > severity_rank(b.get("severity")) else "unchanged"
    return "unchanged"


def compare(args):
    before, after = json.loads(Path(args.before).read_text()), json.loads(Path(args.after).read_text())
    kind = before["spec"]["kind"]
    b, a = before["measured"], after["measured"]
    result = verdict(kind, b, a)
    rows = []
    keys = {"unit": ["mcCabe", "loc", "lines"], "duplicate": ["duplicatedLines", "duplicateBlocks"],
            "hotspot": ["loc", "maxMcCabe", "longestUnit", "units"], "finding": ["present", "severity"]}[kind]
    for k in keys:
        rows.append((k, b.get(k, "-"), a.get(k, "-")))
    for k in ["mainLinesOfCode", "duplicatedLines", "unitsMcCabeOver25", "unitsMcCabeOver10", "unitsOver100Lines"]:
        rows.append((f"total {k}", before["totals"].get(k), after["totals"].get(k)))
    if args.markdown:
        print(f"**Target:** `{before['target']}` — **{result}**\n")
        print("| metric | before | after |\n| --- | ---: | ---: |")
        for k, x, y in rows:
            print(f"| {k} | {x} | {y} |")
    else:
        print(f"target: {before['target']}")
        print(f"{'metric':32s} {'before':>12s} {'after':>12s}")
        for k, x, y in rows:
            print(f"{k:32s} {str(x):>12s} {str(y):>12s}")
        print(f"\nverdict: {result}")
    if before.get("analysisAt") == after.get("analysisAt"):
        print("\nWARNING: both snapshots come from the same analysis — run `sokrates generateReports` after the change before the second snapshot.", file=sys.stderr)
    b_loc, a_loc = before["totals"].get("mainLinesOfCode") or 0, after["totals"].get("mainLinesOfCode") or 0
    if b_loc and a_loc and abs(a_loc - b_loc) > 0.1 * b_loc:
        print(f"\nWARNING: the analysis scope changed between the snapshots (main lines of code {b_loc} -> {a_loc}); the totals are not comparable."
              " Check _sokrates/config.json (is _sokrates/ itself ignored?) and re-run both analyses with the same configuration.", file=sys.stderr)
    return 0 if result == "improved" else (2 if result == "not found" else 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--target", help="the target id (from select_targets.py)")
    s.add_argument("--like", help="reuse the target definition of this earlier snapshot")
    s.add_argument("--sokrates", default="_sokrates")
    s.add_argument("-o", "--out", required=True)
    c = sub.add_parser("compare")
    c.add_argument("before")
    c.add_argument("after")
    c.add_argument("--markdown", action="store_true")
    args = parser.parse_args()
    if args.command == "snapshot":
        if not args.target and not args.like:
            parser.error("snapshot needs --target or --like")
        try:
            return snapshot(args)
        except (FileNotFoundError, ValueError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
    return compare(args)


if __name__ == "__main__":
    sys.exit(main())
