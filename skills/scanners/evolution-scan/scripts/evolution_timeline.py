#!/usr/bin/env python3
"""Build a deterministic evolution timeline from a Sokrates git history export.

Pre-computation for the evolution-scan skill. Parses Sokrates' git-history.txt
(one line per file per commit) and git-commits.txt (sha + message) and emits a
JSON digest the AI scanner narrates: activity per period, the shift of focus
between areas, contributor arrivals/departures, file births and deaths,
commit-message themes, and the biggest commits per period to skim.

Usage:
  python3 evolution_timeline.py --src-root <path> [--data <extracted-data-dir>]
                                [--period auto|month|quarter] [--depth 2]
                                [--top 8] [-o out.json]

Inputs, in order of preference:
  <src-root>/git-history.txt + <src-root>/git-commits.txt   (Sokrates exports)
  <data-dir>/zips/git-history.zip                            (inside data.zip)
If neither exists the script exits 3 with a message — the scanner then reports
that evolution cannot be measured (never invents history).

--data additionally supplies text/mainFiles*.txt so files seen in history but
absent today count as deleted, and areas get current file/LOC sizes.

git-history.txt line format (space separated, names use &nbsp; for spaces):
  YYYY-MM-DD <email> <sha> <path> <author-name> <added> <removed>
"""

import argparse
import io
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

THEMES = [
    ("fix", re.compile(r"\b(fix|fixes|fixed|bug|bugfix|hotfix|resolve[sd]?|repair|regression|crash|broken|prevent|avoid|handle|guard|reject|tolerate|correct|ensure|fallback)\b", re.I)),
    ("feature", re.compile(r"\b(add|adds|added|implement|implements|introduce[sd]?|support|new|enable|allow|feat|feature)\b", re.I)),
    ("refactor", re.compile(r"\b(refactor|refactoring|rename|move[sd]?|extract|simplify|clean ?up|cleanup|restructure|reorganize|split|consolidate|dedup)\b", re.I)),
    ("test", re.compile(r"\b(test|tests|testing|spec|snapshot|coverage|e2e)\b", re.I)),
    ("docs", re.compile(r"\b(doc|docs|documentation|readme|changelog|comment|typo)\b", re.I)),
    ("deps-chore", re.compile(r"\b(bump|upgrade|update|deps|dependency|dependencies|version|release|ci|workflow|chore|lint|format|prettier|clippy)\b", re.I)),
    ("revert", re.compile(r"\b(revert|rollback|roll back)\b", re.I)),
    ("perf", re.compile(r"\b(perf|performance|faster|speed|optimi[sz]e|latency|memory)\b", re.I)),
    ("security", re.compile(r"\b(security|secure|harden|isolate|restrict|sandbox|permission|approval|auth|token|secret|vulnerab|redact|escalat)\b", re.I)),
]

TEST_PATH_RE = re.compile(r"(^|/)(tests?|__tests__|testdata|spec)/|(_test|\.test|_spec|\.spec)\.|(^|/)test_")
# Paths whose line counts say nothing about intent: lockfiles, snapshots, fixtures, generated/minified code.
NOISE_PATH_RE = re.compile(r"(\.lock$|lock\.(yaml|yml|json)$|(^|/)(snapshots?|__snapshots__|fixtures?|testdata|generated|vendor|third_party|node_modules)/|\.snap$|\.min\.(js|css)$|\.(svg|png|gif|jpg|ico|woff2?)$)", re.I)


def parse_date(s):
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def parse_history_lines(lines):
    """Yield (date, email, sha, path, name, added, removed) tuples."""
    for ln in lines:
        parts = ln.rstrip("\n").split(" ")
        if len(parts) < 7:
            continue
        d = parse_date(parts[0])
        if not d:
            continue
        email, sha, path = parts[1], parts[2], parts[3]
        try:
            added, removed = int(parts[-2]), int(parts[-1])
        except ValueError:
            added, removed = 0, 0
        name = " ".join(parts[4:-2]).replace("&nbsp;", " ")
        yield d, email, sha, path, name, added, removed


def load_history(src_root: Path, data_dir: Path):
    hist_path = src_root / "git-history.txt" if src_root else None
    commits_path = src_root / "git-commits.txt" if src_root else None
    if hist_path and hist_path.is_file():
        history = list(parse_history_lines(hist_path.read_text(errors="replace").splitlines()))
        messages = load_messages(commits_path.read_text(errors="replace").splitlines()) if commits_path and commits_path.is_file() else {}
        return history, messages, str(hist_path)
    zip_path = data_dir / "zips" / "git-history.zip" if data_dir else None
    if zip_path and zip_path.is_file():
        history, messages = [], {}
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                text = io.TextIOWrapper(zf.open(name), encoding="utf-8", errors="replace").read().splitlines()
                if "commit" in name.lower() and "history" not in name.lower():
                    messages.update(load_messages(text))
                else:
                    history.extend(parse_history_lines(text))
        return history, messages, str(zip_path)
    return None, None, None


def load_messages(lines):
    msgs = {}
    for ln in lines:
        ln = ln.rstrip("\n")
        if not ln:
            continue
        sha, _, msg = ln.partition(" ")
        if len(sha) >= 7:
            msgs[sha] = msg
    return msgs


def load_current_files(data_dir: Path):
    """path -> {'loc': int, 'kind': main|test|generated|build|other} from Sokrates text exports."""
    files = {}
    if not data_dir:
        return files
    kinds = [("main", "mainFiles"), ("test", "testFiles"), ("generated", "generatedFiles"),
             ("build", "buildAndDeploymentFiles"), ("other", "otherFiles")]
    for kind, base in kinds:
        # Sokrates exports <kind>Files.txt for main files and <kind>FilesWithHistory.txt for all kinds.
        p = next((c for c in (data_dir / "text" / f"{base}.txt", data_dir / "text" / f"{base}WithHistory.txt")
                  if c.is_file()), None)
        if p is None:
            continue
        lines = p.read_text(errors="replace").splitlines()
        if not lines:
            continue
        header = lines[0].split("\t")
        try:
            pi = next(i for i, h in enumerate(header) if h.strip().lower() in ("path", "file", "file path"))
        except StopIteration:
            pi = 0
        li = next((i for i, h in enumerate(header) if "lines" in h.lower()), None)
        for ln in lines[1:]:
            cols = ln.split("\t")
            if len(cols) <= pi or not cols[pi].strip():
                continue
            loc = 0
            if li is not None and len(cols) > li:
                try:
                    loc = int(cols[li].strip())
                except ValueError:
                    loc = 0
            files[cols[pi].strip()] = {"loc": loc, "kind": kind}
    return files


def area_of(path: str, depth: int) -> str:
    parts = path.split("/")
    if len(parts) <= 1:
        return "(root)"
    return "/".join(parts[:min(depth, len(parts) - 1)])


def period_key(d: date, mode: str) -> str:
    if mode == "month":
        return f"{d.year}-{d.month:02d}"
    q = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{q}"


def classify(msg: str):
    found = [name for name, rx in THEMES if rx.search(msg or "")]
    return found[0] if found else "other"


def pct(a, b):
    return round(100.0 * a / b, 1) if b else 0.0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src-root", required=True, help="Analyzed source root (where git-history.txt lives)")
    ap.add_argument("--data", help="Extracted Sokrates data directory (fallback history + current file inventory)")
    ap.add_argument("--period", default="auto", choices=["auto", "month", "quarter"])
    ap.add_argument("--depth", type=int, default=2, help="Path depth that defines an 'area' (default 2)")
    ap.add_argument("--top", type=int, default=8, help="List sizes (default 8)")
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    src_root = Path(args.src_root)
    data_dir = Path(args.data) if args.data else None
    history, messages, source = load_history(src_root, data_dir)
    if not history:
        print("error: no git history found (git-history.txt in src root, or zips/git-history.zip in data)",
              file=sys.stderr)
        return 3

    # Identity merge: several e-mails with the same (normalized) author name are one person.
    # The canonical id is the e-mail with the most history lines; merges are reported in stats.
    name_emails = defaultdict(Counter)
    for d, email, sha, path, name, added, removed in history:
        key = re.sub(r"[^a-z0-9]", "", (name or "").lower())
        if key:
            name_emails[key][email] += 1
    alias = {}
    identity_merges = []
    for key, emails in name_emails.items():
        if len(emails) > 1:
            canon = emails.most_common(1)[0][0]
            for e in emails:
                if e != canon:
                    alias[e] = canon
            identity_merges.append({"canonical": canon, "aliases": sorted(e for e in emails if e != canon),
                                    "name_key": key})
    if alias:
        history = [(d, alias.get(email, email), sha, path, name, added, removed)
                   for d, email, sha, path, name, added, removed in history]

    history.sort(key=lambda r: (r[0], r[2]))
    first, last = history[0][0], history[-1][0]
    span_days = (last - first).days or 1
    mode = args.period if args.period != "auto" else ("month" if span_days < 730 else "quarter")
    current = load_current_files(data_dir)
    depth = args.depth

    # ---- aggregate per commit
    commits = {}
    for d, email, sha, path, name, added, removed in history:
        c = commits.setdefault(sha, {"sha": sha, "date": d, "author": email, "name": name,
                                     "files": 0, "added": 0, "removed": 0, "signal_churn": 0,
                                     "areas": Counter(), "paths": [], "all_paths": []})
        c["files"] += 1
        c["added"] += added
        c["removed"] += removed
        if not NOISE_PATH_RE.search(path):
            c["signal_churn"] += added + removed
        c["all_paths"].append(path)
        c["areas"][area_of(path, depth)] += 1
        if len(c["paths"]) < 6:
            c["paths"].append(path)
    for c in commits.values():
        c["message"] = messages.get(c["sha"], "")
        c["theme"] = classify(c["message"])

    # ---- per period
    periods = {}
    first_seen_file, last_seen_file = {}, {}
    file_commits = Counter()
    file_added, file_removed = Counter(), Counter()
    author_first, author_last, author_commits = {}, {}, Counter()
    author_areas = defaultdict(Counter)
    area_first, area_last = {}, {}
    area_commits, area_commits_90, area_commits_365 = Counter(), Counter(), Counter()
    area_authors = defaultdict(set)
    area_added, area_removed = Counter(), Counter()
    d90, d365, d180 = last - timedelta(days=90), last - timedelta(days=365), last - timedelta(days=180)

    for d, email, sha, path, name, added, removed in history:
        area = area_of(path, depth)
        file_commits[path] += 1
        file_added[path] += added
        file_removed[path] += removed
        first_seen_file.setdefault(path, d)
        last_seen_file[path] = max(last_seen_file.get(path, d), d)
        area_first.setdefault(area, d)
        area_last[area] = max(area_last.get(area, d), d)
        area_authors[area].add(email)
        area_added[area] += added
        area_removed[area] += removed

    for c in commits.values():
        d, email = c["date"], c["author"]
        pk = period_key(d, mode)
        p = periods.setdefault(pk, {"period": pk, "commits": 0, "authors": set(), "files_touched": 0,
                                    "added": 0, "removed": 0, "areas": Counter(), "themes": Counter(),
                                    "new_authors": [], "notable": []})
        p["commits"] += 1
        p["authors"].add(email)
        p["files_touched"] += c["files"]
        p["added"] += c["added"]
        p["removed"] += c["removed"]
        p["themes"][c["theme"]] += 1
        for a, n in c["areas"].items():
            p["areas"][a] += 1
            area_commits[a] += 1
            if d >= d90:
                area_commits_90[a] += 1
            if d >= d365:
                area_commits_365[a] += 1
        author_commits[email] += 1
        author_first.setdefault(email, d)
        author_last[email] = max(author_last.get(email, d), d)
        for a in c["areas"]:
            author_areas[email][a] += 1
        p["notable"].append(c)

    # new files / deleted files per period
    for path, d in first_seen_file.items():
        pk = period_key(d, mode)
        periods[pk].setdefault("new_files", 0)
        periods[pk]["new_files"] += 1
    deleted = [p for p in first_seen_file if current and p not in current]
    # Rename/move detection: a vanished file whose last commit also introduced a file with the same
    # basename is counted as moved, not deleted (cheap heuristic; exact renames need git itself).
    first_commit_of_file = {}
    for d, email, sha, path, name, added, removed in history:
        first_commit_of_file.setdefault(path, sha)
    introduced_in = defaultdict(set)  # sha -> basenames first introduced by that commit
    for path, sha in first_commit_of_file.items():
        introduced_in[sha].add(path.rsplit("/", 1)[-1])
    last_commit_of_file = {}
    for d, email, sha, path, name, added, removed in history:
        last_commit_of_file[path] = sha
    moved = [p for p in deleted if p.rsplit("/", 1)[-1] in introduced_in.get(last_commit_of_file[p], ())]
    moved_set = set(moved)
    deleted = [p for p in deleted if p not in moved_set]
    for path in moved:
        pk = period_key(last_seen_file[path], mode)
        periods[pk].setdefault("files_moved_estimate", 0)
        periods[pk]["files_moved_estimate"] += 1
    for path in deleted:
        pk = period_key(last_seen_file[path], mode)
        periods[pk].setdefault("files_last_seen_now_gone", 0)
        periods[pk]["files_last_seen_now_gone"] += 1
    for email, d in author_first.items():
        periods[period_key(d, mode)]["new_authors"].append(email)

    total_commits = len(commits)
    period_list = []
    for pk in sorted(periods):
        p = periods[pk]
        non_merge = [c for c in p["notable"] if not re.match(r"^\s*merge\b", c["message"] or "", re.I)] or p["notable"]
        notable = sorted(non_merge, key=lambda c: -c["signal_churn"])[:args.top]
        notable_files = sorted(non_merge, key=lambda c: -c["files"])[:max(3, args.top // 2)]
        top_areas = p["areas"].most_common(args.top)
        per_author = Counter(c["author"] for c in p["notable"])
        top3 = sum(n for _, n in per_author.most_common(3))
        domains = Counter((c["author"].rsplit("@", 1)[-1] if "@" in c["author"] else "?") for c in p["notable"])
        new_auth = sorted(p["new_authors"], key=lambda e: -author_commits[e])
        period_list.append({
            "period": pk,
            "commits": p["commits"],
            "low_sample": p["commits"] < 10,
            "share_of_all_commits_pct": pct(p["commits"], total_commits),
            "authors": len(p["authors"]),
            "top3_authors_share_pct": pct(top3, p["commits"]),
            "author_domains": [{"domain": dom, "share_pct": pct(n, p["commits"])} for dom, n in domains.most_common(3)],
            "new_authors_count": len(new_auth),
            "new_authors_top": [{"author": e, "total_commits": author_commits[e]} for e in new_auth[:3]],
            "files_touched": p["files_touched"],
            "new_files": p.get("new_files", 0),
            "files_last_seen_now_gone": p.get("files_last_seen_now_gone", 0),
            "files_moved_estimate": p.get("files_moved_estimate", 0),
            "lines_added": p["added"],
            "lines_removed": p["removed"],
            "top_areas": [{"area": a, "commits": n, "pct_of_period_commits_touching": pct(n, p["commits"])} for a, n in top_areas],
            "themes": dict(p["themes"].most_common()),
            "notable_commits": [{
                "sha": c["sha"][:10], "date": c["date"].isoformat(), "author": c["name"] or c["author"],
                "message": c["message"], "files": c["files"], "added": c["added"], "removed": c["removed"],
                "sample_paths": c["paths"][:4]
            } for c in notable],
            "notable_by_files_touched": [{
                "sha": c["sha"][:10], "date": c["date"].isoformat(), "author": c["name"] or c["author"],
                "message": c["message"], "files": c["files"], "sample_paths": c["paths"][:4]
            } for c in notable_files],
        })

    # ---- areas
    area_list = []
    area_current_files, area_current_loc = Counter(), Counter()
    for path, info in current.items():
        a = area_of(path, depth)
        area_current_files[a] += 1
        area_current_loc[a] += info.get("loc", 0)
    area_author_commits = defaultdict(Counter)
    for c in commits.values():
        for a in c["areas"]:
            area_author_commits[a][c["author"]] += 1
    for a in sorted(set(area_commits) | set(area_current_files), key=lambda x: -area_commits.get(x, 0)):
        c_all, c90, c365 = area_commits.get(a, 0), area_commits_90.get(a, 0), area_commits_365.get(a, 0)
        flags = []
        top_author, top_n = (area_author_commits[a].most_common(1) or [(None, 0)])[0]
        top_share = pct(top_n, c_all)
        if c365 >= 8 and top_share >= 70:
            flags.append("single-owner")
        if current and area_current_files.get(a, 0) == 0 and a in area_last and area_last[a] >= d90:
            flags.append("not-inventoried")  # still committed to, but absent from Sokrates' inventory (ignored by config?)
        if a in area_first and area_first[a] >= d180:
            flags.append("emerging")
        if area_current_files.get(a, 0) >= 5 and a in area_last and area_last[a] < d365:
            flags.append("dormant")
        if c365 >= 8 and c90 * 4 > c365 * 1.6:
            flags.append("accelerating")
        if c365 >= 8 and c90 * 4 < c365 * 0.4:
            flags.append("cooling")
        if c_all == 0 and area_current_files.get(a, 0):
            flags.append("no-history")
        if "not-inventoried" in flags and "cooling" in flags:
            flags.remove("cooling")  # size 0 is an inventory artifact, not a trend
        area_list.append({
            "area": a, "commits": c_all, "commits_365d": c365, "commits_90d": c90,
            "share_of_all_commits_pct": pct(c_all, total_commits),
            "authors": len(area_authors.get(a, ())), "top_author": top_author, "top_author_share_pct": top_share,
            "first_commit": area_first[a].isoformat() if a in area_first else None,
            "last_commit": area_last[a].isoformat() if a in area_last else None,
            "lines_added": area_added.get(a, 0), "lines_removed": area_removed.get(a, 0),
            "current_files": area_current_files.get(a, 0), "current_loc": area_current_loc.get(a, 0),
            "flags": flags,
        })

    # focus shift: area share per period for the overall top areas
    top_area_names = [a["area"] for a in area_list[:args.top]]
    focus = []
    for p in period_list:
        shares = {a: 0.0 for a in top_area_names}
        for ta in p["top_areas"]:
            if ta["area"] in shares:
                shares[ta["area"]] = ta["pct_of_period_commits_touching"]
        focus.append({"period": p["period"], "commits": p["commits"], "pct_of_period_commits_touching": shares})

    # ---- people
    gone_after = max(180, span_days // 4)   # "gone" = silent for 180 days, or a quarter of a long history
    d_gone = last - timedelta(days=gone_after)
    d_prev90 = d90 - timedelta(days=90)
    a90, aprev = Counter(), Counter()
    for c in commits.values():
        if c["date"] >= d90:
            a90[c["author"]] += 1
        elif c["date"] >= d_prev90:
            aprev[c["author"]] += 1
    people = []
    for email in sorted(author_commits, key=lambda e: -author_commits[e]):
        last_d = author_last[email]
        status = "active" if last_d >= d90 else ("fading" if last_d >= d_gone else "gone")
        people.append({
            "author": email, "commits": author_commits[email], "share_pct": pct(author_commits[email], total_commits),
            "commits_90d": a90[email], "commits_prev_90d": aprev[email],
            "first_commit": author_first[email].isoformat(), "last_commit": last_d.isoformat(),
            "tenure_days": (last_d - author_first[email]).days, "status": status,
            "top_areas": [a for a, _ in author_areas[email].most_common(3)],
        })
    significant = max(5, total_commits * 0.01)
    arrivals = [p for p in people if parse_date(p["first_commit"]) >= d365]
    departures = [p for p in people if p["status"] == "gone" and p["commits"] >= significant]
    fading = sorted([p for p in people if p["commits"] >= significant and p["status"] != "gone"
                     and p["commits_prev_90d"] >= 10 and p["commits_90d"] < 0.5 * p["commits_prev_90d"]],
                    key=lambda p: p["commits_90d"] - p["commits_prev_90d"])
    rising = sorted([p for p in people if p["commits_90d"] >= 10 and p["commits_90d"] > 2 * max(p["commits_prev_90d"], 2)],
                    key=lambda p: -(p["commits_90d"] - p["commits_prev_90d"]))
    active_now = [p for p in people if p["status"] == "active"]
    drive_by = sum(1 for e in author_commits if author_commits[e] == 1)

    # ---- lifecycle
    ages = sorted(((last - d).days for d in first_seen_file.values()))
    def quantile(xs, q):
        return xs[int(q * (len(xs) - 1))] if xs else 0
    oldest_current = sorted(((first_seen_file[p], p) for p in first_seen_file if not current or p in current))[:args.top]
    most_rewritten = sorted(((file_removed[p], p) for p in file_commits if (not current or p in current)
                             and file_commits[p] >= 5), reverse=True)[:args.top]
    most_committed = file_commits.most_common(args.top)
    deleted_areas = Counter(area_of(p, depth) for p in deleted).most_common(args.top)
    lifecycle = {
        "files_seen_in_history": len(first_seen_file),
        "files_current": len(current) if current else None,
        "files_deleted": len(deleted) if current else None,
        "files_moved_estimate": len(moved) if current else None,
        "deleted_by_area": [{"area": a, "files": n} for a, n in deleted_areas],
        "file_age_days_quantiles": {"p10": quantile(ages, 0.1), "p50": quantile(ages, 0.5), "p90": quantile(ages, 0.9)},
        "oldest_surviving_files": [{"path": p, "since": d.isoformat(), "commits": file_commits[p]} for d, p in oldest_current],
        "most_committed_files": [{"path": p, "commits": n, "since": first_seen_file[p].isoformat(),
                                  "last": last_seen_file[p].isoformat()} for p, n in most_committed],
        "most_rewritten_files": [{"path": p, "lines_removed": r, "lines_added": file_added[p],
                                  "commits": file_commits[p]} for r, p in most_rewritten],
    }

    # ---- themes overall + trend (first half vs second half of the last 365d)
    themes_all = Counter(c["theme"] for c in commits.values())
    recent = [c for c in commits.values() if c["date"] >= d365]
    mid = last - timedelta(days=182)
    t_old = Counter(c["theme"] for c in recent if c["date"] < mid)
    t_new = Counter(c["theme"] for c in recent if c["date"] >= mid)
    theme_trend = {t: {"older_half_pct": pct(t_old[t], sum(t_old.values())),
                       "recent_half_pct": pct(t_new[t], sum(t_new.values()))}
                   for t in sorted(set(t_old) | set(t_new))}

    # ---- activity trend
    def commits_between(a, b):
        return sum(1 for c in commits.values() if a <= c["date"] < b)
    trend = {
        "commits_last_90d": commits_between(d90, last + timedelta(days=1)),
        "commits_prev_90d": commits_between(d90 - timedelta(days=90), d90),
        "commits_last_365d": commits_between(d365, last + timedelta(days=1)),
        "authors_last_90d": len({c["author"] for c in commits.values() if c["date"] >= d90}),
        "authors_prev_90d": len({c["author"] for c in commits.values() if d90 - timedelta(days=90) <= c["date"] < d90}),
    }
    busiest = max(period_list, key=lambda p: p["commits"]) if period_list else None

    out = {
        "stats": {
            "history_data": "present",
            "history_source": source,
            "history_span": {"first_commit": first.isoformat(), "last_commit": last.isoformat(), "days": span_days},
            "period_mode": mode, "area_depth": depth,
            "commits": total_commits, "authors": len(author_commits),
            "identity_merges": identity_merges,
            "files_seen_in_history": len(first_seen_file),
            "busiest_period": {"period": busiest["period"], "commits": busiest["commits"]} if busiest else None,
            "messages_available": bool(messages),
            "current_inventory_available": bool(current),
            "themes_overall": dict(themes_all.most_common()),
            "theme_other_pct": pct(themes_all.get("other", 0), total_commits),
            "theme_trend_reliable": pct(themes_all.get("other", 0), total_commits) < 30,
            "theme_trend_last_year": theme_trend,
            "activity_trend": trend,
            "active_authors_now": len(active_now),
            "drive_by_authors_single_commit": drive_by,
            "arrivals_last_365d": len(arrivals),
            "departures": len(departures),
            "fading_major_contributors": len(fading),
        },
        "periods": period_list,
        "focus_shift": {"areas": top_area_names, "by_period": focus},
        "areas": [a for a in area_list if a["commits"] >= 5 or a["flags"]][:120],
        "people": {"top": people[:args.top * 2], "arrivals_last_365d": arrivals[:args.top],
                   "departures": departures[:args.top], "fading": fading[:args.top], "rising": rising[:args.top],
                   "gone_threshold_days": gone_after},
        "lifecycle": lifecycle,
    }
    text = json.dumps(out, indent=2)
    if args.output:
        Path(args.output).write_text(text)
        print(f"wrote {args.output}: {total_commits} commits, {len(author_commits)} authors, "
              f"{first} → {last}, {len(period_list)} {mode}s", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
