#!/usr/bin/env python3
"""What can the installed Sokrates do? A probe instead of dated advice.

Runs the Sokrates CLI found on this machine with no command (which prints the usage), parses the
commands and their options, and reports the capabilities the skills branch on: the one-shot commands,
-dataOnly, -ai / -postAnalysis, -prune, -urls, addCustomTab, the organization commands. With --data it
also reports which exports a data.zip holds. Standard library only.

Usage:
  python3 capabilities.py [--run "<command prefix>"] [--data <data.zip or folder>] [--json out.json]

The runner is detected like situation.py does (sokrates on the PATH, SOKRATES_JAR, Docker) unless --run
gives it; a `sokrates` wrapper script is read to name the jar it runs.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from situation import tooling  # noqa: E402

CAPABILITY_RULES = {   # capability -> (command that must exist, option it must have or None)
    "analyze": ("analyze", None),
    "analyzeGitRepo": ("analyzeGitRepo", None),
    "analyzeLandscape": ("analyzeLandscape", None),
    "analyzeGitHubOrg": ("analyzeGitHubOrg", None),
    "analyzeGitLabGroup": ("analyzeGitLabGroup", None),
    "addCustomTab": ("addCustomTab", None),
    "dataOnly": ("generateReports", "-dataOnly"),
    "ai": ("analyze", "-ai"),
    "postAnalysis": ("analyze", "-postAnalysis"),
    "aiMaxRepos": ("analyzeLandscape", "-aiMaxRepos"),
    "prune": ("analyzeLandscape", "-prune"),
    "urls": ("analyzeLandscape", "-urls"),
    "skipGitHistory": ("analyze", "-skipGitHistory"),
}

DATA_FEATURES = {   # feature -> an entry whose presence proves it
    "history_zip": "zips/git-history.zip",
    "units": "units.json",
    "duplicates": "duplicates.json",
    "temporal_dependencies": "text/temporal_dependencies_different_folders_30_days.txt",
    "files_with_history": "text/mainFilesWithHistory.txt",
    "contributors": "text/contributors.txt",
    "metrics": "text/metrics.txt",
}


def alias_jar(command):
    """The jar a `sokrates` wrapper script runs, when the command is such a script."""
    path = shutil.which(command) if command and "/" not in command else command
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


def usage_text(run):
    """The CLI's usage output; `help` is not a command, so the CLI answers with the usage (and never runs an analysis, which a bare Docker run would)."""
    try:
        completed = subprocess.run(run + " help", shell=True, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"could not run `{run} help`: {e}"
    text = (completed.stdout or "") + (completed.stderr or "")
    if "Commands:" not in text and "* analyze" not in text:
        return None, f"`{run} help` did not print the Sokrates usage (exit {completed.returncode}): {text.strip()[:200]}"
    return text, None


def parse_usage(text):
    """{command: [option names]} from the usage output: `* <command>: ...` lines followed by `- options: [-x <arg>] ...`."""
    commands = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^\* (\w+):", line)
        if m:
            current = m.group(1)
            commands[current] = []
            continue
        m = re.match(r"^\s+- options:\s*(.*)$", line)
        if m and current:
            commands[current] = re.findall(r"\[(-\w+)", m.group(1))
    return commands


def capabilities_of(commands):
    out = {}
    for name, (command, option) in CAPABILITY_RULES.items():
        out[name] = command in commands and (option is None or option in commands[command])
    return out


def data_features(path):
    p = Path(path)
    zip_path = p if p.is_file() else next((c for c in (p / "data.zip", p / "data" / "data.zip", p / "reports" / "data" / "data.zip",
                                                       p / "_sokrates" / "reports" / "data" / "data.zip") if c.is_file()), None)
    if not zip_path:
        return None
    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = set(archive.namelist())
    except (OSError, zipfile.BadZipFile):
        return None
    return {"zip": str(zip_path), "written": time.strftime("%Y-%m-%d", time.localtime(zip_path.stat().st_mtime)),
            **{feature: entry in names for feature, entry in DATA_FEATURES.items()}}


def installed_skills(folder):
    """The skills an agent folder holds, and the ones its source has that are not linked there (added after the last install).
    Every entry is a link or a copy of a skill folder; the source is where the `sokrates` entry skill's link points."""
    folder = Path(folder)
    if not folder.is_dir():
        return {"folder": str(folder), "present": False, "installed": [], "missing": [], "source": None}
    installed = sorted(p.name for p in folder.iterdir() if (p / "SKILL.md").is_file())
    source, missing = None, []
    entry = folder / "sokrates"
    if entry.is_symlink():
        try:
            root = entry.resolve().parent.parent          # <source>/skills/sokrates -> <source>
            if (root / "skills").is_dir():
                source = str(root)
                available = {p.parent.name for p in (root / "skills").glob("*/SKILL.md")} | {p.parent.name for p in (root / "skills").glob("*/*/SKILL.md")}
                missing = sorted(available - set(installed))
        except OSError:
            pass
    return {"folder": str(folder), "present": True, "installed": installed, "missing": missing, "source": source}


def agent_skill_folders():
    home = Path.home()
    return {"claude": home / ".claude" / "skills", "codex, gemini, cursor, copilot": home / ".agents" / "skills"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", help="the command prefix that runs Sokrates (default: detected)")
    ap.add_argument("--data", help="a data.zip (or a folder holding one) whose exports to report")
    ap.add_argument("--skills", action="store_true", help="also report which sokrates-skills the agents' skills folders hold, and which are missing since the last install")
    ap.add_argument("--json", help="write the result as JSON here")
    args = ap.parse_args()
    tools = tooling()
    run = args.run or tools["run"]
    result = {"run": run, "jar": None, "jar_built": None, "commands": {}, "capabilities": {}, "data": None, "error": None}
    if not run:
        result["error"] = "Sokrates not found: no `sokrates` on the PATH, no SOKRATES_JAR, no docker"
    else:
        jar = alias_jar(run.split()[0]) if run.split()[0] == "sokrates" else (tools["jar"] if run.startswith("java ") else None)
        if jar and Path(jar).is_file():
            result["jar"] = jar
            result["jar_built"] = time.strftime("%Y-%m-%d", time.localtime(Path(jar).stat().st_mtime))
        text, error = usage_text(run)
        if error:
            result["error"] = error
        else:
            result["commands"] = parse_usage(text)
            result["capabilities"] = capabilities_of(result["commands"])
    if args.data:
        result["data"] = data_features(args.data)
    if args.skills:
        result["skills"] = {agents: installed_skills(folder) for agents, folder in agent_skill_folders().items()}
    if result["error"]:
        print(f"Sokrates: {result['error']}")
    else:
        print(f"Sokrates: `{run}`" + (f" runs {result['jar']} (built {result['jar_built']})" if result["jar"] else ""))
        print(f"  commands ({len(result['commands'])}): {', '.join(result['commands'])}")
        have = [k for k, v in result["capabilities"].items() if v]
        lack = [k for k, v in result["capabilities"].items() if not v]
        print(f"  has: {', '.join(have) or '-'}")
        if lack:
            print(f"  lacks (older build): {', '.join(lack)}")
    if result["data"]:
        d = result["data"]
        print(f"  data: {d['zip']} (written {d['written']}); " + ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in d.items() if k not in ("zip", "written")))
    elif args.data:
        print(f"  data: no data.zip at {args.data}")
    for agents, info in (result.get("skills") or {}).items():
        if not info["present"]:
            print(f"  skills for {agents}: none ({info['folder']} does not exist) — run `sokrates installSkills`")
        elif info["missing"]:
            print(f"  skills for {agents}: {len(info['installed'])} installed, {len(info['missing'])} added since the last install and not linked: "
                  f"{', '.join(info['missing'])} — run `sokrates installSkills` (or install.sh) again")
        else:
            print(f"  skills for {agents}: {len(info['installed'])} installed" + (" (sokrates entry skill missing)" if "sokrates" not in info["installed"] else ""))
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))
    return 0 if not result["error"] else 1


if __name__ == "__main__":
    sys.exit(main())
