#!/usr/bin/env python3
"""Propose virtual landscapes for a Sokrates landscape from what the repository analyses reveal.

Discovers repository analyses under an analysis root (like Sokrates' updateLandscape does), extracts
per repository: name, folder, main LOC, dominant technology, extensions, tags, contributors (count,
top e-mail domains, top committers), latest commit — and proposes groupings, each with members,
LOC/repo shares, coverage, remainder, and a ready `virtualLandscapes` config:

  naming        repository-name conventions: shared prefixes/suffixes/tokens -> real regex patterns
                (`api-.*`, `.*-service`), the only proposal that keeps working for new repositories
  folders       the folder each analysis sits in (a candidate for folder sub-landscapes as well)
  technology    dominant language family per repository
  activity      active / fading / dormant by latest commit, and size tiers by main LOC
  organisation  dominant contributor e-mail domain per repository (in-house vs community, org units)
  teams         repositories that share their main committers (greedy clusters)
  tags          Sokrates tag rules that fired in the repository analysis (docker, react, maven, …)
  user          --groups <file.json>: your own grouping {"Platform": ["core-.*", "repo-x"], ...}
                (patterns are Sokrates name regexes; plain names are escaped) — measured the same way

Usage:
  python3 propose_virtual_landscapes.py <analysis-root> [--groups groups.json] [-o proposals.json]
                                        [--min-members 2] [--depth 1]

Sokrates semantics reproduced: virtual-landscape membership = includeRepoNamePatterns non-empty AND
repository metadata.name matches any include (CASE-SENSITIVE, full-string) AND matches no exclude;
a repository can be in several; the rest go to the Remainder. Names are `metadata.name` from each
repository's config, not folder names.
"""

import argparse
import json
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

TECH_FAMILIES = [
    ("Rust", {"rs"}), ("Java", {"java"}), ("Kotlin", {"kt", "kts"}), ("Scala", {"scala"}), ("Go", {"go"}),
    ("TypeScript", {"ts", "tsx"}), ("JavaScript", {"js", "jsx", "mjs", "cjs"}), ("Python", {"py"}), ("C#", {"cs"}),
    ("C/C++", {"c", "h", "cc", "cpp", "cxx", "hpp", "hh"}), ("Haskell", {"hs"}), ("OCaml", {"ml", "mli"}), ("Thrift/Proto", {"thrift", "proto"}), ("Notebooks", {"ipynb"}), ("Swift", {"swift"}), ("Objective-C", {"m", "mm"}), ("Ruby", {"rb"}),
    ("PHP", {"php"}), ("Dart", {"dart"}), ("Shell", {"sh", "bash"}), ("SQL", {"sql", "plsql", "tsql"}), ("Erlang/Elixir", {"erl", "ex", "exs"}),
    ("Web (HTML/CSS)", {"html", "css", "scss", "vue"}), ("Docs", {"md", "rst", "adoc"}), ("Config", {"yaml", "yml", "json", "toml"}),
]
STOP_TOKENS = {"the", "and", "for", "lib", "libs", "src", "app", "apps", "repo", "project", "main", "core", "new", "old", "test", "tests",
               "v1", "v2", "v3", "js", "ts", "py", "rs", "go", "java", "kt"}


def tech_of(ext):
    for fam, exts in TECH_FAMILIES:
        if ext in exts:
            return fam
    return ext or "?"


def discover(root: Path):
    found = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        rel = (os.path.relpath(dirpath, root) + "/").replace(os.sep, "/")
        if "/_sokrates_landscape/landscapes/" in "/" + rel:
            dirnames[:] = []; continue
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules")]
        if Path(dirpath).name == "data" and ("data.zip" in filenames or "analysisResults.json" in filenames):
            found.append(Path(dirpath))
    return found


def read_entry(data_dir: Path, name: str):
    z = data_dir / "data.zip"
    if z.is_file():
        try:
            with zipfile.ZipFile(z) as zf:
                if name in zf.namelist():
                    return zf.read(name).decode("utf-8", errors="replace")
        except zipfile.BadZipFile:
            return None
    f = data_dir / name
    return f.read_text(errors="replace") if f.is_file() else None


def repo_info(data_dir: Path, root: Path):
    raw = read_entry(data_dir, "analysisResults.json")
    if raw is None:
        return None
    try:
        ar = json.loads(raw)
    except json.JSONDecodeError:
        return None
    main = ar.get("mainAspectAnalysisResults") or {}
    exts = {}
    for item in main.get("linesOfCodePerExtension") or []:
        n = str(item.get("name", "")).strip().replace("*.", "").lower()
        exts[n] = exts.get(n, 0) + int(item.get("value", 0) or 0)
    dominant = max(exts, key=exts.get) if exts else ""
    contributors = []
    for c in (ar.get("contributorsAnalysisResults") or {}).get("contributors") or []:
        contributors.append({"email": str(c.get("email", "")).lower(), "commits": int(c.get("commitsCount", 0) or 0),
                             "latest": str(c.get("latestCommitDate", "") or "")})
    contributors.sort(key=lambda c: -c["commits"])
    domains = Counter()
    for c in contributors:
        if "@" in c["email"]:
            domains[c["email"].rsplit("@", 1)[-1]] += c["commits"]
    tags = []
    for t in ar.get("foundTags") or []:
        if isinstance(t, dict):
            tags.append(str(t.get("tag") or t.get("name") or ""))
        elif isinstance(t, str):
            tags.append(t)
    rel_folder = str(data_dir.parent.relative_to(root)).replace(os.sep, "/")
    # analyses live at <repo>/_sokrates/reports/data → repo folder is 3 levels up; plain <repo>/data → 1 level
    parts = rel_folder.split("/")
    repo_folder = "/".join(parts[:-2]) if len(parts) >= 3 and parts[-2] == "reports" and parts[-3] == "_sokrates" else rel_folder
    meta = ar.get("metadata") or {}
    return {"name": str(meta.get("name", "") or ""), "description": str(meta.get("description", "") or "").strip()[:160],
            "links": [l.get("href") for l in (meta.get("links") or []) if isinstance(l, dict) and l.get("href")][:2],
            "folder": repo_folder or ".",
            "main_loc": int(main.get("linesOfCode", 0) or 0), "dominant_ext": dominant, "tech": tech_of(dominant),
            "extensions": exts, "contributors": len(contributors), "top_committers": [c["email"] for c in contributors[:5]],
            "domains": domains.most_common(3), "latest_commit": max((c["latest"] for c in contributors), default=""),
            "tags": [t for t in tags if t]}


def rx_literal(name):
    return re.escape(name)


def measure(landscapes, repos, total_loc):
    """landscapes: list of (name, include_patterns, exclude_patterns). Returns rows + remainder + coverage."""
    rows, assigned = [], set()
    for name, inc, exc in landscapes:
        members = []
        for r in repos:
            try:
                if inc and any(re.fullmatch(p, r["name"]) for p in inc) and not any(re.fullmatch(p, r["name"]) for p in exc):
                    members.append(r)
            except re.error:
                pass
        assigned.update(r["name"] for r in members)
        loc = sum(r["main_loc"] for r in members)
        rows.append({"landscape": name, "repositories": len(members), "loc": loc, "loc_share_pct": round(100 * loc / max(1, total_loc), 1),
                     "members": [r["name"] for r in members][:40], "members_all": [r["name"] for r in members],
                     "includeRepoNamePatterns": inc, "excludeRepoNamePatterns": exc})
    rest = [r for r in repos if r["name"] not in assigned]
    return rows, rest, round(100 * len(assigned) / max(1, len(repos)), 1)


def to_config(rows, remainder_name="Remainder"):
    return {"remainderLandscapeMetadata": {"name": remainder_name},
            "landscapes": [{"metadata": {"name": r["landscape"], "description": r.get("description", "")}, "includeRepoNamePatterns": r["includeRepoNamePatterns"],
                            "excludeRepoNamePatterns": r["excludeRepoNamePatterns"]} for r in rows if r["repositories"]]}


def measure_tree(vl, repos, total_loc, prefix="", warnings=None):
    """Measure a real `virtualLandscapes` object (nested), the way VirtualLandscapeBuilder does. Returns flat rows."""
    rows = []
    landscapes = []
    for v in (vl or {}).get("landscapes") or []:
        meta = v.get("metadata") or {}
        landscapes.append((prefix + str(meta.get("name", "?")), v.get("includeRepoNamePatterns") or [], v.get("excludeRepoNamePatterns") or [], v))
    for name, inc, exc, v in landscapes:
        for pat in inc + exc:
            try:
                re.compile(pat)
            except re.error as e:
                if warnings is not None:
                    warnings.append(f"landscape `{name}`: pattern `{pat}` does not compile ({e}) — Sokrates would silently match nothing")
    flat, rest, coverage = measure([(n, i, e) for n, i, e, _ in landscapes], repos, total_loc)
    for row, (name, inc, exc, v) in zip(flat, landscapes):
        row["level"] = prefix.count("/")
        rows.append(row)
        members = [r for r in repos if r["name"] in set(row["members_all"])]
        if (v.get("virtualLandscapes") or {}).get("landscapes"):
            rows.extend(measure_tree(v["virtualLandscapes"], members, total_loc, name + "/", warnings))
    if landscapes:
        rname = ((vl or {}).get("remainderLandscapeMetadata") or {}).get("name") or "Remainder"
        rows.append({"landscape": prefix + rname, "repositories": len(rest), "loc": sum(r["main_loc"] for r in rest),
                     "loc_share_pct": round(100 * sum(r["main_loc"] for r in rest) / max(1, total_loc), 1), "members": [r["name"] for r in rest][:40],
                     "members_all": [r["name"] for r in rest], "includeRepoNamePatterns": [], "excludeRepoNamePatterns": [], "level": prefix.count("/"),
                     "is_remainder": True, "coverage_pct": coverage})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("analysis_root")
    ap.add_argument("--groups", help="JSON file {landscape name: [name regex or plain name, ...]} — your own grouping to measure")
    ap.add_argument("-o", "--output")
    ap.add_argument("--min-members", type=int, default=2)
    ap.add_argument("--depth", type=int, default=1, help="folder depth for the folders proposal")
    args = ap.parse_args()
    root = Path(args.analysis_root).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr); return 2
    repos = [r for r in (repo_info(d, root) for d in sorted(discover(root))) if r]
    if not repos:
        print(f"error: no repository analyses under {root}", file=sys.stderr); return 2
    warnings = []
    # apply the landscape's own filters so counts match what Sokrates will show
    lconf_path = root / "_sokrates_landscape" / "config.json"
    lconf = {}
    if lconf_path.is_file():
        try:
            lconf = json.loads(lconf_path.read_text())
        except json.JSONDecodeError as e:
            warnings.append(f"{lconf_path}: invalid JSON ({e}) — thresholds not applied")
    th_loc = int(lconf.get("repositoryThresholdLocMain", lconf.get("projectThresholdLocMain", 0)) or 0)
    th_contrib = int(lconf.get("repositoryThresholdContributors", lconf.get("projectThresholdContributors", 1)) or 1)
    th_date = str(lconf.get("ignoreRepositoriesLastUpdatedBefore", lconf.get("ignoreProjectsLastUpdatedBefore", "")) or "")
    seen, kept, dropped = set(), [], []
    for r in repos:
        why = []
        if lconf.get("includeOnlyOneRepositoryWithSameName", True) and r["name"] in seen:
            why.append("duplicate name")
        seen.add(r["name"])
        if r["main_loc"] < th_loc: why.append(f"LOC < {th_loc}")
        if r["contributors"] and r["contributors"] < th_contrib: why.append(f"contributors < {th_contrib}")
        if th_date and r["latest_commit"] and r["latest_commit"][:10] < th_date: why.append(f"last commit < {th_date}")
        (dropped if why else kept).append((r, why))
    if dropped:
        warnings.append(f"{len(dropped)} repositories are excluded by the landscape's thresholds and not counted here: " + ", ".join(f"{r['name']} ({'; '.join(w)})" for r, w in dropped[:6]) + (" …" if len(dropped) > 6 else ""))
    repos = [r for r, _ in kept]
    existing_subs = sorted(str(p.parent.relative_to(root)) for p in root.rglob("_sokrates_landscape/index.html") if p.parent.parent != root and "/landscapes/" not in str(p))
    if existing_subs:
        warnings.append(f"folder sub-landscapes already exist ({len(existing_subs)}: {', '.join(existing_subs[:8])}{' …' if len(existing_subs) > 8 else ''}) — virtual landscapes should add a *different* view, not repeat the folders")
    existing_vl = (lconf.get("virtualLandscapes") or {}).get("landscapes") or []
    names = Counter(r["name"] for r in repos)
    dupes = [n for n, c in names.items() if c > 1]
    if dupes:
        warnings.append(f"{len(dupes)} repository names are not unique ({', '.join(dupes[:5])}) — Sokrates keeps the first found; name-based grouping cannot tell them apart")
    if any(not r["name"] for r in repos):
        warnings.append("some repositories have a blank metadata.name — set it in their _sokrates/config.json first")
    total_loc = sum(r["main_loc"] for r in repos) or 1
    last = max((r["latest_commit"] for r in repos), default="")
    proposals = []

    def add(kind, landscapes, note=""):
        rows, rest, coverage = measure(landscapes, repos, total_loc)
        rows = [r for r in rows if r["repositories"] >= 1]
        if len([r for r in rows if r["repositories"] >= args.min_members]) < 2:
            return
        proposals.append({"kind": kind, "landscapes": len(rows), "coverage_pct": coverage, "remainder": len(rest),
                          "remainder_names": [r["name"] for r in rest][:20], "rows": sorted(rows, key=lambda r: -r["loc"]), "note": note,
                          "config": to_config(rows)})

    # ---- naming conventions
    has_org = sum(1 for r in repos if " / " in r["name"]) > 0.5 * len(repos)
    def repo_part(name):
        return name.split(" / ", 1)[1] if has_org and " / " in name else name
    if has_org:
        orgs = Counter(r["name"].split(" / ", 1)[0] for r in repos if " / " in r["name"])
        add("organisations", [(o, [f"{re.escape(o)} / .*"], []) for o, c in orgs.most_common() if c >= args.min_members],
            "GitHub organisation prefix of `org / repo` names — usually the same as the folders; a starting point for nesting, not the map itself")
    tokens_of = {r["name"]: [t for t in re.split(r"[-_./ ]+", repo_part(r["name"]).lower()) if t] for r in repos}
    prefix_count, suffix_count, token_count = Counter(), Counter(), Counter()
    ext_count = Counter()
    for n, toks in tokens_of.items():
        if len(toks) >= 2:
            prefix_count[toks[0]] += 1; suffix_count[toks[-1]] += 1
        for t in set(toks):
            token_count[t] += 1
        m = re.search(r"\.([a-z]{1,4})$", repo_part(n).lower())
        if m:
            ext_count[m.group(1)] += 1
    conv = []
    used = set()
    for ext, c in ext_count.most_common():
        if c >= 2:
            conv.append((f"*.{ext}", [f"(?i).*[.]{re.escape(ext)}(-.*)?"], [])); used.add(ext)
    head = "(?i).* / " if has_org else "(?i)"   # with org / repo names, conventions apply to the repo part only
    for tok, c in prefix_count.most_common():
        if c >= max(2, args.min_members) and tok not in STOP_TOKENS and c < 0.9 * len(repos):
            conv.append((f"{tok}-*", [f"{head}{re.escape(tok)}[-_./ ].*"], [])); used.add(tok)
    for tok, c in suffix_count.most_common():
        if c >= max(2, args.min_members) and tok not in STOP_TOKENS and tok not in used and c < 0.9 * len(repos):
            conv.append((f"*-{tok}", [f"(?i).*[-_./ ]{re.escape(tok)}"], [])); used.add(tok)
    for tok, c in token_count.most_common():
        if c >= max(3, args.min_members) and tok not in used and tok not in STOP_TOKENS and len(tok) >= 3 and c < 0.9 * len(repos):
            conv.append((f"*{tok}*", [f"(?i).*(^|[-_./ ]){re.escape(tok)}([-_./ ]|$).*"], [])); used.add(tok)
    add("naming", conv[:30], "regex patterns on repository names (case-insensitive via (?i); org prefixes analysed separately); the only kind that classifies future repositories automatically — product families usually show up as suffix/extension conventions (*.gl, *-sdk, h3-*); drop token groups that are coincidences")

    # ---- folders
    by_folder = defaultdict(list)
    for r in repos:
        parts = r["folder"].split("/")
        by_folder["/".join(parts[:args.depth]) if r["folder"] != "." else "(root)"].append(r)
    add("folders", [(f, [rx_literal(r["name"]) for r in rs], []) for f, rs in sorted(by_folder.items()) if len(rs) >= args.min_members],
        "explicit name lists per folder — if the folder structure is meaningful, prefer real folder sub-landscapes (a _sokrates_landscape per folder) which need no maintenance")

    # ---- technology
    by_tech = defaultdict(list)
    for r in repos:
        by_tech[r["tech"]].append(r)
    add("technology", [(t, [rx_literal(r["name"]) for r in rs], []) for t, rs in sorted(by_tech.items(), key=lambda kv: -len(kv[1])) if len(rs) >= args.min_members],
        "dominant language family; explicit lists (Sokrates cannot match on technology) — regenerate when repositories change")

    # ---- activity and size
    if last:
        d_last = date.fromisoformat(last[:10]) if re.match(r"\d{4}-\d{2}-\d{2}", last) else date.today()
        tiers = {"Active (commits in the last 180 days)": [], "Fading (180 days to 2 years)": [], "Dormant (no commits for 2+ years)": []}
        for r in repos:
            lc = r["latest_commit"][:10]
            if lc and lc >= (d_last - timedelta(days=180)).isoformat():
                tiers["Active (commits in the last 180 days)"].append(r)
            elif lc and lc >= (d_last - timedelta(days=730)).isoformat():
                tiers["Fading (180 days to 2 years)"].append(r)
            else:
                tiers["Dormant (no commits for 2+ years)"].append(r)
        add("activity", [(t, [rx_literal(r["name"]) for r in rs], []) for t, rs in tiers.items() if len(rs) >= args.min_members],
            "snapshot by latest commit — useful for a one-off 'what is alive' view; lists go stale, so regenerate or use ignoreRepositoriesLastUpdatedBefore instead")
    sizes = {"Large (100k+ LOC)": [r for r in repos if r["main_loc"] >= 100000], "Medium (10k–100k LOC)": [r for r in repos if 10000 <= r["main_loc"] < 100000],
             "Small (under 10k LOC)": [r for r in repos if r["main_loc"] < 10000]}
    add("size", [(t, [rx_literal(r["name"]) for r in rs], []) for t, rs in sizes.items() if len(rs) >= args.min_members], "size tiers by main LOC (snapshot)")

    # ---- organisation (dominant e-mail domain)
    by_domain = defaultdict(list)
    for r in repos:
        if r["domains"]:
            by_domain[r["domains"][0][0]].append(r)
    add("organisation", [(d, [rx_literal(r["name"]) for r in rs], []) for d, rs in sorted(by_domain.items(), key=lambda kv: -len(kv[1])) if len(rs) >= args.min_members],
        "dominant contributor e-mail domain per repository — separates in-house from community or one org unit from another when domains differ")

    # ---- teams: greedy clusters of repositories sharing main committers
    clusters = []
    remaining = [r for r in repos if r["top_committers"]]
    while remaining:
        seed = remaining.pop(0)
        members, people = [seed], set(seed["top_committers"][:3])
        changed = True
        while changed:
            changed = False
            for r in list(remaining):
                if len(people & set(r["top_committers"][:3])) >= 2 or (len(people & set(r["top_committers"][:3])) >= 1 and len(r["top_committers"]) <= 2):
                    members.append(r); people |= set(r["top_committers"][:3]); remaining.remove(r); changed = True
        clusters.append((members, people))
    team_ls = []
    team_names = Counter()
    for i, (members, people) in enumerate(sorted(clusters, key=lambda c: -len(c[0]))):
        if len(members) >= max(2, args.min_members):
            leads = [e for e, _ in Counter(e for r in members for e in r["top_committers"][:3]).most_common(3)
                     if e.split("@")[0] not in ("git", "root", "admin", "noreply", "bot")]
            lead = (leads[0] if leads else "unknown").split("@")[0]
            team_names[lead] += 1
            name = f"Team around {lead}" + (f" ({team_names[lead]})" if team_names[lead] > 1 else "")
            team_ls.append((name, [rx_literal(r["name"]) for r in members], []))
    add("teams", team_ls[:15], "repositories whose top-3 committers overlap — a proxy for team ownership; name the groups after the real teams (config-teams.json gives the names when it exists)")

    # ---- tags
    by_tag = defaultdict(list)
    for r in repos:
        for t in set(r["tags"]):
            by_tag[t].append(r)
    add("tags", [(t, [rx_literal(r["name"]) for r in rs], []) for t, rs in sorted(by_tag.items(), key=lambda kv: -len(kv[1])) if len(rs) >= args.min_members][:12],
        "tag rules that fired in each repository analysis (CI/CD, build tools, frameworks); overlapping by nature")

    # ---- user grouping
    if args.groups:
        try:
            groups = json.loads(Path(args.groups).read_text())
        except (OSError, json.JSONDecodeError) as e:
            print(f"error: cannot read --groups: {e}", file=sys.stderr); return 2
        if isinstance(groups, dict) and "landscapes" in groups:
            rows = measure_tree(groups, repos, total_loc, "", warnings)
            top = [r for r in rows if r["level"] == 0 and not r.get("is_remainder")]
            overlaps = Counter(n for r in top for n in r["members_all"])
            multi = [n for n, c in overlaps.items() if c > 1]
            rem = next((r for r in rows if r["level"] == 0 and r.get("is_remainder")), None)
            proposals.insert(0, {"kind": "user", "landscapes": len(top), "coverage_pct": rem["coverage_pct"] if rem else 100.0,
                                 "remainder": rem["repositories"] if rem else 0, "remainder_names": rem["members_all"][:40] if rem else [],
                                 "rows": rows, "in_several": multi, "note": "your virtualLandscapes object, measured (nested rows indented; each level has its own remainder)",
                                 "config": groups})
            if multi:
                warnings.append(f"{len(multi)} repositories fall into several top-level landscapes: {', '.join(multi[:6])}")
            for r in rows:
                if not r["repositories"] and not r.get("is_remainder"):
                    warnings.append(f"landscape `{r['landscape']}` matches no repository — matching is case-sensitive and full-string")
                if r.get("is_remainder") and r["repositories"] and "/" in r["landscape"]:
                    warnings.append(f"nested remainder `{r['landscape']}` holds {r['repositories']} repositories — name it (remainderLandscapeMetadata) or extend the nested patterns")
            groups = {}
        user_ls = []
        for gname, pats in groups.items():
            inc = []
            if isinstance(pats, dict):   # {"include": [...], "exclude": [...]}
                exc_list = [str(x) for x in pats.get("exclude") or []]
                pats = pats.get("include") or []
            else:
                exc_list = []
            for p in pats if isinstance(pats, list) else [pats]:
                p = str(p)
                try:
                    re.compile(p)
                except re.error as e:
                    warnings.append(f"group `{gname}`: pattern `{p}` does not compile ({e}) — Sokrates would silently match nothing"); continue
                is_regex = any(ch in p for ch in ".*+?[](){}|^$\\")
                if not is_regex and p not in names:
                    warnings.append(f"group `{gname}`: `{p}` is not a repository name (names are case-sensitive metadata.name values)")
                inc.append(p if is_regex else rx_literal(p))
            user_ls.append((gname, inc, exc_list))
        if not user_ls:
            user_ls = None
        rows, rest, coverage = measure(user_ls, repos, total_loc) if user_ls else ([], [], 0.0)
        if user_ls:
            overlaps = Counter(n for r in rows for n in r["members_all"])
            multi = [n for n, c in overlaps.items() if c > 1]
            proposals.insert(0, {"kind": "user", "landscapes": len(rows), "coverage_pct": coverage, "remainder": len(rest), "remainder_names": [r["name"] for r in rest][:40],
                                 "rows": rows, "in_several": multi, "note": "your grouping, measured", "config": to_config(rows)})
            if multi:
                warnings.append(f"{len(multi)} repositories fall into several of your groups (allowed by Sokrates, but check it is intended): {', '.join(multi[:6])}")
            for r in rows:
                if not r["repositories"]:
                    warnings.append(f"group `{r['landscape']}` matches no repository — remember matching is case-sensitive and full-string")

    if existing_vl:
        rows = measure_tree(lconf["virtualLandscapes"], repos, total_loc, "", warnings)
        rem = next((r for r in rows if r["level"] == 0 and r.get("is_remainder")), None)
        proposals.insert(0, {"kind": "existing", "landscapes": len([r for r in rows if r["level"] == 0 and not r.get("is_remainder")]),
                             "coverage_pct": rem["coverage_pct"] if rem else 100.0, "remainder": rem["repositories"] if rem else 0,
                             "remainder_names": rem["members_all"][:40] if rem else [], "rows": rows, "note": "the virtualLandscapes already in config.json, measured", "config": lconf["virtualLandscapes"]})
    out = {"analysis_root": str(root), "repositories": len(repos), "total_main_loc": total_loc, "latest_commit": last,
           "landscape_thresholds": {"repositoryThresholdLocMain": th_loc, "repositoryThresholdContributors": th_contrib, "ignoreRepositoriesLastUpdatedBefore": th_date},
           "existing_folder_sublandscapes": existing_subs,
           "repository_table": [{k: v for k, v in r.items() if k not in ("extensions",)} for r in repos],
           "proposals": proposals, "warnings": warnings}
    if args.output:
        Path(args.output).write_text(json.dumps(out, indent=2))
    print(f"Virtual landscape proposals — {root}: {len(repos)} repositories, {total_loc} main LOC, latest commit {last[:10]}")
    for p in proposals:
        print(f"\n[{p['kind']}] {p['landscapes']} landscapes, coverage {p['coverage_pct']}%, remainder {p['remainder']}" + (f"  — {p['note']}" if p.get("note") else ""))
        limit = len(p["rows"]) if p["kind"] in ("user", "existing") else 20
        for r in p["rows"][:limit]:
            indent = "  " * (r.get("level", 0) + 1)
            print(f"{indent}{r['landscape'].split('/')[-1][:44]:<44} {r['repositories']:>4} repos {r['loc']:>10} LOC {r['loc_share_pct']:>5}%   {', '.join(r['members'][:5])}{' …' if r['repositories'] > 5 else ''}")
        if len(p["rows"]) > limit:
            print(f"  … {len(p['rows']) - limit} more (all rows in the JSON output)")
        if p.get("in_several"):
            print(f"  in several groups: {', '.join(p['in_several'][:8])}")
    unplaced = proposals[0]["remainder_names"] if proposals and proposals[0]["kind"] in ("user", "existing") else []
    if unplaced:
        print("\nRemainder — descriptions to classify by hand:")
        by_name = {r["name"]: r for r in repos}
        for n in unplaced[:25]:
            r = by_name.get(n, {})
            print(f"  {n:<44} {r.get('tech', '?'):<12} {r.get('description', '') or '(no description)'}")
    for w in warnings:
        print(f"WARNING: {w}")
    if args.output:
        print(f"\nwrote {args.output}  (repository_table includes descriptions, links, tech, tags, top committers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
