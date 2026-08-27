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

- **`functionality-scan`** (`data` group) names *what* data the system manages from the user's perspective. `persistence-model/data-classes` is still written here — with the storage lens (format, writer, write safety, sensitivity per class) and a reference to functionality's finding — but no other storage finding re-describes a folder.
- **`tech-stack-scan`** (`databases-storage`) names the storage technologies and drivers. Read it first; do not repeat the inventory — describe the usage.
- **`reliability-scan`** (`resources/persisted-state`, `in-place-overwrite-<artifact>`, `data-zip-packaging`-style artifact findings, `handling/tolerant-readers`) owns *crash safety of writes* and *what a reader does with a corrupt input* as a reliability posture. This scanner owns the fuller picture — format compatibility, integrity checks, corruption recovery paths, migrations, lifecycle — and **references reliability's findings by id instead of restating them**; a storage finding on the same artifact must add a mechanism reliability did not cover (a second writer, a recovery path, a format property), and when reliability already rated the write pattern `medium`, the storage consequence of the same crash is one rung lower.
- **`architecture-scan`** may already have named an unversioned data contract between components (`boundaries/*`); `schema-and-format/format-versioning` references it and adds the format-level evidence (fields, readers) rather than restating the contract.
- **`security-scan`** owns secrets at rest, encryption, path traversal and access control. Note where sensitive data lands on disk (`data-classes`) with a cross-reference; do not audit it.
- **`performance-scan`** owns the cost of I/O (whole-file reads, N+1 queries) and `caching-and-reuse`. `access-patterns/file-access` states streaming vs whole-file and append vs rewrite *per data class* as a durability/compatibility fact; when performance already describes the same writer, reference it and keep only the storage consequence.
- **`domain-language-scan`** owns concept definitions; use its names for data classes.

**Cross-referencing.** List existing ids first (`grep -h '"id"' _sokrates/findings/ai-insights/*.json --exclude=combined-report.json`) and reference siblings as `sokrates_refs: ["finding:<scanner>/<group>/<slug>"]` — only ids you saw. Never copy another scanner's evidence blocks.

## Workflow

1. **Orient per the core skill.** From `tech-stack-scan` (storage technologies), `functionality-scan` (data managed), `architecture-scan` (which component owns persistence), `reliability-scan` (write-safety verdicts). Decide the system kind and its live slots: a **batch tool** writing an output tree (`data-classes`, `data-directory`, `file-access`, `read-modify-write`, `format-versioning`, `partial-output`, `cleanup`, `store-<output-archive>`); a **service with a database** (`database-access`, `transactions`, `connections`, `migrations`, `schema-ownership`, `backup-restore`, `retention-<class>`); a **desktop/CLI app with a home directory** (`data-directory`, `store-<class>` per store with its own mechanism, `locking`, `format-versioning`, `compatibility`, `corruption-recovery`, `retention-<class>`, `cleanup`, `export-import`); a **library defining a format** (`schema-ownership`, `format-versioning`, `compatibility`, `read-validation`). Sibling findings to pull by slug: `reliability-scan/resources/*` and `degradation/*`, `functionality-scan/data/*`, `tech-stack-scan/databases-storage/*`, `architecture-scan/boundaries/*` and `evolution/*`, `security-scan/secrets/*`, `performance-scan/io-and-memory/*`.
2. **Count with the script, then find the persistence code.** Run
   ```bash
   python3 <this-skill-path>/scripts/count_storage_sites.py <src-root> --json <scratch>/storage-counts.json
   ```
   It counts, per ecosystem and excluding tests: file write/read sites, atomic-write and temp-file shapes, serialization calls (JSON/YAML/TOML/protobuf/pickle/serde), SQL and ORM usage, transactions, migrations, schema/version markers, checksums, compression/archives, cache/store directories, cleanup/retention calls, env vars and paths that locate data — facts to copy into `stats`, leads to read. From the top files, locate the persistence layer: the writer(s) and reader(s) per data class, the schema/migration code, the path resolution (where the data directory comes from), and the format definitions (structs/classes with serialization annotations). Read those completely; for files over ~800 lines — and for persistence layers of tens of thousands of lines — grep for the mechanism vocabulary (`rename|persist|sync_all|force\(|PRAGMA|journal_mode|try_lock|schema_version|migrat|retention|max_bytes|remove_dir|Zip|Mapper|serde`) and read ±20 lines around each hit; the script's `--json` `hits` list gives you file, line and snippet to start from (re-read before citing).
3. **Build the data-class inventory.** For every kind of persistent data — user configuration, application state, caches, logs/transcripts, generated outputs, databases, secrets, temp files: location and how it is resolved (home dir, env var, project-relative), format, size class, owner component, single- or multi-writer, sensitivity. This is the `persistence-model/data-classes` finding and the frame for everything else — size class and sensitivity go in `attributes.classes` (one object per class), the narrative in the description. Slots in steps 4–7 with no subject (no database, no migrations, no backups) get **no finding**: record the absence in `stats` and in one line of the posture.
4. **Read the access paths.** ORM vs raw SQL vs query builder; prepared statements; transactions and their boundaries; connection handling and pooling; locking and concurrent access (file locks, `WAL`, advisory locks, lock files); streaming vs whole-file; append-only vs rewrite; read-modify-write cycles and who wins.
5. **Read schema and format ownership.** Where the schema lives (migrations, DDL, ORM models, serde structs); migration mechanism and ordering; on-disk format versioning (version fields, magic bytes, `schema_version` tables); backward/forward compatibility (unknown fields tolerated? old files upgraded in place?); what happens to data written by a newer version.
6. **Read integrity and recovery.** Atomic write shapes (temp + rename, `fsync`, journaling) — cite reliability's finding when it exists; checksums or hashes; corruption detection and what follows it (rebuild from a source of truth, backup and reset, crash); partial-output handling (is a half-written output tree distinguishable from a complete one?); archive safety (zip bombs are security's; truncated archives are here).
7. **Read the lifecycle.** Creation and initialization (first run, `init`); retention and cleanup (temp files, caches, logs — bounded? on what trigger?); backup and restore; export/import; deletion on uninstall or user request; what accumulates without bound.
8. **Synthesize the posture.** One `storage-posture/posture` finding, `severity: info`, `confidence: likely`: per data class the verdict on durability, compatibility and lifecycle; the riskiest data class; the strongest mechanisms; the three highest-leverage changes as `finding:` refs. Evidence cites the data-directory resolution or the main writer.
9. Write findings, validate, render; re-run the merge script if a `combined-report.json` exists. Report per the core workflow. Scanner id: `storage-scan`, version `1.1`.

## Group taxonomy

| group | contents |
|---|---|
| `persistence-model` | The data-class inventory: what is stored where, in what format, resolved how, owned by whom, how sensitive; the storage technologies as used (not as listed) |
| `access-patterns` | How data is read and written: ORM/SQL/query builders, prepared statements, transactions, connections and pooling, locking and concurrent access, streaming vs whole-file, append vs rewrite, read-modify-write |
| `schema-and-format` | Schema ownership, migrations and their mechanism, on-disk format definitions and versioning, backward/forward compatibility, handling of data from other versions |
| `integrity` | Atomic writes and durability (referencing reliability), checksums, corruption detection and recovery, partial-output handling, archive/format validation on read |
| `lifecycle` | Initialization, retention and cleanup, backup/restore, export/import, deletion, unbounded accumulation |
| `storage-posture` | The synthesis (one finding, `info`, id `storage-posture/posture`) |

**Precedence**: a write that is not atomic → reference `reliability-scan` and describe the *recovery* in `integrity`; a version field → `schema-and-format`; tolerance of unknown fields is a compatibility strategy → `schema-and-format/format-versioning` even when it also hides corruption (say so there; `integrity` gets only detection/recovery mechanisms); a lock → `access-patterns`, a lock *file* left behind → `lifecycle`; a temp file → `lifecycle` unless it is the atomic-write staging file (`integrity`); a parser that turns errors into defaults → reference `reliability-scan` (`error-model/tolerant-conventions`); a destructive extract/clean that security-scan already audited → reference, do not count as `cleanup`.

## Stable ids

Slugs are **data-class, mechanism or artifact names, never consequences**. Fixed slugs (use only when the subject exists; parametrised slugs take the kebab-case data-class name as the code names it):

| group | fixed slugs |
|---|---|
| `persistence-model` | `data-classes` (the inventory, one finding, classes in `attributes`), `data-directory` (how locations are resolved), `store-<class>` (only when the class has a reader/writer mechanism of its own worth describing — a session store, a state database — never as a prose re-description of a folder) |
| `access-patterns` | `database-access` (ORM/SQL style, prepared statements), `transactions`, `connections`, `locking`, `file-access` (streaming vs whole, append vs rewrite), `read-modify-write` (merges with `locking` when the only shared state is config files: one finding, slug `read-modify-write`) |
| `schema-and-format` | `schema-ownership`, `migrations`, `format-versioning` (when no format carries a version, this one finding also covers the tolerance that substitutes for it — `compatibility` is then not used), `compatibility` (only when versioning exists and compatibility is a separate mechanism) |
| `integrity` | `write-durability` (only when reliability has no `persisted-state` finding; otherwise the refs go in the posture), `<artifact>-overwrite` (a specific non-atomic write reliability did not name, e.g. `auth-json-overwrite`), `checksums`, `corruption-recovery` (the *recovery path* after detection — reliability owns what the reader does on parse failure; for a home-directory app this one finding subsumes `read-validation`, `checksums` and `partial-output` unless one is a standout), `partial-output`, `read-validation` |
| `lifecycle` | `initialization`, `retention-<class>` (one per class whose retention is worth a verdict — an unbounded class is a `retention-<class>` finding, never a separate `unbounded-accumulation`), `cleanup` (temp files, caches, stale artifacts together), `backup-restore`, `export-import` |
| `storage-posture` | `posture` |

Project-specific findings get a free slug naming the artifact (`integrity/data-zip-truncation`), never the consequence. Several mechanisms sharing a slug are listed in `attributes`.

## What a good finding looks like

Evidence is the path resolution line, the serialization annotation, the `CREATE TABLE`/migration header, the `rename` call, the `PRAGMA journal_mode`, the retention constant, the version field. Descriptions speak per data class: "session transcripts are append-only JSONL under `~/.codex/sessions/<date>/`, one writer task, no version field; older readers skip unknown lines". One finding per data class or mechanism, not per call site; the inventory finding carries the table, the per-class findings carry the judgments.

Expect 10–16 findings for a service or a desktop/CLI app with a home directory; 8–14 for a batch tool that writes an output tree; 4–8 for a library; roughly half `info` (the model and the mechanisms that work). Mandatory slots: `data-classes`, `data-directory`, `file-access` or `database-access`, `format-versioning`, `posture`; everything else only when the subject exists. Java vocabulary: Jackson `DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES`, `@JsonProperty` vs `@JsonIgnore`, `Files.newOutputStream`/`newBufferedWriter`, `FileChannel.force` (fsync), `StandardCopyOption.ATOMIC_MOVE`, `File.createTempFile(prefix, suffix, dir)` + `renameTo` (the staging idiom), `ZipFile` vs `ZipInputStream`, `Properties.store/load`.

## Severity calibration

- `high` — silent data loss or corruption of *user* data with no recovery path (no atomic write *and* no source of truth *and* no detection — re-login or regeneration counts as a recovery path), or a format change with no versioning where old data becomes unreadable; unbounded accumulation of *junk* (caches, logs, temp) that fills the disk in normal use. User-valued data (sessions, history) with no retention knob is `low`.
- `medium` — a corrupt file crashes the program instead of being detected and recovered; concurrent writers with no locking on shared state in a multi-user or long-running system; migrations without ordering or rollback on a database that holds user data; regenerable data with no partial-output marker (`low` when reliability already carries the write pattern at `medium`); read-modify-write races on config with more than one writer; silent corruption of user-visible *display* data that is regenerable (garbled names) is `medium` when it reaches the user, `low` when a rerun fixes it.
- `low` — retention that relies on the user, temp files not cleaned on failure, formats without a version field but with tolerant readers, caches without bounds that are cheap to rebuild, secrets stored in a plain config (cross-reference security).
- `info` — the data-class inventory, the access patterns, the mechanisms that work.
- Mitigations lower a finding one rung: a source of truth exists, the data is regenerable, the writer is single and short-lived, the tool is single-user and interactive.

## Output

Follow the core workflow: write `_sokrates/findings/ai-insights/storage-scan.json`, validate until OK, render the explorer, re-merge if a combined report exists, report leading with the posture summary (what is stored where and which data class is most at risk, in two sentences) and any above-info findings.

`stats` — copy the script's **facts** under its own keys (zeros included — 0 fsync, 0 locks, 0 version markers are facts; omit only keys whose shape does not exist in the ecosystem; a fact key you verified as entirely false positives is omitted and named in `count_notes`), add `count_rule`, and on top:

- `data_classes` — list of data-class names as used in the findings
- `storage_backends` — list, e.g. `["filesystem (JSON, JSONL, zip)", "SQLite (WAL)", "S3"]`
- `formats` — list of on-disk formats with their versioning: `{"session JSONL": "unversioned", "state.db": "schema_version table", "config.json": "tolerant reader"}`
- `migration_mechanism` — short string or `none`; list when several migrators exist
- `write_safety` — object per data class from `atomic`, `in-place`, `append-only`, `database`, `mixed` (with the parts in `attributes` of the class finding)
- `retention` — object per data class from `bounded`, `bounded-by-config`, `ttl`, `unbounded`, `user-managed`, `ephemeral`, `rebuilt-per-run`
- `sensitive_on_disk` — list of data classes holding secrets or user content, with the protection (`0600`, `keyring`, `encrypted`, `plain`)
- `format_properties` — object per format: list from `versioned`, `unversioned`, `tolerant-reader`, `strict-reader`, `rewritten-by-tool`, `user-edited`
