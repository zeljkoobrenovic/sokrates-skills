#!/usr/bin/env python3
"""Check a Sokrates landscape configuration against the repository analyses it will aggregate.

Re-implements the landscape's discovery and matching rules (LandscapeAnalysisInitiator, TagMap /
RepositoryTag, VirtualLandscapeBuilder, TeamsConfig, PeopleConfig, LandscapeAnalysisResults) so you
can see, before running `sokrates updateLandscape`, which repositories will be found, how filters and
thresholds cut them, which tags and virtual landscapes each gets, and how contributors map to
people/teams/bots.

Usage:
  python3 check_landscape.py <analysis-root> [--conf <_sokrates_landscape/config.json>] [--json out.json]

Checks and lints:
  - config files parse; unknown / legacy / dead keys; regexes that do not compile (Sokrates treats
    them as non-matching without any error)
  - repository discovery: data/data.zip or data/analysisResults.json, nested sub-landscapes,
    duplicate metadata names (first found wins), blank names
  - per repository: main LOC, contributors, latest commit, dominant extension -> which thresholds
    exclude it, which tags match, which virtual landscapes include it
  - contributors across repositories: ignore/bot/transform/people pipeline, team assignment,
    unmatched active contributors, people-config aliases that never match anyone
Exit code 1 on errors (unparseable files, bad regexes, no repositories found).
"""

import argparse
import io
import json
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

KNOWN_KEYS = {"metadata", "virtualLandscapes", "analysisRoot", "repositoryReportsUrlPrefix", "parentUrl", "breadcrumbs",
              "extensionThresholdLoc", "repositoryThresholdLocMain", "repositoryThresholdContributors", "contributorThresholdCommits",
              "ignoreRepositoriesLastUpdatedBefore", "commitsMaxYears", "significantContributorMinCommitDaysPerYear",
              "anonymizeContributors", "showRepositoryControls", "repositoriesShortListLimit", "repositoriesListLimit",
              "repositoriesHistoryLimit", "contributorsListLimit", "contributorLinkTemplate", "contributorAvatarLinkTemplate",
              "ignoreContributors", "bots", "tagContributors", "ignoreExtensions", "includeOnlyOneRepositoryWithSameName",
              "mergeExtensions", "transformContributorEmails", "showContributorsTrendsOnFirstTab", "maxSublandscapeDepth",
              "iFramesAtStart", "iFrames", "iFramesRepositoriesAtStart", "iFramesRepositories", "iFramesContributorsAtStart",
              "iFramesContributors", "customTabs", "customHtmlReportHeaderFragment"}
LEGACY_KEYS = {"projectReportsUrlPrefix": "repositoryReportsUrlPrefix", "projectThresholdLocMain": "repositoryThresholdLocMain",
               "projectThresholdContributors": "repositoryThresholdContributors", "ignoreProjectsLastUpdatedBefore": "ignoreRepositoriesLastUpdatedBefore",
               "projectsShortListLimit": "repositoriesShortListLimit", "projectsListLimit": "repositoriesListLimit",
               "projectsHistoryLimit": "repositoriesHistoryLimit", "iFramesProjectsAtStart": "iFramesRepositoriesAtStart"}
DEAD_KEYS = {"repositoriesShortListLimit": "read nowhere in the report generator"}
GHOST_KEYS = {"showExtensionsOnFirstTab", "ignoreRepositories", "contributorAliases", "maxRepositoriesOnList", "people", "teams", "tagRules"}


def load_json(path, errors, default):
    if not path.is_file():
        return default, False
    try:
        return json.loads(path.read_text()), True
    except json.JSONDecodeError as e:
        errors.append(f"{path.name}: invalid JSON ({e})")
        return default, True


def rx(pattern, where, errors, flags=0):
    try:
        return re.compile(pattern, flags)
    except re.error as e:
        errors.append(f"{where}: regex `{pattern}` does not compile ({e}) — Sokrates would silently treat it as non-matching")
        return None


def matches_any(value, patterns, flags=0):
    for p in patterns:
        try:
            if re.fullmatch(p, value, flags):
                return True
        except re.error:
            continue
    return False


def apply_ops(value, ops):
    for op in ops or []:
        name = (op.get("op") or "").lower()
        params = op.get("params") or []
        try:
            if name == "replace" and len(params) >= 2:
                value = re.sub(params[0], params[1], value)
            elif name == "remove" and params:
                value = re.sub(params[0], "", value)
            elif name == "extract" and params:
                m = re.search(params[0], value)
                value = m.group(1) if m and m.groups() else (m.group(0) if m else value)
            elif name == "trim":
                value = value.strip()
            elif name == "lowercase":
                value = value.lower()
            elif name == "uppercase":
                value = value.upper()
            elif name == "append" and params:
                value = value + params[0]
            elif name == "prepend" and params:
                value = params[0] + value
        except re.error:
            pass
    return value


# ---------- repository discovery (LandscapeAnalysisInitiator) ----------
def discover(root: Path):
    repos, sublandscapes = [], []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        if "/_sokrates_landscape/landscapes/" in (dirpath + "/").replace(os.sep, "/"):
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules")]
        p = Path(dirpath)
        if p.name == "_sokrates_landscape" and "index.html" in filenames and p.parent != root:
            sublandscapes.append(p.parent)
        if p.name == "data" and ("data.zip" in filenames or "analysisResults.json" in filenames):
            repos.append(p)
    return repos, sublandscapes


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


def repo_summary(data_dir: Path, root: Path):
    raw = read_entry(data_dir, "analysisResults.json")
    if raw is None:
        return None
    try:
        ar = json.loads(raw)
    except json.JSONDecodeError:
        return {"path": str(data_dir.parent.relative_to(root)), "error": "analysisResults.json invalid"}
    meta = ar.get("metadata") or {}
    main = (ar.get("mainAspectAnalysisResults") or {})
    loc = main.get("linesOfCode", 0)
    exts = {}
    for item in main.get("linesOfCodePerExtension") or []:
        n = str(item.get("name", "")).strip().replace("*.", "").lower()   # names look like "  *.rs"
        exts[n] = exts.get(n, 0) + int(item.get("value", 0) or 0)
    contributors = []
    for c in (ar.get("contributorsAnalysisResults") or {}).get("contributors") or []:
        contributors.append({"email": str(c.get("email", "")), "userName": str(c.get("userName", "") or ""),
                             "commits": int(c.get("commitsCount", 0) or 0), "latest": str(c.get("latestCommitDate", "") or "")})
    latest = max((c["latest"] for c in contributors), default="")
    # file paths for pathPatterns tags, from the aspect exports
    paths = []
    for entry in ("text/aspect_main.txt", "text/aspect_test.txt", "text/aspect_generated.txt",
                  "text/aspect_build_and_deployment.txt", "text/aspect_other.txt"):
        t = read_entry(data_dir, entry)
        if t:
            for ln in t.splitlines()[1:]:
                cell = ln.split("\t")[0].strip()
                if cell:
                    paths.append(cell)
    return {"path": str(data_dir.parent.relative_to(root)), "name": str(meta.get("name", "") or ""),
            "main_loc": loc, "extensions": exts, "dominant_extension": max(exts, key=exts.get) if exts else "",
            "contributors": contributors, "contributors_count": len(contributors), "latest_commit": latest, "file_paths": paths}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("analysis_root")
    ap.add_argument("--conf", help="landscape config.json (default <root>/_sokrates_landscape/config.json)")
    ap.add_argument("--json")
    args = ap.parse_args()
    errors, warnings, notes = [], [], []
    root = Path(args.analysis_root).resolve()
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory"); return 1
    conf_path = Path(args.conf) if args.conf else root / "_sokrates_landscape" / "config.json"
    folder = conf_path.parent
    config, exists = load_json(conf_path, errors, {})
    if not exists:
        notes.append(f"{conf_path} does not exist yet — updateLandscape will create it with defaults; previewing defaults")
    tags_doc, _ = load_json(folder / "config-tags.json", errors, [])
    teams_doc, _ = load_json(folder / "config-teams.json", errors, {"teams": []})
    people_doc, _ = load_json(folder / "config-people.json", errors, {"people": []})

    for k in config:
        if k in LEGACY_KEYS:
            warnings.append(f"config.json: `{k}` is a legacy alias — Sokrates rewrites it as `{LEGACY_KEYS[k]}`")
        elif k in GHOST_KEYS or k not in KNOWN_KEYS:
            warnings.append(f"config.json: `{k}` is not a landscape field — silently ignored and dropped on rewrite")
        if k in DEAD_KEYS:
            notes.append(f"config.json: `{k}` has no effect ({DEAD_KEYS[k]})")
    def cfg(key, default):
        return config.get(key, config.get({v: k for k, v in LEGACY_KEYS.items()}.get(key, ""), default))

    # regex sanity
    for k in ("ignoreContributors", "bots"):
        for p in cfg(k, []) or []:
            rx(p, f"config.json {k}", errors)
    for t in cfg("tagContributors", []) or []:
        for p in t.get("patterns") or []:
            rx(p, f"tagContributors `{t.get('name')}`", errors)
    for grp in tags_doc if isinstance(tags_doc, list) else []:
        for t in grp.get("repositoryTags") or grp.get("projectTags") or []:
            for key in ("patterns", "excludePatterns", "pathPatterns", "excludePathPatterns"):
                for p in t.get(key) or []:
                    rx(p, f"config-tags `{grp.get('name')}/{t.get('tag')}` {key}", errors)
    def walk_virtual(vl, prefix=""):
        for v in (vl or {}).get("landscapes") or []:
            name = (v.get("metadata") or {}).get("name", "?")
            for key in ("includeRepoNamePatterns", "excludeRepoNamePatterns"):
                for p in v.get(key) or []:
                    rx(p, f"virtual landscape `{prefix}{name}` {key}", errors)
            if not v.get("includeRepoNamePatterns"):
                warnings.append(f"virtual landscape `{prefix}{name}` has no includeRepoNamePatterns — it will be empty")
            walk_virtual(v.get("virtualLandscapes"), prefix + name + "/")
    walk_virtual(cfg("virtualLandscapes", {}))
    for t in (teams_doc or {}).get("teams") or []:
        for key in ("emailPatterns", "userNamePatterns"):
            for p in t.get(key) or []:
                rx(p, f"team `{t.get('name')}` {key}", errors, re.I)
    for p_ in (people_doc or {}).get("people") or []:
        for key in ("emailPatterns", "userNamePatterns"):
            for p in p_.get(key) or []:
                rx(p, f"person `{p_.get('email')}` {key}", errors, re.I)
        if "name" in p_ or "link" in p_:
            warnings.append(f"config-people: person `{p_.get('email')}` uses legacy `name`/`link` — rewrite as `userName`/`links` (lost on save)")

    # ---------- discovery ----------
    repo_dirs, subs = discover(root)
    repos = [r for r in (repo_summary(d, root) for d in sorted(repo_dirs)) if r]
    if not repos:
        errors.append(f"no repository analyses found under {root} (looking for */data/data.zip or */data/analysisResults.json)")
    for r in repos:
        if r.get("error"):
            warnings.append(f"{r['path']}: {r['error']}")
    repos = [r for r in repos if not r.get("error")]
    names = Counter(r["name"] for r in repos)
    only_one = cfg("includeOnlyOneRepositoryWithSameName", True)
    seen = set()
    for r in repos:
        r["skipped_duplicate_name"] = bool(only_one and r["name"] in seen)
        seen.add(r["name"])
        if not r["name"]:
            warnings.append(f"{r['path']}: blank metadata.name — collides with every other blank-named repository")
    for n, c in names.items():
        if c > 1 and n:
            warnings.append(f"{c} repositories share metadata.name `{n}` — only the first found is analysed")

    # ---------- thresholds ----------
    th_loc = int(cfg("repositoryThresholdLocMain", 0) or 0)
    th_contrib = int(cfg("repositoryThresholdContributors", 1) or 1)
    th_date = str(cfg("ignoreRepositoriesLastUpdatedBefore", "") or "")
    for r in repos:
        reasons = []
        if r["skipped_duplicate_name"]:
            reasons.append("duplicate name")
        if r["main_loc"] < th_loc:
            reasons.append(f"main LOC {r['main_loc']} < {th_loc}")
        if r["contributors_count"] and r["contributors_count"] < th_contrib:
            reasons.append(f"contributors {r['contributors_count']} < {th_contrib}")
        if th_date and r["latest_commit"] and r["latest_commit"] < th_date:
            reasons.append(f"latest commit {r['latest_commit']} < {th_date}")
        r["excluded_by"] = reasons
    included = [r for r in repos if not r["excluded_by"]]

    # ---------- tags ----------
    tag_groups = tags_doc if isinstance(tags_doc, list) else []
    if not tag_groups:
        notes.append("config-tags.json absent/empty — updateLandscape will write the default CI/CD, build-tools and tech groups")
    tag_hits = Counter()
    for r in included:
        r["tags"] = []
        dominant, name = r["dominant_extension"], r["name"]
        for grp in tag_groups:
            for t in grp.get("repositoryTags") or grp.get("projectTags") or []:
                if any(dominant.lower() == e.lower() for e in t.get("excludeExtensions") or []):
                    continue
                if matches_any(name, t.get("excludePatterns") or []):
                    continue
                hit = matches_any(name, t.get("patterns") or []) \
                    or any(dominant.lower() == e.lower() for e in t.get("mainExtensions") or []) \
                    or any(any(x.lower() == e.lower() for x in r["extensions"]) for e in t.get("anyExtensions") or [])
                if not hit and t.get("pathPatterns"):
                    ex = t.get("excludePathPatterns") or []
                    hit = any(matches_any(p, t["pathPatterns"]) and not matches_any(p, ex) for p in r["file_paths"])
                if hit:
                    key = f"{grp.get('name')} / {t.get('tag')}"
                    r["tags"].append(key); tag_hits[key] += 1
    for grp in tag_groups:
        for t in grp.get("repositoryTags") or grp.get("projectTags") or []:
            key = f"{grp.get('name')} / {t.get('tag')}"
            if included and tag_hits[key] == 0:
                notes.append(f"tag `{key}` matches no repository")

    # ---------- virtual landscapes ----------
    def assign_virtual(vl, repos_in, prefix=""):
        out = []
        matched_any = set()
        for v in (vl or {}).get("landscapes") or []:
            name = prefix + (v.get("metadata") or {}).get("name", "?")
            inc, exc = v.get("includeRepoNamePatterns") or [], v.get("excludeRepoNamePatterns") or []
            members = [r for r in repos_in if inc and matches_any(r["name"], inc) and not matches_any(r["name"], exc)]
            matched_any.update(id(r) for r in members)
            out.append({"landscape": name, "repositories": len(members), "names": [r["name"] for r in members][:12]})
            if not members:
                warnings.append(f"virtual landscape `{name}` matches no repository (name matching is case-sensitive, full-string)")
            out.extend(assign_virtual(v.get("virtualLandscapes"), members, name + "/"))
        if (vl or {}).get("landscapes"):
            rest = [r for r in repos_in if id(r) not in matched_any]
            out.append({"landscape": prefix + ((vl.get("remainderLandscapeMetadata") or {}).get("name") or "Remainder"),
                        "repositories": len(rest), "names": [r["name"] for r in rest][:12]})
        return out
    virtual = assign_virtual(cfg("virtualLandscapes", {}), included)

    # ---------- contributors pipeline ----------
    ignore_pats = [p.lower() for p in cfg("ignoreContributors", []) or []]
    bot_pats = cfg("bots", [".*\\[bot\\].*", ".*[-]bot[@].*"]) or []
    ops = cfg("transformContributorEmails", []) or []
    people = (people_doc or {}).get("people") or []
    teams = (teams_doc or {}).get("teams") or []
    th_commits = int(cfg("contributorThresholdCommits", 1) or 1)

    def person_for(cid, user_name):
        for p in people:
            if cid.lower() == str(p.get("email", "")).lower():
                return p
            if matches_any(cid, p.get("emailPatterns") or [], re.I):
                return p
            if user_name:
                key = re.sub(r"\s+", "", user_name).lower()
                if key and key == re.sub(r"\s+", "", str(p.get("userName", "") or "")).lower():
                    return p
                if matches_any(user_name, p.get("userNamePatterns") or [], re.I):
                    return p
        return None

    canon = defaultdict(lambda: {"commits": 0, "repos": set(), "latest": "", "userName": "", "sources": set()})
    ignored, people_used = Counter(), Counter()
    for r in included:
        for c in r["contributors"]:
            cid = c["email"].lower()
            if matches_any(cid, ignore_pats, re.I):
                ignored[cid] += 1; continue
            cid2 = apply_ops(cid, ops)
            p = person_for(cid2, c["userName"])
            if p:
                people_used[str(p.get("email"))] += 1
                cid2 = str(p.get("email")) or str(p.get("userName")) or cid2
                uname = str(p.get("userName") or c["userName"])
            else:
                uname = c["userName"]
            if matches_any(cid2, ignore_pats, re.I) or not cid2:
                ignored[cid2 or cid] += 1; continue
            e = canon[cid2]
            e["commits"] += c["commits"]; e["repos"].add(r["name"]); e["latest"] = max(e["latest"], c["latest"])
            e["userName"] = e["userName"] or uname; e["sources"].add(cid)
    contributors, bots = {}, {}
    for cid, e in canon.items():
        if e["commits"] < th_commits:
            continue
        (bots if matches_any(cid, bot_pats, re.I) else contributors)[cid] = e
    for p in people:
        if people_used[str(p.get("email"))] == 0:
            notes.append(f"config-people: `{p.get('email')}` matches no contributor")
    # teams
    today = date.today()
    team_members = defaultdict(list)
    undefined_active, undefined_inactive = [], []
    for cid, e in contributors.items():
        team = next((t.get("name") for t in teams
                     if matches_any(cid, t.get("emailPatterns") or [], re.I)
                     or (e["userName"] and matches_any(e["userName"], t.get("userNamePatterns") or [], re.I))), None)
        if team:
            team_members[team].append(cid)
        else:
            active = e["latest"] and e["latest"][:10] >= (today - timedelta(days=180)).isoformat()
            (undefined_active if active else undefined_inactive).append(cid)
    for t in teams:
        if not team_members.get(t.get("name")):
            warnings.append(f"team `{t.get('name')}` has no members")
    if teams and undefined_active:
        warnings.append(f"{len(undefined_active)} active contributors match no team (→ 'Undefined Team'): {', '.join(undefined_active[:5])}")
    merged = [(cid, sorted(e["sources"])) for cid, e in contributors.items() if len(e["sources"]) > 1]
    suspicious = defaultdict(set)
    for cid, e in contributors.items():
        if e["userName"]:
            suspicious[re.sub(r"\s+", "", e["userName"]).lower()].add(cid)
    alias_candidates = {k: sorted(v) for k, v in suspicious.items() if len(v) > 1}
    if alias_candidates:
        notes.append(f"{len(alias_candidates)} user names map to several contributor ids — run `sokrates updateLandscapePeopleConfigByUserName` to merge them: "
                     + "; ".join(f"{k}: {', '.join(v[:3])}" for k, v in list(alias_candidates.items())[:4]))

    # ---------- output ----------
    out = {"analysis_root": str(root), "config": str(conf_path), "config_exists": exists,
           "sub_landscapes": [str(s.relative_to(root)) for s in subs],
           "repositories": [{k: v for k, v in r.items() if k not in ("contributors", "file_paths", "extensions")} for r in repos],
           "included": len(included), "excluded": len(repos) - len(included),
           "tags": dict(tag_hits.most_common()), "virtual_landscapes": virtual,
           "contributors": {"canonical": len(contributors), "bots": len(bots), "ignored": sum(ignored.values()),
                            "merged_identities": merged[:50], "teams": {k: len(v) for k, v in team_members.items()},
                            "undefined_team_active": len(undefined_active), "alias_candidates": alias_candidates},
           "errors": errors, "warnings": warnings, "notes": notes}
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2))

    print(f"Sokrates landscape check — {root}")
    print(f"config: {conf_path} ({'exists' if exists else 'MISSING — defaults previewed'})   name: {(cfg('metadata', {}) or {}).get('name', '')!r}")
    print(f"sub-landscapes: {len(subs)}   repositories found: {len(repos)}   included: {len(included)}   excluded: {len(repos) - len(included)}")
    print("\nRepositories:")
    for r in sorted(repos, key=lambda r: -r["main_loc"])[:60]:
        status = "EXCLUDED: " + "; ".join(r["excluded_by"]) if r["excluded_by"] else ", ".join(r.get("tags", [])[:6])
        print(f"  {r['name'] or '(blank)':<32} {r['main_loc']:>9} LOC {r['contributors_count']:>4} contrib  {r['latest_commit'][:10]:<10} {r['dominant_extension']:<6} {status}")
    if len(repos) > 60:
        print(f"  … {len(repos) - 60} more")
    if tag_hits:
        print("\nTags: " + ", ".join(f"{k} ({n})" for k, n in tag_hits.most_common(20)))
    if virtual:
        print("\nVirtual landscapes:")
        for v in virtual:
            print(f"  {v['landscape']:<40} {v['repositories']:>4} repos   {', '.join(v['names'][:6])}")
    print(f"\nContributors: {len(contributors)} canonical, {len(bots)} bots, {sum(ignored.values())} ignored, {len(merged)} identities merged by config"
          + (", teams: " + ", ".join(f"{k} ({len(v)})" for k, v in sorted(team_members.items(), key=lambda kv: -len(kv[1]))[:10]) if team_members else ", no teams configured"))
    for level, items in (("ERROR", errors), ("WARNING", warnings), ("note", notes)):
        for it in items:
            print(f"{level}: {it}")
    print(f"\n{'FAILED' if errors else 'OK'}: {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
