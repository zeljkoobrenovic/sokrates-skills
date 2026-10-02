#!/usr/bin/env python3
"""Where am I, and what is the next Sokrates step? The entry point of the sokrates-skills.

Looks at a folder (default: the current one), works out whether it is a repository, a landscape root or
nothing yet, how far the Sokrates work has come (configuration, analysis, AI findings, improvements) and
prints the situation plus a ranked list of next steps, each naming the skill or command that does it.
Standard library only; reads config.json and data.zip, never the source tree.

Usage:
  python3 situation.py [folder] [--json out.json]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path


def alias_jar(command):
    """The jar a `sokrates` wrapper script runs, when the command is such a script (mirrors capabilities.py)."""
    import re
    path = shutil.which(command)
    if not path or not Path(path).is_file():
        return None
    try:
        head = Path(path).read_bytes()[:4000]
    except OSError:
        return None
    if b"\0" in head:
        return None
    match = re.search(rb"(\S+\.jar)", head)
    return match.group(1).decode("utf-8", errors="replace") if match else None


SKIP_DIRS = {".git", "node_modules", "target", "build", "dist", "venv", ".venv", "__pycache__", "_sokrates", "_sokrates_landscape"}


# ----------------------------------------------------------------------------- reading

def read_json(path):
    try:
        return json.loads(Path(path).read_text(errors="replace"))
    except (OSError, ValueError):
        return None


def zip_entry(zip_path, entry):
    try:
        with zipfile.ZipFile(zip_path) as archive:
            return archive.read(entry).decode("utf-8", errors="replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return None


def metrics_of(zip_path):
    text = zip_entry(zip_path, "text/metrics.txt") or ""
    out = {}
    for line in text.splitlines():
        key, _, value = line.partition(": ")
        try:
            out[key] = float(value) if "." in value else int(value)
        except ValueError:
            pass
    return out


def git_head_time(folder):
    """When analyzed content last changed: the newest commit that touched something other than documentation."""
    if not (folder / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "-C", str(folder), "log", "-1", "--format=%ct", "--", ".", ":(exclude,glob)**/*.md", ":(exclude)*.md",
                              ":(exclude)docs", ":(exclude)CHANGELOG*", ":(exclude)LICENSE*"], capture_output=True, text=True, timeout=10)
        return int(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def has_source_files(folder, limit=2000):
    seen = 0
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if "." in name and not name.startswith("."):
                seen += 1
                if seen >= 3:
                    return True
        if seen > limit:
            break
    return seen > 0


def find_repository_analyses(root, max_depth=4):
    """Repository analyses under a landscape root: a reports/data/data.zip (analyzeGitRepo layout) or
    _sokrates/reports/data/data.zip, never inside a _sokrates_landscape folder."""
    found = []
    root = Path(root)
    for dirpath, dirs, files in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        if len(rel.parts) > max_depth + 3:
            dirs[:] = []
            continue
        if "_sokrates_landscape" in rel.parts or ".git" in rel.parts:
            dirs[:] = []
            continue
        if Path(dirpath).name == "data" and "data.zip" in files and Path(dirpath).parent.name == "reports":
            analysis = Path(dirpath).parent.parent          # the folder holding config.json next to reports/
            if analysis.name == "_sokrates":
                analysis = analysis.parent
            if analysis != root:
                found.append(analysis)
            dirs[:] = []
    return sorted(set(found))


# ----------------------------------------------------------------------------- the probes

def tooling():
    docker = shutil.which("docker")
    sokrates = shutil.which("sokrates")
    java = shutil.which("java")
    jar = os.environ.get("SOKRATES_JAR")
    if sokrates:
        run = "sokrates"
    elif jar and Path(jar).is_file():
        run = f"java -jar {jar}"
    elif docker:
        run = 'docker run --rm -v "$(pwd):/code" ghcr.io/zeljkoobrenovic/sokrates'
    else:
        run = None
    agents = [a for a in ("claude", "codex", "gemini") if shutil.which(a)]
    return {"sokrates_cli": bool(sokrates), "jar": jar if jar and Path(jar).is_file() else None, "java": bool(java),
            "docker": bool(docker), "run": run, "agents": agents}


def repository_situation(folder, sokrates_dir=None):
    """A repository with its analysis under _sokrates/, or (sokrates_dir given) an analysis kept without its source,
    the layout analyzeGitRepo leaves: config.json next to reports/."""
    analysis_only = sokrates_dir is not None
    sokrates_dir = sokrates_dir or folder / "_sokrates"
    config = read_json(sokrates_dir / "config.json") if (sokrates_dir / "config.json").is_file() else None
    data_zip = sokrates_dir / "reports" / "data" / "data.zip"
    insights = sokrates_dir / "reports" / "ai-insights"
    s = {"kind": "analysis" if analysis_only else "repository", "folder": str(folder), "git": (folder / ".git").exists(),
         "config": config is not None, "analysis": data_zip.is_file(), "analysis_stale": None,
         "findings": {}, "findings_total": 0, "findings_attention": 0, "findings_with_recommendation": 0,
         "people_config": (sokrates_dir / "config-people.json").is_file(), "post_analysis": None,
         "metrics": {}, "largest_component_share": None, "components": None, "decompositions": [],
         "concerns": [], "contributors": None, "explorer": (insights / "index.html").is_file(),
         "has_sources": False if analysis_only else has_source_files(folder), "source_url": None}
    if analysis_only:
        marker = read_json(sokrates_dir / "source.json")
        if isinstance(marker, dict):
            s["source_url"] = marker.get("url")
    if config:
        s["decompositions"] = [{"name": d.get("name"), "depth": d.get("componentsFolderDepth"), "explicit": len(d.get("components") or [])}
                               for d in config.get("logicalDecompositions") or []]
        s["concerns"] = [c.get("name") for g in config.get("concernGroups") or [] for c in g.get("concerns") or []]
        s["name"] = (config.get("metadata") or {}).get("name")
    if data_zip.is_file():
        m = metrics_of(data_zip)
        s["metrics"] = {k: m.get(k) for k in ("LINES_OF_CODE_MAIN", "NUMBER_OF_FILES_MAIN", "LINES_OF_CODE_TEST", "DUPLICATION_PERCENTAGE",
                                               "NUMBER_OF_UNITS", "CONDITIONAL_COMPLEXITY_DISTRIBUTION_VERY_HIGH_RISK_LOC",
                                               "CONDITIONAL_COMPLEXITY_DISTRIBUTION_HIGH_RISK_LOC") if m.get(k) is not None}
        head = git_head_time(folder)
        s["analysis_stale"] = (head is not None and data_zip.stat().st_mtime < head)
        s["analysis_age_days"] = round((time.time() - data_zip.stat().st_mtime) / 86400, 1)
        contributors = zip_entry(data_zip, "text/contributors.txt")
        if contributors:
            s["contributors"] = max(0, len([l for l in contributors.splitlines() if l.strip()]) - 1)
        main_loc = s["metrics"].get("LINES_OF_CODE_MAIN") or 0
        try:
            with zipfile.ZipFile(data_zip) as archive:
                sizes = []
                for name in archive.namelist():
                    if name.startswith("text/aspect_component_primary_") and name.endswith(".txt"):
                        loc = 0
                        for line in archive.read(name).decode("utf-8", errors="replace").splitlines()[1:]:
                            cells = line.split("\t")
                            try:
                                loc += int(cells[1])
                            except (IndexError, ValueError):
                                pass
                        sizes.append(loc)
            if sizes:
                s["components"] = len(sizes)
                s["largest_component_share"] = round(100.0 * max(sizes) / main_loc, 1) if main_loc else None
        except (OSError, zipfile.BadZipFile):
            pass
    if insights.is_dir():
        for path in sorted(insights.glob("*.json")):
            doc = read_json(path)
            if not isinstance(doc, dict) or doc.get("scanner") in (None, "combined"):
                continue
            findings = [f for f in doc.get("findings") or [] if isinstance(f, dict)]
            s["findings"][doc["scanner"]] = {"count": len(findings), "analyzed_at": doc.get("analyzed_at"),
                                             "stale": data_zip.is_file() and path.stat().st_mtime < data_zip.stat().st_mtime}
            s["findings_total"] += len(findings)
            s["findings_attention"] += sum(1 for f in findings if str(f.get("severity")).lower() in ("critical", "high", "medium", "low"))
            s["findings_with_recommendation"] += sum(1 for f in findings if str(f.get("recommendation", "")).strip()
                                                     and str(f.get("severity")).lower() != "info")
    state = read_json(sokrates_dir / "post-analysis.json")
    if isinstance(state, dict):
        s["post_analysis"] = {k: state.get(k) for k in ("command", "ranOn", "exitCode")}
    return s


def landscape_situation(folder):
    landscape_dir = folder / "_sokrates_landscape"
    repos = find_repository_analyses(folder)
    config = read_json(landscape_dir / "config.json") if (landscape_dir / "config.json").is_file() else None
    s = {"kind": "landscape", "folder": str(folder), "repositories": len(repos),
         "repository_folders": [str(r.relative_to(folder)) for r in repos[:50]],
         "config": config is not None, "report": (landscape_dir / "index.html").is_file(),
         "data": (landscape_dir / "data" / "data.zip").is_file(),
         "people_config": (landscape_dir / "config-people.json").is_file(),
         "virtual_landscapes": len(((config or {}).get("virtualLandscapes") or {}).get("landscapes") or []),
         "repositories_with_findings": 0, "findings_total": 0, "sources_marked": 0}
    if config:
        s["name"] = (config.get("metadata") or {}).get("name")
    for repo in repos:
        insights = (repo / "reports" / "ai-insights") if (repo / "reports").is_dir() else (repo / "_sokrates" / "reports" / "ai-insights")
        if insights.is_dir():
            n = 0
            for path in insights.glob("*.json"):
                doc = read_json(path)
                if isinstance(doc, dict) and doc.get("scanner") not in (None, "combined"):
                    n += len(doc.get("findings") or [])
            if n:
                s["repositories_with_findings"] += 1
                s["findings_total"] += n
        if (repo / "source.json").is_file():
            s["sources_marked"] += 1
    return s


def classify(folder):
    if (folder / "_sokrates_landscape").is_dir():
        return landscape_situation(folder)
    if (folder / "config.json").is_file() and (folder / "reports" / "data" / "data.zip").is_file() and not (folder / "_sokrates").is_dir():
        return repository_situation(folder, sokrates_dir=folder)
    if (folder / "_sokrates").is_dir() or (folder / ".git").exists():
        return repository_situation(folder)
    repos = find_repository_analyses(folder, max_depth=2)
    if len(repos) >= 2:
        return landscape_situation(folder)
    if has_source_files(folder):
        return repository_situation(folder)
    return {"kind": "empty", "folder": str(folder)}


# ----------------------------------------------------------------------------- the advice

def step(skill, why, command=None):
    return {"skill": skill, "why": why, "command": command}


def analysis_steps(s, tools):
    """An analysis kept without its source: everything that needs the tree happens where the source is."""
    run = tools["run"] or "sokrates"
    url = s.get("source_url")
    where = f"`{run} analyzeGitRepo -url {url}`" if url else f"`{run} analyzeGitRepo -url <git url>`"
    steps = [step("analyzeGitRepo", "this folder holds an analysis but no source code (the layout analyzeGitRepo keeps): scans, configuration previews "
                  "and improvements need the tree — re-run " + where + " (it reuses this config.json) with -ai <agent> to scan, or clone the repository and work there")]
    if s["findings"]:
        steps.append(step("sokrates-scan-core", f"{s['findings_total']} findings from {len(s['findings'])} scanners are here to read, summarize or diff: "
                          "summarize_findings.py / diff_findings.py on reports/ai-insights"))
    return steps


def repository_steps(s, tools):
    steps = []
    run = tools["run"]
    if not s["has_sources"] and not s["analysis"]:
        return [step("none", "no source files here — point me at a repository, or give a git URL for `sokrates analyzeGitRepo -url …`")]
    if not run:
        steps.append(step("install", "Sokrates is not installed: no `sokrates` on the PATH, no SOKRATES_JAR, no Docker",
                          "see https://sokrates.dev (Install & use): Docker image ghcr.io/zeljkoobrenovic/sokrates, or the CLI jar"))
    if not s["analysis"]:
        steps.append(step("analyze", "no analysis yet (`_sokrates/reports/data/data.zip` is missing)" + ("" if s["config"] else "; `analyze` also writes the first configuration"),
                          f"{run or 'sokrates'} analyze"))
    elif s["analysis_stale"]:
        steps.append(step("analyze", "the analysis is older than the last commit", f"{run or 'sokrates'} analyze"))
    if s["config"]:
        depth1 = all((d.get("depth") or 0) <= 1 and d.get("explicit", 0) == 0 for d in s["decompositions"]) and len(s["decompositions"]) <= 1
        share = s.get("largest_component_share")
        if depth1 and (s["components"] in (None, 1) or (share is not None and share >= 70)):
            steps.append(step("sokrates-decompositions", "the only decomposition is folder depth 1 and " +
                              (f"one component holds {share}% of the code" if share else "it yields a single component") +
                              " — the components, dependencies and ownership views say nothing yet"))
        if set(s["concerns"]) <= {"TODOs"}:
            steps.append(step("sokrates-features-of-interest", "no features of interest beyond the default TODOs — debt markers, security-sensitive code, integrations and feature flags are not tracked"))
        if s["contributors"] and s["contributors"] >= 2 and not s["people_config"]:
            steps.append(step("sokrates-people-config", f"{s['contributors']} contributor identities and no config-people.json — the same person may be counted several times"))
        if s["analysis"] and not depth1 and set(s["concerns"]) > {"TODOs"}:
            steps.append(step("sokrates-repo-config", "the configuration has been tuned; re-check the scope (generated and vendored code in main, extensions missing) when the tree changed a lot"))
    if s["analysis"]:
        if not s["findings"]:
            steps.append(step("full-scan", "no AI findings yet — a basic scan (what is this, what does it do, how is it built) is the next layer; a deep dive answers a specific worry",
                              "ask for a basic scan, or `sokrates analyze -ai claude` next time"))
        else:
            stale = [k for k, v in s["findings"].items() if v["stale"]]
            if stale:
                steps.append(step("full-scan", f"findings of {', '.join(stale)} predate the current analysis — re-run those scanners (or diff_findings.py after)"))
            if not s["explorer"]:
                steps.append(step("sokrates-scan-core", "findings exist but no explorer page", "python3 <scan-core>/scripts/render_findings.py _sokrates/reports"))
            if s["findings_with_recommendation"]:
                steps.append(step("sokrates-improve", f"{s['findings_with_recommendation']} findings carry a recommendation; the analysis also ranks complex units, duplicated blocks and hotspots — act on one and prove it with the numbers"))
            elif s["metrics"].get("LINES_OF_CODE_MAIN"):
                steps.append(step("sokrates-improve", "pick the most complex unit, the costliest duplicate or a hotspot and improve it, measured before and after"))
    return steps


def landscape_steps(s, tools):
    steps = []
    run = tools["run"] or "sokrates"
    if s["repositories"] == 0:
        steps.append(step("analyzeLandscape", "no repository analyses under this root",
                          f"{run} analyzeLandscape -urls repos.txt   (or analyzeGitHubOrg -org <login>, analyzeGitLabGroup -group <path>)"))
        return steps
    if not s["report"] and not s["data"]:
        steps.append(step("analyzeLandscape", f"{s['repositories']} repository analyses but no landscape report yet", f"{run} analyzeLandscape"))
    steps.append(step("sokrates-landscape-config", "check what the landscape will aggregate: discovery, thresholds, tags, teams, name and description",
                      "python3 <landscape-config>/scripts/check_landscape.py ."))
    if not s["people_config"]:
        steps.append(step("sokrates-people-config", "no landscape config-people.json — identities are merged per address only", "python3 <people-config>/scripts/build_people_config.py --landscape ."))
    if s["repositories"] >= 5 and s["virtual_landscapes"] == 0:
        steps.append(step("sokrates-virtual-landscapes", f"{s['repositories']} repositories and no virtual landscapes — group them by naming convention, technology, team or activity"))
    if s["repositories"] >= 2:
        steps.append(step("sokrates-improve", f"across {s['repositories']} repositories: the most complex units, costliest duplicates and most urgent findings ranked together say which repository to improve first",
                          "python3 <sokrates-improve>/scripts/select_targets.py --landscape ."))
    if s["repositories_with_findings"] >= 2:
        steps.append(step("landscape-synthesis-scan", f"{s['repositories_with_findings']} repositories carry AI findings — the portfolio story (concentration, recurring findings, coverage gaps, priorities) is one scan away",
                          "python3 <landscape-synthesis-scan>/scripts/landscape_digest.py ."))
    if s["repositories_with_findings"] < s["repositories"]:
        missing = s["repositories"] - s["repositories_with_findings"]
        steps.append(step("full-scan", f"{missing} of {s['repositories']} repositories have no AI findings — the landscape's AI Insights tab aggregates them",
                          f"{run} analyzeLandscape -ai claude -aiMaxRepos 5   (incremental: only repositories whose head moved)"))
    return steps


def describe(s, tools):
    lines = []
    if s["kind"] == "empty":
        lines.append(f"{s['folder']}: no source files, no Sokrates analysis, no landscape.")
    elif s["kind"] in ("repository", "analysis"):
        name = s.get("name") or Path(s["folder"]).name
        if s["kind"] == "analysis":
            lines.append(f"Analysis of {name} ({s['folder']}), without the source" + (f"; from {s['source_url']}" if s.get("source_url") else ""))
        else:
            lines.append(f"Repository {name} ({s['folder']})" + ("" if s["git"] else ", no .git"))
        if s["analysis"]:
            m = s["metrics"]
            parts = [f"analysis {s.get('analysis_age_days')} days old" + (" — STALE, older than the last commit" if s["analysis_stale"] else "")]
            if m.get("LINES_OF_CODE_MAIN") is not None:
                parts.append(f"{m['LINES_OF_CODE_MAIN']} main LOC in {m.get('NUMBER_OF_FILES_MAIN')} files")
            if m.get("DUPLICATION_PERCENTAGE") is not None:
                parts.append(f"duplication {round(m['DUPLICATION_PERCENTAGE'], 1)}%")
            if s["components"]:
                parts.append(f"{s['components']} components (largest {s['largest_component_share']}%)")
            if s["contributors"] is not None:
                parts.append(f"{s['contributors']} contributor identities")
            lines.append("  " + "; ".join(parts))
        else:
            lines.append("  no analysis" + (", configuration present" if s["config"] else ", no configuration"))
        if s["findings"]:
            lines.append(f"  AI findings: {s['findings_total']} from {len(s['findings'])} scanners ({s['findings_attention']} above info)" +
                         ("" if s["explorer"] else ", no explorer page"))
        else:
            lines.append("  AI findings: none")
        if s["post_analysis"]:
            lines.append(f"  post-analysis hook ran on {s['post_analysis'].get('ranOn')} (exit {s['post_analysis'].get('exitCode')})")
    else:
        lines.append(f"Landscape {s.get('name') or Path(s['folder']).name} ({s['folder']}): {s['repositories']} repository analyses" +
                     (f", {s['sources_marked']} from git URLs (prunable)" if s["sources_marked"] else ""))
        lines.append("  " + ("report present" if s["report"] else ("data only" if s["data"] else "no landscape report yet")) +
                     f"; AI findings in {s['repositories_with_findings']} repositories ({s['findings_total']} findings)" +
                     f"; virtual landscapes: {s['virtual_landscapes']}; people config: {'yes' if s['people_config'] else 'no'}")
    run = tools["run"]
    jar = alias_jar("sokrates") if run == "sokrates" else None
    wrapped = f" (runs {jar}, built {time.strftime('%Y-%m-%d', time.localtime(Path(jar).stat().st_mtime))})" if jar and Path(jar).is_file() else ""
    lines.append("  Sokrates: " + (f"run as `{run}`{wrapped}" if run else "NOT FOUND (no sokrates, SOKRATES_JAR or docker)") +
                 (f"; agents on PATH: {', '.join(tools['agents'])}" if tools["agents"] else "; no agent CLI on PATH"))
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?", default=".")
    ap.add_argument("--json", help="write the situation and steps as JSON here")
    args = ap.parse_args()
    folder = Path(args.folder).resolve()
    if not folder.is_dir():
        print(f"error: {folder} is not a directory", file=sys.stderr)
        return 2
    tools = tooling()
    s = classify(folder)
    steps = {"repository": repository_steps, "analysis": analysis_steps, "landscape": landscape_steps}.get(s["kind"], lambda s, t: [
        step("none", "nothing to do here — give a repository folder, a git URL (`sokrates analyzeGitRepo -url …`) or a folder of analyses")])(s, tools)
    for line in describe(s, tools):
        print(line)
    print("\nNext steps, in order:")
    for i, st in enumerate(steps, 1):
        print(f"{i:3d}. [{st['skill']}] {st['why']}")
        if st["command"]:
            print(f"       {st['command']}")
    if args.json:
        Path(args.json).write_text(json.dumps({"situation": s, "tooling": tools, "steps": steps}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
