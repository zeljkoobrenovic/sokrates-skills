#!/usr/bin/env python3
"""Count performance-relevant code shapes for the performance scanner.

Deterministic, standard-library only. Every shape is context-aware where it
matters: "in loop" means inside a `for`/`while`/`loop`/`.forEach(`/`.stream()`/
`.iter()` body by a crude brace/indent heuristic; static/lazy initializers are
excluded from per-call shapes. Test code is excluded by path (test/tests/spec/
mock/fixture segments, *_test.*, *Test.java, test_*.py) and, for Rust, inside
`#[cfg(test)]` modules.

Usage:
  python3 count_perf_sites.py <src-root> [--json out.json] [--top 12] [--exclude DIR ...]

Console: facts (copy into `stats`), leads (read before citing), top files per
shape. JSON: everything, every hit as file:line:snippet.

Shapes (facts unless marked lead):
  all      regex_compile_in_loop_sites, per_call_allocation_sites, whole_file_read_sites,
           string_concat_in_loop_candidates, sort_in_loop_sites, static_collection_sites,
           parallel_sites, executor_sites, lock_sites, cache_sites, limit_constants,
           nested_loop_candidates (lead), linear_lookup_in_loop_candidates (lead),
           io_in_loop_candidates (lead)
  Rust     clone_in_loop_candidates, deep_copy_sites (Arc::unwrap_or_clone/make_mut),
           blocking_in_async_candidates (block_on/block_in_place in async fn files),
           spawn_blocking_sites, std_lock_in_async_files, channel_capacities (list)
  JS/TS    sync_io_sites (readFileSync etc.), await_in_loop_candidates (lead)
  Python   global_regex_sites vs re.compile in functions, list_in_loop_candidates (lead)
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
TEST_SEGMENT = re.compile(r"(^|[._-])(tests?|spec|specs|mocks?|fixtures?|testdata|test[-_]support|benches?)([._-]|$)", re.I)
TEST_FILE = re.compile(r"(_tests?\.\w+$|Tests?\.java$|\.spec\.\w+$|\.test\.\w+$|^test_.*\.py$|^tests?\.rs$|^conftest\.py$)", re.I)

LOOP_OPEN = re.compile(r"\b(for|while)\s*\(|\bloop\s*\{|\bfor\s+\w[^{;]*\bin\b[^{;]*\{|\.forEach\s*\(|\.for_each\s*\(|^\s*(for|while)\b.*:\s*$")
COMMENT = re.compile(r"^\s*(//|/\*|\*|#)")
STATIC_INIT = re.compile(r"\bstatic\s+(final\s+)?[\w<>\[\], ?]+\s+\w+\s*=|\bstatic\s*\{|LazyLock|OnceLock|OnceCell|Lazy::new|lazy_static!|^\s*(pub\s+)?const\s+[A-Z_]+|^\s*(pub\s+)?static\s+[A-Z_]+|^[A-Z_]{3,}\s*=")
ASYNC_FN = re.compile(r"\basync\s+fn\b|\basync\s+(function|\(|\w+\s*\()|^\s*async\s+def\b")
RUST_CFG_TEST = re.compile(r"#\[cfg\(test\)\]")
RUST_MOD_OPEN = re.compile(r"^\s*(pub(\([^)]*\))?\s+)?mod\s+\w+\s*\{")

# key -> (regex, in_loop_required, exclude_static, note)
COMMON = {
    "regex_compile_in_loop_sites": (re.compile(r"Pattern\.compile\(|\.replaceAll\(|\.replaceFirst\(|\.matches\(\s*\"|\.split\(\s*\"[^\"]*[\\\[\]*+?|()][^\"]*\"|new RegExp\(|Regex::new\(|re\.compile\(|re\.(match|search|sub|findall|split)\("), True, True, "regex compiled or implicitly compiled inside a loop body"),
    "per_call_allocation_sites": (re.compile(r"new (SimpleDateFormat|ObjectMapper|Gson|GsonBuilder|DecimalFormat|MessageDigest)\(|Pattern\.compile\(|Regex::new\(|DateTimeFormatter\.ofPattern\("), False, True, "expensive object built per call (not in a static/lazy field)"),
    "whole_file_read_sites": (re.compile(r"FileUtils\.(readFileToString|readLines|readFileToByteArray)\(|Files\.(readAllLines|readString|readAllBytes)\(|IOUtils\.toString\(|fs::read_to_string\(|fs::read\(|readFileSync\(|readFile\(|\.read_text\(|\.read_bytes\(|\.readlines\(\)|ioutil\.ReadFile\(|os\.ReadFile\("), False, False, "whole-file reads (fine for small files; check what can be large)"),
    "string_concat_in_loop_candidates": (re.compile(r"\b\w+\s*\+=\s*[\"'\w]|\.push_str\(&format!"), True, False, "string building by += inside a loop"),
    "sort_in_loop_sites": (re.compile(r"\.sort(ed|By|_by|_unstable|_by_key)?\(|Collections\.sort\(|sorted\("), True, False, "sort inside a loop body"),
    "static_collection_sites": (re.compile(r"static\s+(final\s+)?(Map|HashMap|List|ArrayList|Set|HashSet|ConcurrentHashMap)<|static\s+mut\s+|lazy_static!|LazyLock<(Mutex|RwLock)|OnceLock<(Mutex|RwLock)|^\s*_?[A-Z_]+_CACHE\s*[:=]"), False, False, "process-wide mutable collections (caches that may leak across runs)"),
    "parallel_sites": (re.compile(r"parallelStream\(\)|\.parallel\(\)|rayon::|par_iter\(\)|tokio::spawn\(|JoinSet|join_all\(|FuturesOrdered|FuturesUnordered|buffer_unordered\(|buffered\(|Promise\.all(Settled)?\(|multiprocessing\.|concurrent\.futures|asyncio\.gather\(|ThreadPoolExecutor|go func"), False, False, "parallelism present"),
    "executor_sites": (re.compile(r"Executors\.new\w+\(|newFixedThreadPool\(\s*\d+|ForkJoinPool\(|worker_threads\(\s*\d+|max_workers\s*=\s*\d+|new Worker\(|threadpool|num_cpus|available_processors|availableProcessors\(\)"), False, False, "thread/worker pool creation and sizing"),
    "lock_sites": (re.compile(r"\bsynchronized\b|ReentrantLock|std::sync::(Mutex|RwLock)|tokio::sync::(Mutex|RwLock)|Mutex::new\(|RwLock::new\(|threading\.Lock\(|sync\.(Mutex|RWMutex)"), False, False, "locks (read which ones sit on hot paths)"),
    "cache_sites": (re.compile(r"@lru_cache|functools\.cache|@cached\b|Caffeine|CacheBuilder|LoadingCache|\bmemoize\(|useMemo\(|useCallback\(|OnceCell|OnceLock|LazyLock|lazy_static!|lru::LruCache|LruCache|moka::|cached!|(Concurrent)?HashMap<[^>]*>\s+\w*([cC]ache|[mM]emo|compiled)\w*\s*=|\w*([cC]ache|[mM]emo)\w*\s*=\s*new (Concurrent)?HashMap"), False, False, "caches/memoization present (library caches and map fields named cache/memo)"),
    "limit_constants": (re.compile(r"\b(const|static|final|let|var|int|long|usize|u32|u64|i32|i64|private|public|protected)\b[^=\n]*\b\w*(MAX|MAXIMUM|LIMIT|CAP|BUDGET|THRESHOLD|[mM]ax[A-Z_]\w*|[lL]imit\w*|[tT]hreshold\w*)\w*\s*(:\s*\w+)?\s*=\s*-?\d+"), False, False, "named numeric caps and limits (constants and fields)"),
    "nested_loop_candidates": (re.compile(r"\b(for|while)\s*\(|\bfor\s+\w[^{;]*\bin\b|\.forEach\s*\(|\.for_each\s*\(|\.stream\(\)"), True, False, "lead: loop header inside another loop body — read for same-collection nesting"),
    "linear_lookup_in_loop_candidates": (re.compile(r"\.contains\(|\.indexOf\(|\.containsKey\(|\bin\s+\w+_list\b|\.includes\(|\.find\(\s*\(?\w*\)?\s*=>|\.iter\(\)\.(find|any|position)\(|\.stream\(\)\.(filter|anyMatch)\([^)]*\)\.(findAny|findFirst|isPresent)"), True, False, "lead: membership/search call inside a loop — read the receiver's type (List = linear)"),
    "io_in_loop_candidates": (re.compile(r"new File(Input|Output)Stream\(|FileUtils\.\w+\(|Files\.\w+\(|File::open\(|fs::\w+\(|open\(|readFile|writeFile|\.execute\(|\.query\(|fetch\(|\.get\(\s*\"http|reqwest::|http\.(get|post)|requests\.(get|post)|\.send\(\)\.await"), True, False, "lead: I/O, DB or network call inside a loop (N+1 shapes)"),
}
RUST_ONLY = {
    "clone_in_loop_candidates": (re.compile(r"\.clone\(\)|\.to_string\(\)|\.to_vec\(\)|\.to_owned\(\)"), True, False, "clones/allocations inside a loop body"),
    "deep_copy_sites": (re.compile(r"Arc::unwrap_or_clone\(|Arc::make_mut\(|Rc::make_mut\("), False, False, "deep copy of shared state"),
    "blocking_in_async_candidates": (re.compile(r"\bblock_on\(|block_in_place\(|std::thread::sleep\(|std::fs::\w+\(|std::io::stdin\(\)"), False, False, "blocking calls in files that contain async fns"),
    "spawn_blocking_sites": (re.compile(r"spawn_blocking\("), False, False, ""),
    "std_lock_in_async_files": (re.compile(r"std::sync::(Mutex|RwLock)|use std::sync::\{[^}]*(Mutex|RwLock)"), False, False, "std locks in files that contain async fns (held across await?)"),
    "channel_capacity_sites": (re.compile(r"mpsc::channel\(\s*\d+|bounded\(\s*\d+|broadcast::channel\(\s*\d+|unbounded_channel\(\)|mpsc::unbounded\("), False, False, "channel capacities (unbounded = unbounded)"),
}
JS_ONLY = {
    "sync_io_sites": (re.compile(r"\b\w+Sync\("), False, False, "synchronous fs calls (blocking the event loop)"),
    "await_in_loop_candidates": (re.compile(r"\bawait\b"), True, False, "lead: await inside a loop — sequential where parallel may be intended"),
}
PY_ONLY = {
    "list_in_loop_candidates": (re.compile(r"\bin\s+\w+\s*(:|\))|\.append\(|\+\s*\["), True, False, "lead: list membership/growth inside a loop"),
}


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


def loop_depths(lines, lang):
    """Return per-line loop depth (0 = not inside any loop body) by a brace/indent heuristic."""
    depths = [0] * (len(lines) + 1)
    if lang == "python":
        stack = []  # indent levels of open loops
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped:
                depths[i] = len(stack)
                continue
            indent = len(line) - len(line.lstrip())
            while stack and indent <= stack[-1]:
                stack.pop()
            depths[i] = len(stack)
            if re.match(r"(for|while)\b.*:\s*(#.*)?$", stripped):
                stack.append(indent)
        return depths
    stack = []  # brace depth at which each loop body opened
    depth = 0
    for i, line in enumerate(lines, 1):
        opened_loop = bool(LOOP_OPEN.search(line))
        depths[i] = len(stack) + (0 if opened_loop else 0)
        opens, closes = line.count("{") + line.count("("), line.count("}") + line.count(")")
        if opened_loop:
            stack.append(depth)
        depth += opens - closes
        while stack and depth <= stack[-1]:
            stack.pop()
    return depths


def scan(root: Path, excludes):
    hits, notes, files_seen = defaultdict(list), {}, defaultdict(int)
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
        files_seen[lang] += 1
        lines = text.splitlines()
        depths = loop_depths(lines, lang)
        has_async = bool(ASYNC_FN.search(text))
        shapes = dict(COMMON)
        if lang == "rust":
            shapes.update(RUST_ONLY)
        elif lang == "js":
            shapes.update(JS_ONLY)
        elif lang == "python":
            shapes.update(PY_ONLY)
        rel = path.relative_to(root).as_posix()
        candidates = rust_non_test(lines) if lang == "rust" else enumerate(lines, 1)
        for lineno, line in candidates:
            if COMMENT.match(line):
                continue
            for key, (rx, in_loop, excl_static, note) in shapes.items():
                if not rx.search(line):
                    continue
                if in_loop and depths[lineno] < 1:
                    continue
                if key == "nested_loop_candidates" and depths[lineno] < 1:
                    continue
                if excl_static and (STATIC_INIT.search(line) or any(STATIC_INIT.search(lines[j]) for j in range(max(0, lineno - 3), lineno - 1))):
                    continue
                if key in ("blocking_in_async_candidates", "std_lock_in_async_files") and not has_async:
                    continue
                hits[key].append((rel, lineno, line.strip()[:160]))
                if note:
                    notes[key] = note
    return hits, notes, files_seen


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
    hits, notes, files_seen = scan(root, set(args.exclude))
    for key in list(hits):
        seen, uniq = set(), []
        for row in hits[key]:
            if (row[0], row[1]) not in seen:
                seen.add((row[0], row[1])); uniq.append(row)
        hits[key] = uniq
    stats = {k: len(v) for k, v in sorted(hits.items())}
    if "std_lock_in_async_files" in hits:
        stats["std_lock_in_async_files"] = len({f for f, _, _ in hits["std_lock_in_async_files"]})
    leads = {k: n for k, n in stats.items() if k.endswith("_candidates")}
    facts = {k: n for k, n in stats.items() if k not in leads}
    print(f"Scanned {sum(files_seen.values())} non-test source files "
          f"({', '.join(f'{l}: {n}' for l, n in sorted(files_seen.items()))}) under {root}")
    print("Loop context by brace/indent heuristic; static/lazy initializers excluded from per-call shapes; test code excluded by path"
          + (" and Rust #[cfg(test)] modules" if "rust" in files_seen else "") + ".\n")
    print("stats (copy into findings stats):")
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
            "count_rule": "non-test files by path; loop context by brace/indent heuristic; static/lazy initializers excluded from per-call shapes"
                          + ("; Rust #[cfg(test)] modules excluded" if "rust" in files_seen else ""),
            "stats": facts, "leads": leads, "notes": notes,
            "hits": {k: [{"file": f, "line": l, "snippet": s} for f, l, s in v] for k, v in hits.items()},
        }, indent=2))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
