---
name: landscape-synthesis-scan
description: The portfolio story over a whole Sokrates landscape's AI findings: where attention concentrates, which findings recur across repositories so one fix pattern resolves many, which repositories or scanners are uncovered, and what to do first across the estate. Use on a landscape (_sokrates_landscape/) whose repositories were scanned: risks across our repositories, what repeats, which repos need attention first. Needs findings in at least one repository.
---

# Landscape synthesis scan

The per-repository scanners say what is wrong in one codebase. A landscape aggregates their findings
(`sokrates analyzeLandscape` writes `_sokrates_landscape/data/ai-insights.json` and the AI Insights tab),
but nothing reads the aggregate. This scanner does: it turns hundreds of findings over dozens of
repositories into the few things a portfolio owner must know. Read `sokrates-scan-core/SKILL.md` first;
the findings format, the evidence rules and the validate/render steps apply here too, with the
landscape-level adaptations below.

## Workflow

1. **Digest the landscape** - deterministic, from the aggregated data:
   ```bash
   python3 <this-skill-path>/scripts/landscape_digest.py <landscape root> [--top 15] [-o <scratch>/digest.json]
   ```
   It reads the landscape's `ai-insights.json` (or, for older landscapes, every repository's findings
   files) and reports: repositories ranked by findings above info with their severity mix and the scanners
   that ran; **recurring** findings - the same `scanner/group/slug` id in two or more repositories (the
   stable-id contract makes this possible; it is why ids derive from the subject, not the wording);
   **scanner coverage gaps** - repositories a scanner never ran on; and the top findings by severity.
   No findings at all means stop: say that the repositories must be scanned first
   (`sokrates analyzeLandscape -ai claude -aiMaxRepos 10` scans incrementally).

2. **Read where the digest points, not everything.** Open the findings files (or the explorers) of the
   top three to five repositories by attention and of every recurring finding, enough to say *why* the
   same thing shows up in several places (a shared template, a copied module, a convention, an org-wide
   default) and whether one fix would resolve it everywhere. Do not re-verify per-repository evidence -
   those scanners did, and `validate_findings.py` passed there.

3. **Write the findings**, grouped:
   | group | what goes in it |
   | --- | --- |
   | `concentration` | where attention concentrates: the repositories that carry most of the above-info findings, and whether that is size, age, a team, or neglect |
   | `recurring` | one finding per recurring pattern: which repositories, the common cause, the single fix that would resolve it in all of them |
   | `coverage` | what the picture cannot show: repositories without findings, scanners that never ran, stale scans (`scannedAt` far behind the latest commit) |
   | `priorities` | the ordered list of what to do first across the estate, each item naming repositories and the finding ids it resolves |
   | `posture` | one summary finding (severity `info`) with the landscape-wide numbers |

   Severity follows the worst underlying finding for `recurring`, the share of the estate for
   `concentration`, and is `info` for `coverage` and `posture`. Landscape findings have **no file/line
   evidence**: their grounding is the per-repository findings they rest on, cited in `sokrates_refs` as
   `landscape:<repository name>#<finding id>` (one entry per underlying finding, at least two for a
   recurring one), plus `data:ai-insights.json` for numbers taken from the aggregate. Confidence is
   `certain` when the underlying findings are, `likely` when the common cause is inferred.

4. **Save, validate, render** into the landscape folder, which has no `ai-insights/` of its own yet:
   ```bash
   mkdir -p <landscape root>/_sokrates_landscape/ai-insights
   # write landscape-synthesis-scan.json there, target.name = the landscape's metadata.name, target.src_root = "../.."
   python3 <core-skill-path>/scripts/validate_findings.py <landscape root>/_sokrates_landscape/ai-insights/landscape-synthesis-scan.json --src-root <landscape root>
   python3 <core-skill-path>/scripts/render_findings.py <landscape root>/_sokrates_landscape/ai-insights/
   python3 <core-skill-path>/scripts/summarize_findings.py <landscape root>/_sokrates_landscape/ai-insights/ -o <landscape root>/_sokrates_landscape/ai-insights/summary.md
   ```
   The summary Markdown is what goes to the people who own the estate; the explorer is for browsing.

5. **Report**: the posture in one paragraph, the top priorities with the repositories each touches, the
   recurring patterns with their single fix, and the coverage gaps - and what the next step is
   (`sokrates-improve` on the first priority's repositories, or scanning the uncovered ones).

## What this scanner is not

It does not scan code. Everything it says rests on the per-repository scanners' findings; when those are
thin or stale, it says so under `coverage` instead of filling the gap with guesses.
