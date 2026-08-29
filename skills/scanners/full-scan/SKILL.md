---
name: full-scan
description: Orchestrates the Sokrates AI scanner suite over one codebase in whichever bundle the user asks for - a basic scan (the six descriptive scanners that answer "what is this codebase"), a deep dive (the evaluative scanners, all of them or one named family: quality, runtime, security), or a full scan (all seventeen) - running them in dependency order so later scanners build on earlier findings, validating each, merging into the combined report, and diffing against previous results on re-runs. Use when the user asks for a full scan, a basic or quick scan, a deep dive, an overview of an unfamiliar codebase, "run all scanners", a whole-codebase audit combining tech stack + functionality + risks + CI/CD + IaC + configuration + testing + observability + reliability + performance + storage + network + security + architecture + domain + maintainability, or a re-scan to see what changed. Requires a _sokrates analysis in the target project.
---

# Full scan (orchestrator)

Runs the scanner family and produces one combined, validated result. The individual scanners do the work — this skill only supplies the bundle, the order, the shared setup, and the roll-up. Read `sokrates-scan-core/SKILL.md` first as always; each scanner's own SKILL.md governs its scan.

## Which bundle to run

The family splits in two. **Basic** scanners *describe* the codebase — they answer "what is this, what does it do, how is it built" and are what a newcomer needs. **Deep dives** *evaluate* one dimension each, and answer "how good is it at X". The split is recorded as `tier` in `templates/scanners.json` (deep dives also carry a `family`), and the explorer groups its sidebar by it.

| bundle | scanners | when |
|---|---|---|
| **basic** | `functionality-scan`, `domain-language-scan`, `architecture-scan`, `evolution-scan`, `tech-stack-scan`, `cicd-scan` | "what is this codebase", onboarding, a first pass on something unfamiliar, a cheap re-run to see what moved |
| **deep dive** | every non-basic scanner, or one named family | "how good is X", a review with a specific worry, or a follow-up after a basic scan |
| **full** | all seventeen | a complete audit, a baseline, the artifact of record |

Deep dives run as a whole or by **family**, so the user can name a dimension instead of paying for all eleven:

| family | scanners | the question |
|---|---|---|
| `quality` | `testing-scan`, `reliability-scan`, `maintainability-scan`, `risk-synthesis-scan` | can we keep changing this safely? |
| `runtime` | `performance-scan`, `storage-scan`, `network-scan`, `observability-scan` | how does it behave when it runs? |
| `security` | `security-scan`, `iac-scan`, `configuration-scan` | what is exposed, and how is it deployed and configured? |

**Choosing when the user did not say.** "Scan this repo", "analyse this codebase", "what is this" → basic, and say what a deep dive would add. A named worry ("is this well tested", "how does it handle load", "is it secure") → the matching family, plus `tech-stack-scan` when nothing has been scanned yet. "Full scan", "everything", "audit" → full. When a request is ambiguous and the codebase is large, propose basic first rather than silently spending a full scan; when it is small (under ~20k lines) the difference is minor, so prefer the wider bundle.

**Deep dives read basic findings.** A deep dive on a project with no existing findings still runs (the skills degrade gracefully), but it orients from `tech-stack-scan`, `functionality-scan` and `architecture-scan` when they are there. If none exist and the deep dive is more than one family, run the basic bundle first — it is cheaper than every deep dive re-deriving the same skeleton, and the cross-references land.

## Why order matters

Scanners consume earlier scanners' findings (each re-verifies evidence itself, but the orientation savings are large). The dependency order observed in practice:

| wave | scanners | consume |
|---|---|---|
| 1 | `tech-stack-scan`, `risk-synthesis-scan` | Sokrates data only |
| 2 | `functionality-scan`, `cicd-scan`, `observability-scan`, `reliability-scan` |
| 2b | `testing-scan` | tech-stack (frameworks), cicd (gating), functionality (feature list), risk-synthesis (hotspots) — run after `cicd-scan` and `functionality-scan` | tech-stack (the stack skeleton, telemetry SDKs, resilience libraries, product surfaces) and risk-synthesis (hotspots as the load-bearing paths) |
| 3 | `architecture-scan` | waves 1–2 (stack skeleton, coupling, isolation boundaries from reliability) — its `security-boundaries` group feeds wave 4 |
| 3b | `performance-scan`, `storage-scan`, `network-scan`, `iac-scan`, `configuration-scan` | waves 1–3 (functionality for workload/data/integrations, architecture for the main loop and communication, reliability for the write-safety and retry verdicts they reference; for `iac-scan` also cicd's deployment and release findings, for `configuration-scan` functionality's entry points) — run after `architecture-scan` and `reliability-scan`; independent of each other |
| 4 | `security-scan`, `domain-language-scan` | wave 3 (architecture's security boundaries and component map; network/storage for TLS, endpoints and secret files; iac for declared infrastructure hardening and configuration for the secret-supply plumbing whose protection security then rates; the feature inventory as the capability list) |
| 5 | `evolution-scan` | waves 1–4 (component names, hotspots and knowledge risk, migrations in progress to date the story against) |
| 6 | `maintainability-scan` | everything — the maintainability roll-up grades from Sokrates numbers and the other scanners' findings; run last |

Scanners within a wave are independent — run them in parallel (as subagents) when the harness allows; run waves sequentially. If a needed predecessor is missing or fails, its consumers still run (the skills degrade gracefully) — note the gap in the final report.

**The wave order applies to whichever bundle you are running**: take the bundle's scanner list, drop the waves that are empty for it, and run the rest in the same sequence. A basic scan is waves 1–3 plus `evolution-scan`; a `security` deep dive is `security-scan` after `iac-scan` and `configuration-scan`, since it reads their findings.

## Procedure

1. **Shared setup, once.** Read `_sokrates/config.json`; unzip `reports/data/data.zip` to the scratch directory once and pass that path to every scanner run. Fix the shared parameters up front so all seventeen findings files agree: `target.name`, `target.src_root`, `analyzed_at` (one value for the whole suite), `target.commit` if a git checkout.
2. **Re-scan detection.** If `_sokrates/reports/ai-insights/<scanner>.json` files already exist with an older `analyzed_at`, copy them to the scratch directory *before* overwriting — they are the diff baseline.
3. **Run the waves.** For each scanner **in the chosen bundle**: execute its SKILL.md, validate until OK, render the explorer. A scanner that cannot pass validation ships with its unverifiable findings dropped or downgraded per the core rules — never ship a failing file.
4. **Merge:**
   ```bash
   python3 <core-skill-path>/scripts/merge_findings.py _sokrates/reports/ai-insights/
   python3 <core-skill-path>/scripts/render_findings.py _sokrates/reports/ai-insights/
   ```
   and validate the produced `combined-report.json` (it should re-verify in full). The render call is the final one — it rebuilds the explorer with every scanner's file present.
5. **Diff on re-runs.** For each baseline saved in step 2:
   ```bash
   python3 <core-skill-path>/scripts/diff_findings.py <scratch>/<scanner>.json _sokrates/reports/ai-insights/<scanner>.json
   ```
   Collect the new / resolved / changed items across scanners — on a re-scan these, not the full inventory, are the headline.
6. **Report.** Say which bundle you ran. Lead with the combined attention table (severity above info, all scanners run), then per-scanner one-liners with validation results ("N/N verified"), then (re-runs) the cross-scanner diff summary. Point at `_sokrates/reports/ai-insights/index.html` (the explorer) and `combined-report.json` as the artifacts of record. After a basic scan, close with one line on what a deep dive would add and which family fits what you saw — a codebase whose basic findings surfaced thin tests or a wide attack surface has earned that suggestion.

## Budget guidance

A full first scan of a large codebase is roughly 17 scanner-runs of reading work; a basic scan is 6 and a single deep-dive family 3–4. Parallelize within waves, and prefer trimming per-scanner scope (each skill's own scoping advice) over skipping scanners *within a bundle*: the combined report's value is completeness of the coverage it claims, with each scanner free to keep its finding count modest. Choosing a narrower bundle is the right way to spend less — a basic scan that is actually finished beats a full scan that is rushed. When the user asks for an ad-hoc subset ("everything except security"), run the requested scanners in the same wave order and note in the merged summary which scanners are absent.
