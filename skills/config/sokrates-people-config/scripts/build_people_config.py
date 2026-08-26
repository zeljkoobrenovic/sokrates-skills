#!/usr/bin/env python3
"""Build a Sokrates `config-people.json` (contributor identity merging) from git history, with a review file.

Works for one repository or a whole landscape:

  --repo <path>        reads <path>/git-history.txt (Sokrates export) — or, without it, the contributors in
                       <path>/_sokrates/reports/data/data.zip — and writes <path>/_sokrates/config-people.json
  --landscape <root>   discovers every repository analysis under <root>, reads each repository's git-history.txt
                       (when the source is present) or its analysisResults contributors, imports each repository's
                       own _sokrates/config-people.json as trusted merges, and writes
                       <root>/_sokrates_landscape/config-people.json

Identity resolution (each merge records which rules fired and a confidence):
  R1 same e-mail (case-insensitive)                                           certain
  R2 same user-name key (whitespace removed, lower-cased) — Sokrates' own rule  high   (generic names excluded)
  R3 GitHub noreply forms: 123+login@users.noreply.github.com ↔ login@…      high
  R4 e-mail local part equals another identity's GitHub login / user-name key  high
  R5 same local part on different domains (alice@corp.com ↔ alice@gmail.com)  medium (review)
  R6 local part is first.last / flast / firstl of a user name                  medium (review)
  R7 user names similar (ratio ≥ 0.9) but keys differ (typos, accents)         low    (not merged; listed)
Bots (`[bot]`, `-bot@`, github-actions, dependabot, renovate, …) are excluded from merging.

Outputs (next to each other):
  config-people.json              Sokrates shape: {"people": [{"email", "userName", "links", "image", "emailPatterns", "userNamePatterns"}]}
                                  e-mail patterns are \\Q…\\E literals; canonical e-mail = the most active non-noreply address
  config-people-for-review.json   every merge with rules, confidence, per-identity commits and activity spans, plus
                                  low-confidence candidates NOT applied, generic-name merges, and existing entries kept

Existing config-people.json entries are preserved (hand edits win): their e-mails are seeded as certain groups.

Usage:
  python3 build_people_config.py --repo <repo> [--min-confidence high|medium] [--all] [--dry-run]
  python3 build_people_config.py --landscape <root> [--min-confidence high|medium] [--all] [--dry-run]
"""

import argparse
import difflib
import json
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

BOT_RE = re.compile(r"(\[bot\]|[-_.]bot@|^bot@|[-_.]robot|merge-queue|submit queue|github-actions|dependabot|renovate|greenkeeper|snyk-bot|codecov|semantic-release|copilot|noreply@github\.com$)", re.I)
GENERIC_KEYS = {"admin", "administrator", "root", "user", "dev", "developer", "test", "unknown", "anonymous", "ubuntu", "ec2user", "jenkins",
                "build", "ci", "deploy", "git", "github", "gitlab", "me", "none", "null", "n/a", "na"}
CONF_RANK = {"certain": 0, "high": 1, "medium": 2, "low": 3}


def name_key(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").lower())


def name_tokens(name: str):
    return [t for t in re.split(r"[\s._\-]+", (name or "").lower()) if t]


def is_bot(email: str, name: str) -> bool:
    return bool(BOT_RE.search(email or "") or BOT_RE.search(name or ""))


# ---------------------------------------------------------------- inputs
def parse_git_history(path: Path, repo_label: str):
    """Sokrates git-history.txt: 'YYYY-MM-DD email sha path Name&nbsp;Parts added removed' -> identities."""
    ids = {}
    for ln in path.read_text(errors="replace").splitlines():
        parts = ln.split(" ")
        if len(parts) < 7 or not re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
            continue
        date, email, sha = parts[0], parts[1].lower(), parts[2]
        name = " ".join(parts[4:-2]).replace("&nbsp;", " ").strip()
        key = (email, name)
        e = ids.setdefault(key, {"email": email, "userName": name, "commits": set(), "first": date, "last": date, "repos": set()})
        e["commits"].add(sha)
        e["first"] = min(e["first"], date); e["last"] = max(e["last"], date); e["repos"].add(repo_label)
    return list(ids.values())


def read_zip_entry(data_dir: Path, name: str):
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


def parse_analysis_contributors(data_dir: Path, repo_label: str):
    raw = read_zip_entry(data_dir, "analysisResults.json")
    if not raw:
        return []
    try:
        ar = json.loads(raw)
    except json.JSONDecodeError:
        return []
    out = []
    for c in (ar.get("contributorsAnalysisResults") or {}).get("contributors") or []:
        email = str(c.get("email", "")).lower()
        if not email:
            continue
        out.append({"email": email, "userName": str(c.get("userName", "") or "").strip(), "commits": int(c.get("commitsCount", 0) or 0),
                    "first": str(c.get("firstCommitDate", "") or ""), "last": str(c.get("latestCommitDate", "") or ""), "repos": {repo_label}})
    return out


def discover_repos(root: Path):
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        rel = "/" + os.path.relpath(dirpath, root).replace(os.sep, "/") + "/"
        if "/_sokrates_landscape/landscapes/" in rel:
            dirnames[:] = []; continue
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules")]
        if Path(dirpath).name == "data" and ("data.zip" in filenames or "analysisResults.json" in filenames):
            yield Path(dirpath)


def load_existing_people(path: Path):
    if not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    return doc.get("people") or [] if isinstance(doc, dict) else []


def literal_from_pattern(p: str):
    m = re.fullmatch(r"\\Q(.*)\\E", p)
    return m.group(1).lower() if m else None


# ---------------------------------------------------------------- resolution
class UnionFind:
    def __init__(self):
        self.parent = {}
        self.reasons = defaultdict(list)   # (a,b) -> [(rule, confidence, note)]

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b, rule, conf, note=""):
        ra, rb = self.find(a), self.find(b)
        self.reasons[tuple(sorted((a, b)))].append((rule, conf, note))
        if ra != rb:
            self.parent[rb] = ra


def resolve(identities, existing_groups, min_conf):
    """identities: list of dicts (email, userName, commits, first, last, repos). Returns groups + low-confidence candidates."""
    # collapse to (email, userName) identity records, aggregate commits
    recs = {}
    for it in identities:
        key = (it["email"], it["userName"])
        r = recs.setdefault(key, {"email": it["email"], "userName": it["userName"], "commits": 0, "first": "", "last": "", "repos": set()})
        r["commits"] += len(it["commits"]) if isinstance(it["commits"], set) else int(it["commits"])
        r["first"] = min([x for x in (r["first"], it["first"]) if x] or [""]); r["last"] = max(r["last"], it["last"]); r["repos"] |= set(it["repos"])
    recs = {k: v for k, v in recs.items() if not is_bot(v["email"], v["userName"])}
    uf = UnionFind()
    for k in recs:
        uf.find(k)
    by_email = defaultdict(list)
    by_namekey = defaultdict(list)
    by_local = defaultdict(list)
    login_of = {}
    for k, r in recs.items():
        by_email[r["email"]].append(k)
        nk = name_key(r["userName"])
        if nk:
            by_namekey[nk].append(k)
        local = r["email"].split("@")[0]
        m = re.fullmatch(r"(?:\d+\+)?([a-z0-9-]+)", local) if r["email"].endswith("@users.noreply.github.com") else None
        if m:
            login_of[k] = m.group(1)
            by_local[m.group(1)].append(k)
        else:
            by_local[local].append(k)
    # R1 same email
    for email, ks in by_email.items():
        for other in ks[1:]:
            uf.union(ks[0], other, "R1", "certain", "same e-mail")
    # existing config: seed certain groups
    for emails in existing_groups:
        ks = [k for e in emails for k in by_email.get(e, [])]
        for other in ks[1:]:
            uf.union(ks[0], other, "R0", "certain", "existing config-people entry")
    # R2 same name key
    generic_hits = []
    for nk, ks in by_namekey.items():
        if len(ks) < 2:
            continue
        if nk in GENERIC_KEYS or len(nk) < 3:
            generic_hits.append((nk, ks)); continue
        for other in ks[1:]:
            uf.union(ks[0], other, "R2", "high", f"same user-name key `{nk}`")
    # R3/R4 GitHub logins and local parts
    namekey_index = {name_key(r["userName"]): k for k, r in recs.items() if name_key(r["userName"])}
    for local, ks in by_local.items():
        if len(local) < 3 or local in GENERIC_KEYS:
            continue
        noreply = [k for k in ks if k in login_of]
        others = [k for k in ks if k not in login_of]
        for a in noreply:
            for b in noreply:
                if a < b:
                    uf.union(a, b, "R3", "high", f"GitHub noreply forms of login `{local}`")
            for b in others:
                uf.union(a, b, "R4", "high", f"local part `{local}` equals GitHub login")
        # R4b: login equals someone's name key
        if noreply and local in namekey_index:
            uf.union(noreply[0], namekey_index[local], "R4", "high", f"GitHub login `{local}` equals user-name key")
        # R5 same local part, different domains
        domains = {recs[k]["email"].split("@")[-1] for k in others}
        if len(others) >= 2 and len(domains) >= 2:
            for b in others[1:]:
                uf.union(others[0], b, "R5", "medium", f"same local part `{local}` on different domains")
    # R6 local part derived from a user name (first.last, flast, firstl)
    for k, r in recs.items():
        toks = name_tokens(r["userName"])
        if len(toks) < 2:
            continue
        first, last = toks[0], toks[-1]
        forms = {f"{first}.{last}", f"{first}{last}", f"{first[0]}{last}", f"{first}{last[0]}", f"{first}_{last}", f"{last}.{first}"}
        for form in forms:
            for other in by_local.get(form, []):
                if other != k and name_key(recs[other]["userName"]) != name_key(r["userName"]):
                    uf.union(k, other, "R6", "medium", f"local part `{form}` derived from `{r['userName']}`")
    # R7 similar names (not merged)
    low = []
    # bucket by the first two characters and compare only within a bucket (keeps large landscapes fast)
    buckets = defaultdict(list)
    for k, r in recs.items():
        nk = name_key(r["userName"])
        if len(nk) >= 6 and r["commits"] >= 2:
            buckets[nk[:2]].append((nk, k))
    seen = set()
    pairs = ((a, b) for bucket in buckets.values() if len(bucket) <= 400 for i, a in enumerate(bucket) for b in bucket[i + 1:])
    for (nk1, k1), (nk2, k2) in pairs:
        if True:
            if nk1 == nk2 or uf.find(k1) == uf.find(k2) or abs(len(nk1) - len(nk2)) > 3:
                continue
            sm = difflib.SequenceMatcher(None, nk1, nk2)
            if sm.quick_ratio() >= 0.9 and sm.ratio() >= 0.9:
                pair = tuple(sorted((uf.find(k1), uf.find(k2))))
                if pair in seen:
                    continue
                seen.add(pair)
                low.append({"a": {"email": recs[k1]["email"], "userName": recs[k1]["userName"], "commits": recs[k1]["commits"]},
                            "b": {"email": recs[k2]["email"], "userName": recs[k2]["userName"], "commits": recs[k2]["commits"]},
                            "rule": "R7", "confidence": "low", "note": "similar user names — verify before merging"})
    # apply min confidence: rebuild groups using only edges at or above the threshold
    allowed = {c for c, rank in CONF_RANK.items() if rank <= CONF_RANK[min_conf]}
    uf2 = UnionFind()
    for k in recs:
        uf2.find(k)
    for (a, b), rs in uf.reasons.items():
        if any(c in allowed for _, c, _ in rs):
            uf2.union(a, b, rs[0][0], rs[0][1])
    groups = defaultdict(list)
    for k in recs:
        groups[uf2.find(k)].append(k)
    skipped = []
    for (a, b), rs in uf.reasons.items():
        if not any(c in allowed for _, c, _ in rs) and uf2.find(a) != uf2.find(b):
            skipped.append({"a": {"email": recs[a]["email"], "userName": recs[a]["userName"], "commits": recs[a]["commits"]},
                            "b": {"email": recs[b]["email"], "userName": recs[b]["userName"], "commits": recs[b]["commits"]},
                            "rule": rs[0][0], "confidence": rs[0][1], "note": rs[0][2] + " — below --min-confidence, not applied"})
    result = []
    for root, ks in groups.items():
        members = sorted((recs[k] for k in ks), key=lambda r: -r["commits"])
        emails = sorted({r["email"] for r in members})
        names = Counter(r["userName"] for r in members if r["userName"])
        rules = []
        worst = "certain"
        for (a, b), rs in uf.reasons.items():
            if a in ks and b in ks:
                for rule, conf, note in rs:
                    if conf in allowed:
                        rules.append(f"{rule}: {note}")
                        if CONF_RANK[conf] > CONF_RANK[worst]:
                            worst = conf
        canonical = next((r["email"] for r in members if not r["email"].endswith("@users.noreply.github.com")), members[0]["email"])
        display = names.most_common(1)[0][0] if names else canonical.split("@")[0]
        result.append({"email": canonical, "userName": display, "emails": emails, "names": [n for n, _ in names.most_common()],
                       "identities": [{"email": r["email"], "userName": r["userName"], "commits": r["commits"], "first": r["first"], "last": r["last"],
                                       "repos": sorted(r["repos"])[:8]} for r in members],
                       "commits": sum(r["commits"] for r in members), "confidence": worst, "rules": sorted(set(rules))})
    result.sort(key=lambda g: -g["commits"])
    generic = [{"name_key": nk, "identities": [{"email": recs[k]["email"], "userName": recs[k]["userName"], "commits": recs[k]["commits"]} for k in ks],
                "note": "generic user name shared by several e-mails — NOT merged"} for nk, ks in generic_hits]
    return result, skipped + low, generic


def review_flags(group):
    flags = []
    if group["confidence"] in ("medium",):
        flags.append("medium-confidence rule involved")
    if len(group["names"]) > 1:
        keys = [name_key(n) for n in group["names"]]
        toks = [set(t for t in name_tokens(n) if len(t) >= 3) for n in group["names"]]
        def related(i, j):
            return bool(toks[i] & toks[j]) or any(t in keys[j] for t in toks[i]) or any(t in keys[i] for t in toks[j])
        if any(not related(0, j) for j in range(1, len(keys))):
            flags.append(f"display names look unrelated: {' / '.join(group['names'][:3])}")
    domains = {e.split('@')[-1] for e in group["emails"]}
    if len(domains) >= 3:
        flags.append(f"{len(domains)} different e-mail domains")
    big = [i for i in group["identities"] if i["commits"] >= 50]
    if len(big) >= 2 and len({i["email"].split('@')[-1] for i in big}) > 1:
        spans = [(i["first"], i["last"]) for i in big if i["first"] and i["last"]]
        if len(spans) >= 2 and all(s[0] <= spans[0][1] and spans[0][0] <= s[1] for s in spans[1:]):
            flags.append("two heavily used addresses active in the same period — could be two people")
    return flags


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--repo", help="repository root (contains git-history.txt and/or _sokrates/)")
    g.add_argument("--landscape", help="landscape analysis root (contains _sokrates_landscape/ and repository analyses)")
    ap.add_argument("--min-confidence", default="high", choices=["high", "medium"], help="lowest confidence merged into config-people.json (default high; medium merges R5/R6 too)")
    ap.add_argument("--all", action="store_true", help="also write single-identity contributors (Sokrates does not need them)")
    ap.add_argument("--dry-run", action="store_true", help="write only the review file")
    ap.add_argument("-o", "--output-dir", help="override the output folder")
    args = ap.parse_args()

    identities, existing_groups, sources, notes = [], [], [], []
    if args.repo:
        repo = Path(args.repo).resolve()
        out_dir = Path(args.output_dir) if args.output_dir else repo / "_sokrates"
        gh = repo / "git-history.txt"
        if gh.is_file():
            identities = parse_git_history(gh, repo.name); sources.append(str(gh))
        else:
            data = repo / "_sokrates" / "reports" / "data"
            identities = parse_analysis_contributors(data, repo.name); sources.append(str(data))
            notes.append("no git-history.txt — used the analysis contributors (already merged by the repository's previous config-people.json, if any)")
        existing = load_existing_people(out_dir / "config-people.json")
    else:
        root = Path(args.landscape).resolve()
        out_dir = Path(args.output_dir) if args.output_dir else root / "_sokrates_landscape"
        existing = load_existing_people(out_dir / "config-people.json")
        for data in sorted(discover_repos(root)):
            repo_dir = data.parent.parent.parent if data.parent.name == "reports" and data.parent.parent.name == "_sokrates" else data.parent
            label = str(repo_dir.relative_to(root)) if repo_dir != root else root.name
            gh = repo_dir / "git-history.txt"
            if gh.is_file():
                identities += parse_git_history(gh, label); sources.append(str(gh))
            else:
                identities += parse_analysis_contributors(data, label); sources.append(str(data))
            # each repository's own people config is trusted evidence
            for person in load_existing_people(repo_dir / "_sokrates" / "config-people.json"):
                emails = {str(person.get("email", "")).lower()} | {literal_from_pattern(p) for p in person.get("emailPatterns") or []}
                emails.discard(None); emails.discard("")
                if len(emails) > 1:
                    existing_groups.append(sorted(emails))
        if not sources:
            print(f"error: no repository analyses under {root}", file=sys.stderr); return 2
    if not identities:
        print("error: no contributor identities found", file=sys.stderr); return 2
    for person in existing:
        emails = {str(person.get("email", "")).lower()} | {literal_from_pattern(p) for p in person.get("emailPatterns") or []}
        emails.discard(None); emails.discard("")
        if emails:
            existing_groups.append(sorted(emails))

    groups, not_applied, generic = resolve(identities, existing_groups, args.min_confidence)
    merged = [g for g in groups if len(g["emails"]) > 1]   # same e-mail with several display names needs no config
    existing_by_email = {}
    for person in existing:
        for e in {str(person.get("email", "")).lower()} | {literal_from_pattern(p) for p in person.get("emailPatterns") or []}:
            if e:
                existing_by_email[e] = person

    # ---- config-people.json
    people = []
    for gp in groups:
        if len(gp["emails"]) == 1 and not args.all:
            continue
        prior = next((existing_by_email[e] for e in gp["emails"] if e in existing_by_email), None)
        entry = {"email": prior.get("email") if prior and prior.get("email") else gp["email"],
                 "userName": prior.get("userName") if prior and prior.get("userName") else gp["userName"],
                 "links": (prior or {}).get("links") or [], "image": (prior or {}).get("image") or "",
                 "emailPatterns": sorted({f"\\Q{e}\\E" for e in gp["emails"]} | set((prior or {}).get("emailPatterns") or [])),
                 "userNamePatterns": (prior or {}).get("userNamePatterns") or []}
        people.append(entry)
    people.sort(key=lambda p: p["userName"].lower())

    # ---- review file
    review = {
        "summary": {"mode": "repository" if args.repo else "landscape", "sources": len(sources), "identities_seen": len({(i['email'], i['userName']) for i in identities}),
                    "people_after_merge": len(groups), "merged_people": len(merged),
                    "identities_merged_away": sum(len(g["identities"]) - 1 for g in merged), "min_confidence": args.min_confidence,
                    "existing_entries_preserved": len(existing), "candidates_not_applied": len(not_applied), "generic_name_collisions": len(generic)},
        "review_first": [], "merges": [], "not_applied": not_applied, "generic_name_collisions": generic,
        "how_to_read": ["review_first: merges with a medium-confidence rule, unrelated display names, many domains, or two busy addresses active at the same time",
                        "merges: every merge applied, with the rules that fired and per-identity commits/activity",
                        "not_applied: candidate pairs below --min-confidence (R5/R6) and similar-name pairs (R7) — merge by hand by adding \\Qemail\\E to a person's emailPatterns",
                        "to reject a merge: split the entry in config-people.json into two people; the tool preserves existing entries on re-run"],
    }
    for gp in merged:
        flags = review_flags(gp)
        item = {"canonical": gp["email"], "userName": gp["userName"], "confidence": gp["confidence"], "rules": gp["rules"],
                "identities": gp["identities"], "flags": flags}
        review["merges"].append(item)
        if flags:
            review["review_first"].append(item)

    out_dir.mkdir(parents=True, exist_ok=True)
    review_path = out_dir / "config-people-for-review.json"
    review_path.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n")
    if not args.dry_run:
        (out_dir / "config-people.json").write_text(json.dumps({"people": people}, indent=2, ensure_ascii=False) + "\n")

    s = review["summary"]
    print(f"{s['mode']}: {s['identities_seen']} identities from {s['sources']} source(s) → {s['people_after_merge']} people; "
          f"{s['merged_people']} merged people absorb {s['identities_merged_away']} identities (min confidence {args.min_confidence})")
    for n in notes:
        print(f"note: {n}")
    print(f"review first ({len(review['review_first'])}):")
    for item in review["review_first"][:15]:
        print(f"  {item['userName']} <{item['canonical']}> [{item['confidence']}] " + "; ".join(item["flags"]))
        for i in item["identities"][:4]:
            print(f"      {i['commits']:>6} commits  {i['email']:<45} {i['userName']}  {i['first'][:10]}..{i['last'][:10]}")
    print(f"not applied ({len(not_applied)}): " + "; ".join(f"{x['a']['email']} ~ {x['b']['email']} ({x['rule']})" for x in not_applied[:6]) + (" …" if len(not_applied) > 6 else ""))
    print(f"wrote {review_path}" + ("" if args.dry_run else f" and {out_dir / 'config-people.json'} ({len(people)} entries)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
