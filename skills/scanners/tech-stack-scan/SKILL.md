---
name: tech-stack-scan
description: Deep technology-stack scan of a codebase with (or without) a Sokrates analysis - identifies languages, frameworks, libraries, build tooling, CI/CD, infrastructure, databases, external services and protocols, each backed by file/line evidence, and writes a validated findings report into _sokrates/reports/ai-insights/. Use whenever the user asks what technologies/libraries/frameworks/infra a codebase uses, asks for a tech inventory, tech radar input, dependency overview, or a "deep tech scan", or when another analysis needs a reliable picture of the stack first.
---

# Tech stack deep scan

Produce an evidence-backed inventory of every technology a codebase relies on — not just what its manifests declare, but what the code actually uses and what the project runs on.

**First read `sokrates-scan-core/SKILL.md`** (sibling skill). It defines the output format, evidence rules, the validate/render scripts, and how to orient using the `_sokrates` data. This file only adds what is specific to tech scanning.

## What counts as a finding

One finding per *technology*, at the most useful level of aggregation: "Tokio async runtime" is one finding even if 40 crates import it. Attach 1–3 representative evidence citations — prefer the *declaration* (manifest line) plus, for major items, one *usage* site that proves it is actually used. Record the version in `attributes.version` when the manifest pins one.

Aim for completeness on the significant items rather than exhaustiveness on trivia: every framework, runtime, datastore, and infrastructure element must be there; a utility library that appears once may be grouped into a single "notable smaller libraries" finding per ecosystem.

Absences can be findings too (no CI, no tests, no build system, no lockfile): file each under the group whose subject is absent (no CI → `ci-cd`, no build → `build-tooling`), set severity by the consequence of the gap using the cross-scanner scale, and evidence it with the nearest delimiting positive fact (the `.gitignore` line, the install instruction that assumes no build) with the evidence `note` saying what the citation delimits. On a project too small for ecosystem dependency totals, put LOC/file counts per language in `stats` instead.

## Group taxonomy

Use exactly these groups (skip empty ones):

| group | contents |
|---|---|
| `languages-runtimes` | Programming languages with approximate share (cite Sokrates metrics via `sokrates_refs`), runtimes and pinned versions (Node, JVM, Python, rustc editions/toolchains) |
| `frameworks` | Application-shaping frameworks: web, UI, async runtimes, test frameworks, CLI frameworks |
| `libraries` | Significant libraries that don't shape the architecture; group minor ones per ecosystem |
| `build-tooling` | Build systems, package managers, monorepo/workspace tooling, linters/formatters, codegen |
| `ci-cd` | CI providers and pipelines, release automation, artifact publishing |
| `infrastructure` | Containers, orchestration, IaC, cloud providers, dev environments (devcontainer, nix) — the technologies only; what the definitions declare and how they are hardened is `iac-scan`'s |
| `databases-storage` | Databases, caches, queues/brokers, file/blob storage — declared drivers *and* connection/config evidence |
| `external-services` | Third-party APIs and SaaS the code calls (payment, auth, LLM APIs, telemetry backends) |
| `protocols-formats` | Wire protocols and interchange formats that shape interfaces: gRPC/protobuf, GraphQL, WebSocket, JSON-RPC, OpenAPI |

When an item fits two groups, classify by its *role in the system*, not by how it enters the code:

- A datastore beats its driver library: SQLite via SQLx is one `databases-storage` finding (mention the driver there), not a `libraries` one.
- A hosted third-party service beats its SDK: Sentry, Statsig, S3/R2 go to `external-services` even though they appear as libraries or in CI configs.
- Sandboxing, virtualization, and dev environments (Landlock, embedded V8, devcontainer, nix) are `infrastructure`.
- Dependency-*sourcing* risks (git-pinned forks, local patches to third-party code, wildcard versions) are about dependency management: put them in `build-tooling`, listing the affected technologies in the description and `tags`.

## Where to look

Work breadth-first: manifests → build/deploy files → code-level signals.

1. **Manifests and lockfiles** — find them all before reading any (Sokrates' `buildAndDeploymentFiles.json` lists most):
   `package.json` (+workspaces), `Cargo.toml` (workspace roots first), `go.mod`, `pyproject.toml`/`requirements*.txt`/`setup.py`, `pom.xml`/`build.gradle*`, `*.csproj`, `Gemfile`, `composer.json`, `mix.exs`. Lockfiles confirm resolved versions; manifests are the primary evidence.
2. **Build & dev environment** — `Makefile`, `justfile`, `BUILD.bazel`/`MODULE.bazel`, `CMakeLists.txt`, `flake.nix`, `.devcontainer/`, `.tool-versions`/`.nvmrc`/`rust-toolchain.toml`, `Dockerfile*`, `docker-compose*`, `*.tf`, `helm/`, `k8s/`.
3. **CI/CD** — `.github/workflows/*.yml`, `.gitlab-ci.yml`, `Jenkinsfile`, `.circleci/`; release configs (`goreleaser`, `changesets`, `release-please`).
4. **Code-level signals** — for each major declared dependency, confirm real usage (one grep for its import). Then hunt for what manifests *don't* declare: hardcoded external API base URLs (`https://api.…`), connection strings and driver imports, protocol schemas (`*.proto`, `*.graphql`, `openapi.*`), telemetry SDK initialization, feature-flag/auth SDKs.
5. **Env & config surface** — `.env.example`, `config/*.yaml`, settings modules: service names in config keys often reveal external services no manifest mentions.

## Severity — when a stack fact becomes a risk

Most findings are `severity: info`. Raise severity (and add a `recommendation`) only for:

- **EOL / unmaintained**: runtime or framework version past end-of-life, or a dependency archived/deprecated upstream — `medium`–`high` depending on exposure. Only claim EOL status you are confident of; if unsure of current status, state the version as `info` and note the uncertainty in the description.
- **Declared but unused / duplicated purpose**: two libraries doing the same job, or heavyweight unused dependencies — `low`.
- **Risky sourcing**: dependencies pulled from git URLs or unpinned ranges in applications, vendored copies with local patches (check `patches/`, `third_party/`) — `low`–`medium`.
- **Version fragmentation**: the same dependency at conflicting major versions across the workspace — `low`–`medium`.

## Output

Follow the core workflow: write `_sokrates/reports/ai-insights/tech-stack-scan.json` (`scanner: "tech-stack-scan"`, `scanner_version: "1.0"`), validate until OK, render the explorer, then report to the user leading with a stack summary (the two-sentence "what is this built with") and the attention items.

Put ecosystem totals into `stats`, e.g. `{"direct_dependencies": {"cargo": 143, "npm": 27}, "manifest_files": 12}`.
