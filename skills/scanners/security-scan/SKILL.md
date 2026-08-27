---
name: security-scan
description: Code-level security audit of a codebase - hunts concrete dangerous patterns and judges each in context: hardcoded secrets and tokens, injection-prone command/SQL/path construction, weak or home-rolled crypto and bad randomness, unsafe deserialization and archive/path traversal, unsafe-memory blocks and their justifications - and reports what was checked and found clean alongside what wasn't. Use whenever the user asks to audit code for vulnerabilities, find hardcoded secrets, check for injection or unsafe patterns, review unsafe blocks, or asks "is this code secure". Design-level review (trust boundaries, sandboxing, auth architecture) is security-design-scan; this scanner works at the line level. Works best with a Sokrates analysis (_sokrates folder).
---

# Security code scan

A design can be sound while a single line betrays it. This scanner hunts the lines: the credential in a config file, the command built by string concatenation, the SHA-1 where integrity matters, the `unsafe` block with no safety comment, the archive extractor that trusts its paths. It is the line-level complement to `security-design-scan` — that scanner maps the walls; this one probes them for cracks.

**First read `sokrates-scan-core/SKILL.md`** (sibling skill) — output format, evidence rules, validate/render scripts, `_sokrates` data layout. This file adds only what is specific to code-level security scanning.

## The false-positive discipline (read this first)

This scanner's failure mode is crying wolf. A grep hit is a *candidate*, never a finding: before reporting, read enough context to answer (a) can attacker-influenced data actually reach this line, and (b) what mitigation already stands in front of it. A pattern that is present but mitigated, unreachable, or test-only is reported — if at all — as `info` with the mitigation named, or folded into the clean-audit finding. When exploitability is uncertain after reading, say so explicitly and cap severity at `medium` with confidence `possible`. One confirmed finding with a traced input path outweighs twenty "this looks suspicious" entries — and one false `critical` destroys the report's credibility.

## Scope boundaries with sibling scanners

- Architecture-level topics (trust boundaries, sandbox design, auth flows, permission models, deliberate insecure defaults) belong to `security-design-scan`; cite its findings for context instead of re-litigating them.
- Pipeline security (action pinning, publish credentials) is `cicd-scan`'s; telemetry privacy is `observability-scan`'s; panics/unwraps and error handling as a robustness matter are `reliability-scan`'s — here they count only where they are a security-relevant denial-of-service or memory-safety concern.
- Dependency CVE auditing requires a vulnerability database this scanner doesn't have: do not guess CVE status. Report the *mechanisms* (is `cargo-deny`/`npm audit`/Dependabot configured?) and leave concrete advisories alone unless one is explicitly documented in-repo.
- You may reference prior-scan findings in descriptions, but every evidence citation must be minted from files you read in this run.

## Workflow

1. Orient per the core skill. Prior findings tell you the stack and the sensitive areas (auth crates, exec paths, secret stores). Use Sokrates' file inventory to skip vendored/generated code per the config's ignore rules — vendored findings are noise unless locally patched.
2. **Sweep for secrets.** Grep for credential shapes: `api_key`, `secret`, `token`, `password`, `BEGIN.*PRIVATE KEY`, base64-ish and hex-ish long literals near auth words, known prefixes (`sk-`, `ghp_`, `AKIA`, `xox`). Then *read every hit*: distinguish real credentials (critical), test fixtures and placeholders (fold into clean-audit), and published/intentional identifiers like OAuth client ids or telemetry keys (info, with the intentionality stated — cross-check `security-design-scan`/`observability-scan` for ones already judged).
3. **Sweep injection surfaces.** Where the code builds commands, queries, paths, or markup from variables: shell invocation sites (`sh -c`, `Command::new` with formatted args), SQL string building vs. bound parameters, path joins from external input (traversal, symlink/zip-slip in extractors), format-string and template sinks. For each *category*, trace one or two representative paths from input to sink and report the category's verdict, not every call site.
4. **Audit the crypto.** Inventory algorithms in use and their jobs: hashing for integrity vs. identity vs. passwords, randomness sources (crypto RNG vs. `rand` where it matters), TLS configuration overrides (`danger_accept_invalid_certs`), home-rolled primitives, comparison of secrets (timing). Judge fitness-for-purpose: SHA-1 as a cache key is fine; as a signature it isn't.
5. **Audit unsafe/native code** (language-appropriate): `unsafe` blocks in Rust — count them, read the load-bearing ones, check for safety comments and whether invariants are argued; FFI boundaries; `eval`/dynamic code execution in scripting layers.
6. **Write the clean bill.** Per-category clean verdicts live in their *subject* groups (a "SQL is uniformly parameterized" finding goes in `injection`; "CSPRNG everywhere it matters" in `crypto`); `audit-coverage` holds exactly one overall coverage statement (swept vs. not covered). Evidence a clean bill with a representative instance of the *safe pattern* (the bound-parameter query, the CSPRNG call) at `confidence: certain` — a negative claim can't cite a line, but its positive counter-evidence can, and that is the blessed pattern. Test code can be strength evidence too, not only noise: a test that *asserts* a security property (file modes under hostile umask, constant-time comparison) is citable support for the clean bill.
7. Write findings, validate, render, and report per the core workflow. Fields: `scanner: "security-scan"`, `scanner_version: "1.0"`.

## Group taxonomy

| group | contents |
|---|---|
| `secrets` | Credential material in the tree: real leaks (critical), intentional published identifiers (info, with intent evidenced), the secrets-hygiene verdict |
| `injection` | Command/SQL/path/template construction from attacker-influenceable data — one finding per category with representative traced paths, including the mitigated-by-design verdicts |
| `crypto` | Algorithm fitness-for-purpose, randomness sources, TLS overrides, secret comparison, home-rolled primitives |
| `unsafe-code` | `unsafe` blocks, FFI seams, dynamic code execution: counts, the load-bearing instances read, safety-argument hygiene |
| `input-handling` | Deserialization of untrusted data, archive extraction, size/recursion limits on parsers, TOCTOU shapes on checked-then-used resources |
| `audit-coverage` | What was swept and found clean, and what was *not* covered (areas skipped, categories needing tools this scan lacks) — the honest coverage statement |

Tie-breaker: file by the *sink category*, not the data source — a path traversal in an archive extractor is `input-handling`; a shell command built from an archive entry name is `injection`. `audit-coverage` holds only coverage statements, never individual defects.

## Severity calibration

- `critical` — a real credential in the tree, or a confirmed injection path (attacker-influenceable data reaches the sink and no mitigation stands in the way).
- `high` — a dangerous pattern on a plausible input path with weak or bypassable mitigation; TLS verification disabled on non-test paths; secrets compared non-constant-time where an oracle exists.
- `medium` — the pattern exists, exploitability uncertain after reading (say why); missing limits on parsers fed external data; unsafe blocks without safety arguments in load-bearing code.
- `low` — hardening gaps and hygiene: test-only shortcuts adjacent to production code, deprecated algorithms in low-stakes roles, lint suppressions (`#[allow]`, `nosec`) on security lints without justification.
- `info` — clean-bill findings, intentional published identifiers, mitigated patterns worth documenting.

When unsure between two levels, pick the lower — and never let a `possible`-confidence finding carry more than `medium`.

## Output

Follow the core workflow: write `_sokrates/findings/ai-insights/security-scan.json`, validate until OK, render the explorer, report leading with the verdict sentence (worst confirmed finding, or the clean bill) and the coverage statement. Expect roughly 10–20 findings, and on a healthy codebase it is *normal* for clean-bill entries to outnumber defects — do not manufacture severity to look useful.

Use these `stats` keys where they apply (canonical, counting things checked, never findings — example numbers fictional): `secret_candidates_reviewed`, `categories_swept` and `sweeps_clean` (sink/sweep categories examined vs. those with no defect found), `unsafe_blocks_total` and `unsafe_files` (count `unsafe` *blocks* and files separately — state the counting method in the finding, since raw grep hits, blocks, and files differ and cross-run diffs need one definition), `unsafe_blocks_read`, e.g. `{"secret_candidates_reviewed": 99, "categories_swept": 9, "sweeps_clean": 9, "unsafe_blocks_total": 99, "unsafe_files": 99, "unsafe_blocks_read": 9}`. Add extras freely alongside.
