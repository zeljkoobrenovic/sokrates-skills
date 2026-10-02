---
name: sokrates
description: Start here for anything about Sokrates (sokrates.dev), a source-code analysis tool - "analyze this repository", "what is this codebase", "set up / improve the Sokrates config", "scan for risks", "build a landscape of our repositories", "improve the code where it matters". Works out where the user is (no analysis yet, a fresh configuration, findings present, a landscape root) and routes to the right sokrates-skill, running Sokrates itself when that is the next step.
---

# Sokrates (start here)

Sokrates measures a codebase - size, complexity, duplication, churn, coupling, contributors - and writes
one analysis per repository (`_sokrates/`) or one landscape over many (`_sokrates_landscape/`). The
other sokrates-skills configure it, add AI findings on top of its data, and act on what it found.
This skill decides which of them applies now. Do not guess the situation: measure it.

## 1. Find out where you are

```bash
python3 <this-skill-path>/scripts/situation.py [folder] [--json <scratch>/situation.json]
```

It prints the situation (repository or landscape, analysis present and how old, configuration tuned or
not, AI findings, how Sokrates can be run on this machine) and **ranked next steps, each naming the
skill or command**. Trust the order: a step only makes sense once the ones before it are done - findings
built on an untuned configuration describe the wrong scope, an improvement measured on a stale analysis
proves nothing.

## 2. Act on the first applicable step

| the script says | do |
| --- | --- |
| `[install]` | Sokrates is not on this machine. Tell the user the options (Docker image `ghcr.io/zeljkoobrenovic/sokrates`, the CLI jar) and stop; do not substitute your own analysis. |
| `[analyze]` | Run the printed command in the repository root (it includes git history extraction, `init` when there is no configuration, and the reports). Then re-run `situation.py`. |
| `[sokrates-repo-config]` `[sokrates-decompositions]` `[sokrates-features-of-interest]` `[sokrates-people-config]` | Load that skill and follow it. Every change to `config.json` is followed by `sokrates analyze` (or `generateReports`), so the data the next steps read is current. |
| `[full-scan]` | Load `full-scan`; it chooses the bundle (basic, a deep-dive family, or full) from what the user asked. A named worry ("is it secure", "well tested") goes straight to that scanner family. |
| `[sokrates-scan-core]` | Findings without an explorer page: run the printed `render_findings.py`. |
| `[sokrates-improve]` | Load `sokrates-improve`; it selects a target from the data, changes the code on a branch and proves the effect by re-measuring. |
| `[analyzeLandscape]` `[sokrates-landscape-config]` `[sokrates-virtual-landscapes]` | Landscape work: run the printed command, then the landscape skills. |

When the user named what they want, start from that and use the situation only to check the
prerequisites - "scan this repo" with no analysis means: analyze first, say so, then scan.

## 3. Running Sokrates

`situation.py` prints the form that works here, in this preference: `sokrates` on the PATH, the jar from
`SOKRATES_JAR`, or Docker (`docker run --rm -v "$(pwd):/code" ghcr.io/zeljkoobrenovic/sokrates <command>`).
The commands that matter:

| command | does |
| --- | --- |
| `analyze` | one repository, in place: git history, configuration if missing, reports under `_sokrates/` |
| `analyzeGitRepo -url <git url>` | clone, analyze, keep only the analysis under `<owner>/<repo>/` |
| `analyzeLandscape [-urls repos.txt]` | analyze every listed repository, then the landscape over all analyses under the root |
| `analyzeGitHubOrg -org <login>` / `analyzeGitLabGroup -group <path>` | a whole organization, one landscape per org |
| `-dataOnly` | only the `data.zip` - enough for every skill, much faster, no HTML |
| `-ai claude\|codex\|gemini` | run the agent with the skills after each analysis (incremental, `-aiMaxRepos`, `-aiForce`) |

A relative `-confFile _sokrates/config.json` and an absolute source root both work in current builds;
Sokrates ignores its own output unconditionally. Older builds behave differently - when something looks
off, check the version (`<run> ` with no arguments prints the usage, which lists the commands and flags).

## 4. Which skill when (the map)

| you want | skill |
| --- | --- |
| the configuration right: scope, file classes, thresholds | `sokrates-repo-config` |
| meaningful components | `sokrates-decompositions` |
| debt markers, security-sensitive code, integrations, feature flags tracked | `sokrates-features-of-interest` |
| one person = one contributor | `sokrates-people-config` |
| what this codebase is, does, how it is built | `full-scan` (basic) |
| how good it is at testing, reliability, maintainability, risk | `full-scan` family `quality` |
| performance, storage, network, observability | `full-scan` family `runtime` |
| security, infrastructure, configuration | `full-scan` family `security` |
| the findings format, validation, explorer, merge, diff | `sokrates-scan-core` |
| make the code better where the numbers say so, and prove it | `sokrates-improve` |
| a landscape: what gets aggregated, tags, teams | `sokrates-landscape-config` |
| sub-landscapes by naming, technology, team, activity | `sokrates-virtual-landscapes` |

## 5. Rules shared by every skill

- Numbers come from the Sokrates data (`_sokrates/reports/data/data.zip`), never from reading the tree
  and estimating. Findings cite file, line and verbatim snippet and are validated before they are reported.
- Reports are generated artefacts: edit `config.json`, never a file under `reports/`.
- Say what was done and what was skipped. A scan that did not validate, an improvement that did not
  move the numbers, an analysis that could not run: report it as such.
