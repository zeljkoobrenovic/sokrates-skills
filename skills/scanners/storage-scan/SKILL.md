---
name: storage-scan
description: Maps how a codebase works with persistent data - the persistence model (which data lives in files, databases, caches, object stores, and in what formats), how it is accessed (ORM vs raw SQL, transactions, locking, concurrent access, streaming vs whole-file), how schemas and on-disk formats are owned, versioned and migrated, how data is kept intact (atomic writes, checksums, corruption handling, backward compatibility of formats), and its lifecycle (creation, retention, cleanup, backup, export/import) - synthesized into a storage posture with the risks per data class. Use whenever the user asks where a project stores its data, how it uses files or a database, about the data model on disk, migrations, file formats, data integrity or corruption, retention/cleanup, or wants a persistence/storage review. Works best with a Sokrates analysis (_sokrates folder) but degrades gracefully without one.
---

# Storage scan

A program's persistent data outlives every process that touched it, so the code that reads and writes it carries obligations the rest of the codebase does not: formats must stay readable across versions, writes must not leave garbage behind, concurrent writers must not corrupt each other, and old data must be findable and removable. This scanner reads how a codebase meets those obligations — what it stores, where, in what shape, through which access paths, and how it survives its own upgrades and crashes.

**First read `sokrates-scan-core/SKILL.md`** (sibling skill) — output format, evidence rules, validate/render scripts, `_sokrates` layout. This file adds only what is specific to storage scanning.

## The one question

*For each class of data: where does it live, who writes it, what happens when the writer crashes halfway, and can next year's version still read it?* Ask it per data class, not per file.

## Scope and boundaries with sibling scanners

- **`functionality-scan`** (`data` group) names *what* data the system manages from the user's perspective. This scanner describes *how* it is persisted and kept intact; reference its data findings rather than re-inventorying.
- **`tech-stack-scan`** (`databases-storage`) names the storage technologies and drivers. Read it first; do not repeat the inventory — describe the usage.
- **`reliability-scan`** (`resources/persisted-state`, `in-place-overwrite-<artifact>`) owns *crash safety of writes* as a reliability posture. This scanner owns the fuller picture — format compatibility, integrity checks, corruption recovery, migrations, lifecycle — and **references reliability's write-safety findings by id instead of restating them**; add a storage finding only for what reliability did not cover (recovery from a corrupt file, format versioning, cleanup of partial output).
- **`security-scan` / `security-design-scan`** own secrets at rest, encryption, path traversal and access control. Note where sensitive data lands on disk (`data-classes`) with a cross-reference; do not audit it.
- **`performance-scan`** owns the cost of I/O (whole-file reads, N+1 queries). Mention the access pattern here only as a storage-shape fact.
- **`domain-language-scan`** owns concept definitions; use its names for data classes.

**Cross-referencing.** List existing ids first (`grep -h '"id"' _sokrates/findings/ai-insights/*.json --exclude=combined-report.json`) and reference siblings as `sokrates_refs: ["finding:<scanner>/<group>/<slug>"]` — only ids you saw. Never copy another scanner's evidence blocks.

## Workflow

1. **Orient per the core skill.** From `tech-stack-scan` (storage technologies), `functionality-scan` (data managed), `architecture-scan` (which component owns persistence), `reliability-scan` (write-safety verdicts). Decide the system kind: a batch tool that writes an output tree, a service with a database, a desktop/CLI app with a config-and-cache home directory, a library that defines a format — each has a different set of live slots below.
2. **Count with the script, then find the persistence code.** Run
   ```bash
   python3 <this-skill-path>/scripts/count_storage_sites.py <src-root> --json <scratch>/storage-counts.json
   ```
   It counts, per ecosystem and excluding tests: file write/read sites, atomic-write and temp-file shapes, serialization calls (JSON/YAML/TOML/protobuf/pickle/serde), SQL and ORM usage, transactions, migrations, schema/version markers, checksums, compression/archives, cache/store directories, cleanup/retention calls, env vars and paths that locate data — facts to copy into `stats`, leads to read. From the top files, locate the persistence layer: the writer(s) and reader(s) per data class, the schema/migration code, the path resolution (where the data directory comes from), and the format definitions (structs/classes with serialization annotations). Read those completely (outline files over ~800 lines).
3. **Build the data-class inventory.** For every kind of persistent data — user configuration, application state, caches, logs/transcripts, generated outputs, databases, secrets, temp files: location and how it is resolved (home dir, env var, project-relative), format, size class, owner component, single- or multi-writer, sensitivity. This is the `persistence-model/data-classes` finding and the frame for everything else.
4. **Read the access paths.** ORM vs raw SQL vs query builder; prepared statements; transactions and their boundaries; connection handling and pooling; locking and concurrent access (file locks, `WAL`, advisory locks, lock files); streaming vs whole-file; append-only vs rewrite; read-modify-write cycles and who wins.
5. **Read schema and format ownership.** Where the schema lives (migrations, DDL, ORM models, serde structs); migration mechanism and ordering; on-disk format versioning (version fields, magic bytes, `schema_version` tables); backward/forward compatibility (unknown fields tolerated? old files upgraded in place?); what happens to data written by a newer version.
6. **Read integrity and recovery.** Atomic write shapes (temp + rename, `fsync`, journaling) — cite reliability's finding when it exists; checksums or hashes; corruption detection and what follows it (rebuild from a source of truth, backup and reset, crash); partial-output handling (is a half-written output tree distinguishable from a complete one?); archive safety (zip bombs are security's; truncated archives are here).
7. **Read the lifecycle.** Creation and initialization (first run, `init`); retention and cleanup (temp files, caches, logs — bounded? on what trigger?); backup and restore; export/import; deletion on uninstall or user request; what accumulates without bound.
8. **Synthesize the posture.** One `storage-posture/posture` finding, `severity: info`, `confidence: likely`: per data class the verdict on durability, compatibility and lifecycle; the riskiest data class; the strongest mechanisms; the three highest-leverage changes as `finding:` refs. Evidence cites the data-directory resolution or the main writer.
9. Write findings, validate, render; re-run the merge script if a `combined-report.json` exists. Report per the core workflow. Scanner id: `storage-scan`, version `1.0`.

## Group taxonomy

| group | contents |
|---|---|
| `persistence-model` | The data-class inventory: what is stored where, in what format, resolved how, owned by whom, how sensitive; the storage technologies as used (not as listed) |
| `access-patterns` | How data is read and written: ORM/SQL/query builders, prepared statements, transactions, connections and pooling, locking and concurrent access, streaming vs whole-file, append vs rewrite, read-modify-write |
| `schema-and-format` | Schema ownership, migrations and their mechanism, on-disk format definitions and versioning, backward/forward compatibility, handling of data from other versions |
| `integrity` | Atomic writes and durability (referencing reliability), checksums, corruption detection and recovery, partial-output handling, archive/format validation on read |
| `lifecycle` | Initialization, retention and cleanup, backup/restore, export/import, deletion, unbounded accumulation |
| `storage-posture` | The synthesis (one finding, `info`, id `storage-posture/posture`) |

**Precedence**: a write that is not atomic → reference `reliability-scan` and describe the *recovery* in `integrity`; a version field → `schema-and-format`, its absence with a corruption consequence → `integrity`; a lock → `access-patterns`, a lock *file* left behind → `lifecycle`; a temp file → `lifecycle` unless it is the atomic-write staging file (`integrity`); a format that tolerates unknown fields → `schema-and-format/compatibility`, one that turns parse errors into defaults → reference `reliability-scan` (`error-model/tolerant-conventions`).

## Stable ids

Slugs are **data-class, mechanism or artifact names, never consequences**. Fixed slugs (use only when the subject exists; parametrised slugs take the kebab-case data-class name as the code names it):

| group | fixed slugs |
|---|---|
| `persistence-model` | `data-classes` (the inventory, one finding, classes in `attributes`), `data-directory` (how locations are resolved), `store-<class>` (one per data class worth its own finding, e.g. `store-session-transcripts`, `store-config`) |
| `access-patterns` | `database-access` (ORM/SQL style, prepared statements), `transactions`, `connections`, `locking`, `file-access` (streaming vs whole, append vs rewrite), `read-modify-write` |
| `schema-and-format` | `schema-ownership`, `migrations`, `format-versioning`, `compatibility` |
| `integrity` | `write-durability` (references reliability), `checksums`, `corruption-recovery`, `partial-output`, `read-validation` |
| `lifecycle` | `initialization`, `retention-<class>`, `cleanup`, `backup-restore`, `export-import`, `unbounded-accumulation` |
| `storage-posture` | `posture` |

Project-specific findings get a free slug naming the artifact (`integrity/data-zip-truncation`), never the consequence. Several mechanisms sharing a slug are listed in `attributes`.

## What a good finding looks like

Evidence is the path resolution line, the serialization annotation, the `CREATE TABLE`/migration header, the `rename` call, the `PRAGMA journal_mode`, the retention constant, the version field. Descriptions speak per data class: "session transcripts are append-only JSONL under `~/.codex/sessions/<date>/`, one writer task, no version field; older readers skip unknown lines". One finding per data class or mechanism, not per call site; the inventory finding carries the table, the per-class findings carry the judgments.

Expect 10–16 findings for a service or a desktop/CLI app with a home directory; 6–10 for a batch tool or a library; roughly half `info` (the model and the mechanisms that work).

## Severity calibration

- `high` — silent data loss or corruption of *user* data with no recovery path (no atomic write *and* no source of truth *and* no detection), or a format change with no versioning where old data becomes unreadable; unbounded accumulation of user data with no cleanup that will fill the disk in normal use.
- `medium` — a corrupt file crashes the program instead of being detected and recovered; concurrent writers with no locking on shared state; migrations without ordering or rollback on a database that holds user data; regenerable data with no partial-output marker; read-modify-write races on config.
- `low` — retention that relies on the user, temp files not cleaned on failure, formats without a version field but with tolerant readers, caches without bounds that are cheap to rebuild, secrets stored in a plain config (cross-reference security).
- `info` — the data-class inventory, the access patterns, the mechanisms that work.
- Mitigations lower a finding one rung: a source of truth exists, the data is regenerable, the writer is single and short-lived.

## Output

Follow the core workflow: write `_sokrates/findings/ai-insights/storage-scan.json`, validate until OK, render the explorer, re-merge if a combined report exists, report leading with the posture summary (what is stored where and which data class is most at risk, in two sentences) and any above-info findings.

`stats` — copy the script's **facts** under its own keys (omit keys whose shape does not exist in the ecosystem), add `count_rule`, and on top:

- `data_classes` — list of data-class names as used in the findings
- `storage_backends` — list, e.g. `["filesystem (JSON, JSONL, zip)", "SQLite (WAL)", "S3"]`
- `formats` — list of on-disk formats with their versioning: `{"session JSONL": "unversioned", "state.db": "schema_version table", "config.json": "tolerant reader"}`
- `migration_mechanism` — short string or `none`
- `write_safety` — object per data class from `atomic`, `in-place`, `append-only`, `database`
- `retention` — object per data class from `bounded`, `unbounded`, `user-managed`, `ephemeral`
