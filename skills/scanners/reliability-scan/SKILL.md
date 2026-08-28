---
name: reliability-scan
description: Maps how a codebase behaves when things go wrong - its error model (exceptions vs result types, error hierarchies and classification), how failures are handled at the call sites that matter (swallowed, catch-all, rethrown with context, crashed on), how failures are isolated so one broken part does not take the rest down (process/task boundaries, bulkheads, plugin containment), how it recovers (retries, backoff, timeouts, circuit breakers, idempotency), how it degrades (fallbacks, partial results, offline modes), and whether resources are released, persisted state survives a crash and shutdown is orderly - synthesized into a reliability posture with the blast radius of the main failure modes. Use whenever the user asks how a project handles errors or failures, whether errors are swallowed, what happens when a dependency/network/disk fails, about resilience, robustness, fault tolerance, retries, timeouts, graceful degradation, crash safety, or wants a reliability review or hardening plan. Works best with a Sokrates analysis (_sokrates folder) but degrades gracefully without one.
---

# Reliability scan

Every codebase encodes a theory of failure: which errors its authors expected, which they decided to survive, and which they were happy to crash on. This scanner reads that theory out of the code — not the happy path, but the `catch`, the `?`, the `unwrap`, the retry loop, the timeout constant, the shutdown hook — and says how the system behaves when a dependency, the network, the disk, or its own logic fails, and how far a single failure spreads.

**First read `sokrates-scan-core/SKILL.md`** (sibling skill) — output format, evidence rules, validate/render scripts, `_sokrates` layout. This file adds only what is specific to reliability scanning.

## The one question

*If X fails — panics, throws, times out, returns garbage — what else dies, hangs, or goes quietly wrong?* Ask it for every boundary you read. It produces the findings that matter; everything below is scaffolding for answering it with evidence.

## Scope and boundaries with sibling scanners

- **`observability-scan`** owns *reporting* of errors (where they are logged, crash hooks, what an operator sees). This scanner owns *handling and containment* — what the code does with the error and how far it propagates, including exit codes after failure and "success reported after a swallowed error". Where observability already has the reporting side of a call site, the reliability finding covers only the handling/loss consequence and carries a `finding:` ref to it — never restate.
- **`security-scan`** owns `unsafe` blocks, injection, crypto, and resource-exhaustion *attacks* (unbounded input, zip bombs). Panics/unwraps on runtime input and resource *leaks* are reliability.
- **`architecture-scan`** (`security-boundaries`) owns sandboxing as a *trust* boundary and **`security-scan`** the approval/fail-closed *policy*. The same process boundary is fair game here as a *failure* boundary — describe what it contains, not what it protects against. A tolerant parser security-scan has judged for input validation is cited here only for its failure consequence, with the cross-reference.
- **`architecture-scan`** owns the component map and runtime communication. Use its component names in `sokrates_refs` — or crate/module names when the Sokrates decomposition is coarser than the code. Describe only failure behaviour.
- Crash safety of persisted state (atomic writes, fsync, half-written files, cleanup after failed writes) is **owned here** under `resources` — it is routinely the most actionable finding. Limits that bound *cost* rather than protect correctness belong to a performance scanner.

**Cross-referencing.** Before writing, list the ids already present (`grep -h '"id"' _sokrates/reports/ai-insights/*.json --exclude=combined-report.json`) and reference a sibling finding as `sokrates_refs: ["finding:<scanner>/<group>/<slug>"]` — only ids you saw, never guessed. Prior scanners' evidence blocks are never copied; every citation is minted from files you read in this run.

## Workflow

1. **Orient per the core skill.** Prior findings help: `tech-stack-scan` names the runtime, async model, HTTP/DB clients and resilience libraries (`backoff`, `tenacity`, `resilience4j`, `p-retry`, Polly); `architecture-scan` the components and how they communicate; `observability-scan` the error-reporting map; `risk-synthesis-scan` the hotspots. Decide what kind of system this is — a short-lived batch/CLI tool, a long-running server, an interactive agent runtime, a library — because it determines which groups will be rich and which legitimately thin. Secondary ecosystems and UIs under ~10 % of main LOC (an SDK next to the product, a desktop explorer next to a CLI) are skimmed and their coverage stated in the summary, not rated separately.
2. **Count with the script, then find the load-bearing files.** Run
   ```bash
   python3 <this-skill-path>/scripts/count_handling_sites.py <src-root> --json <scratch>/handling-counts.json
   ```
   It applies one deterministic test-exclusion rule (test path segments, `*_test.*`, `*Test.java`, and Rust `#[cfg(test)]` modules) so counts compare across runs; the console shows the top files per shape and the JSON holds every hit. Copy its **facts** into `stats` (see Output); its **leads** (`*_candidates`, `*_keyword_files`) are reading lists — never stats, never findings until read. Then locate the files that matter, by name and from the architecture findings: the main request/command/turn loop, the persistence writer(s), the wrapper around external calls (HTTP client, model provider, DB), the child-process/plugin/tool boundary, the central error type(s), the shutdown path. Typically 5–10 files. Read them completely when they are of readable size; for multi-thousand-line files outline with grep (`fn |spawn|timeout|rename|abort|catch|except`) and read the handling regions around each hit. Sokrates hotspots get budget only when they lie on a write or boundary path — a hot report generator with no failure handling teaches nothing here.
3. **Identify the error model.** How errors are represented and classified: exception hierarchies, `Result`/`Either` types, error enums and their variants, `thiserror`/`anyhow`/custom `Error` types, error codes, retryable-vs-fatal partitions, user-facing vs internal mapping, lint or policy enforcement (`expect_used = "deny"`, checked-exception conventions). The absence of a central type (strings thrown, `Box<dyn Error>` everywhere, `except Exception`) *is* the `error-model` finding.
4. **Read the handling on the files from step 2.** What the call site does with a failure: swallow, default, print-and-continue, catch-all, rethrow with or without context, panic/unwrap on runtime input, poison-and-unwrap on locks, success reported after failure (exit code 0, archive with missing entries). Readers that turn errors into defaults: a *shared helper* whose contract is null/empty-on-failure (a JSON mapper, a `readFile` utility) is `error-model/tolerant-conventions`; a *call site* that catches and substitutes its own default is `handling/tolerant-readers`. Designed vs accidental: a skip that tells the user what was skipped and why is `degradation`; a default with no message is `handling` — the same method can contain both. Rust `let _ =` is only a swallow when the dropped result is a filesystem, persistence or join outcome — never for channel sends.
5. **Trace isolation boundaries.** Process boundaries (child processes, workers, sandboxes), task/thread boundaries (spawned tasks, supervisors, join-handle handling — is a task panic ever observed?, `allSettled` vs `all`), plugin/extension/tool/model-call containment, per-request isolation in servers, and global state a failure can poison (static caches reused across iterations, singletons, shared connections, poisoned locks). For a single-process batch tool the answer to "what else dies" is usually "this run" — then report the process model once and spend the rest on state reused across iterations, background threads, subprocesses, and what is left on disk.
6. **Read recovery and degradation.** Retries (bounded? backoff? jitter? which error classes?), timeouts and their values, circuit breakers/rate limiting, idempotency of retried work, reconnection, fallbacks (alternate providers, cached data, offline modes), fail-safe defaults, partial results by design, user-facing recovery (resume, retry, state preserved on crash). Cite the constants.
7. **Check resource safety, crash safety and shutdown.** Cleanup on failure paths (RAII/`Drop`, `finally`, `with`/`defer`, try-with-resources), leak-prone shapes, cancellation propagation, signal handling (`SIGTERM`/`SIGHUP`/`ctrl_c` — the script counts them), shutdown order (flushes, in-flight work, lock files, child processes reaped), and persisted state: in-place overwrite vs temp-and-rename, fsync, what a crash mid-write leaves behind, whether cleanup runs even when the write failed. The `in_place_write_candidates` and `atomic_write_sites` leads from the script are the fastest way in.
8. **Synthesize the posture.** One `reliability-posture/posture` finding, `severity: info`, `confidence: likely`: per failure source what happens today and the blast radius, the most fragile paths, the strongest mechanisms, and the three highest-leverage changes as `finding:` refs to the findings that carry the recommendations — not repeated. Evidence cites the boundary code that exists.
9. Write findings, validate, render; if a `combined-report.json` exists in the folder, re-run the merge script after rendering. Report per the core workflow. Scanner id: `reliability-scan`, version `1.1`.

## Group taxonomy

| group | contents |
|---|---|
| `error-model` | How errors are represented and classified: exception/`Result` conventions, central error types and their taxonomy, retryable vs fatal partitions, user-facing vs internal mapping, lint/policy enforcement, type-level tolerant conventions — and the absence of a model |
| `handling` | The call site's decision on the paths that matter: swallowed or silently-defaulted errors, print-and-continue, catch-all handlers *inside* a component, panics/unwraps/asserts on runtime or untrusted input, lock-poison conventions, errors rethrown with vs without context, success reported after failure, inconsistent conventions between subsystems |
| `isolation` | Failure containment: process/task/thread boundaries and what they contain (a catch-all *at* a task/plugin/request boundary belongs here, not in `handling`), timeouts that bound *someone else's* code (child process, plugin, model call), supervisors and restart policies, shared state a failure can poison — and the blast radius where a boundary is missing |
| `recovery` | Retries and backoff, timeouts on *our own* outgoing calls and on the run itself (watchdogs — state the crash consequence), circuit breakers and rate limiting, reconnection, idempotency of retried work, resume-after-crash |
| `degradation` | *Designed* reduced modes: fallbacks and alternates, offline or reduced-function modes, fail-safe defaults, partial results that are a feature, what the user sees when a dependency is down. An accidental partial result from a swallowed error stays in `handling` |
| `resources` | Cleanup on failure paths, leak-prone shapes, cancellation propagation, signal handling, shutdown order, crash safety of persisted state (atomic writes, fsync, cleanup after failed writes) |
| `reliability-posture` | The synthesis (one finding, `info`, id `reliability-posture/posture`) |

**Precedence when a mechanism matches several groups** — pick the group of its *primary* mechanism, in this order: circuit breaker / retry → `recovery`; timeout bounding others' code → `isolation`; timeout on our outgoing call or the run → `recovery`; fallback or fail-safe default → `degradation`; catch-all at a boundary → `isolation`, inside a component → `handling`; partial output — designed → `degradation`, accidental → `handling`.

## Stable ids

Free-text slugs made two honest runs on an unchanged tree agree on 1 of 17 ids. So slugs are **mechanism or artifact names, never consequences or verb phrases**, and the recurring subjects use these fixed slugs (one finding each, present-or-absent):

| group | fixed slugs |
|---|---|
| `error-model` | `central-type` (present or absent), `enforcement` (lints/policies), `tolerant-conventions` |
| `handling` | `print-and-continue`, `catch-all-<entrypoint>` (kebab-case of the method or command, e.g. `catch-all-generate-reports`), `unwrap-residue`, `lock-poison-convention`, `tolerant-readers`, `exit-codes` (the exit-status contract, including exit 0 after failure) |
| `isolation` | `process-model`, `task-boundary`, `child-process`, `plugin-boundary` (MCP/hooks/extensions together), `request-boundary`, `panic-boundaries`, `shared-state` |
| `recovery` | `outgoing-retry` (all retry policies together, sub-policies in `attributes`), `timeouts`, `circuit-breaker`, `reconnection`, `watchdog`, `resume` |
| `degradation` | `fallbacks` (all designed fallbacks together), `optional-stages`, `offline-mode`, `fail-safe-defaults` |
| `resources` | `persisted-state` (the general atomic-write / fsync posture for *generated* outputs), `in-place-overwrite-<artifact>` (only for *user-edited or non-regenerable* artifacts, e.g. `in-place-overwrite-config`, `in-place-overwrite-history`), `stream-cleanup`, `temp-files`, `cancellation`, `shutdown`, `signals` |
| `reliability-posture` | `posture` |

Project-specific defects that fit no fixed slug get a free slug naming the *artifact or boundary* (`resources/data-zip-packaging`, `isolation/turn-task`), still never the consequence. When several mechanisms share a fixed slug, list them in `attributes` (e.g. `"policies": ["http: 4 retries", "stream: 5 retries", "reconnect: 30 s cap"]`, `"subjects": ["LanguageAnalyzerFactory overrides", "landscape recursion"]`) — the id stays stable and the diff can still see the substance move. The canonical **absence** slot per thin group is: `recovery/outgoing-retry`, `degradation/fallbacks`, `isolation/process-model`, `error-model/central-type`, `resources/persisted-state`. A shared convention is **one** finding; split only where the *consequence* differs materially, and then the split is by artifact (`in-place-overwrite-config` vs `in-place-overwrite-history`).

## What a good finding looks like

Anchor every claim in handling or configuration code you read: the `except Exception: pass` line, the retry loop header with its bound, the timeout constant, the `catch_unwind` at the plugin boundary, the `Drop` impl, the `rename` (or its absence) in the writer. For "what if it panics" findings the evidence is the spawn site or the boundary that exists; the description reasons about what it contains — real, validating evidence with `likely`/`possible` confidence is correct: confidence rates the inference, not the citation.

One finding per practice, mechanism, or boundary — not per call site. Cluster by subsystem when practices differ; that contrast (the server retries with backoff, the CLI gives up on first failure) is itself a finding. Well-handled areas deserve explicit `info` findings with their mechanism cited — the map of what is robust is half the review's value and what re-runs diff against.

**Finding count** — the fixed-slug table drives it, not a target number: fill every slot the code has a real answer for (present or absent-and-why), skip slots with nothing to say. That lands at 14–22 for an interactive runtime or server and 12–20 for a batch CLI or library; the absent-and-why findings count. Tests that document intended failure behaviour may be cited as supporting evidence.

## Severity calibration

- `high` — a failure that corrupts or loses *user* data or state that cannot be regenerated (half-written persistent file with no atomic write and no other source of truth, retry of a non-idempotent side effect), or a single fault that takes down the whole system where a boundary was clearly intended.
- `medium` — a load-bearing path with swallowed or catch-all handling that hides real failures or reports success after them; a failure that makes the system *hang* instead of fail (a client waiting forever on a dead task); unbounded retries or missing timeouts on an external call in the main flow; a global cache/connection one failure poisons for the rest of the run; shutdown that can drop in-flight work; loss of *regenerable* artifacts with no atomic write; truncate-then-write of a small user-edited file that usually has an external source of truth (git) — regenerable or recoverable loss caps at `medium`.
- `low` — friction and drift: inconsistent error conventions, `unwrap`/`expect` on inputs practically always valid, cleanup that relies on the happy path, dead or half-adopted resilience helpers, tail loss of an append-only log (no fsync) as opposed to corruption. Mitigations lower a finding one rung: opt-in/feature-gated, interruptible by the user, covered by a fallback.
- `info` — the descriptive map. Deliberate invariants (`unreachable!` after exhaustive matching, asserts on programmer errors) are `info` or `low` with the reason stated.
- Only the individual findings carry actionable severity; the posture finding is `info`.

## Output

Follow the core workflow: write `_sokrates/reports/ai-insights/reliability-scan.json`, validate until OK, render the explorer, re-merge if a combined report exists, report leading with the posture summary (how this system behaves when its main dependencies fail, and how far one failure spreads, in two sentences) and any above-info findings.

`stats` — copy the script's **facts** under its own keys (never its leads; omit keys that do not apply to the ecosystem; no zeros or nulls for "not applicable") and add `count_rule` from its JSON. Judgment stats on top:

- `retry_mechanisms`, `timeout_mechanisms` — distinct mechanisms after reading (the script's `*_keyword_files` leads point at them)
- `error_types` — `enum`/`class` that implement the error trait/interface and cross a module boundary, that you read
- `isolation_boundaries` — list, e.g. `["child process per tool call", "tokio task per session"]`
- `failure_sources` — one verdict per canonical source that exists (`network`, `disk`, `database`, `external_process`, `plugins`, `own_bugs`, `resource_exhaustion`) from this vocabulary: `bounded-retry`, `unbounded-retry`, `no-retry`, `timeout`, `no-timeout`, `contained`, `process-wide`, `hang`, `silent-default`, `atomic-write`, `in-place-write`, `no-fsync`, `fallback`, `fail-closed`, `fail-open` — several joined with `+`, e.g. `{"network": "bounded-retry+timeout+fallback", "disk": "in-place-write+silent-default", "own_bugs": "contained+hang"}`

If the project has no error-handling concern in `_sokrates/config.json`, suggest `sokrates-features-of-interest` in the report; do not treat a concern's file list as a reading plan (tests dominate it).
