#!/usr/bin/env python3
"""Digest the AI findings of a whole landscape: where attention concentrates, what repeats, what is uncovered.

Deterministic pre-computation for the landscape-synthesis-scan skill. Reads the landscape's aggregated
`ai-insights.json` (written by `sokrates analyzeLandscape` into `_sokrates_landscape/data/data.zip`) or,
for landscapes built by an older Sokrates, every repository's `reports/ai-insights/<scanner>.json` under the
root, and emits:
  repositories_ranked   repositories by findings above info, with their severity mix and scanners
  recurring             the same finding id (scanner/group/slug) in two or more repositories — one fix
                        pattern that resolves many
  scanner_coverage      for every scanner that ran somewhere, the repositories it has not run on
  top_findings          the highest-severity findings across the landscape
  totals                findings by severity, repositories with and without findings

Usage:
  python3 landscape_digest.py <landscape root | ai-insights.json> [--top 15] [-o digest.json]
Standard library only.
"""

import argparse
import json
import os
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def severity_of(value):
    s = str(value or "info").lower()
    return s if s in SEVERITY_ORDER else "info"


def load_aggregated(root):
    """The landscape's own ai-insights.json: inside data/data.zip, or loose next to it."""
    folder = root / "_sokrates_landscape" / "data"
    loose = folder / "ai-insights.json"
    if loose.is_file():
        return json.loads(loose.read_text(errors="replace")), str(loose)
    archive = folder / "data.zip"
    if archive.is_file():
        try:
            with zipfile.ZipFile(archive) as z:
                if "ai-insights.json" in z.namelist():
                    return json.loads(z.read("ai-insights.json").decode("utf-8", errors="replace")), f"{archive}!ai-insights.json"
        except zipfile.BadZipFile:
            pass
    return None, None


def repository_name(analysis):
    config = analysis / "config.json"
    if not config.is_file():
        config = analysis / "_sokrates" / "config.json"
    try:
        name = (json.loads(config.read_text(errors="replace")).get("metadata") or {}).get("name")
        if name:
            return name
    except (OSError, ValueError):
        pass
    return analysis.name


def collect_from_repositories(root):
    """The aggregated shape, built from the repositories' own findings files (older landscapes)."""
    repositories, findings = [], []
    for dirpath, dirs, files in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        if "_sokrates_landscape" in rel.parts or ".git" in rel.parts or len(rel.parts) > 6:
            dirs[:] = []
            continue
        if Path(dirpath).name != "ai-insights":
            continue
        dirs[:] = []
        reports = Path(dirpath).parent
        analysis = reports.parent if reports.parent.name != "_sokrates" else reports.parent.parent
        repo = repository_name(analysis)
        scanners, by_severity, total = [], Counter(), 0
        for path in sorted(Path(dirpath).glob("*.json")):
            try:
                doc = json.loads(path.read_text(errors="replace"))
            except (OSError, ValueError):
                continue
            if not isinstance(doc, dict) or doc.get("scanner") in (None, "combined") or "findings" not in doc:
                continue
            fs = [f for f in doc["findings"] if isinstance(f, dict)]
            scanners.append({"scanner": doc["scanner"], "analyzedAt": doc.get("analyzed_at", ""), "findings": len(fs),
                             "attention": sum(1 for f in fs if severity_of(f.get("severity")) != "info"), "summary": doc.get("summary", "")})
            for f in fs:
                sev = severity_of(f.get("severity"))
                by_severity[sev] += 1
                total += 1
                findings.append({"repo": repo, "scanner": doc["scanner"], "id": f.get("id", ""), "group": f.get("group", ""), "title": f.get("title", ""),
                                 "severity": sev, "confidence": f.get("confidence", ""), "description": f.get("description", ""),
                                 "recommendation": f.get("recommendation", ""), "url": ""})
        if scanners:
            repositories.append({"name": repo, "scannedAt": max(s["analyzedAt"] for s in scanners), "scanners": scanners,
                                 "findingsBySeverity": dict(by_severity), "findings": total, "attention": total - by_severity["info"]})
    return {"repositories": repositories, "findings": findings}


def count_repositories(root):
    """Every repository analysis under the root (with or without findings), like the landscape counts them."""
    found = 0
    for dirpath, dirs, files in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        if "_sokrates_landscape" in rel.parts or ".git" in rel.parts or len(rel.parts) > 6:
            dirs[:] = []
            continue
        if Path(dirpath).name == "data" and "data.zip" in files and Path(dirpath).parent.name == "reports":
            found += 1
            dirs[:] = []
    return found


def digest(doc, top, repositories_total=None):
    repos = doc.get("repositories") or []
    findings = [f for f in doc.get("findings") or [] if isinstance(f, dict)]
    by_severity = Counter(severity_of(f.get("severity")) for f in findings)
    ranked = sorted(repos, key=lambda r: (-int(r.get("attention", 0)), -int(r.get("findings", 0)), r.get("name", "")))
    repositories_ranked = [{"repo": r.get("name"), "attention": r.get("attention", 0), "findings": r.get("findings", 0),
                            "by_severity": r.get("findingsBySeverity", {}), "scanners": [s.get("scanner") for s in r.get("scanners") or []],
                            "scanned_at": r.get("scannedAt", "")} for r in ranked]
    by_id = defaultdict(list)
    for f in findings:
        if f.get("id"):
            by_id[f["id"]].append(f)
    recurring = []
    for fid, group in by_id.items():
        repo_names = sorted({f.get("repo", "") for f in group})
        if len(repo_names) >= 2:
            worst = min(group, key=lambda f: SEVERITY_ORDER[severity_of(f.get("severity"))])
            recurring.append({"id": fid, "repositories": repo_names, "count": len(repo_names), "severity": severity_of(worst.get("severity")),
                              "title": worst.get("title", ""), "recommendation": worst.get("recommendation", "")})
    recurring.sort(key=lambda r: (-r["count"], SEVERITY_ORDER[r["severity"]], r["id"]))
    scanners_present = sorted({s.get("scanner") for r in repos for s in r.get("scanners") or [] if s.get("scanner")})
    coverage = {}
    for scanner in scanners_present:
        lacking = sorted(r.get("name", "") for r in repos if scanner not in [s.get("scanner") for s in r.get("scanners") or []])
        coverage[scanner] = {"ran_on": len(repos) - len(lacking), "missing_in": lacking}
    top_findings = sorted((f for f in findings if severity_of(f.get("severity")) != "info"),
                          key=lambda f: (SEVERITY_ORDER[severity_of(f.get("severity"))], f.get("repo", ""), f.get("id", "")))[:top]
    return {
        "totals": {"repositories_with_findings": len(repos), "repositories_total": repositories_total if repositories_total is not None else len(repos),
                   "findings": len(findings), "attention": len(findings) - by_severity["info"], "by_severity": {s: by_severity[s] for s in SEVERITY_ORDER},
                   "scanners": scanners_present},
        "repositories_ranked": repositories_ranked,
        "recurring": recurring,
        "scanner_coverage": coverage,
        "top_findings": [{k: f.get(k, "") for k in ("repo", "scanner", "id", "severity", "confidence", "title", "recommendation", "url")} for f in top_findings],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="the landscape root (holds _sokrates_landscape/ and the repository analyses), or an ai-insights.json")
    ap.add_argument("--top", type=int, default=15, help="top findings to list (default 15)")
    ap.add_argument("-o", "--output", help="write the digest as JSON here")
    args = ap.parse_args()
    target = Path(args.target)
    repositories_total = None
    if target.is_file():
        doc, source = json.loads(target.read_text(errors="replace")), str(target)
    elif target.is_dir():
        doc, source = load_aggregated(target)
        if doc is None:
            doc, source = collect_from_repositories(target), f"{target} (repository findings files; no aggregated ai-insights.json)"
        repositories_total = count_repositories(target)
    else:
        print(f"error: {target} does not exist", file=sys.stderr)
        return 2
    if not doc.get("repositories"):
        print(f"error: no AI findings in {source} — run the scanners on the repositories first (sokrates analyzeLandscape -ai <agent>)", file=sys.stderr)
        return 1
    result = digest(doc, args.top, repositories_total)
    t = result["totals"]
    print(f"Landscape AI findings — {source}")
    print(f"  {t['repositories_with_findings']} of {t['repositories_total']} repositories have findings: {t['findings']} findings, {t['attention']} above info "
          f"({', '.join(f'{n} {s}' for s, n in t['by_severity'].items() if n and s != 'info') or 'none'}); scanners: {', '.join(t['scanners'])}")
    print("\nRepositories by attention:")
    for r in result["repositories_ranked"][:args.top]:
        mix = ", ".join(f"{n} {s}" for s, n in sorted(r["by_severity"].items(), key=lambda kv: SEVERITY_ORDER.get(kv[0], 9)) if n and s != "info")
        print(f"  {r['attention']:4d}  {r['repo']:<40} {mix or '-'}   [{', '.join(r['scanners'])}]")
    print(f"\nRecurring findings (same id in several repositories): {len(result['recurring'])}")
    for r in result["recurring"][:args.top]:
        print(f"  {r['count']:3d}x  {r['severity']:<8} {r['id']}  — {r['title'][:70]}")
        print(f"        in: {', '.join(r['repositories'][:8])}" + (f" … +{len(r['repositories']) - 8}" if len(r["repositories"]) > 8 else ""))
    gaps = {s: c for s, c in result["scanner_coverage"].items() if c["missing_in"]}
    print(f"\nScanner coverage gaps: {len(gaps)}")
    for s, c in gaps.items():
        print(f"  {s:<24} ran on {c['ran_on']}, missing in {len(c['missing_in'])}: {', '.join(c['missing_in'][:6])}" + (" …" if len(c["missing_in"]) > 6 else ""))
    print(f"\nTop findings:")
    for f in result["top_findings"]:
        print(f"  {f['severity']:<8} {f['repo']:<28} {f['id']}  — {f['title'][:60]}")
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2))
        print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
