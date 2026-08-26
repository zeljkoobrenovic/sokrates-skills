---
name: security-design-scan
description: Maps how security is designed into a codebase - where trust boundaries lie and what crosses them, how execution is sandboxed and privileges separated, how identity/auth and permission models work, how secrets and sensitive data are handled by design, how third-party code (plugins, extensions, models, dependencies) is trusted at runtime - and synthesizes the overall defensive posture and its gaps. Use whenever the user asks how a project handles security, wants the security architecture/model explained or documented, asks about sandboxing, permissions, auth design, trust boundaries, threat surface, or wants a security design review. This is the design-level scanner: systematic hunting for injection bugs, leaked secrets, or vulnerable code patterns is a code-audit (security-scan) concern, though anything dangerous found while reading is still reported. Works best with a Sokrates analysis (_sokrates folder).
---

# Security design scan

Security code answers "how"; a security design answers "against what, and where". This scanner reads the mechanisms — sandbox setup, permission checks, credential flows, validation at boundaries — and reconstructs the design they imply: what the authors treat as untrusted, which lines they defend, how the layers compose, and which paths cross a boundary with nothing checking them. The output is the document a security reviewer wishes the team had written: the trust model as actually implemented, with evidence.

**First read `sokrates-scan-core/SKILL.md`** (sibling skill) — it defines the output format, evidence rules, validate/render scripts, and the `_sokrates` data layout. This file adds only what is specific to security design scanning.

## Scope boundaries with sibling scanners

- **Found-while-reading beats scope**: a leaked credential, an obviously injectable call — report it at its true severity even though hunting for such things systematically is `security-scan`'s job.
- Pipeline security (action pinning, publish credentials, artifact signing acts) belongs to `cicd-scan`; *this* scanner covers how the shipped product decides what to trust at runtime (installer verification, plugin/extension vetting, update trust).
- Telemetry privacy design is `observability-scan`'s pipeline group; cross-reference rather than duplicate, but the *decision framework* for what user data may leave the machine is fair game here.

## Workflow

1. Orient per the core skill. Prior findings help: `tech-stack-scan` names the auth/crypto/sandbox technologies, `cicd-scan` the artifact flow, `observability-scan` the data egress. Read them first if present (`_sokrates/findings/ai-insights/*.json`) instead of rediscovering. You may reference prior-scan findings in descriptions, but never copy their evidence blocks — every evidence citation in your findings must be minted from files *you* read in this run (prior citations may be stale).
2. **Find the security vocabulary of the codebase.** Grep for the load-bearing words: `sandbox`, `policy`, `permission`, `approval`, `trust`, `untrusted`, `auth`, `token`, `credential`, `secret`, `redact`, `escalat`, `privilege`, `verify`, `signature`, `allowlist`/`denylist`. Component and crate names matter (`*-sandbox`, `*-auth`, `execpolicy`); so do `SECURITY.md`, threat-model docs, and security-relevant config surfaces. This produces the map of *intended* mechanisms.
3. **Trace each mechanism to its enforcement point.** For each mechanism, read where it is actually enforced, not just defined: the syscall-filter setup, the function that says yes/no to a command, the middleware that checks the token. Note the *default* (secure or open when unconfigured?) and the *bypass surface* (flags, env vars, config that disables it — deliberate escape hatches are design facts, not automatically flaws).
4. **Walk the untrusted inputs.** Enumerate where outside data enters (network responses, model output, user files, third-party plugins/extensions, IPC) and follow two or three of the most important paths to where each is validated, constrained, or trusted. Model-generated content deserves special attention in AI systems: what can output from the model cause without a human gate?
5. **Synthesize the posture.** State the design in one coherent narrative: the layers, how they compose (defense in depth or a single wall), what the design defends against, and what it visibly does not. Gaps and posture judgments are inferences — mark them `likely`/`possible`; confidence rates the claim, not the citations, so real evidence lines under an inferred conclusion are correct.
6. Write findings, validate, render, and report per the core workflow. Scanner id: `security-design-scan`, version `1.0`.

## Group taxonomy

| group | contents |
|---|---|
| `trust-boundaries` | The boundary map: where untrusted data enters, what sits on each side, which crossings are checked and which are trusted by design — one overview finding, with separate findings only for the two or three boundaries that carry their own story (fold minor ones into the overview to respect the finding budget) |
| `sandboxing-isolation` | Execution confinement and privilege separation: OS sandbox mechanisms, process/worker isolation, filesystem restriction, **network confinement and egress policy** (this is its home — not `trust-boundaries`), escape hatches and their gating |
| `identity-access` | Authentication and authorization design: identity/credential flows, token lifecycle and storage, permission/policy models, approval and consent flows, admin/managed overrides |
| `secrets-data-protection` | How secrets and sensitive data are handled *by design*: storage location and permissions, in-memory handling, redaction layers, what is deliberately never persisted; crypto choices in their design role |
| `input-validation` | Validation posture at the boundaries found in step 4: parsers and schema checks, constraint enforcement, canonicalization, injection-resistant construction — and boundaries crossed unvalidated |
| `third-party-trust` | Runtime trust in code and content the team didn't write: plugin/extension/marketplace vetting, installer and update verification, dependency trust at load time, model-output containment |
| `security-posture` | The synthesis: the layered narrative, defense-in-depth assessment, deliberate trade-offs the design makes, and the gap list — what a reviewer should probe next |

Tie-breaker for findings that straddle groups: file a finding under the group of the *mechanism it concerns* — a weak or disabled default belongs with the mechanism it weakens (a disabled sandbox is `sandboxing-isolation`, a secrets-leaking default is `secrets-data-protection`), never in `security-posture`, which holds only synthesis. This keeps ids stable across independent runs, which the diffing story depends on.

## What a good finding looks like

Each mechanism finding answers: *what the mechanism is* (from reading its enforcement point, not its README), *what it defends against* (the implied threat — "prevents model-suggested commands from touching files outside the workspace"), *its default and bypass surface* (off-by-default? disabled by one env var? who can flip it), and *how it composes* with the neighboring layers. Cite the enforcement line and the default/bypass line — those two lines are usually the whole story.

Strengths are findings: a well-built sandbox documented as `info` is half the value and is what makes the gap findings credible. Absences are evidenced by the nearest delimiting positive fact (the check that exists on the neighboring path, the config field that would hold the missing policy) with the evidence `note` saying what the citation delimits.

Aggregate by mechanism or boundary, not by file; expect roughly 10–18 findings for a security-conscious codebase, fewer for a project where security design is thin — and "the design is thin, here is the entire surface" is itself a legitimate `security-posture` finding.

## Severity calibration

Descriptive mechanism findings are `info`. Raise severity for design-level defects:

- `critical` — found-while-reading concrete dangers: committed credentials, a boundary whose "check" is demonstrably a no-op on a dangerous path.
- `high` — a load-bearing boundary crossed unchecked by design (untrusted content reaching execution or credentials without any gate), or a security mechanism whose default *silently* disables it in real deployments.
- `medium` — single-wall defenses where depth is warranted; escape hatches reachable without consent or audit trail; sensitive data handled inconsistently across components that should share one design. A *deliberate, documented* insecure default (a compatibility trade-off the team visibly chose, with the safe mode available) is also `medium`, not `high` — the finding then presents the trade-off and recommends flipping the default or shrinking its blast radius; reserve `high` for defaults whose insecurity is silent or undocumented.
- `low` — hardening opportunities and drift: duplicated policy logic that will diverge, validation done in some entry points but not equivalent siblings, docs/design mismatch.
- `info` — the mechanism map and posture narrative, including strengths.

When judging AI-agent systems, weigh the model-output path like any other untrusted input: prompt-injection resilience is a design property (what gates stand between model output and side effects), not a code bug.

## Output

Follow the core workflow: write `_sokrates/findings/ai-insights/security-design-scan.json`, validate until OK, render the explorer, report leading with the posture narrative (the trust model in three sentences) and any above-info findings.

Use these `stats` keys where they apply (canonical, counting *things in the design*, never findings): `trust_boundaries_mapped` (distinct boundaries in the overview map), `mechanisms_traced` (mechanisms followed to their enforcement point), `escape_hatches` (distinct bypass flags/config switches, not findings about them), `unchecked_crossings` (boundary crossings found with no gate), e.g. `{"trust_boundaries_mapped": 6, "mechanisms_traced": 9, "escape_hatches": 4, "unchecked_crossings": 1}`. Add extras freely alongside.
