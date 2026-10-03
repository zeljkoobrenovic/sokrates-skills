#!/usr/bin/env python3
"""Measure an improvement target before and after a change, from the Sokrates analysis.

  snapshot  --target <id> [--sokrates _sokrates] -o before.json
            the target's numbers now, plus the repository totals; after the change (and
            `sokrates generateReports`) take a second snapshot with the same --target, or with
            --like before.json to reuse the target definition (a duplicate:<index> changes index
            between runs; --like keeps the files it referred to).
  compare   before.json after.json [--markdown | --for-commit]
            the before/after table and the verdict (--for-commit: the same numbers as a block to paste into the commit message): improved / unchanged / worse / not found, or for a
            finding whose cited code changed without a re-check yet: needs re-check.
            Exit code 0 = improved, 1 = unchanged or worse, 2 = target not found after the change,
            3 = needs re-check (run scan-core's recheck_findings.py --prompt, then the scoped agent re-check).

Target ids come from select_targets.py: unit:<file>#<name>[@<start line>], duplicate:<index>, hotspot:<path>,
finding:<finding id>. A unit name alone is ambiguous for overloads (the short name drops the parameter list):
the @<start line> picks the overload at that line for the first snapshot; the snapshot then records its
parameter count, which --like uses to find the same overload after the change, when the lines have shifted.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sokrates_data import SokratesData, evidence_state, severity_rank  # noqa: E402


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


def file_units(data, file):
    """The units of one file (name, parameters, line, McCabe, size), for overload resolution and helper detection."""
    return [{"name": u.get("shortName", ""), "parameters": u.get("numberOfParameters"), "startLine": u.get("startLine"),
             "mcCabe": int(u.get("mcCabeIndex", 0)), "loc": int(u.get("linesOfCode", 0))}
            for u in data.units() if same_file(u.get("relativeFileName", ""), file)]


def pick_unit(candidates, spec):
    """The overload the spec means: by parameter count when known (stable across a refactoring), else the one nearest the
    given start line, else the most complex one. Returns (unit, note) - the note says when the name alone was ambiguous."""
    if len(candidates) == 1:
        return candidates[0], None
    by_parameters = [u for u in candidates if spec.get("parameters") is not None and u.get("numberOfParameters") == spec["parameters"]]
    if len(by_parameters) == 1:
        return by_parameters[0], None
    pool = by_parameters or candidates
    if spec.get("startLine") is not None:
        unit = min(pool, key=lambda u: abs(int(u.get("startLine", 0)) - int(spec["startLine"])))
        return unit, None
    unit = max(pool, key=lambda x: (int(x.get("mcCabeIndex", 0)), int(x.get("linesOfCode", 0))))
    lines = ", ".join(str(u.get("startLine")) for u in pool)
    return unit, (f"{len(pool)} units named '{spec['name']}' in {spec['file']} (lines {lines}); measuring the most complex one, at line "
                  f"{unit.get('startLine')} with {unit.get('numberOfParameters')} parameter(s) - name it as #{spec['name']}@{unit.get('startLine')} to be sure")


def measure_unit(data, spec):
    candidates = [u for u in data.units() if same_file(u.get("relativeFileName", ""), spec["file"]) and u.get("shortName") == spec["name"]]
    if not candidates:
        return {"found": False}
    u, note = pick_unit(candidates, spec)
    spec["parameters"] = u.get("numberOfParameters")
    spec["startLine"] = u.get("startLine")
    measured = {"found": True, "mcCabe": int(u.get("mcCabeIndex", 0)), "loc": int(u.get("linesOfCode", 0)),
                "lines": f"{u.get('startLine')}-{u.get('endLine')}", "unitsInFile": len(file_units(data, spec["file"])),
                "fileUnits": file_units(data, spec["file"])}
    if note:
        measured["note"] = note
    return measured


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
            "commits90": h["commits90"] if h else None,
            "folderFiles": folder_files(data, path)}


def folder_files(data, path):
    """The main files in the hotspot's folder (path, lines), so a split can be seen: the new files are where the lines went."""
    folder = path.rpartition("/")[0]
    return [{"path": f.get("relativePath"), "loc": int(f.get("linesOfCode", 0))}
            for f in data.json("files.json", []) if isinstance(f, dict) and str(f.get("relativePath", "")).rpartition("/")[0] == folder]


def new_files(before_measured, after_measured):
    """Files of the hotspot's folder that exist after the change and did not before."""
    before_paths = {f["path"] for f in before_measured.get("folderFiles", [])}
    return [f for f in after_measured.get("folderFiles", []) if f["path"] not in before_paths]


def measure_finding(data, finding_id):
    for f in data.findings():
        if f.get("id") == finding_id:
            return {"found": True, "present": True, "severity": f.get("severity"), "confidence": f.get("confidence"), "title": f.get("title", ""),
                    "evidence": evidence_state(f, data.root.parent)}
    return {"found": True, "present": False}


def parse_target(target):
    kind, _, rest = target.partition(":")
    if kind == "unit":
        file, _, name = rest.rpartition("#")
        name, _, line = name.partition("@")
        spec = {"kind": "unit", "file": file, "name": name}
        if line:
            if not line.isdigit():
                raise ValueError(f"unit target '{target}': the part after @ must be the unit's start line")
            spec["startLine"] = int(line)
        return spec
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
        measured = measure_unit(data, spec)
        if measured.get("note"):
            print(f"WARNING: {measured['note']}", file=sys.stderr)
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
    print(f"{target_id}: {json.dumps({k: v for k, v in measured.items() if k not in ('fileUnits', 'note')})}")
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
        if severity_rank(a.get("severity")) > severity_rank(b.get("severity")):
            return "improved"
        if a.get("evidence") == "gone":
            return "needs re-check"     # the cited code changed but nobody has judged the finding yet
        return "unchanged"
    return "unchanged"


def new_helpers(before_measured, after_measured):
    """Units of the target's file that exist after the change and did not before (by name and parameter count)."""
    before_units = {(u["name"], u.get("parameters")) for u in before_measured.get("fileUnits", [])}
    return [u for u in after_measured.get("fileUnits", []) if (u["name"], u.get("parameters")) not in before_units]


def commit_lines(kind, target, result, b, a, split_files):
    """The numbers for a commit message, ready to paste: one summary line and the before -> after pairs."""
    name = target.partition(":")[2].rpartition("#")[2].partition("@")[0] if kind == "unit" else target.partition(":")[2].rpartition("/")[2]
    if kind == "unit":
        summary = f"{name}: McCabe {b.get('mcCabe')} -> {a.get('mcCabe')}, lines {b.get('loc')} -> {a.get('loc')}"
        table = [f"| {name} | {b.get('mcCabe')} -> {a.get('mcCabe')} | {b.get('loc')} -> {a.get('loc')} |"]
        header = "| unit | McCabe | lines |\n| --- | ---: | ---: |"
    elif kind == "hotspot":
        extra = f" (+{' +'.join(str(f['loc']) for f in split_files)} new)" if split_files else ""
        summary = f"{name}: {b.get('loc')} -> {a.get('loc')} lines{extra}, longest unit {b.get('longestUnit')} -> {a.get('longestUnit')}, max McCabe {b.get('maxMcCabe')} -> {a.get('maxMcCabe')}"
        table = [f"| {name} | {b.get('loc')} -> {a.get('loc')}{extra} | {b.get('units')} -> {a.get('units')} |"]
        header = "| file | lines | units |\n| --- | ---: | ---: |"
    elif kind == "duplicate":
        summary = f"duplicated lines {b.get('duplicatedLines')} -> {a.get('duplicatedLines')} in {len(b.get('files', []))} file(s)"
        table = [f"| {target} | {b.get('duplicatedLines')} -> {a.get('duplicatedLines')} | {b.get('duplicateBlocks')} -> {a.get('duplicateBlocks')} |"]
        header = "| duplicate | lines | blocks |\n| --- | ---: | ---: |"
    else:
        summary = f"{target}: {b.get('severity')} {'present' if b.get('present') else 'absent'} -> {a.get('severity')} {'present' if a.get('present') else 'absent'}"
        table = [f"| {target} | {b.get('severity')} -> {a.get('severity')} | {b.get('evidence')} -> {a.get('evidence')} |"]
        header = "| finding | severity | evidence |\n| --- | ---: | ---: |"
    return f"{summary} ({result})\n\n{header}\n" + "\n".join(table)


def compare(args):
    before, after = json.loads(Path(args.before).read_text()), json.loads(Path(args.after).read_text())
    kind = before["spec"]["kind"]
    b, a = before["measured"], after["measured"]
    result = verdict(kind, b, a)
    rows = []
    keys = {"unit": ["mcCabe", "loc", "lines"], "duplicate": ["duplicatedLines", "duplicateBlocks"],
            "hotspot": ["loc", "maxMcCabe", "longestUnit", "units"], "finding": ["present", "severity", "evidence"]}[kind]
    for k in keys:
        rows.append((k, b.get(k, "-"), a.get(k, "-")))
    helpers = new_helpers(b, a) if kind == "unit" else []
    if helpers:
        moved_mccabe = sum(h["mcCabe"] - 1 for h in helpers)
        rows.append(("new helpers in the file", "-", f"{len(helpers)} ({', '.join(h['name'] for h in helpers[:6])}{', …' if len(helpers) > 6 else ''})"))
        rows.append(("mcCabe incl. new helpers", b.get("mcCabe", "-"), a.get("mcCabe", 0) + moved_mccabe))
        rows.append(("loc incl. new helpers", b.get("loc", "-"), a.get("loc", 0) + sum(h["loc"] for h in helpers)))
    split_files = new_files(b, a) if kind == "hotspot" else []
    if split_files:
        names = ", ".join(f"{f['path'].rpartition('/')[2]} ({f['loc']})" for f in split_files[:6]) + (", …" if len(split_files) > 6 else "")
        rows.append(("new files in the folder", "-", f"{len(split_files)}: {names}"))
        rows.append(("loc incl. new files", b.get("loc", "-"), a.get("loc", 0) + sum(f["loc"] for f in split_files)))
    for k in ["mainLinesOfCode", "duplicatedLines", "unitsMcCabeOver25", "unitsMcCabeOver10", "unitsOver100Lines"]:
        rows.append((f"total {k}", before["totals"].get(k), after["totals"].get(k)))
    if args.for_commit:
        print(commit_lines(kind, before["target"], result, b, a, split_files if kind == "hotspot" else []))
    elif args.markdown:
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
    if kind == "unit" and a.get("found") and result in ("worse", "unchanged") and a.get("loc", 0) < b.get("loc", 0) and a.get("mcCabe", 0) >= b.get("mcCabe", 0):
        print("\nThe unit got shorter but not simpler: Sokrates counts every if / else if / loop / case / catch / && / || / ?: as a decision,"
              " so ternaries and boolean operators that flatten nesting still count as branches. Replace them with guard clauses,"
              " a lookup table or a helper that owns the decision.", file=sys.stderr)
    if split_files and result == "improved":
        lost, appeared = b.get("loc", 0) - a.get("loc", 0), sum(f["loc"] for f in split_files)
        if appeared > lost * 1.1 + 20:
            print(f"\nNote: the file lost {lost} lines but {appeared} appeared in {len(split_files)} new file(s): more code was written than moved"
                  " - check for duplicated code or copied import lists (check_imports.py) before calling it a split.", file=sys.stderr)
    if helpers and result == "improved":
        moved = sum(h["mcCabe"] - 1 for h in helpers)
        dropped = b.get("mcCabe", 0) - a.get("mcCabe", 0)
        if moved >= dropped > 0:
            print(f"\nNote: the {dropped} decision(s) the unit lost moved into {len(helpers)} new helper(s) (they carry {moved});"
                  " the maximum per unit dropped, the total did not - that is what extracting helpers does. Make sure each helper"
                  " has a name and a purpose of its own; pieces that only call each other are the split the rules forbid.", file=sys.stderr)
    if before.get("analysisAt") == after.get("analysisAt"):
        print("\nWARNING: both snapshots come from the same analysis — run `sokrates generateReports` after the change before the second snapshot.", file=sys.stderr)
    b_loc, a_loc = before["totals"].get("mainLinesOfCode") or 0, after["totals"].get("mainLinesOfCode") or 0
    if b_loc and a_loc and abs(a_loc - b_loc) > 0.1 * b_loc:
        print(f"\nWARNING: the analysis scope changed between the snapshots (main lines of code {b_loc} -> {a_loc}); the totals are not comparable."
              " Check _sokrates/config.json (is _sokrates/ itself ignored?) and re-run both analyses with the same configuration.", file=sys.stderr)
    if result == "needs re-check":
        print("\nThe finding is still in the file but its cited code changed: run scan-core's recheck_findings.py --prompt on the"
              " findings file and let the scoped agent re-check decide resolved / partly / unresolved, then compare again.", file=sys.stderr)
    return 0 if result == "improved" else (2 if result == "not found" else (3 if result == "needs re-check" else 1))


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
    c.add_argument("--for-commit", action="store_true", help="print the numbers as a commit-message block (paste it, never type numbers)")
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
