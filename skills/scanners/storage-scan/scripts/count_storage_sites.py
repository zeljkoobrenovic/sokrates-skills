#!/usr/bin/env python3
"""Count persistence-related code shapes for the storage scanner.

Deterministic, standard-library only. Test code is excluded by path (test/tests/spec/
mock/fixture segments, *_test.*, *Test.java, test_*.py) and, for Rust, inside
`#[cfg(test)]` modules. Facts are copied into `stats`; leads (`*_candidates`,
`*_keyword_files`) are reading lists, never stats.

Usage:
  python3 count_storage_sites.py <src-root> [--json out.json] [--top 12] [--exclude DIR ...]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

EXTS = {
    "rust": {".rs"}, "java": {".java", ".kt", ".scala"}, "csharp": {".cs"},
    "js": {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}, "python": {".py"}, "go": {".go"},
    "config": {".toml", ".yaml", ".yml", ".json", ".env", ".ini", ".properties", ".sql"},
}
SKIP_DIRS = {"node_modules", "target", "build", "dist", "out", ".git", "vendor", "venv", ".venv",
             "__pycache__", "_sokrates", "_sokrates_landscape"}
TEST_SEGMENT = re.compile(r"(^|[._-])(tests?|spec|specs|mocks?|fixtures?|testdata|test[-_]support)([._-]|$)", re.I)
TEST_FILE = re.compile(r"(_tests?\.\w+$|Tests?\.java$|\.spec\.\w+$|\.test\.\w+$|^test_.*\.py$|^tests?\.rs$|^conftest\.py$)", re.I)
COMMENT = re.compile(r"^\s*(//|/\*|\*|#(?!\[)|<!--|--\s)")
RUST_CFG_TEST = re.compile(r"#\[cfg\(test\)\]")
RUST_MOD_OPEN = re.compile(r"^\s*(pub(\([^)]*\))?\s+)?mod\s+\w+\s*\{")

# key -> (regex, languages or None for all, note). Keys ending in _candidates/_keyword_files are leads.
PATTERNS = {
    "file_write_sites": (re.compile(r"new FileWriter\(|new FileOutputStream\(|Files\.(write(String)?|newOutputStream|newBufferedWriter|copy)\(|FileUtils\.(write\w*|copyFile|copyDirectory)\(|writeStringToFile|PrintWriter\(|\.writeValue\(\s*new File|properties\.store\(|\.store\(\s*new File|(std::|tokio::)?fs::write\(|File::create(_new)?\(|OpenOptions::new\(\)|tokio::fs::OpenOptions|writeFile(Sync)?\(|createWriteStream\(|open\([^)]*,\s*['\"][wa]|os\.WriteFile\(|os\.Create\(|File\.Write(All)?"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "file write sites"),
    "file_read_sites": (re.compile(r"FileUtils\.(readFileToString|readLines|readFileToByteArray)\(|Files\.(readAllLines|readString|readAllBytes|lines|newBufferedReader|newInputStream)\(|new File(Reader|InputStream)\(|new ZipFile\(|\.readValue\(\s*new File|properties\.load\(|fs::read_to_string\(|fs::read\(|File::open\(|readFile(Sync)?\(|createReadStream\(|open\([^)]*,\s*['\"]r|\.read_text\(|\.read_bytes\(|os\.ReadFile\(|File\.Read(All)?"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "file read sites"),
    "append_sites": (re.compile(r"\.append\(true\)|StandardOpenOption\.APPEND|OpenOptions::new\(\)[^;]*\.append\(true\)|appendFile(Sync)?\(|flags:\s*['\"]a|open\([^)]*,\s*['\"]a|os\.O_APPEND"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "append-mode opens (append-only stores)"),
    "atomic_write_sites": (re.compile(r"\.renameTo\(|ATOMIC_MOVE|Files\.move\(|fs::rename\(|\.persist(_noclobber)?\(|NamedTempFile|write_atomically|atomic_write|AtomicFile|\brename(Sync)?\(|os\.replace\(|os\.rename\(|os\.Rename\(|File\.Move\(|File\.Replace\("), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "rename/move (temp+rename writes)"),
    "fsync_sites": (re.compile(r"\.sync_all\(\)|\.sync_data\(\)|\.getFD\(\)\.sync\(\)|FileChannel\.force\(|\.force\(true\)|fsync(Sync)?\(|os\.fsync\(|\.Sync\(\)|sync_parent|sync_dir"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "explicit durability"),
    "temp_file_sites": (re.compile(r"createTempFile\(|createTempDirectory\(|deleteOnExit\(|tempfile::|NamedTemporaryFile|mkdtemp|TemporaryDirectory|os\.tmpdir\(|os\.CreateTemp\("), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "temp files and dirs"),
    "serialization_sites": (re.compile(r"ObjectMapper|writeValueAsString|readValue\(|Gson\b|toJson\(|fromJson\(|serde_json::(to|from)_(string|str|vec|slice|writer|reader)|toml::(to|from)_str|serde_yaml|bincode::|JSON\.(parse|stringify)\(|json\.(dumps?|loads?)\(|yaml\.(safe_)?(load|dump)|pickle\.|json\.(Marshal|Unmarshal)|\.pb\.|prost::|protobuf"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "serialization calls (format boundaries)"),
    "format_type_sites": (re.compile(r"#\[derive\([^)]*(Serialize|Deserialize)|@JsonProperty\b|@JsonPropertyOrder|@Serializable|\[JsonProperty|@dataclass_json|BaseModel\)|class \w+\(BaseModel"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "types/fields that define an on-disk or wire format"),
    "format_exclusion_sites": (re.compile(r"@JsonIgnore\b|#\[serde\(skip|\[JsonIgnore|exclude\s*=\s*True"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "fields excluded from serialization"),
    "tolerant_parser_sites": (re.compile(r"FAIL_ON_UNKNOWN_PROPERTIES|#\[serde\(deny_unknown_fields|ignoreUnknown\s*=\s*true|extra\s*=\s*['\"]?(ignore|forbid|allow)|MissingMemberHandling"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "unknown-field policy of parsers (compatibility strategy)"),
    "sql_sites": (re.compile(r"['\"]\s*(SELECT|INSERT|UPDATE|DELETE|CREATE TABLE|ALTER TABLE|DROP TABLE)\b|sqlx::|rusqlite|prepareStatement\(|createStatement\(|(stmt|statement|ps|conn|connection|cursor|cur|db|tx|pool)\.(execute(Query|Update)?|query(_row|_map)?)\(|db\.(Query|Exec)\("), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "SQL statements and executions"),
    "orm_sites": (re.compile(r"@Entity|@Table|@Column|@Repository|JpaRepository|sqlalchemy|django\.db|models\.Model|diesel::|sea_orm|prisma|typeorm|mongoose|@PrimaryKey|\.objects\.(filter|get|create)\("), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "ORM usage"),
    "transaction_sites": (re.compile(r"\.beginTransaction\(|@Transactional|setAutoCommit\(false\)|\.commit\(\)|\.rollback\(\)|BEGIN TRANSACTION|\.begin\(\)\.await|\.transaction\(|with .*\.begin\(\)|session\.begin|db\.Begin\("), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "transactions"),
    "migration_sites": (re.compile(r"Flyway|Liquibase|alembic|schema_version|user_version|PRAGMA user_version|sqlx::migrate!|Migrator|MigrateDatabase|migrations/|\bmigrate\(\)|CREATE TABLE IF NOT EXISTS|ALTER TABLE"), ['rust', 'java', 'csharp', 'js', 'python', 'go', 'config'], "migrations and schema versioning"),
    "format_version_sites": (re.compile(r"\b(schema|format|file|data|config)_?[vV]ersion\b|\bVERSION_[A-Z_]*\s*[:=]|magic\s*(bytes|number)|\"version\"\s*:"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "version fields/markers in formats"),
    "checksum_sites": (re.compile(r"MessageDigest|DigestUtils|sha2::|Sha256|md5::|crc32|hashlib\.|createHash\(|crypto\.subtle\.digest|\bchecksum\b"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "hashes/checksums (integrity or identity)"),
    "archive_sites": (re.compile(r"ZipOutputStream|ZipInputStream|ZipFile|zip::|tar::|flate2|zstd::|lz4|snap::|GZIPOutputStream|zlib|gzip\.|tarfile|zipfile|archiver|fflate|JSZip"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "archives and compression"),
    "db_pragma_sites": (re.compile(r"PRAGMA\s+\w+|journal_mode|SqliteJournalMode|SqliteSynchronous|synchronous\s*=|\bWAL\b|busy_timeout|foreign_keys"), ['rust', 'java', 'csharp', 'js', 'python', 'go', 'config'], "database durability/concurrency settings"),
    "lock_file_sites": (re.compile(r"FileLock|FileChannel\.(try)?[lL]ock\(|\bflock\(|fcntl\.(flock|lockf)|lockfile|\.lock\b[\"']|LOCK_EX|fs2::FileExt|fd_lock|FileExt::|file\.(try_)?lock(_shared|_exclusive)?\(|\.try_lock\(\)\s*\{|\.lock\(\)\s*\{|rwlock\(|\.lock\.write\(|lock_file"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "file locks and lock files"),
    "data_dir_sites": (re.compile(r"user_home|System\.getProperty\(\"user\.home\"\)|dirs::(home|config|data|cache)_dir|home_dir\(\)|os\.homedir\(\)|Path\.home\(\)|expanduser\(|XDG_(CONFIG|DATA|CACHE)_HOME|APPDATA|LOCALAPPDATA|\.join\(\"\.\w+\"\)|/\.\w+/"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "data-directory resolution"),
    "data_dir_env_candidates": (re.compile(r"(getenv|env::var|process\.env\.|os\.environ)[^\n]*(DIR|HOME|PATH|ROOT|DATA|CACHE)"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "lead: env vars that locate data"),
    "cleanup_sites": (re.compile(r"deleteDirectory\(|FileUtils\.(delete\w*|clean\w*)\(|\.delete\(\)|Files\.delete(IfExists)?\(|remove_dir_all\(|remove_file\(|fs::remove|rmSync\(|\brm\(|shutil\.rmtree\(|os\.remove\(|os\.RemoveAll\(|\.unlink\("), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "deletion/cleanup calls"),
    "retention_keyword_files": (re.compile(r"\b(retention|retain|prune|expire|expir(y|ation)|ttl|max_age|maxAge|rotate|rotation)\b"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "files mentioning retention/rotation"),
    "backup_keyword_files": (re.compile(r"\b(backup|restore|snapshot)\b"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "files mentioning backup/export"),
    "cloud_storage_sites": (re.compile(r"s3::|S3Client|aws_sdk_s3|boto3|storage\.blob|BlobServiceClient|google\.cloud\.storage|@aws-sdk/client-s3|minio|gcs"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "object storage clients"),
    "cache_store_sites": (re.compile(r"redis|memcache|lru::LruCache|LruCache|moka::|Caffeine|@Cacheable|node-cache|keyv"), ['rust', 'java', 'csharp', 'js', 'python', 'go'], "caches and key-value stores"),
}


def language_of(path: Path):
    for lang, exts in EXTS.items():
        if path.suffix in exts:
            return lang
    return None


def is_test_path(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    return bool(TEST_FILE.search(rel.name)) or any(TEST_SEGMENT.search(p) for p in rel.parts[:-1])


def rust_non_test(lines):
    pending, skip_depth, depth = False, None, 0
    for i, line in enumerate(lines, 1):
        if skip_depth is None:
            if RUST_CFG_TEST.search(line):
                pending = True
            elif pending and RUST_MOD_OPEN.search(line):
                skip_depth, pending = depth, False
            else:
                if pending and line.strip() and not line.strip().startswith(("#[", "//")):
                    pending = False
                    depth += line.count("{") - line.count("}")
                    continue
                yield i, line
        depth += line.count("{") - line.count("}")
        if skip_depth is not None and depth <= skip_depth:
            skip_depth = None


def scan(root: Path, excludes):
    hits, files_seen = defaultdict(list), defaultdict(int)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if any(p in SKIP_DIRS or p in excludes for p in parts[:-1]):
            continue
        lang = language_of(path)
        if not lang or is_test_path(path, root):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if lang == "config" and len(text) > 400_000:
            continue
        files_seen[lang] += 1
        lines = text.splitlines()
        rel = path.relative_to(root).as_posix()
        candidates = rust_non_test(lines) if lang == "rust" else enumerate(lines, 1)
        for lineno, line in candidates:
            if COMMENT.match(line):
                continue
            for key, (rx, langs, _note) in PATTERNS.items():
                if langs and lang not in langs:
                    continue
                if rx.search(line):
                    hits[key].append((rel, lineno, line.strip()[:160]))
    return hits, files_seen


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("src_root")
    ap.add_argument("--json")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--exclude", action="append", default=[], metavar="DIR")
    args = ap.parse_args(argv)
    root = Path(args.src_root).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2
    hits, files_seen = scan(root, set(args.exclude))
    mig_files = [p for p in root.rglob("*.sql") if "migration" in p.as_posix().lower() and not any(d in p.parts for d in SKIP_DIRS)]
    for mp in mig_files:
        hits["migration_files"].append((mp.relative_to(root).as_posix(), 1, "migration file"))
    PATTERNS.setdefault("migration_files", (None, None, "SQL files under a migrations directory"))
    stats = {}
    for k in list(PATTERNS):  # zeros for fact keys are facts (0 fsync, 0 locks); leads only when hit
        v = hits.get(k, [])
        if not v and k.endswith(("_candidates", "_keyword_files")):
            continue
        stats[k] = len({f for f, _, _ in v}) if k.endswith("_keyword_files") else len(v)
    stats = dict(sorted(stats.items()))
    leads = {k: n for k, n in stats.items() if k.endswith(("_candidates", "_keyword_files"))}
    facts = {k: n for k, n in stats.items() if k not in leads}
    notes = {k: PATTERNS[k][2] for k in stats}
    print(f"Scanned {sum(files_seen.values())} non-test files "
          f"({', '.join(f'{l}: {n}' for l, n in sorted(files_seen.items()))}) under {root}\n")
    print("stats (facts; copy into findings stats after discarding keys you verified as false positives, naming them in count_notes):")
    for k, n in facts.items():
        print(f"  {k:36s} {n:6d}   {notes.get(k, '')}")
    print("leads (read before citing; do NOT copy as stats):")
    for k, n in leads.items():
        print(f"  {k:36s} {n:6d}   {notes.get(k, '')}")
    print()
    for key, rows in sorted(hits.items()):
        per_file = defaultdict(int)
        for f, _, _ in rows:
            per_file[f] += 1
        print(f"{key} — top files:")
        for f, n in sorted(per_file.items(), key=lambda kv: -kv[1])[: args.top]:
            print(f"  {n:5d}  {f}")
        print()
    if args.json:
        Path(args.json).write_text(json.dumps({
            "src_root": str(root), "files_scanned": dict(files_seen),
            "count_rule": "non-test files by path (test/tests/spec/mock/fixture segments, *_test.*, *Test.java, test_*.py)"
                          + ("; Rust #[cfg(test)] modules excluded" if "rust" in files_seen else "") + "; single-line regex matches",
            "stats": facts, "leads": leads, "notes": notes,
            "hits": {k: [{"file": f, "line": l, "snippet": s} for f, l, s in v] for k, v in hits.items()},
        }, indent=2))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
