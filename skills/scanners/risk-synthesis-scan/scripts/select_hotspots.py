#!/usr/bin/env python3
"""Select risk hotspots from an extracted Sokrates data folder.

Deterministic pre-selection for the risk-synthesis-scan skill: parses the
Sokrates text exports and emits a JSON shortlist of (a) complexity/activity
hotspot files, (b) knowledge-risk signals (bus factor, single-owner files),
and (c) the strongest change-coupling pairs. The AI scanner then reads the
shortlisted code and does the semantic explanation.

Usage:
  python3 select_hotspots.py --data <extracted-data-dir> [--src-root <path>]
                             [--top 10] [-o out.json]

With --src-root (recommended), hotspot files are opened to locate embedded
Rust test modules, so production vs. test code is not conflated.

<extracted-data-dir> is the folder data.zip was unzipped into (must contain
text/mainFilesWithHistory.txt, text/units.txt, text/contributors.txt,
text/temporal_dependencies_different_folders_30_days.txt).
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__|testdata|spec)/"        # tests/, spec/ directories
    r"|[a-z0-9]_tests?/"                             # service_tests/, snapshot_test/
    r"|(_test|\.test|_spec|\.spec)\."                # foo_test.rs, foo.test.ts
    r"|(^|/)test_"                                   # test_foo.py
    r"|(^|/)tests?\.[a-z]+$"                         # tests.rs, test.ts
)


def read_tsv(path: Path):
    lines = path.read_text(errors="replace").splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    return [dict(zip(header, ln.split("\t"))) for ln in lines[1:] if ln.strip()]


def to_int(value, default=0):
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default


def parse_units(path: Path):
    """units.txt is blocks of 'key: value' lines separated by blank lines."""
    units, current = [], {}
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            if current.get("file"):
                units.append(current)
            current = {}
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key == "unit":
            current["unit"] = value
        elif key == "file":
            current["file"] = value
        elif key == "start line":
            current["start_line"] = to_int(value)
        elif key == "size":
            current["size_loc"] = to_int(value.replace("LOC", ""))
        elif key == "McCabe index":
            current["mccabe"] = to_int(value)
    if current.get("file"):
        units.append(current)
    return units


# Only a top-level `#[cfg(test)]` directly followed by an inline `mod ... {`
# marks the test-module boundary: item-level cfg(test) attributes and
# `mod tests;` declarations (tests in a separate file) don't split the file.
CFG_TEST_RE = re.compile(r"^#\[cfg\(test\)\]")
INLINE_MOD_RE = re.compile(r"^(pub\s+)?mod\s+\w+\s*\{")


def find_test_module_start(path: Path):
    """Return the 1-based line of the first top-level `#[cfg(test)] mod ... {`, or None."""
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return None
    for n, ln in enumerate(lines, 1):
        if CFG_TEST_RE.match(ln):
            following = next((l for l in lines[n:n + 3] if l.strip()), "")
            if INLINE_MOD_RE.match(following):
                return n
    return None


def count_lines(path: Path):
    try:
        return len(path.read_text(errors="replace").splitlines())
    except OSError:
        return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="Extracted Sokrates data directory")
    ap.add_argument("--src-root", help="Source root; enables embedded-test-module detection in hotspot files")
    ap.add_argument("--top", type=int, default=10, help="Shortlist size per category (default 10)")
    ap.add_argument("-o", "--output", help="Write JSON here (default: stdout)")
    args = ap.parse_args()

    data = Path(args.data)
    text = data / "text"
    for required in ("mainFilesWithHistory.txt", "units.txt", "contributors.txt"):
        if not (text / required).exists():
            print(f"error: missing {text / required} — is --data the extracted data.zip folder?", file=sys.stderr)
            return 2

    # --- per-file complexity from units ---
    units = parse_units(text / "units.txt")
    units_by_file = {}
    for u in units:
        units_by_file.setdefault(u["file"], []).append(u)

    # --- hotspot scoring over main files ---
    files = []
    for row in read_tsv(text / "mainFilesWithHistory.txt"):
        path = row.get("path", "")
        loc = to_int(row.get("# lines of code"))
        commits_90d = to_int(row.get("# commits (90d)"))
        commits = to_int(row.get("# commits"))
        contributors = to_int(row.get("# contributors"))
        file_units = sorted(units_by_file.get(path, []), key=lambda u: -u.get("mccabe", 0))
        max_mccabe = file_units[0]["mccabe"] if file_units else 0
        # Risk grows with how hard the file is to change safely (complexity, size)
        # and how often people actually change it (recent commits).
        score = round((1 + max_mccabe) * (1 + commits_90d) * math.log2(loc + 1))
        files.append({
            "path": path,
            "loc": loc,
            "commits_total": commits,
            "commits_90d": commits_90d,
            "contributors": contributors,
            "last_contributor": row.get("last contributor", ""),
            "last_updated": row.get("last updated", ""),
            "max_mccabe": max_mccabe,
            "top_units": [
                {"unit": u.get("unit", ""), "start_line": u.get("start_line", 0),
                 "size_loc": u.get("size_loc", 0), "mccabe": u.get("mccabe", 0)}
                for u in file_units[:3]
            ],
            "hotspot_score": score,
            # Pure test files stay in the shortlist (a churning test hotspot can
            # still be worth a look) but are flagged so the reader doesn't treat
            # them as production risk.
            "is_test_file": bool(TEST_PATH_RE.search(path)),
        })

    # Degrade loudly, not silently: without git history (mainFilesWithHistory.txt
    # empty, or all commit counts zero) fall back to a complexity-only ranking
    # built from mainFiles.txt so the shortlist is never quietly empty.
    history_present = bool(files) and any(f["commits_total"] > 0 for f in files)
    if not history_present:
        print("warning: no git history in the Sokrates data — falling back to a "
              "complexity-only ranking; churn, ownership, and coupling signals are unavailable",
              file=sys.stderr)
        if not files:
            for row in read_tsv(text / "mainFiles.txt"):
                path = row.get("path", "")
                loc = to_int(row.get("# lines of code"))
                file_units = sorted(units_by_file.get(path, []), key=lambda u: -u.get("mccabe", 0))
                max_mccabe = file_units[0]["mccabe"] if file_units else 0
                files.append({
                    "path": path, "loc": loc, "commits_total": 0, "commits_90d": 0,
                    "contributors": 0, "last_contributor": "", "last_updated": "",
                    "max_mccabe": max_mccabe,
                    "top_units": [
                        {"unit": u.get("unit", ""), "start_line": u.get("start_line", 0),
                         "size_loc": u.get("size_loc", 0), "mccabe": u.get("mccabe", 0)}
                        for u in file_units[:3]
                    ],
                    "hotspot_score": round((1 + max_mccabe) * math.log2(loc + 1)),
                    "is_test_file": bool(TEST_PATH_RE.search(path)),
                })

    # With --src-root, split embedded Rust test modules out before the final
    # ranking, so a file isn't shortlisted on the strength of its test code.
    # Only candidates near the cut line are opened (3x the shortlist size).
    candidates = sorted(files, key=lambda f: -f["hotspot_score"])
    if args.src_root:
        for f in candidates[:args.top * 3]:
            marker = find_test_module_start(Path(args.src_root) / f["path"])
            if not marker:
                continue
            f["test_module_start_line"] = marker
            total_lines = max(1, count_lines(Path(args.src_root) / f["path"]))
            f["loc_production_estimate"] = round(f["loc"] * (marker / total_lines))
            f["loc_test_estimate"] = f["loc"] - f["loc_production_estimate"]
            file_units = sorted(units_by_file.get(f["path"], []), key=lambda u: -u.get("mccabe", 0))
            production_units = [u for u in file_units if u.get("start_line", 0) < marker]
            f["test_units_excluded"] = len(file_units) - len(production_units)
            f["max_mccabe"] = production_units[0]["mccabe"] if production_units else 0
            f["top_units"] = [
                {"unit": u.get("unit", ""), "start_line": u.get("start_line", 0),
                 "size_loc": u.get("size_loc", 0), "mccabe": u.get("mccabe", 0)}
                for u in production_units[:3]
            ]
            f["hotspot_score"] = round(
                (1 + f["max_mccabe"]) * (1 + f["commits_90d"])
                * math.log2(f["loc_production_estimate"] + 1))
        candidates.sort(key=lambda f: -f["hotspot_score"])

    hotspots = candidates[:args.top]

    # --- knowledge risk ---
    # contributors.txt has an extra unnamed trailing column: commit share in percent.
    contributor_lines = (text / "contributors.txt").read_text(errors="replace").splitlines()
    contributor_header = contributor_lines[0].split("\t") if contributor_lines else []
    contributors_rows = [ln.split("\t") for ln in contributor_lines[1:] if ln.strip()]
    bus_factor_top = []
    for parts in contributors_rows[:5]:
        row = dict(zip(contributor_header, parts))
        share = parts[len(contributor_header)] if len(parts) > len(contributor_header) else ""
        bus_factor_top.append({
            "contributor": row.get("Contributor", ""),
            "commits_all_time": to_int(row.get("#commits (all time)")),
            "commits_365d": to_int(row.get("#commits (365 days)")),
            "last_commit": row.get("last commit", ""),
            "share_pct": to_int(share.strip().rstrip("%")),
        })
    # Last commit anywhere in the repo per contributor — lets consumers see
    # whether a single-owner file's owner has gone quiet entirely.
    last_commit_by_contributor = {}
    for parts in contributors_rows:
        row = dict(zip(contributor_header, parts))
        last_commit_by_contributor[row.get("Contributor", "")] = row.get("last commit", "")

    # Test files are excluded: losing a test's only author is a far smaller risk
    # than losing the only person who understands production logic.
    single_owner = [
        {**f, "owner": f["last_contributor"],
         "owner_last_commit_in_repo": last_commit_by_contributor.get(f["last_contributor"], "")}
        for f in sorted(
            [f for f in files
             if f["contributors"] == 1 and f["loc"] >= 200 and not TEST_PATH_RE.search(f["path"])],
            key=lambda f: (-f["commits_90d"], -f["loc"]),
        )[:args.top]
    ]

    # --- change coupling ---
    coupling = []
    coupling_file = text / "temporal_dependencies_different_folders_30_days.txt"
    if coupling_file.exists():
        for row in read_tsv(coupling_file):
            same = to_int(row.get("# same commits"))
            c1 = to_int(row.get("# commits file 1"))
            c2 = to_int(row.get("# commits file 2"))
            if same < 5:
                continue
            f1, f2 = row.get("file 1", ""), row.get("file 2", "")
            # A file and a submodule living in its same-named directory
            # (Rust `#[path]` / mod.rs style) are one logical unit, not coupling.
            p1, p2 = Path(f1), Path(f2)
            same_module = p1.stem == p2.parent.name or p2.stem == p1.parent.name
            coupling.append({
                "file1": f1,
                "file2": f2,
                "same_commits": same,
                "commits1": c1,
                "commits2": c2,
                "coupling_ratio": round(same / max(1, min(c1, c2)), 2),
                "same_module_hint": same_module,
            })
        coupling.sort(key=lambda c: (-c["coupling_ratio"], -c["same_commits"]))
        coupling = coupling[:args.top]

    # Link hotspots that are shotgun-edit partners of other files.
    coupled_lookup = {}
    for c in coupling:
        if c["same_module_hint"]:
            continue
        coupled_lookup.setdefault(c["file1"], []).append(c["file2"])
        coupled_lookup.setdefault(c["file2"], []).append(c["file1"])
    for h in hotspots:
        h["coupled_with"] = coupled_lookup.get(h["path"], [])

    out = {
        "hotspots": hotspots,
        "knowledge_risk": {
            "bus_factor_top_contributors": bus_factor_top,
            "single_owner_files": single_owner,
        },
        "change_coupling": coupling,
        "stats": {
            "main_files_analyzed": len(files),
            "units_analyzed": len(units),
            "contributors_total": len(contributors_rows),
            "history_data": "present" if history_present else "absent",
        },
    }
    payload = json.dumps(out, indent=2)
    if args.output:
        Path(args.output).write_text(payload)
        print(f"wrote {args.output}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
