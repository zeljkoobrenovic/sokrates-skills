---
name: observability-scan
description: Maps how a codebase observes itself - logging practice and hygiene, metrics and what they measure, tracing and context propagation, error/crash reporting, health/readiness surfaces - and infers what monitoring can exist downstream (which dashboards and alerts the emitted signals could feed, where the telemetry goes, what stays dark). Use whenever the user asks how a project does logging/metrics/tracing/telemetry, what monitoring or alerting exists or is possible, whether errors are swallowed, what data leaves the machine, or wants an observability audit or gap analysis. Works best with a Sokrates analysis (_sokrates folder) but degrades gracefully without one.
---

# Observability scan

A codebase's telemetry code is a statement about what its authors expect to go wrong and what they can afford to see. This scanner reads that statement: which signals the code emits (logs, metrics, traces, crash reports, health states), how disciplined the emission is, where the data flows, and — the inferential step — what monitoring the emitted signals *can and cannot support*. You cannot see the team's dashboards from the repo, but you can say "these metrics exist, so alerting on X is possible; nothing measures Y, so Y is invisible in production."

**First read `sokrates-scan-core/SKILL.md`** (sibling skill) — it defines the output format, evidence rules, validate/render scripts, and the `_sokrates` data layout. This file adds only what is specific to observability scanning.

## Workflow

1. Orient per the core skill; use the tech-stack findings (`_sokrates/findings/ai-insights/tech-stack-scan.json`, if present) to learn the telemetry SDKs already identified rather than rediscovering them.
2. **Inventory the emission surface by grep, then read the hits that matter.** Search for the ecosystem's signal vocabulary — for Rust: `tracing::`/`info!`/`warn!`/`error!`, `metrics`/`counter`/`histogram`/`Gauge`, `#[instrument]`, `sentry`, `otel`/`opentelemetry`, `panic::set_hook`; for JS/TS: `console.`, `pino`, `winston`, `debug(`, `Sentry.`, `@opentelemetry`; for Python: `logging.`, `structlog`, `sentry_sdk`, `opentelemetry`, `prometheus_client`. Record rough counts (they go in `stats`), then read the *initialization and export* code closely — where the subscriber/provider/exporter is configured is where most of the truth lives.
3. **Follow the data out.** For each signal type, find where it leaves the process: exporter endpoints, backend SDKs, env vars that enable/point telemetry, file sinks, "no-op unless configured" defaults. Note sampling, batching, and buffering decisions. This is where privacy questions live too: what user content, paths, or identifiers ride along, and what redaction exists.
4. **Probe the dark spots.** Pick a handful of load-bearing paths (from Sokrates hotspots or the architecture) and check what they emit on failure. Grep for error-swallowing shapes (`let _ =`, empty `catch`, `.ok()` on fallible calls, logged-then-dropped errors) in those paths specifically — a repo-wide count is noise, a swallowed error on the payment path is a finding.
5. **Infer the monitoring posture.** From the assembled evidence, state what a production operator of this system could alert on today, and what they could not. Mark these `likely`/`possible` per the confidence rules — they are inferences, and saying so is the point.
6. Write findings, validate, render, and report per the core workflow. Scanner id: `observability-scan`, version `1.0`.

## Group taxonomy

| group | contents |
|---|---|
| `logging` | Frameworks and conventions: structured vs. freeform, level discipline, log destinations, rotation; hygiene findings (sensitive data in logs, redaction mechanisms, noisy or missing levels) |
| `metrics` | What is measured and how: counters/gauges/histograms and their subjects, naming conventions, cardinality risks, emission paths |
| `tracing` | Spans and context propagation: instrumentation coverage, cross-process/async propagation, sampling |
| `error-reporting` | Crash and error capture: panic/exception hooks, error-reporting services, user-facing vs. operator-facing error paths — including their absence: swallowed-error and silent-failure findings from step 4 belong here *as reporting gaps* (what the operator cannot see); what the code does with the error — handling, containment, recovery — is `reliability-scan`'s, cross-reference by id rather than duplicate |
| `health-diagnostics` | Health/readiness surfaces, self-diagnostics commands, debug endpoints or views, feedback/diagnostic bundles users can send |
| `telemetry-pipeline` | Where the data goes: exporters, backends, enabling env vars/config, defaults (on/off), sampling and batching, privacy/opt-out posture |
| `monitoring-posture` | The synthesis: what alerting/dashboards the emitted signals can support, per subsystem; and the blind spots — components or failure modes that emit nothing |

## What a good finding looks like

Anchor every claim in emission or configuration code you read: the subscriber setup line, one representative `counter!` call, the exporter endpoint construction. For hygiene findings, the evidence is the offending line itself (the `error!` that logs a full request body; the `let _ =` on the flush). For `monitoring-posture` findings, evidence cites the signals that *do* exist while the description reasons about what they enable or miss. That combination — real, validating evidence with `likely`/`possible` confidence — is correct, not contradictory: confidence rates the *claim* (the inference about downstream monitoring), not the citations. Example: evidence cites the OTLP exporter setup and two metric definitions; the description says "an operator who configures OTLP could alert on session failures and latency; nothing measures queue depth, so backpressure is invisible"; confidence `likely`.

One finding per practice or posture, not per call site: "HTTP client retries are counted but not timed" beats forty citations of `counter!`. Cluster per subsystem when practices differ (the TUI logs differently than the server — that contrast is itself a finding). For a mid-size to large codebase expect roughly 10–16 findings; fewer for a small project, and prefer merging over splitting when in doubt — granularity consistency is what makes re-runs comparable.

## Severity calibration

- `high` — telemetry that actively harms: secrets/credentials or clearly sensitive user content written to logs or shipped to a backend; error paths that crash the observer.
- `medium` — operationally blinding or privacy-material: a load-bearing subsystem whose failures are invisible (swallowed errors, no signal on the critical path); telemetry on by default without redaction of user content; unbounded metric cardinality on a hot path.
- On-by-default telemetry that ships only well-minimized data (sanitized low-cardinality metrics, no user content) is `low` at most — the finding then documents the minimization, and the severity reflects only the residual concern (default-on posture, embedded backend keys). Hardcoded telemetry credentials are worth *noting* here, but auditing them as a secret-exposure risk belongs to a security scan.
- `low` — friction and drift: inconsistent level usage that will mistrain operators, duplicated half-adopted telemetry stacks, dead instrumentation.
- `info` — the descriptive map: what exists, where data flows, what monitoring is possible. Well-instrumented areas deserve explicit `info` findings — the map of what works is half the audit's value.

## Output

Follow the core workflow: write `_sokrates/findings/ai-insights/observability-scan.json`, validate until OK, render the explorer, report leading with the posture summary (what this system can see about itself, in two sentences) and any above-info findings.

Use these `stats` keys where they apply (canonical, so re-runs and dashboards can compare): `log_call_sites`, `metric_call_sites`, `instrumented_fns`, `exporters` (list), and `telemetry_default` — an object per signal when defaults differ, e.g. `{"logs": "off", "traces": "off", "metrics": "statsig"}`. Add scanner-specific extras freely alongside.
