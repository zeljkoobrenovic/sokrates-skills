---
name: performance-scan
description: Static performance and efficiency review of a codebase - builds the workload model (what scales with input size, the hot loops and data volumes), then reads the hot paths for algorithmic and data-structure choices (nested scans, quadratic matching, regex compiled in loops, wrong collection for the access pattern), I/O and memory behaviour (whole-file reads, unbuffered streams, everything-in-memory models, allocation churn, round trips in loops), concurrency (parallelism present and missing, pool sizing, contention and serialization points, blocking in async), caching and recomputation, and the explicit limits and safeguards that keep one big input from dominating - synthesized into a ranked list of likely bottlenecks and the highest-leverage optimizations. Use whenever the user asks why a project is slow, where the bottlenecks are, what scales badly, about memory usage, parallelism, caching, performance optimizations or a performance/efficiency review. Works best with a Sokrates analysis (_sokrates folder) - its stage timings, file inventory and unit metrics size the reading - but degrades gracefully without one.
---

# Performance scan

This is a **static** review: it infers performance from the shape of the code — the nested loop over the file list, the regex compiled per line, the `Vec` searched linearly inside a hot path, the thread pool sized 1 — and from the workload the code is written for. There is no profiler run and no benchmark, so the scanner's job is a ranked, evidenced argument about *where time and memory most plausibly go*, not a measurement. Say so in the summary; most above-`info` findings are `likely` at best, and a claim that something *is* the bottleneck needs the workload argument, not just the loop.

**First read `sokrates-scan-core/SKILL.md`** (sibling skill) — output format, evidence rules, validate/render scripts, `_sokrates` layout. This file adds only what is specific to performance scanning.

## The one question

*What does the cost scale with, and which code is on that path?* Files × lines × commits × contributors for an analysis tool; requests × tokens × tools for an agent runtime; rows × joins for a data service. Every finding above `info` must name the scaling factor it rides on.

## Scope and boundaries with sibling scanners

- **`reliability-scan`** owns timeouts, retries and limits that protect *correctness under failure*; this scanner owns limits and safeguards that bound *cost* (caps, sampling, skip-if-over-N switches, configurable expensive stages). Blocking in async and lock contention: performance owns the *cost*, reliability owns the *failure* (hang, poison). **When reliability already cites a mechanism** (an output cap, a tool gate, a writer's flush policy, a skip switch), do not re-cite it as its own finding — mention it with a `finding:` ref inside the posture or the relevant group-level finding, and add a finding only for a cost aspect reliability did not cover.
- **`observability-scan`** owns which latency/throughput signals are *measured*; this scanner says what is *slow*. If nothing measures a hot path, say so in `performance-posture` and reference observability's blind-spot finding rather than restating it.
- **`risk-synthesis-scan`** owns the maintainability reading of hotspots (complexity, churn, ownership). The same files are read here only for their runtime cost; do not repeat the maintainability argument.
- **`architecture-scan`** owns the component map and communication style. Use its component names in `sokrates_refs` (or crate/module names when the decomposition is coarser); describe only cost.
- **`tech-stack-scan`** already names the runtime, async model, DB drivers and caches — read it first rather than rediscovering.

**Cross-referencing.** List existing ids first (`grep -h '"id"' _sokrates/findings/ai-insights/*.json --exclude=combined-report.json`) and reference siblings as `sokrates_refs: ["finding:<scanner>/<group>/<slug>"]` — only ids you saw. Never copy another scanner's evidence blocks.

## Workflow

1. **Orient per the core skill and build the workload model.** From `functionality-scan` (what the software does), `architecture-scan` (the pipeline/loop shape) and the Sokrates data (`references/sokrates-data-guide.md`): what are the inputs, how big do they get, what is the main loop, what runs per input item, what runs once. Write this down first — it is the `workload-model/scaling-factors` finding and the frame for everything else. Decide the system kind and apply its checklist:
   - **Batch tool / pipeline** (analysis, build, ETL): currency is wall-clock per run and peak memory; cost scales with input records; the slots that matter are `quadratic-<stage>`, `regex-per-item-<stage>`, `input-loading`, `output-writing`, `in-memory-model`, `parallel-stages`/`serial-stages`, `caps-and-skips`; look for the tool's own stage timings first.
   - **Server / interactive runtime** (agents, APIs, UIs): currency is latency per request/turn and throughput; cost scales with per-request work × concurrency; the slots that matter are `main-loop`, `repeated-work-<stage>` (per request/step), `n-plus-one-<call>`, `locks`, `blocking-in-async`, `pool-sizing`, `channel-capacities`, `unbounded-growth`; `sampling` and `configurable-stages` rarely apply.
   - **Library**: currency is per-call cost and allocation; the public hot API is the main loop.
2. **Find any measurement before reading code.** Sokrates' own `executionTimes.txt` (stage shares of the analysis run) when the target *is* a Sokrates-like tool; the target's benchmarks, profiler output, timing logs, CI duration artifacts. A measured stage share outranks every static inference below — cite it and rank by it. Then locate the main loop from the architecture/functionality findings and the entry-point module, and list every callee that runs per item/request: that list is the hot path. Read every class/module on it (outline files over ~800 lines with grep for `for |while |loop |\.iter\(|\.stream\(|regex|Pattern\.compile|clone\(|sort|contains\(|await` and read the loop bodies). Typically 8–18 files.
3. **Count with the script, then use Sokrates for sizing, not discovery.** Run
   ```bash
   python3 <this-skill-path>/scripts/count_perf_sites.py <src-root> --json <scratch>/perf-counts.json
   ```
   It counts loop-aware shapes (regex compiled in a loop, per-call allocation of expensive objects, whole-file reads, sorts in loops, static collections, parallelism/executors/locks/caches present, named limit constants; Rust: deep copies, `spawn_blocking`, std locks in async files, channel capacities) with one deterministic test-exclusion rule, and lists the top files per shape. Copy its **facts** into `stats`; its **leads** (`*_candidates`) are reading lists, never stats. Cross the hot-path list from step 2 with the script's top files — a shape on the hot path is a finding, the same shape in a once-per-run report generator is `info` at most. Sokrates' `units.json`/`files.json` size the files you read and supply `metric:` refs; big or complex does **not** mean hot — the largest units are usually rendering code that runs once.
4. **Read the hot paths** and answer, per path: what is the complexity in the scaling factors from step 1; what is recomputed; what is held in memory at peak; what runs serially that could run in parallel; what safeguard exists. Cite the loop header, the compile call, the pool size, the cap constant. Language notes: in Java `String.replaceAll`/`matches`/`split(regex)` compile a `Pattern` per call — that, not `Pattern.compile` (usually a static final), is the common regex-per-item shape; `computeIfAbsent` is group-by, not caching. In Rust look at `Arc::unwrap_or_clone`/`make_mut` (deep copies), `.clone()` in `loop`/`for` bodies, `std::sync` vs `tokio::sync` locks in async code, `block_on`/`block_in_place` vs `spawn_blocking`, `JoinSet`/`buffer_unordered(n)`/`FuturesOrdered` for parallelism, `mpsc::channel(n)` capacities, and exclude `LazyLock`/`OnceLock` initializers from per-call shapes. In JS `*Sync` fs calls and `await` inside `for` are the blocking and serialization shapes.
5. **Read the deliberate optimizations too.** Parallel stages, streaming writers, compressed embeds, incremental caches, early exits, chosen data structures — they are `info` findings with the mechanism cited, and they are what a re-run diffs against. "The duplication analysis is parallel and skippable" is as important as "the dependency matcher is quadratic".
6. **Synthesize the posture.** One `performance-posture/posture` finding, `severity: info`, `confidence: likely`: the ranked likely bottlenecks with their scaling factors, what grows without bound, where parallelism would pay, and the three highest-leverage changes as `finding:` refs to the findings that carry the recommendations. Evidence cites the main loop. The document `summary` stays to three or four sentences (currency, scaling factor, top bottleneck, static caveat); the ranking lives in the posture finding, not in both.
7. Write findings, validate, render; re-run the merge script if a `combined-report.json` exists. Report per the core workflow. Scanner id: `performance-scan`, version `1.1`.

## Group taxonomy

| group | contents |
|---|---|
| `workload-model` | What the system does under load: inputs and their sizes, the main loop and what runs per item vs once, the scaling factors, the performance currency (latency/throughput/memory/startup) |
| `algorithms-and-data` | Complexity and data-structure choices on hot paths: nested scans, quadratic matching, linear lookups in loops, regex compiled per item, sorting in loops, repeated work — and the well-chosen structures |
| `io-and-memory` | I/O and memory behaviour: whole-file reads, unbuffered streams, per-item opens, N+1 calls, flush-per-write; everything-in-memory models, unbounded collections, allocation churn, large embedded payloads, peak memory |
| `concurrency` | Parallelism present and absent on the main loop, pool sizing, serialization points, contention on hot locks, blocking in async, single-threaded stages between parallel ones |
| `caching-and-reuse` | Caches and memoization, their bounds and invalidation, recomputation a cache would remove, static caches that leak across runs |
| `limits-and-safeguards` | Caps, sampling, skip-if-over-N switches, configurable expensive stages, streaming vs build-then-write — and where a limit is missing so one big input dominates |
| `performance-posture` | The synthesis (one finding, `info`, id `performance-posture/posture`) |

**Precedence when a subject matches several groups**: a cap that exists on an algorithm → `limits-and-safeguards`; a cap *missing* on a super-linear algorithm → `algorithms-and-data/quadratic-<stage>` (mention the missing cap); a cache that fixes a quadratic path → `caching-and-reuse`; repeated *I/O* (re-reading a file per stage) → `io-and-memory/input-loading`, repeated *computation* → `algorithms-and-data/repeated-work-<stage>` (never also `caching-and-reuse/recomputation-*` — that slug is dropped); a lock around I/O or a single writer task → `concurrency/serial-stages`, with `output-writing` describing only the write strategy; thread-safety of a cache → `caching-and-reuse/static-caches`; memory that grows with the *input* → `io-and-memory/in-memory-model`, that grows with the *session/run duration* → `io-and-memory/unbounded-growth`; missing parallelism → `concurrency/serial-stages`.

## Stable ids

Slugs are **mechanism, stage or artifact names, never consequences or verb phrases**. Recurring subjects use these fixed slugs (one finding each, present-or-absent):

| group | fixed slugs |
|---|---|
| `workload-model` | `scaling-factors` (currency and factors together), `main-loop` |
| `algorithms-and-data` | `quadratic-<stage>`, `regex-per-item-<stage>`, `linear-lookups-<stage>`, `repeated-work-<stage>`, `optimized-<stage>` (a deliberately efficient stage, one per stage worth naming) |
| `io-and-memory` | `input-loading`, `in-memory-model`, `unbounded-growth`, `output-writing`, `n-plus-one-<call>`, `embedded-payloads` |
| `concurrency` | `parallel-stages`, `serial-stages`, `pool-sizing`, `locks`, `blocking-in-async`, `channel-capacities` |
| `caching-and-reuse` | `caches`, `static-caches` |
| `limits-and-safeguards` | `caps-and-skips`, `sampling`, `configurable-stages`, `missing-limits` |
| `performance-posture` | `posture` |

Fixed slugs are **used only when the subject exists** — no absence findings except `serial-stages` (a tool that never parallelized) and `missing-limits`; half the table is expected to stay empty for any given system kind. Parametrised slugs (`<stage>`, `<call>`) take the kebab-case name of the pipeline stage or call as the code names it, so one fix changes one id.

Project-specific findings get a free slug naming the stage or artifact (`algorithms-and-data/quadratic-temporal-coupling`), never the consequence. Several mechanisms sharing a fixed slug (`caches`, `parallel-stages`, `caps-and-skips`) are listed in `attributes` (`"mechanisms": [...]`) so the id stays stable while the detail diffs.

## What a good finding looks like

Evidence is the loop header, the compile call inside it, the collection type, the pool size, the cap constant, the `parallelStream()` — one to three representative citations per subject, not per occurrence. The description states the scaling factor in the workload's terms ("per file × per concern: the whole tree is rescanned for every concern regex — 14 concerns × 2,300 files"), estimates the order (quadratic, linear-with-big-constant, memory proportional to tree size) and, above `info`, names the fix and what it would change. Numbers from Sokrates (unit size, LOC, complexity) go in the description with `metric:` refs — they are not file/line evidence.

One finding per mechanism or stage. Cluster by pipeline stage when practices differ (the duplication stage is parallel and capped; the dependency stage is serial and unbounded). Expect 12–18 findings for a mid-size to large codebase, roughly half `info` (the optimizations that exist and the workload model); fewer for a small project.

## Severity calibration

- `high` — rare: a super-linear path on the *default* main input with no cap **and** an input size at which it plausibly dominates today (quadratic over all files or commits of a large repository, unbounded memory proportional to input²), or an N+1 external call on the main request path. Requires the workload argument, not only the loop; the same shape on inputs where it is invisible is `medium`.
- `medium` — a hot path with clear waste and a clear fix: regex compiled per item, linear lookup in a per-item loop, whole-input in memory where streaming is natural, per-step deep copy or rebuild of large shared state, serial stage *between* parallel ones, blocking call in an async hot path, a collection that grows with *input* on a long-running process, a missing cap where one exists for sibling stages. A measured stage share (from timing artifacts) may raise a finding one rung above its static rung — say so.
- `low` — waste off the hot path or with small constants; allocation churn; duplicated computation that is cheap; pool sizing that is merely unexplained; limits that exist but are not configurable; a tool that simply never parallelized (`serial-stages` without a parallel sibling); a collection that grows with *session length* under user control.
- `info` — the workload model, the optimizations that exist, the caches and caps present, the posture. Well-optimized stages are `info` with the mechanism cited.
- Confidence is independent of severity: `certain` when the mechanism is visible in the cited code (a nested loop over the same collection, a lock on the request path, a `replaceAll` in the per-line loop), `likely` when the *cost* is inferred (that this is the dominant stage), `possible` when you could not confirm it — then `low`.
- When in doubt between two rungs, pick the lower — a performance review that reads as a nag list is ignored.

## Output

Follow the core workflow: write `_sokrates/findings/ai-insights/performance-scan.json`, validate until OK, render the explorer, re-merge if a combined report exists, report leading with the posture summary (what the cost scales with and where it most plausibly goes, in two sentences) and any above-info findings.

`stats` — copy the script's **facts** under its own keys (never its leads; omit keys whose shape does not exist in the ecosystem; keep a `0` when the shape exists and none was found) and add `count_rule` from its JSON. Judgment stats on top:

- `hot_files_read` — files read in full; `hot_files_outlined` — files outlined by grep
- `pipeline_stages` — list of the top-level stages as the code names them, each tagged `parallel` or `serial`, e.g. `["basics: serial", "duplication: parallel", "reports: serial"]` (replaces free counts, so stage granularity is explicit)
- `caches` — list of caches/memoizations found; `limits` — list of cost caps found
- `scaling_factors` — object with values from `linear`, `quadratic`, `product`, `bounded`, `constant`, e.g. `{"files": "linear", "concerns×files": "product", "components": "quadratic", "commit fan-out": "quadratic", "history": "bounded"}`
- `measured_stage_shares` — when a timing artifact exists: `{"analysis": 0.51, "duplication": 0.14, ...}` with `measured_source` naming the file
- `bottlenecks_ranked` — list of `finding:` ids in posture order
