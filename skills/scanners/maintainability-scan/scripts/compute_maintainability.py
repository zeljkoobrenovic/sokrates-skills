#!/usr/bin/env python3
"""Roll up Sokrates data into maintainability drivers per sub-characteristic (modularity, reusability, analysability, modifiability, testability).

Deterministic, standard-library only. Reads an UNZIPPED data.zip directory and
prints, per component and for the system, the numbers the maintainability scanner
grades from; every number carries its provenance (which Sokrates export it came
from). Says explicitly when an export is absent (e.g. no dependency extraction).

Usage:
  python3 compute_maintainability.py <unzipped-data-dir> [--commits git-commits.txt]
                                     [--decomposition primary] [--json out.json] [--top 10]

Inputs used (all optional except files.json):
  files.json                       component per main file, LOC
  units.json                       unit size and McCabe (top-N capped by Sokrates)
  duplicates.json                  duplicated blocks with components -> cross-component duplication
  text/mainFilesWithHistory.txt    commits, churn, contributors, age per file
  text/temporal_dependencies*.txt  co-changing file pairs -> cross-component co-change
  text/dependencies_<decomp>.txt   component dependencies (from/to blocks) when Sokrates extracted them
  text/metrics.txt                 system totals (risk buckets)
  otherFiles.json / buildAndDeploymentFiles.json   documentation footprint
  text/aspect_concern_*.txt        TODO / deprecated / debt concern hit counts
  --commits git-commits.txt        "<sha> <first line>" -> fix-vs-feature share per component (via mainFilesWithHistory is
                                   per file, so commit categorisation is system-wide unless git-history.txt is beside it)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

FIX_RX = re.compile(r"\b(fix|fixes|fixed|bug|bugfix|hotfix|regression|crash|broken|repair|revert)\b", re.I)
FEAT_RX = re.compile(r"\b(add|adds|added|feat|feature|implement|introduce|support|new)\b", re.I)
REFACTOR_RX = re.compile(r"\b(refactor|cleanup|clean up|rename|move|extract|simplify|reorganize|restructure|tidy)\b", re.I)
DOC_EXT = {".md", ".rst", ".adoc", ".txt"}
DOC_NAME = re.compile(r"(readme|changelog|contributing|architecture|design|adr|docs?/|documentation|guide|handbook)", re.I)
UTIL_NAME = re.compile(r"(util|utils|common|shared|helpers?|core-lib|toolkit|support)", re.I)


def load_json(d: Path, name: str):
    p = d / name
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None


def comp_of(file_obj, decomp: str):
    for c in file_obj.get("components", []):
        if c.startswith(decomp + "::"):
            return c.split("::", 1)[1]
    return "(unassigned)"


def read_tsv(p: Path):
    if not p.is_file():
        return [], []
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return [], []
    header = lines[0].split("\t")
    rows = [l.split("\t") for l in lines[1:] if l.strip()]
    return header, rows


def parse_dependencies(p: Path):
    """text/dependencies_<decomp>.txt: blocks 'from: X' / 'to: Y' / evidence lines."""
    if not p.is_file():
        return None
    edges, cur_from, cur_to = defaultdict(int), None, None
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("from:"):
            cur_from = line[5:].strip()
        elif line.startswith("to:"):
            cur_to = line[3:].strip()
            if cur_from and cur_to:
                edges[(cur_from, cur_to)] += 0
        elif line.strip().startswith("- file:") and cur_from and cur_to:
            edges[(cur_from, cur_to)] += 1
    return dict(edges)


def find_cycles(edges):
    graph = defaultdict(set)
    for a, b in edges:
        if a != b:
            graph[a].add(b)
    cycles, seen = [], set()
    for a in list(graph):
        for b in graph[a]:
            if a in graph.get(b, ()) and (b, a) not in seen:
                cycles.append((a, b)); seen.add((a, b))
    return cycles


def bucket(loc, thresholds=(100, 200, 500, 1000)):
    """Sokrates-like file-size risk buckets: negligible <100, low <200, medium <500, high <1000, very high."""
    names = ("negligible", "low", "medium", "high", "very_high")
    for i, t in enumerate(thresholds):
        if loc < t:
            return names[i]
    return names[-1]


def unit_bucket(loc):
    return bucket(loc, (20, 50, 100, 200))


def mccabe_bucket(m):
    return bucket(m, (6, 11, 26, 51))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("data_dir")
    ap.add_argument("--commits", help="git-commits.txt (sha + first line per commit)")
    ap.add_argument("--decomposition", default="primary")
    ap.add_argument("--json")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--window", default="180", help="temporal-coupling export to use: 180 (default, recent history), 90, 30, or all (lifetime pairs, dominated by old history)")
    ap.add_argument("--min-shared", type=int, default=3, help="minimum shared commits for a co-change pair to count (default 3)")
    ap.add_argument("--src-root", help="source root: counts documentation files in the tree even when Sokrates' config ignores them (docs/, *.md)")
    args = ap.parse_args(argv)
    d = Path(args.data_dir).resolve()
    if not (d / "files.json").is_file():
        print(f"error: {d}/files.json not found — pass the unzipped data.zip directory", file=sys.stderr)
        return 2
    decomp = args.decomposition
    gaps, prov = [], {}
    comp = defaultdict(lambda: {"files": 0, "loc": 0, "loc_high_risk_files": 0, "loc_very_high_risk_files": 0,
                                "units": 0, "unit_loc": 0, "unit_loc_high_complexity": 0, "unit_loc_long": 0,
                                "dup_blocks": 0, "cross_component_dup_blocks": 0, "dup_partners": set(),
                                "commits": 0, "churn": 0, "single_owner_files": 0, "files_with_history": 0,
                                "contributors": set(), "stale_files": 0,
                                "fan_in": 0, "fan_out": 0, "cochange_pairs_cross": 0, "cochange_partners": set()})

    # --- files and components
    files = load_json(d, "files.json") or []
    file_comp = {}
    test_like = re.compile(r"(^|/)(tests?|__tests__|spec|testdata|fixtures?)/|_tests?\.\w+$|(^|/)tests?\.rs$|Tests?\.(java|kt|cs)$|\.(spec|test)\.\w+$|(^|/)test_\w+\.py$")
    test_like_loc = 0
    for f in files:
        c = comp_of(f, decomp)
        file_comp[f["relativePath"]] = c
        e = comp[c]
        e["files"] += 1
        loc = f.get("linesOfCode", 0)
        if test_like.search(f["relativePath"]):
            test_like_loc += loc
            e["test_like_loc"] = e.get("test_like_loc", 0) + loc
            continue  # test-like files in Sokrates' main scope are excluded from size-risk shares
        e["loc"] += loc
        b = bucket(loc)
        if b in ("high", "very_high"):
            e["loc_high_risk_files"] += loc
        if b == "very_high":
            e["loc_very_high_risk_files"] += loc
    prov["files"] = "files.json (main scope, component from the %s decomposition; test-like paths inside main scope — *tests.rs, tests/, *Test.java — are excluded from size-risk shares and reported as test_like_loc)" % decomp

    # --- units
    units = load_json(d, "units.json") or []
    for u in units:
        c = file_comp.get(u.get("relativeFileName", ""), "(unassigned)")
        e = comp[c]
        loc, mc = u.get("linesOfCode", 0), u.get("mcCabeIndex", 0)
        e["units"] += 1
        e["unit_loc"] += loc
        if mccabe_bucket(mc) in ("high", "very_high"):
            e["unit_loc_high_complexity"] += loc
        if unit_bucket(loc) in ("high", "very_high"):
            e["unit_loc_long"] += loc
    prov["units"] = "units.json (Sokrates caps this export at the top 10,000 units — the LARGEST ones — so high_complexity_unit_loc_share is biased upward on big codebases; compare NUMBER_OF_UNITS in metrics.txt)"
    if not units:
        gaps.append("unit-level size/complexity (units.json missing)")

    # --- duplication
    dup = load_json(d, "duplicates.json") or {}
    cross_pairs = defaultdict(int)
    dup_ranges = {}
    for block in dup.get("duplicates", []):
        comps = []
        for fb in block.get("duplicatedFileBlocks", []):
            fo = fb.get("file") or {}
            rp = fo.get("relativePath") or fb.get("sourceFile", {}).get("relativePath", "")
            comps.append(file_comp.get(rp, comp_of(fo, decomp) if fo else "(unassigned)"))
        cs = set(comps)
        for c in cs:
            comp[c]["dup_blocks"] += 1
        for fb in block.get("duplicatedFileBlocks", []):
            fo = fb.get("file") or {}
            rp = fo.get("relativePath", "")
            a, b = fb.get("startLine") or fb.get("start"), fb.get("endLine") or fb.get("end")
            if rp and isinstance(a, int) and isinstance(b, int):
                dup_ranges.setdefault(rp, []).append((a, b))
        if len(cs) > 1:
            for c in cs:
                comp[c]["cross_component_dup_blocks"] += 1
                comp[c]["dup_partners"].update(cs - {c})
            key = tuple(sorted(cs))
            cross_pairs[key] += block.get("blockSize", 0)
    for rp, ranges in dup_ranges.items():  # union of ranges per file -> unique duplicated lines
        ranges.sort()
        covered, cur_a, cur_b = 0, None, None
        for a, b in ranges:
            if cur_b is None or a > cur_b + 1:
                if cur_b is not None:
                    covered += cur_b - cur_a + 1
                cur_a, cur_b = a, b
            else:
                cur_b = max(cur_b, b)
        if cur_b is not None:
            covered += cur_b - cur_a + 1
        c = file_comp.get(rp, "(unassigned)")
        comp[c]["dup_lines"] = comp[c].get("dup_lines", 0) + covered
    prov["duplication"] = "duplicates.json (blocks with components; cross-component = block spans >1 component; duplicated_line_share = union of duplicated line ranges per file / component LOC; Sokrates caps this export at 10,000 blocks — 10000 means capped)"
    if not dup:
        gaps.append("duplication (duplicates.json missing or empty)")

    # --- history per file
    header, rows = read_tsv(d / "text" / "mainFilesWithHistory.txt")
    if rows:
        idx = {h: i for i, h in enumerate(header)}
        for r in rows:
            try:
                path = r[idx["path"]]
                c = file_comp.get(path, "(unassigned)")
                e = comp[c]
                e["files_with_history"] += 1
                e["commits"] += int(r[idx["# commits"]])
                e["churn"] += int(r[idx["line churn"]])
                ncontrib = int(r[idx["# contributors"]])
                if ncontrib == 1:
                    e["single_owner_files"] += 1
                days_last = int(r[idx["days since last update"]])
                e.setdefault("days_last", []).append(days_last)
                e["commits_90d"] = e.get("commits_90d", 0) + int(r[idx["# commits (90d)"]])
                e["contributors"].add(r[idx["last contributor"]]); e["contributors"].add(r[idx["first contributor"]])
            except (KeyError, ValueError, IndexError):
                continue
        all_days = sorted(x for e in comp.values() for x in e.get("days_last", []))
        stale_threshold = min(1095, max(365, 2 * all_days[len(all_days) // 2])) if all_days else 730
        for e in comp.values():
            e["stale_files"] = sum(1 for x in e.get("days_last", []) if x > stale_threshold)
        prov["history"] = f"text/mainFilesWithHistory.txt (commits, line churn, contributors, days since last update per file); stale = untouched for > {stale_threshold} days (2 x median age of last change, clamped to 1–3 years); stale share matters only in components with commits_90d > 0"
    else:
        gaps.append("file history (text/mainFilesWithHistory.txt missing — no git history extracted)")

    # --- temporal coupling
    cochange_cross_pairs, all_pairs, window_used = [], 0, None
    candidates = {"all": ["temporal_dependencies.txt"], "180": ["temporal_dependencies_180_days.txt"],
                  "90": ["temporal_dependencies_90_days.txt"], "30": ["temporal_dependencies_30_days.txt"]}[args.window] + \
                 ["temporal_dependencies.txt", "temporal_dependencies_180_days.txt", "temporal_dependencies_90_days.txt"]
    for name in candidates:
        h, rws = read_tsv(d / "text" / name)
        if rws:
            window_used = name
            for r in rws:
                try:
                    f1, f2, same = r[0], r[1], int(r[2])
                except (ValueError, IndexError):
                    continue
                if same < args.min_shared:
                    continue
                try:
                    strength = round(same / max(1, min(int(r[3]), int(r[4]))), 2)
                except (ValueError, IndexError):
                    strength = None
                all_pairs += 1
                c1, c2 = file_comp.get(f1, "(unassigned)"), file_comp.get(f2, "(unassigned)")
                for c in {c1, c2}:
                    comp[c]["cochange_pairs_all"] = comp[c].get("cochange_pairs_all", 0) + 1
                if c1 != c2:
                    cochange_cross_pairs.append((same, f1, f2, c1, c2, strength))
                    comp[c1]["cochange_pairs_cross"] += 1; comp[c2]["cochange_pairs_cross"] += 1
                    comp[c1]["cochange_partners"].add(c2); comp[c2]["cochange_partners"].add(c1)
            prov["temporal_coupling"] = f"text/{name}, pairs with >= {args.min_shared} shared commits, strength = shared / min(commits f1, commits f2); per-component counts are pairs touching that component (a cross pair counts for both sides); the export is capped at 10,000 pairs"
            break
    else:
        gaps.append("temporal coupling (no text/temporal_dependencies*.txt)")
    cochange_cross_pairs.sort(reverse=True)

    # --- component dependencies
    edges = parse_dependencies(d / "text" / f"dependencies_{decomp}.txt")
    cycles = []
    if edges:
        for (a, b), n in edges.items():
            if a != b:
                comp[a]["fan_out"] += 1; comp[b]["fan_in"] += 1
        cycles = find_cycles(edges)
        prov["dependencies"] = f"text/dependencies_{decomp}.txt (component edges Sokrates extracted from imports)"
    else:
        gaps.append(f"component dependencies (text/dependencies_{decomp}.txt empty or absent — Sokrates extracts none for this language; use architecture-scan's manifest graph)")

    # --- documentation footprint
    doc_files, doc_loc = 0, 0
    for name in ("otherFiles.json", "buildAndDeploymentFiles.json", "files.json"):
        for f in load_json(d, name) or []:
            rp = f.get("relativePath", "")
            if Path(rp).suffix.lower() in DOC_EXT or (DOC_NAME.search(rp) and Path(rp).suffix.lower() in DOC_EXT | {".html"}):
                doc_files += 1; doc_loc += f.get("linesOfCode", 0)
    prov["documentation"] = "files with .md/.rst/.adoc or doc-like paths across Sokrates' main/other/build scopes"
    tree_docs = None
    if args.src_root and Path(args.src_root).is_dir():
        sr = Path(args.src_root)
        md = [q for q in sr.rglob("*") if q.is_file() and q.suffix.lower() in {".md", ".rst", ".adoc"} and not any(x in q.parts for x in ("node_modules", "target", ".git", "_sokrates", "vendor"))]
        tree_docs = {"doc_files_in_tree": len(md), "doc_lines_in_tree": sum(len(q.read_text(errors="replace").splitlines()) for q in md),
                     "docs_dir_present": (sr / "docs").is_dir(), "in_sokrates_scope": doc_files}
        prov["documentation_tree"] = "documentation files found by walking the source root (Sokrates' config may ignore them)"
        # module/file doc-comment coverage per component: first non-blank, non-import line is a doc comment
        doc_rx = re.compile(r"^\s*(//!|/\*\*|/\*!|\"\"\"|#!|///|\* @file|// Package|/// <summary>)")
        for f in files:
            rp = f["relativePath"]
            if test_like.search(rp) or Path(rp).suffix.lower() not in {".rs", ".java", ".kt", ".py", ".ts", ".tsx", ".js", ".go", ".cs", ".scala"}:
                continue
            q = sr / rp
            if not q.is_file():
                continue
            e = comp[file_comp[rp]]
            e["code_files_checked"] = e.get("code_files_checked", 0) + 1
            try:
                head = q.read_text(encoding="utf-8", errors="replace").splitlines()[:15]
            except OSError:
                continue
            if any(doc_rx.match(l) for l in head):
                e["doc_commented_files"] = e.get("doc_commented_files", 0) + 1
        prov["doc_comments"] = "share of code files whose first 15 lines contain a module/file doc comment (//!, /** , \"\"\", ///, package doc)"

    # --- concerns (debt markers)
    concerns = {}
    for p in sorted((d / "text").glob("aspect_concern_*.txt")):
        if "found_text" in p.name or "Unclassified" in p.name or "_AND_" in p.name:
            continue
        if not re.search(r"debt|todo|deprecat|fixme|hack|legacy|suppress", p.name, re.I):
            continue
        n = max(0, len(p.read_text(encoding="utf-8", errors="replace").splitlines()) - 1)
        concerns[p.stem[len("aspect_concern_"):]] = n
    prov["concerns"] = "text/aspect_concern_*.txt (files matching each configured concern; a concern listed with 0 is configured but matched nothing — an absent key means not configured)"

    # --- commits
    commit_mix = None
    if args.commits and Path(args.commits).is_file():
        fix = feat = ref = total = 0
        for line in Path(args.commits).read_text(encoding="utf-8", errors="replace").splitlines():
            msg = line.split(" ", 1)[1] if " " in line else ""
            if not msg or msg.lower().startswith("merge "):
                continue
            total += 1
            if FIX_RX.search(msg):
                fix += 1
            elif REFACTOR_RX.search(msg):
                ref += 1
            elif FEAT_RX.search(msg):
                feat += 1
        if total and (fix + feat + ref) / total >= 0.5:
            commit_mix = {"commits": total, "fix_share": round(fix / total, 2), "feature_share": round(feat / total, 2),
                          "refactor_share": round(ref / total, 2), "unclassified_share": round((total - fix - feat - ref) / total, 2)}
            prov["commit_mix"] = f"{args.commits} first lines, SYSTEM-WIDE keyword classification (fix|bug|regression… / feat|add|implement… / refactor|rename|cleanup…), merges skipped; unclassified is usually large — quote fix_share only relative to feature_share"
        elif total:
            gaps.append(f"fix-vs-feature commit share: {round(100*(total-fix-feat-ref)/total)}% of {total} commit titles unclassifiable by keyword — too weak to quote")
    else:
        gaps.append("fix-vs-feature commit share (pass --commits <project>/git-commits.txt — it lives in the project or _sokrates root, not in the data dir)")

    # --- system totals and per-component table
    total_loc = sum(e["loc"] for e in comp.values()) or 1
    table = {}
    for c, e in comp.items():
        if e["files"] == 0 and e["units"] == 0:
            continue
        table[c] = {
            "files": e["files"], "loc": e["loc"], "loc_share": round(e["loc"] / total_loc, 3),
            "high_risk_file_loc_share": round(e["loc_high_risk_files"] / e["loc"], 2) if e["loc"] else None,
            "very_high_risk_file_loc_share": round(e["loc_very_high_risk_files"] / e["loc"], 2) if e["loc"] else None,
            "units_exported": e["units"],
            "high_complexity_unit_loc_share": round(e["unit_loc_high_complexity"] / e["unit_loc"], 2) if e["unit_loc"] else None,
            "long_unit_loc_share": round(e["unit_loc_long"] / e["unit_loc"], 2) if e["unit_loc"] else None,
            "dup_blocks": e["dup_blocks"], "cross_component_dup_blocks": e["cross_component_dup_blocks"],
            "dup_partners": sorted(e["dup_partners"]),
            "fan_in": e["fan_in"] if edges else None, "fan_out": e["fan_out"] if edges else None,
            "cross_component_cochange_pairs": e["cochange_pairs_cross"], "cochange_partners": sorted(e["cochange_partners"]),
            "cross_component_cochange_share": round(e["cochange_pairs_cross"] / e["cochange_pairs_all"], 2) if e.get("cochange_pairs_all") else None,
            "duplicated_line_share": round(e.get("dup_lines", 0) / e["loc"], 2) if e["loc"] else None,
            "file_commits": e["commits"], "line_churn": e["churn"],
            "single_owner_file_share": round(e["single_owner_files"] / e["files_with_history"], 2) if e["files_with_history"] else None,
            "stale_file_share": round(e["stale_files"] / e["files_with_history"], 2) if e["files_with_history"] else None,
            "commits_90d": e.get("commits_90d", 0),
            "dormant": e.get("commits_90d", 0) == 0 and e["files_with_history"] > 0,
            "contributors_seen_first_last": len(e["contributors"]),
            "doc_commented_file_share": round(e.get("doc_commented_files", 0) / e["code_files_checked"], 2) if e.get("code_files_checked") else None,
            "test_like_loc_in_main_scope": e.get("test_like_loc", 0),
            "looks_like_shared_utility": bool(UTIL_NAME.search(c)),
        }
    sys_stats = {
        "main_loc": total_loc, "components": len(table),
        "very_high_risk_file_loc_share": round(sum(e["loc_very_high_risk_files"] for e in comp.values()) / total_loc, 2),
        "high_risk_file_loc_share": round(sum(e["loc_high_risk_files"] for e in comp.values()) / total_loc, 2),
        "high_complexity_unit_loc_share": round(sum(e["unit_loc_high_complexity"] for e in comp.values()) / max(1, sum(e["unit_loc"] for e in comp.values())), 2),
        "duplicate_blocks": sum(1 for _ in dup.get("duplicates", [])),
        "cross_component_duplicate_blocks": sum(1 for b in dup.get("duplicates", []) if len({file_comp.get((fb.get('file') or {}).get('relativePath', ''), '') for fb in b.get('duplicatedFileBlocks', [])}) > 1),
        "cross_component_duplicated_lines_by_pair": {" <-> ".join(k): n for k, n in sorted(cross_pairs.items(), key=lambda kv: -kv[1])[:args.top]},
        "test_like_loc_inside_main_scope": test_like_loc,
        "cochange_window": window_used, "cochange_min_shared_commits": args.min_shared,
        "cochange_pairs": all_pairs, "cross_component_cochange_pairs": len(cochange_cross_pairs),
        "cross_component_cochange_share": round(len(cochange_cross_pairs) / all_pairs, 2) if all_pairs else None,
        "cross_component_cochange_pairs_per_100_files": round(100 * len(cochange_cross_pairs) / max(1, sum(e["files_with_history"] for e in comp.values())), 1),
        "component_dependency_edges": len(edges) if edges else None,
        "component_cycles": [list(c) for c in cycles] if edges else None,
        "doc_files": doc_files, "doc_loc": doc_loc, "doc_loc_per_kloc": round(doc_loc / (total_loc / 1000), 1), "documentation_tree": tree_docs,
        "doc_commented_file_share": (round(sum(e.get("doc_commented_files", 0) for e in comp.values()) / max(1, sum(e.get("code_files_checked", 0) for e in comp.values())), 2) if any(e.get("code_files_checked") for e in comp.values()) else None),
        "single_owner_file_share": round(sum(e["single_owner_files"] for e in comp.values()) / max(1, sum(e["files_with_history"] for e in comp.values())), 2),
        "stale_file_share": round(sum(e["stale_files"] for e in comp.values()) / max(1, sum(e["files_with_history"] for e in comp.values())), 2),
        "debt_concerns": concerns, "commit_mix": commit_mix,
    }
    # typical-change scenarios: top cross-component co-change pairs, deduped by component pair
    scenarios, seen = [], set()
    for same, f1, f2, c1, c2, strength in cochange_cross_pairs:
        key = tuple(sorted((c1, c2)))
        if key in seen:
            continue
        seen.add(key)
        scenarios.append({"components": list(key), "files": [f1, f2], "shared_commits": same, "strength": strength})
        if len(scenarios) >= args.top:
            break
    # metrics.txt totals if present
    mt = d / "text" / "metrics.txt"
    if mt.is_file():
        want = ("DUPLICATION_PERCENTAGE", "NUMBER_OF_DUPLICATES", "TEST_VS_MAIN_LINES_OF_CODE_PERCENTAGE", "NUMBER_OF_UNITS",
                "NUMBER_OF_CONTRIBUTORS", "NUMBER_OF_ACTIVE_CONTRIBUTORS_30_DAYS")
        for line in mt.read_text(encoding="utf-8", errors="replace").splitlines():
            k, _, v = line.partition(":")
            if k.strip() in want:
                sys_stats["sokrates_" + k.strip().lower()] = v.strip()
        prov["metrics"] = "text/metrics.txt (Sokrates system totals)"

    # --- print
    print(f"Maintainability drivers from {d} ({decomp} decomposition): {sys_stats['components']} components, {total_loc} main LOC\n")
    print("system:")
    for k, v in sys_stats.items():
        if k not in ("debt_concerns", "commit_mix", "component_cycles", "documentation_tree"):
            print(f"  {k:36s} {v}")
    print(f"  component_cycles                     {sys_stats['component_cycles']}")
    print(f"  documentation_tree                   {tree_docs}")
    print(f"  debt_concerns                        {concerns}")
    print(f"  commit_mix                           {commit_mix}")
    print("\nper component (sorted by LOC):")
    hdr = f"  {'component':40s} {'loc':>7s} {'vhr%':>5s} {'cplx%':>6s} {'xdup':>5s} {'xco':>4s} {'fin':>4s} {'fout':>4s} {'1own%':>6s} {'stale%':>6s} {'fcommit':>8s}"
    print(hdr)
    for c, t in sorted(table.items(), key=lambda kv: -kv[1]["loc"]):
        pct = lambda x: "-" if x is None else f"{int(x*100)}"
        print(f"  {c[:40]:40s} {t['loc']:7d} {pct(t['very_high_risk_file_loc_share']):>5s} {pct(t['high_complexity_unit_loc_share']):>6s} "
              f"{t['cross_component_dup_blocks']:5d} {t['cross_component_cochange_pairs']:4d} {('-' if t['fan_in'] is None else t['fan_in']):>4} {('-' if t['fan_out'] is None else t['fan_out']):>4} "
              f"{pct(t['single_owner_file_share']):>6s} {pct(t['stale_file_share']):>6s} {t['file_commits']:8d}")
    print("\ntypical-change scenarios (top cross-component co-change pairs; read these two files each):")
    for sc in scenarios:
        print(f"  {sc['shared_commits']:4d} shared commits  {sc['components'][0]} <-> {sc['components'][1]}\n        {sc['files'][0]}\n        {sc['files'][1]}")
    if cross_pairs:
        print("\ncross-component duplication (component pair -> duplicated lines):")
        for key, n in sorted(cross_pairs.items(), key=lambda kv: -kv[1])[: args.top]:
            print(f"  {n:6d}  {' <-> '.join(key)}")
    if gaps:
        print("\nDATA GAPS (say so in the findings, lower confidence for these drivers):")
        for g in gaps:
            print(f"  - {g}")
    print("\nprovenance:")
    for k, v in prov.items():
        print(f"  {k}: {v}")
    if args.json:
        Path(args.json).write_text(json.dumps({"data_dir": str(d), "decomposition": decomp, "stats": {"system": sys_stats, "components": table, "provenance": prov, "data_gaps": gaps},
                                              "scenarios": scenarios, "cross_component_duplication": [{"components": list(k), "lines": n} for k, n in sorted(cross_pairs.items(), key=lambda kv: -kv[1])]}, indent=2))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
