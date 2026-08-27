---
name: security-scan
description: Security review of a codebase in one pass, design first and code second - how identity, authentication and permissions are designed and enforced, how secrets and sensitive data are handled by design and whether any credential sits in the tree, how untrusted input is validated at the boundaries and whether command/SQL/path/template construction is injection-prone, whether crypto and randomness fit their purpose, how unsafe/native/dynamic code is justified, how third-party code (plugins, extensions, models, dependencies, updates) is trusted at runtime - and a posture that states what was swept clean and what was not covered. Use whenever the user asks how a project handles security, whether the code is secure, wants a security review/audit, asks about auth or permission design, secrets handling, injection, crypto, unsafe code, plugin trust, or the threat surface. Trust boundaries and sandboxing as structure are architecture-scan's security-boundaries group, which this scanner reads first. Works best with a Sokrates analysis (_sokrates folder).
---

# Security scan

A design can be sound while a single line betrays it, and a line can look dangerous while the design already contains it. This scanner does both readings in the right order: first the security *design* — identity, permissions, secrets, validation posture, third-party trust — reconstructed from the enforcement points; then the *hunt* for concrete dangerous patterns, judged in the light of that design. The output is the document a security reviewer wishes the team had written, plus an honest statement of what was probed and what was not.

**First read `sokrates-scan-core/SKILL.md`** (sibling skill) — output format, evidence rules, validate/render scripts, `_sokrates` layout. This file adds only what is specific to security scanning.

## The one question

*What untrusted thing can reach what dangerous thing, and what stands in between?* Ask it per input path and per sink; the design groups say what stands in between, the audit groups say whether it actually holds.

## The false-positive discipline

This scanner's failure mode is crying wolf. A grep hit is a *candidate*, never a finding: before reporting, read enough context to answer (a) can attacker-influenced data actually reach this line, and (b) what mitigation already stands in front of it — including the design mechanisms you mapped in the first half. A pattern that is present but mitigated, unreachable, or test-only is `info` with the mitigation named, or folded into the clean verdict of its category. When exploitability is uncertain after reading, say so and cap severity at `medium` with confidence `possible`. One confirmed finding with a traced input path outweighs twenty "looks suspicious" entries; one false `critical` destroys the report's credibility.

## Scope and boundaries with sibling scanners

- **`architecture-scan`** (`security-boundaries`) owns the *structure* of trust: where untrusted data enters, process/sandbox/privilege boundaries, network confinement of executed code, and their escape hatches. Read it first and reference it; this scanner does not re-map boundaries — it reads what crosses them and how the crossings are checked.
- **`cicd-scan`** owns pipeline security (action pinning, publish credentials, signing steps). This scanner owns how the *shipped product* decides what to trust at runtime (installer/update verification, plugin vetting, dependency trust at load time).
- **`observability-scan`** owns telemetry egress and its privacy; **`network-scan`** owns TLS/proxy configuration as connectivity. Here, TLS verification *disabled* and secrets on the wire are audited; the decision framework for what user data may leave the machine is `secrets` design.
- **`reliability-scan`** owns panics/unwraps and error handling as robustness; here they count only as denial-of-service or memory-safety concerns. **`storage-scan`** owns data-at-rest mechanics; here only secrets at rest and permission bits.
- **`network-scan`** and **`storage-scan`** may already cite the sandbox egress proxy, auth headers or secret files; reference their ids and keep the security judgment.
- Dependency CVE auditing needs a vulnerability database this scanner lacks: do not guess CVE status. Report the *mechanisms* (`cargo-deny`, `npm audit`, Dependabot, lockfile policy) under `third-party-trust`.

**Cross-referencing.** List existing ids first (`grep -h '"id"' _sokrates/findings/ai-insights/*.json --exclude=combined-report.json`) and reference siblings as `sokrates_refs: ["finding:<scanner>/<group>/<slug>"]` — only ids you saw. Never copy another scanner's evidence blocks; every citation is minted from files you read in this run.

## Workflow

1. **Orient per the core skill.** Read `architecture-scan/security-boundaries` (the trust map and sandbox model), `tech-stack-scan` (auth/crypto/sandbox technologies), `cicd-scan` (artifact flow), `network-scan` (endpoints, TLS, proxies), `storage-scan` (secret files), `observability-scan` (egress). Use Sokrates' ignore rules to skip vendored/generated code — vendored findings are noise unless locally patched. Decide the system kind: a service with users and roles, a local tool acting on behalf of one user, an agent runtime executing model-suggested actions, a library.
2. **Find the security vocabulary and trace each mechanism to its enforcement point.** Grep for `policy|permission|approval|trust|untrusted|auth|token|credential|secret|redact|escalat|privilege|verify|signature|allowlist|denylist|sanitiz|validate`; note crate/module names (`*-auth`, `execpolicy`, `*-sandbox`), `SECURITY.md`, threat-model docs. For each mechanism read where it is *enforced*, not where it is defined: the function that says yes/no, the middleware that checks the token, the schema check at the parser. Record the *default* (secure or open when unconfigured) and the *bypass surface* (flags, env vars, config that disable it — deliberate escape hatches are design facts, not automatically flaws).
3. **Walk the untrusted inputs across the boundaries architecture mapped.** Network responses, model output, user files, plugins/extensions, IPC, CLI arguments: follow the two or three most important paths from entry to the first sink and note where each is validated, constrained, or trusted. In AI systems the model-output path is untrusted input: what can it cause without a human gate?
4. **Sweep for secrets.** Credential shapes (`api_key`, `secret`, `token`, `password`, `BEGIN.*PRIVATE KEY`, long base64/hex literals near auth words, known prefixes `sk-`, `ghp_`, `AKIA`, `xox`); *read every hit*: real credentials (critical), fixtures and placeholders (fold into the clean verdict), intentional published identifiers such as OAuth client ids or telemetry keys (info, intent stated). Then the design side of the same group: where secrets live at rest (path, permissions, keyring, encryption), how they are held in memory, what redaction layers exist, what is deliberately never persisted.
5. **Sweep injection surfaces.** Command construction (`sh -c`, `Command::new` with formatted args), SQL string building vs bound parameters, path joins from external input (traversal, symlink, zip-slip in extractors), template/format-string sinks, markup construction. Per *category*, trace one or two representative paths from an input found in step 3 to the sink; report the category's verdict, not every call site.
6. **Audit crypto and randomness.** Algorithms and their jobs (integrity vs identity vs passwords), RNG sources where it matters, TLS overrides (`danger_accept_invalid_certs`, `rejectUnauthorized: false`), home-rolled primitives, timing of secret comparison. Judge fitness-for-purpose: SHA-1 as a cache key is fine; as a signature it is not.
7. **Audit unsafe, native and dynamic code.** `unsafe` blocks (count blocks and files separately, read the load-bearing ones, check safety comments), FFI seams, `eval`/dynamic code execution, deserialization of untrusted data, archive extraction, size and recursion limits on parsers, check-then-use shapes.
8. **Read third-party trust at runtime.** Plugin/extension/marketplace vetting, installer and update verification (signatures, checksums, pinned channels), dependency trust at load time (lockfiles, audit tooling, vendored patches), model-output containment beyond the sandbox (tool allowlists, approval gates).
9. **Synthesize the posture.** One `security-posture/posture` finding, `severity: info`, `confidence: likely`: the design in three sentences (layers, how they compose — defense in depth or one wall — what it defends against and visibly does not), the worst confirmed finding, the coverage statement (categories swept and clean, categories not covered and why), and the three things a reviewer should probe next as `finding:` refs. Evidence cites the central policy or enforcement point.
10. Write findings, validate, render; re-run the merge script if a `combined-report.json` exists. Report per the core workflow. Scanner id: `security-scan`, version `2.0`.

## Group taxonomy

| group | contents |
|---|---|
| `identity-access` | Authentication and authorization design: identity/credential flows, token lifecycle and storage, permission/policy models, approval and consent flows, admin/managed overrides, defaults and bypasses |
| `secrets` | Secrets by design and in the tree: where they live at rest and how protected, in-memory handling, redaction layers, what is never persisted; real leaks (critical), intentional published identifiers (info), the hygiene verdict |
| `input-handling` | Validation posture at the boundaries: parsers and schema checks, canonicalization, deserialization of untrusted data, archive extraction, size/recursion limits, check-then-use shapes — and crossings that arrive unvalidated |
| `injection` | Command/SQL/path/template/markup construction from attacker-influenceable data — one finding per category with representative traced paths, including the mitigated-by-design verdicts |
| `crypto` | Algorithm fitness-for-purpose, randomness sources, TLS overrides, secret comparison, home-rolled primitives |
| `unsafe-code` | `unsafe` blocks, FFI seams, dynamic code execution: counts, the load-bearing instances read, safety-argument hygiene |
| `third-party-trust` | Runtime trust in code and content the team did not write: plugin/extension vetting, installer and update verification, dependency trust at load time and audit tooling, model-output containment beyond the sandbox |
| `security-posture` | The synthesis (one finding, `info`, id `security-posture/posture`): the design narrative, the worst confirmed finding, the coverage statement, what to probe next |

**Precedence**: file by the *mechanism* a finding concerns, never in `security-posture`; a weak or disabled default belongs with its mechanism (a secrets-leaking default is `secrets`); a sink category → `injection`, a source/parser category → `input-handling` (a path traversal in an extractor is `input-handling`; a shell command built from an entry name is `injection`); trust boundaries and sandbox mechanics → reference `architecture-scan`, only their *crossings* are judged here; TLS disabled → `crypto`, TLS configuration otherwise → reference `network-scan`.

## Stable ids

Slugs are **mechanism, category or artifact names, never consequences**. Fixed slugs (use only when the subject exists; a category with nothing dangerous still gets its slug as the clean verdict when it was swept):

| group | fixed slugs |
|---|---|
| `identity-access` | `authentication`, `authorization-model`, `approval-flow`, `token-lifecycle`, `managed-overrides` |
| `secrets` | `at-rest`, `in-memory-and-redaction`, `in-tree` (the sweep verdict: leaks or clean), `published-identifiers` |
| `input-handling` | `boundary-validation` (the posture), `deserialization`, `archives-and-paths`, `parser-limits`, `check-then-use` |
| `injection` | `command`, `sql`, `path`, `template-and-markup` |
| `crypto` | `algorithms`, `randomness`, `tls-overrides`, `secret-comparison` |
| `unsafe-code` | `unsafe-blocks`, `ffi`, `dynamic-execution` |
| `third-party-trust` | `plugins-and-extensions`, `updates-and-installers`, `dependencies`, `model-output` |
| `security-posture` | `posture` |

Project-specific findings get a free slug naming the mechanism or artifact (`secrets/auth-json-permissions`), never the consequence. Several mechanisms sharing a slug are listed in `attributes`. Clean verdicts carry `attributes.swept` (what was checked) so a re-run can see coverage change.

## What a good finding looks like

A design finding answers: what the mechanism is (from its enforcement point), what it defends against, its default and bypass surface, how it composes with neighbours; cite the enforcement line and the default/bypass line. An audit finding cites the sink and the input path that reaches it (or the mitigation that stops it). A clean verdict cites a representative instance of the *safe pattern* (the bound-parameter query, the CSPRNG call) at `confidence: certain`; a test that asserts a security property (file modes, constant-time comparison) is citable support. Absences are evidenced by the nearest delimiting positive fact with the evidence `note` saying what it delimits.

Strengths are findings: a well-built approval flow documented as `info` is what makes the gap findings credible. Aggregate by mechanism or category, not by file. Expect 14–22 findings for a security-conscious codebase (roughly half of them design, a third clean verdicts); for a project where security design is thin, "the design is thin, here is the entire surface" is itself the posture, and the audit half still runs.

## Severity calibration

- `critical` — a real credential in the tree; a confirmed injection path (attacker-influenceable data reaches the sink, nothing in between); a boundary whose "check" is demonstrably a no-op on a dangerous path.
- `high` — a load-bearing boundary crossed unchecked *by design* (untrusted content reaching execution or credentials without any gate); a security mechanism whose default *silently* disables it in real deployments; a dangerous pattern on a plausible input path with weak or bypassable mitigation; TLS verification disabled on non-test paths; non-constant-time secret comparison where an oracle exists.
- `medium` — single-wall defenses where depth is warranted; escape hatches reachable without consent or audit trail; a *deliberate, documented* insecure default with the safe mode available (present the trade-off); a pattern whose exploitability stays uncertain after reading; missing limits on parsers fed external data; `unsafe` blocks without safety arguments in load-bearing code; sensitive data handled inconsistently across components that should share one design.
- `low` — hardening and drift: duplicated policy logic that will diverge, validation present in some entry points but not equivalent siblings, deprecated algorithms in low-stakes roles, lint suppressions on security lints without justification, test-only shortcuts adjacent to production code.
- `info` — the mechanism map, clean verdicts, intentional published identifiers, mitigated patterns worth documenting, the posture.
- When unsure between two levels, pick the lower; never let a `possible`-confidence finding carry more than `medium`. In AI-agent systems, weigh the model-output path like any untrusted input: prompt-injection resilience is the set of gates between model output and side effects, not a code bug.

## Output

Follow the core workflow: write `_sokrates/findings/ai-insights/security-scan.json`, validate until OK, render the explorer, re-merge if a combined report exists, report leading with the verdict sentence (worst confirmed finding, or the clean bill) and the design narrative in three sentences.

`stats` keys (canonical; counting things checked or designed, never findings): `mechanisms_traced`, `escape_hatches`, `unchecked_crossings`, `secret_candidates_reviewed`, `categories_swept` and `sweeps_clean`, `unsafe_blocks_total`, `unsafe_files`, `unsafe_blocks_read`, `not_covered` (list of categories this run could not sweep and why). Add extras freely alongside.
