#!/usr/bin/env python3
"""Count error-handling shapes per ecosystem for the reliability scanner.

Deterministic, standard-library only. Produces the canonical `stats` counts the
reliability-scan SKILL.md asks for, plus per-file hit lists so the scanner knows
where to read. Test code is excluded by path (any path segment containing
"test" or "tests", "*_test.*", "*_tests.*", "*Test.java", "spec" dirs) and, for
Rust, by tracking `#[cfg(test)]` module state inside each file.

Usage:
  python3 count_handling_sites.py <src-root> [--json out.json] [--top 15] [--exclude DIR ...]

Console: the stats and the top files per shape (truncated). JSON: everything,
including every hit as file:line:snippet, grouped by shape.

Two kinds of keys: facts (copy into `stats`) and leads (`*_candidates`, `*_keyword_files`
— reading lists, never stats). Shapes:
  Rust     unwrap_sites, expect_sites, panic_sites, unreachable_sites,
           let_underscore_candidates (candidates), catch_unwind_sites,
           poison_into_inner_sites, join_error_checked_sites, fsync_sites,
           signal_handling_sites, in_place_write_candidates
  Java/Kt  catch_all_sites, empty_catch_sites (single- and multi-line), print_stack_trace_sites,
           atomic_write_sites (rename/move), shutdown_hook_sites, system_exit_sites,
           signal_handling_sites, task_spawn_sites, process_spawn_sites, temp_file_sites,
           tolerant_parser_config_sites; leads: in_place_write_candidates, bare_stream_candidates
           (outside try-with-resources), rethrow_without_cause_candidates, log_only_catch_candidates
  JS/TS    catch_all_sites (bare catch), empty_catch_sites, unhandled_hooks,
           promise_all_sites, signal_handling_sites
  Python   catch_all_sites, empty_catch_sites (except: pass), signal_handling_sites
  Go       dropped_error_candidates, recover_sites, signal_handling_sites
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

EXTS = {
    "rust": {".rs"},
    "java": {".java", ".kt", ".scala"},
    "js": {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"},
    "python": {".py"},
    "go": {".go"},
    "csharp": {".cs"},
}
SKIP_DIRS = {"node_modules", "target", "build", "dist", "out", ".git", "vendor", "venv", ".venv",
             "__pycache__", "_sokrates", "_sokrates_landscape"}
TEST_SEGMENT = re.compile(r"(^|[._-])(tests?|spec|specs|mocks?|fixtures?|testdata|test[-_]support)([._-]|$)", re.I)
TEST_FILE = re.compile(r"(_tests?\.\w+$|Tests?\.java$|\.spec\.\w+$|\.test\.\w+$|^test_.*\.py$|^tests?\.rs$|^conftest\.py$)", re.I)

# (stat key, regex, note). Rust regexes are applied outside #[cfg(test)] modules.
PATTERNS = {
    "rust": [
        ("unwrap_sites", re.compile(r"\.unwrap\(\)"), "unwrap on non-test code"),
        ("expect_sites", re.compile(r"\.expect\(\s*\""), "expect(\"...\") on non-test code (mock .expect(n) excluded)"),
        ("panic_sites", re.compile(r"\bpanic!\("), ""),
        ("unreachable_sites", re.compile(r"\bunreachable!\("), ""),
        ("let_underscore_candidates", re.compile(r"\blet _ = (?!.*\b(send|try_send|send_async|notify)\b)"), "candidates: let _ = on something that is not a channel send"),
        ("catch_unwind_sites", re.compile(r"\bcatch_unwind\b"), ""),
        ("poison_into_inner_sites", re.compile(r"PoisonError|\.into_inner\(\)\s*\)?\s*$|unwrap_or_else\(\s*\|e\|\s*e\.into_inner"), "lock-poison convention"),
        ("join_error_checked_sites", re.compile(r"\bis_panic\(\)|JoinError"), "task panics observed"),
        ("fsync_sites", re.compile(r"\.sync_all\(\)|\.sync_data\(\)"), ""),
        ("signal_handling_sites", re.compile(r"tokio::signal|signal::unix|ctrl_c\(|SIGTERM|SIGHUP|SIGINT"), ""),
        ("in_place_write_candidates", re.compile(r"\bfs::write\(|File::create\(|OpenOptions::new\(\)"), "candidates: writes that may not be atomic"),
        ("atomic_write_sites", re.compile(r"\bfs::rename\(|\.persist\(|NamedTempFile|write_atomically|tempfile"), ""),
        ("timeout_sites", re.compile(r"tokio::time::timeout\(|\btimeout\(Duration|\.timeout\(Duration"), "distinct call sites, dedupe to mechanisms"),
    ],
    "java": [
        ("catch_all_sites", re.compile(r"catch\s*\(\s*(final\s+)?(Exception|Throwable|RuntimeException|Error)\b"), ""),
        ("empty_catch_sites", re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}"), "single-line empty catch (multi-line ones need reading)"),
        ("print_stack_trace_sites", re.compile(r"\.printStackTrace\(\)"), ""),
        ("rethrow_without_cause_candidates", re.compile(r"throw new \w*(Exception|Error)\(\s*\"[^\"]*\"\s*\)"), "candidates: message-only exception thrown within 6 lines after a catch (cause may be lost)"),
        ("log_only_catch_candidates", re.compile(r"^\s*(LOG|log|logger|LOGGER)\.(debug|trace|warn|info|error)\("), "candidates: logging call within 2 lines after a catch — read whether anything else happens"),
        ("task_spawn_sites", re.compile(r"Executors\.new|parallelStream\(\)|new Thread\(|CompletableFuture\.(run|supply)Async|ForkJoinPool"), "isolation leads: where work leaves the calling thread"),
        ("process_spawn_sites", re.compile(r"ProcessBuilder|Runtime\.getRuntime\(\)\.exec\("), "isolation leads: check waitFor/timeout next to them"),
        ("tolerant_parser_config_sites", re.compile(r"FAIL_ON_UNKNOWN_PROPERTIES|FAIL_ON_IGNORED_PROPERTIES|ACCEPT_SINGLE_VALUE"), "error-model leads"),
        ("temp_file_sites", re.compile(r"createTempFile\(|createTempDirectory\(|deleteOnExit\("), "resources leads: temp files and whether they are cleaned"),
        ("in_place_write_candidates", re.compile(r"new FileWriter\(|new FileOutputStream\(|Files\.write(String)?\(|Files\.newOutputStream\(|FileUtils\.write|writeStringToFile|PrintWriter\("), "candidates: direct writes to a target path"),
        ("atomic_write_sites", re.compile(r"\.renameTo\(|ATOMIC_MOVE|Files\.move\("), "rename/move calls (a temp+rename write counts once)"),
        ("shutdown_hook_sites", re.compile(r"addShutdownHook\("), ""),
        ("system_exit_sites", re.compile(r"System\.exit\(|Runtime\.getRuntime\(\)\.halt\("), ""),
        ("signal_handling_sites", re.compile(r"sun\.misc\.Signal|SignalHandler"), ""),
        ("bare_stream_candidates", re.compile(r"(\w+)\s+\w+\s*=\s*new (Zip(In|Out)putStream|File(In|Out)putStream|(Buffered|Input|Output)Stream(Reader|Writer)?|Buffered(Reader|Writer)|FileReader|FileWriter|PrintWriter|Scanner)\("), "candidates: stream declared outside a try-with-resources header (checked 3 lines back)"),
        ("timeout_keyword_files", re.compile(r"\btimeout\b", re.I), "files mentioning timeout (counted per file), dedupe to mechanisms"),
        ("retry_keyword_files", re.compile(r"\bretr(y|ies)\b", re.I), "files mentioning retry (counted per file), dedupe to mechanisms"),
    ],
    "csharp": [
        ("catch_all_sites", re.compile(r"catch\s*(\(\s*(Exception|SystemException)\b[^)]*\))?\s*\{"), ""),
        ("empty_catch_sites", re.compile(r"catch\s*(\([^)]*\))?\s*\{\s*\}"), ""),
        ("in_place_write_candidates", re.compile(r"File\.Write(All)?(Text|Bytes|Lines)\(|new StreamWriter\("), ""),
        ("atomic_write_sites", re.compile(r"File\.Move\(|File\.Replace\("), ""),
        ("timeout_keyword_files", re.compile(r"\bTimeout\b|CancellationTokenSource\(\s*\d"), "files mentioning timeout"),
        ("retry_keyword_files", re.compile(r"\bRetry|Polly\b"), "files mentioning retry"),
    ],
    "js": [
        ("catch_all_sites", re.compile(r"\bcatch\s*(\(\s*\w*\s*\))?\s*\{"), "every catch (JS cannot filter by type)"),
        ("empty_catch_sites", re.compile(r"\bcatch\s*(\(\s*\w*\s*\))?\s*\{\s*\}|\.catch\(\s*\(\s*\)\s*=>\s*\{\s*\}\s*\)|\.catch\(\s*noop\s*\)"), ""),
        ("unhandled_hooks", re.compile(r"process\.on\(\s*['\"](uncaughtException|unhandledRejection)"), ""),
        ("promise_all_sites", re.compile(r"Promise\.all\(|Promise\.allSettled\("), "all vs allSettled"),
        ("signal_handling_sites", re.compile(r"process\.on\(\s*['\"]SIG|AbortController"), ""),
        ("in_place_write_candidates", re.compile(r"writeFile(Sync)?\(|createWriteStream\("), ""),
        ("atomic_write_sites", re.compile(r"\brename(Sync)?\(|write-file-atomic"), ""),
        ("timeout_keyword_files", re.compile(r"setTimeout\(|AbortSignal\.timeout\(|timeout:"), "files mentioning timeout"),
        ("retry_keyword_files", re.compile(r"\bretr(y|ies)\b", re.I), "files mentioning retry"),
    ],
    "python": [
        ("catch_all_sites", re.compile(r"^\s*except\s*(:|\(?\s*(Exception|BaseException)\b)"), ""),
        ("empty_catch_sites", re.compile(r"^\s*except[^:]*:\s*pass\s*$"), "single-line except: pass"),
        ("signal_handling_sites", re.compile(r"signal\.signal\(|asyncio\.CancelledError|KeyboardInterrupt"), ""),
        ("in_place_write_candidates", re.compile(r"open\([^)]*,\s*['\"][wa]"), ""),
        ("atomic_write_sites", re.compile(r"os\.replace\(|os\.rename\(|NamedTemporaryFile"), ""),
        ("timeout_keyword_files", re.compile(r"timeout\s*=|wait_for\(|asyncio\.timeout\("), "files mentioning timeout"),
        ("retry_keyword_files", re.compile(r"\bretr(y|ies)\b|tenacity|backoff", re.I), "files mentioning retry"),
    ],
    "go": [
        ("dropped_error_candidates", re.compile(r"^\s*(_\s*=|_,\s*_\s*:?=|\w+,\s*_\s*:?=)\s*\w"), "candidates: blank-identifier assignments"),
        ("recover_sites", re.compile(r"\brecover\(\)"), ""),
        ("signal_handling_sites", re.compile(r"signal\.Notify\(|os\.Interrupt|syscall\.SIGTERM"), ""),
        ("in_place_write_candidates", re.compile(r"os\.WriteFile\(|os\.Create\(|ioutil\.WriteFile\("), ""),
        ("atomic_write_sites", re.compile(r"os\.Rename\("), ""),
        ("timeout_sites", re.compile(r"context\.WithTimeout\(|time\.After\("), "call sites"),
        ("retry_keyword_files", re.compile(r"\bretr(y|ies)\b", re.I), "files mentioning retry"),
    ],
}
PATTERNS["kotlin"] = PATTERNS["java"]

CATCH_RX = re.compile(r"\bcatch\s*\(|^\s*except\b")
TRY_RES_RX = re.compile(r"\btry\s*\(")
EMPTY_CATCH_BLOCK = re.compile(r"catch\s*\([^)]*\)\s*\{(\s*(//[^\n]*)?\n)+\s*\}")
RUST_CFG_TEST = re.compile(r"#\[cfg\(test\)\]")
RUST_MOD_OPEN = re.compile(r"^\s*(pub(\([^)]*\))?\s+)?mod\s+\w+\s*\{")


def language_of(path: Path):
    for lang, exts in EXTS.items():
        if path.suffix in exts:
            return lang
    return None


def is_test_path(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if TEST_FILE.search(rel.name):
        return True
    return any(TEST_SEGMENT.search(part) for part in rel.parts[:-1])


def rust_non_test_lines(lines):
    """Yield (lineno, text) for lines outside #[cfg(test)] modules (brace-depth tracked)."""
    pending_cfg = False
    skip_depth = None
    depth = 0
    for i, line in enumerate(lines, 1):
        if skip_depth is None:
            if RUST_CFG_TEST.search(line):
                pending_cfg = True
            elif pending_cfg and RUST_MOD_OPEN.search(line):
                skip_depth = depth
                pending_cfg = False
            elif pending_cfg and line.strip() and not line.strip().startswith(("#[", "//")):
                pending_cfg = False  # cfg(test) applied to a fn/item, not a module — skip only that line
                depth += line.count("{") - line.count("}")
                continue
            else:
                yield i, line
        depth += line.count("{") - line.count("}")
        if skip_depth is not None and depth <= skip_depth:
            skip_depth = None


def scan(root: Path, excludes):
    hits = defaultdict(list)  # key -> [(file, line, snippet)]
    notes = {}
    files_seen = defaultdict(int)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(p in SKIP_DIRS or p in excludes for p in rel_parts[:-1]):
            continue
        lang = language_of(path)
        if not lang or is_test_path(path, root):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files_seen[lang] += 1
        lines = text.splitlines()
        candidates = rust_non_test_lines(lines) if lang == "rust" else enumerate(lines, 1)
        pats = PATTERNS[lang]
        rel = path.relative_to(root).as_posix()
        last_catch = -100
        for lineno, line in candidates:
            if CATCH_RX.search(line):
                last_catch = lineno
            for key, rx, note in pats:
                if not rx.search(line):
                    continue
                if key == "bare_stream_candidates" and any(TRY_RES_RX.search(lines[j]) for j in range(max(0, lineno - 4), lineno)):
                    continue
                if key == "rethrow_without_cause_candidates" and not (0 <= lineno - last_catch <= 6):
                    continue
                if key == "log_only_catch_candidates" and not (1 <= lineno - last_catch <= 2):
                    continue
                hits[key].append((rel, lineno, line.strip()[:160]))
                if note:
                    notes[key] = note
        # multi-line empty catch: "catch (...) {" followed only by blank/comment lines and "}"
        if lang in ("java", "csharp"):
            for m in EMPTY_CATCH_BLOCK.finditer(text):
                lineno = text.count("\n", 0, m.start()) + 1
                hits["empty_catch_sites"].append((rel, lineno, m.group(0).split("\n")[0].strip()[:160]))
    return hits, notes, files_seen


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("src_root")
    ap.add_argument("--json", help="write full hit lists to this file")
    ap.add_argument("--top", type=int, default=12, help="files per shape on the console")
    ap.add_argument("--exclude", action="append", default=[], metavar="DIR", help="extra directory names to skip")
    args = ap.parse_args(argv)
    root = Path(args.src_root).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    hits, notes, files_seen = scan(root, set(args.exclude))
    for key in list(hits):
        seen, uniq = set(), []
        for row in hits[key]:
            if (row[0], row[1]) not in seen:
                seen.add((row[0], row[1])); uniq.append(row)
        hits[key] = uniq
    stats = {}
    for k, v in sorted(hits.items()):
        stats[k] = len({f for f, _, _ in v}) if k.endswith("_keyword_files") else len(v)
    candidates = {k: n for k, n in stats.items() if k.endswith(("_candidates", "_keyword_files"))}
    facts = {k: n for k, n in stats.items() if k not in candidates}
    print(f"Scanned {sum(files_seen.values())} non-test source files "
          f"({', '.join(f'{l}: {n}' for l, n in sorted(files_seen.items()))}) under {root}")
    print("Test code excluded by path (test/tests/spec/mock/fixture segments, *_test.*, *Test.java, test_*.py) "
          "and, for Rust, inside #[cfg(test)] modules.\n")
    print("stats (copy into findings stats):")
    for k, n in facts.items():
        print(f"  {k:36s} {n:6d}   {notes.get(k, '')}")
    print("leads (read before citing; do NOT copy as stats):")
    for k, n in candidates.items():
        print(f"  {k:36s} {n:6d}   {notes.get(k, '')}")
    print()
    for key, rows in sorted(hits.items()):
        per_file = defaultdict(int)
        for f, _, _ in rows:
            per_file[f] += 1
        top = sorted(per_file.items(), key=lambda kv: -kv[1])[: args.top]
        print(f"{key} — top files:")
        for f, n in top:
            print(f"  {n:5d}  {f}")
        print()
    if args.json:
        out = {
            "src_root": str(root),
            "files_scanned": dict(files_seen),
            "count_rule": "non-test files by path (test/tests/spec/mock/fixture segments, *_test.*, *Test.java, test_*.py)"
                          + ("; Rust #[cfg(test)] modules excluded" if "rust" in files_seen else "")
                          + "; regex matches, context-checked for try-with-resources and catch proximity",
            "stats": facts,
            "leads": candidates,
            "notes": notes,
            "hits": {k: [{"file": f, "line": l, "snippet": s} for f, l, s in v] for k, v in hits.items()},
        }
        Path(args.json).write_text(json.dumps(out, indent=2))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
