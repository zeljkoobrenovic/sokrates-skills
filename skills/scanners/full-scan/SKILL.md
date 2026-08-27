---
name: full-scan
description: Orchestrates the complete Sokrates AI scanner suite over one codebase - runs all fourteen scanners in dependency order (later scanners build on earlier findings), validates each, merges everything into the combined report, and on re-runs diffs against the previous results. Use when the user asks for a full scan, a complete analysis, "run all scanners", a whole-codebase audit combining tech stack + functionality + risks + CI/CD + testing + observability + reliability + performance + storage + network + security + architecture + domain, or a re-scan to see what changed. Requires a _sokrates analysis in the target project.
---

# Full scan (orchestrator)

Runs the whole scanner family and produces one combined, validated result. The individual scanners do the work — this skill only supplies the order, the shared setup, and the roll-up. Read `sokrates-scan-core/SKILL.md` first as always; each scanner's own SKILL.md governs its scan.

## Why order matters

Scanners consume earlier scanners' findings (each re-verifies evidence itself, but the orientation savings are large). The dependency order observed in practice:

| wave | scanners | consume |
|---|---|---|
| 1 | `tech-stack-scan`, `risk-synthesis-scan` | Sokrates data only |
| 2 | `functionality-scan`, `cicd-scan`, `observability-scan`, `reliability-scan` |
| 2b | `testing-scan` | tech-stack (frameworks), cicd (gating), functionality (feature list), risk-synthesis (hotspots) — run after `cicd-scan` and `functionality-scan` | tech-stack (the stack skeleton, telemetry SDKs, resilience libraries, product surfaces) and risk-synthesis (hotspots as the load-bearing paths) |
| 3 | `architecture-scan` | waves 1–2 (stack skeleton, coupling, isolation boundaries from reliability) — its `security-boundaries` group feeds wave 4 |
| 3b | `performance-scan`, `storage-scan`, `network-scan` | waves 1–3 (functionality for workload/data/integrations, architecture for the main loop and communication, reliability for the write-safety and retry verdicts they reference) — run after `architecture-scan` and `reliability-scan`; independent of each other |
| 4 | `security-scan`, `domain-language-scan` | wave 3 (architecture's security boundaries and component map; network/storage for TLS, endpoints and secret files; the feature inventory as the capability list) |
| 5 | `evolution-scan` | waves 1–4 (component names, hotspots and knowledge risk, migrations in progress to date the story against) |

Scanners within a wave are independent — run them in parallel (as subagents) when the harness allows; run waves sequentially. If a needed predecessor is missing or fails, its consumers still run (the skills degrade gracefully) — note the gap in the final report.

## Procedure

1. **Shared setup, once.** Read `_sokrates/config.json`; unzip `reports/data/data.zip` to the scratch directory once and pass that path to every scanner run. Fix the shared parameters up front so all fourteen findings files agree: `target.name`, `target.src_root`, `analyzed_at` (one value for the whole suite), `target.commit` if a git checkout.
2. **Re-scan detection.** If `_sokrates/findings/ai-insights/<scanner>.json` files already exist with an older `analyzed_at`, copy them to the scratch directory *before* overwriting — they are the diff baseline.
3. **Run the waves.** For each scanner: execute its SKILL.md, validate until OK, render the explorer. A scanner that cannot pass validation ships with its unverifiable findings dropped or downgraded per the core rules — never ship a failing file.
4. **Merge:**
   ```bash
   python3 <core-skill-path>/scripts/merge_findings.py _sokrates/findings/ai-insights/
   python3 <core-skill-path>/scripts/render_findings.py _sokrates/findings/ai-insights/
   ```
   and validate the produced `combined-report.json` (it should re-verify in full). The render call is the final one — it rebuilds the explorer with every scanner's file present.
5. **Diff on re-runs.** For each baseline saved in step 2:
   ```bash
   python3 <core-skill-path>/scripts/diff_findings.py <scratch>/<scanner>.json _sokrates/findings/ai-insights/<scanner>.json
   ```
   Collect the new / resolved / changed items across scanners — on a re-scan these, not the full inventory, are the headline.
6. **Report.** Lead with the combined attention table (severity above info, all scanners), then per-scanner one-liners with validation results ("N/N verified"), then (re-runs) the cross-scanner diff summary. Point at `_sokrates/findings/ai-insights/index.html` (the explorer) and `combined-report.json` as the artifacts of record.

## Budget guidance

A full first scan of a large codebase is roughly 14 scanner-runs of reading work — parallelize within waves, and prefer trimming per-scanner scope (each skill's own scoping advice) over skipping scanners: the combined report's value is completeness of *coverage*, with each scanner free to keep its finding count modest. When the user asks for a subset ("everything except security"), run the requested scanners in the same wave order and note in the merged summary which scanners are absent.
