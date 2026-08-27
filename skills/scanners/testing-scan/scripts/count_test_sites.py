#!/usr/bin/env python3
"""Inventory and count test-related shapes for the testing scanner.

Deterministic, standard-library only. Unlike the other scanners' scripts this one
*includes* test code — it is the subject. It classifies every source file as
test (by path: test/tests/spec/__tests__ segments, *_test.*, *Test.java, test_*.py,
*.spec.*, *.test.*) or main, measures inline test modules inside main files
(Rust `#[cfg(test)]` blocks, Python doctests), and counts test shapes.

Usage:
  python3 count_test_sites.py <src-root> [--json out.json] [--top 12] [--exclude DIR ...]

Console: facts (copy into `stats`), leads (read before citing), test LOC per
top-level folder, top files per shape. JSON: everything, every hit as
file:line:snippet, per-file test inventory.

Facts:  test_files, test_loc, main_loc, inline_test_loc (Rust cfg(test), by crate),
        test_functions, assertions, assertion_density (assertions per test fn),
        mock_sites, snapshot_files, snapshot_assertions, property_tests, fuzz_targets,
        skipped_tests, flaky_markers, sleep_in_tests, clock_in_tests, random_in_tests,
        network_in_tests, doc_tests, frameworks (list), test_loc_by_folder (object)
Leads:  weak_assertion_candidates (tests with no assertion), shared_state_candidates
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
}
SKIP_DIRS = {"node_modules", "target", "build", "dist", "out", ".git", "vendor", "venv", ".venv",
             "__pycache__", "_sokrates", "_sokrates_landscape"}
TEST_SEGMENT = re.compile(r"^(tests?|spec|specs|__tests__|e2e|integration[-_]tests?|testdata|fixtures?|test[-_]support|test[-_]utils?|benches?)$", re.I)
TEST_FILE = re.compile(r"(_tests?\.\w+$|Tests?\.(java|kt|cs|scala)$|\.spec\.\w+$|\.test\.\w+$|^test_.*\.py$|^tests?\.rs$|^conftest\.py$|_spec\.\w+$|Spec\.(kt|scala)$)", re.I)
SNAPSHOT_EXT = {".snap", ".golden", ".approved.txt", ".snapshot"}
SNAPSHOT_DIR = re.compile(r"^(__snapshots__|snapshots|golden|goldens|testdata|fixtures|approved)$", re.I)

TEST_FN = {
    "rust": re.compile(r"^\s*#\[(tokio::)?test\b|^\s*#\[test_case|^\s*#\[rstest\]|^\s*#\[proptest|^\s*#\[quickcheck\]|^\s*#\[should_panic"),
    "java": re.compile(r"^\s*@(Test|ParameterizedTest|RepeatedTest|Property|TestFactory)\b|^\s*fun `|^\s*public void test\w+\("),
    "csharp": re.compile(r"^\s*\[(Fact|Theory|Test|TestMethod|TestCase)\b"),
    "js": re.compile(r"^\s*(it|test|it\.each|test\.each)\s*\(|^\s*(it|test)\.(only|skip|todo|concurrent)\s*\("),
    "python": re.compile(r"^\s*(async\s+)?def test_\w+\(|^\s*@given\(|^\s*@hypothesis"),
    "go": re.compile(r"^func (Test|Example|Fuzz|Benchmark)\w*\("),
}
ASSERT = re.compile(r"\bassert(_eq|_ne|_matches|Eq|Equals|True|False|That|Throws|Null|NotNull|Same|Contains|Snapshot|MatchSnapshot|_debug)?!?\s*[\(\[]|\bexpect\s*\(|\.should\b|\bassertThat\b|\bverify\s*\(|\bpretty_assertions|\bassert_snapshot|\binsta::|\bexpect_that|\bt\.(Error|Fatal|Errorf|Fatalf)\(|\bif .* != .* \{\s*t\.|require\.(Equal|NoError|True)|\.toBe|\.toEqual|\.toMatch|\.toThrow|\.toHaveBeen|self\.assert\w*\(")
MOCK = re.compile(r"\bmock(ito|k|all)?\b|Mockito\.|@Mock\b|\bMock<|\bmock!\(|\bautomock\b|\bunittest\.mock|\bmonkeypatch|\bjest\.(fn|mock|spyOn)\(|\bsinon\.|\bvi\.(fn|mock|spyOn)\(|\bwiremock|\bMockServer|\bhttpmock|\bmockito::|\bnock\(|\bresponses\.(add|activate)|\bFake\w+\(|\bStub\w+\(|\bspy\(")
SNAPSHOT_ASSERT = re.compile(r"assert_snapshot!|assert_debug_snapshot!|insta::|toMatchSnapshot\(|toMatchInlineSnapshot\(|expect_file!|\.approved|Approvals\.verify|assertSnapshot|snapshot\.assert")
PROPERTY = re.compile(r"proptest!|#\[proptest|quickcheck|@given\(|hypothesis|fast-check|fc\.assert|jqwik|@Property\b|testing/quick|rapid\.Check")
FUZZ = re.compile(r"fuzz_target!|cargo-fuzz|libfuzzer|^func Fuzz\w+\(|@FuzzTest|atheris")
SKIP = re.compile(r"#\[ignore\b|@Ignore\b|@Disabled\b|@pytest\.mark\.skip|@unittest\.skip|pytest\.skip\(|\b(it|test|describe)\.skip\(|\bxit\(|\bxtest\(|\bxdescribe\(|@pytest\.mark\.xfail|t\.Skip\(|\[Ignore\b|\.todo\(|SKIP:|TODO: enable|#\[cfg_attr\([^)]*ignore")
FLAKY = re.compile(r"\bflaky\b|\bflakey\b|@pytest\.mark\.flaky|@RetryingTest|@Retry\b|retries?\s*[:=]\s*\d|\bretry\(|jest\.retryTimes|test\.retry|nondeterministic|intermittent", re.I)
SLEEP = re.compile(r"\bsleep\(|\bthread::sleep|Thread\.sleep\(|time\.sleep\(|asyncio\.sleep\(|tokio::time::sleep\(|setTimeout\(|await new Promise\(r|\bdelay\(|time\.Sleep\(")
CLOCK = re.compile(r"\bInstant::now\(|SystemTime::now\(|\bDate\.now\(|new Date\(\)|\bLocalDate(Time)?\.now\(|System\.currentTimeMillis\(|datetime\.now\(|time\.time\(\)|time\.Now\(\)|Utc::now\(|Local::now\(")
RANDOM = re.compile(r"\brand::|thread_rng\(|Math\.random\(|new Random\(\)|random\.(random|randint|choice)\(|rand\.Int|faker|Faker\(|uuid::Uuid::new_v4|UUID\.randomUUID|crypto\.randomUUID")
NETWORK = re.compile(r"https?://(?!localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|example\.com|test\.local)[a-zA-Z0-9.-]+\.[a-z]{2,}|reqwest::(get|Client)|requests\.(get|post)\(|\bfetch\(\s*['\"]https?://(?!localhost|127)|HttpClient\.new|TcpStream::connect\(\s*\"(?!127|localhost)")
DOC_TEST = re.compile(r"^\s*///\s*```|>>> ")
SHARED_STATE = re.compile(r"\bstatic mut\b|lazy_static!|LazyLock|OnceLock|\bglobal\s+\w+|^\s*static\s+\w+.*=\s*new|std::env::set_var\(|os\.environ\[|process\.env\.\w+\s*=|System\.setProperty\(|set_current_dir\(|os\.chdir\(|process\.chdir\(")
FRAMEWORK = {
    "rust": re.compile(r"\b(tokio::test|rstest|proptest|quickcheck|insta|wiremock|mockall|assert_cmd|predicates|criterion|test_case|serial_test|tempfile|pretty_assertions)\b"),
    "java": re.compile(r"\b(org\.junit\.jupiter|org\.junit\.Test|org\.testng|org\.mockito|org\.assertj|org\.hamcrest|io\.kotest|spock\.lang|org\.testcontainers|com\.github\.tomakehurst\.wiremock|io\.rest-assured|org\.jqwik|net\.jqwik|org\.junit\.vintage)\b"),
    "csharp": re.compile(r"\b(Xunit|NUnit\.Framework|Microsoft\.VisualStudio\.TestTools|Moq|FluentAssertions|NSubstitute|FsCheck|Verify)\b"),
    "js": re.compile(r"\bfrom ['\"](vitest|jest|@jest/globals|mocha|chai|@playwright/test|cypress|@testing-library/\w+|sinon|nock|msw|fast-check|ava|tap|supertest|puppeteer)['\"]|require\(['\"](jest|mocha|chai|sinon|nock|tap|ava)['\"]\)"),
    "python": re.compile(r"^\s*(import|from)\s+(pytest|unittest|hypothesis|responses|respx|httpx|pytest_asyncio|freezegun|factory_boy|faker|testcontainers|playwright|selenium|nose|doctest)\b"),
    "go": re.compile(r"\"(testing|github\.com/stretchr/testify\S*|github\.com/onsi/ginkgo\S*|github\.com/onsi/gomega|github\.com/golang/mock\S*|go\.uber\.org/mock\S*|github\.com/google/go-cmp\S*|pgregory\.net/rapid)\""),
}
RUST_CFG_TEST = re.compile(r"#\[cfg\(test\)\]")
RUST_MOD_OPEN = re.compile(r"^\s*(pub(\([^)]*\))?\s+)?mod\s+\w+\s*\{")


def language_of(path: Path):
    for lang, exts in EXTS.items():
        if path.suffix in exts:
            return lang
    return None


def is_test_path(rel: Path) -> bool:
    return bool(TEST_FILE.search(rel.name)) or any(TEST_SEGMENT.match(p) for p in rel.parts[:-1])


def rust_inline_test_ranges(lines):
    """Return list of (start, end) line ranges of #[cfg(test)] mod blocks."""
    ranges, pending, skip_depth, depth, start = [], False, None, 0, 0
    for i, line in enumerate(lines, 1):
        if skip_depth is None:
            if RUST_CFG_TEST.search(line):
                pending = True
            elif pending and RUST_MOD_OPEN.search(line):
                skip_depth, start, pending = depth, i, False
            elif pending and line.strip() and not line.strip().startswith(("#[", "//")):
                pending = False
        depth += line.count("{") - line.count("}")
        if skip_depth is not None and depth <= skip_depth:
            ranges.append((start, i)); skip_depth = None
    return ranges


def loc(lines):
    return sum(1 for l in lines if l.strip() and not l.strip().startswith(("//", "#", "*", "/*")))


def crate_or_folder(rel: Path, lang: str) -> str:
    parts = rel.parts
    if lang == "rust":
        # nearest ancestor containing src/ -> crate folder
        if "src" in parts:
            i = parts.index("src")
            return "/".join(parts[:i]) or "."
    return parts[0] if len(parts) > 1 else "."


def scan(root: Path, excludes):
    hits = defaultdict(list)
    per_file = []
    frameworks = defaultdict(set)
    test_loc_by_folder = defaultdict(int)
    main_loc_by_folder = defaultdict(int)
    inline_loc_by_crate = defaultdict(int)
    totals = defaultdict(int)
    snapshot_files = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(p in SKIP_DIRS or p in excludes for p in rel.parts[:-1]):
            continue
        if path.suffix in SNAPSHOT_EXT or (len(rel.parts) > 1 and SNAPSHOT_DIR.match(rel.parts[-2]) and path.suffix in {".json", ".txt", ".html", ".svg", ".png", ".yaml", ".out"}):
            snapshot_files += 1
            continue
        lang = language_of(path)
        if not lang:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        relp = rel.as_posix()
        folder = rel.parts[0] if len(rel.parts) > 1 else "."
        is_test = is_test_path(rel)
        inline_ranges = rust_inline_test_ranges(lines) if (lang == "rust" and not is_test) else []
        in_inline = set()
        for a, b in inline_ranges:
            in_inline.update(range(a, b + 1))
        file_loc = loc(lines)
        if is_test:
            test_loc_by_folder[folder] += file_loc
            totals["test_files"] += 1
            totals["test_loc"] += file_loc
        else:
            inline = loc([lines[i - 1] for i in sorted(in_inline)]) if in_inline else 0
            main_loc_by_folder[folder] += file_loc - inline
            totals["main_loc"] += file_loc - inline
            if inline:
                inline_loc_by_crate[crate_or_folder(rel, lang)] += inline
                totals["inline_test_loc"] += inline
                totals["inline_test_files"] += 1
        # shapes are counted only inside test code (test files or inline test ranges)
        fn_rx = TEST_FN[lang]
        test_fns, asserts = 0, 0
        current_fn_line, fn_has_assert, weak = None, True, []
        for i, line in enumerate(lines, 1):
            in_test_code = is_test or i in in_inline
            if not in_test_code:
                if lang in ("rust", "python") and DOC_TEST.search(line):
                    totals["doc_tests"] += 1
                continue
            for m in FRAMEWORK[lang].finditer(line):
                groups = [g for g in m.groups() if g] if m.groups() else []
                frameworks[lang].add(groups[-1] if groups else m.group(0).strip('"\''))
            if fn_rx.search(line):
                if current_fn_line and not fn_has_assert:
                    weak.append(current_fn_line)
                current_fn_line, fn_has_assert = i, False
                test_fns += 1
            if ASSERT.search(line):
                asserts += 1; fn_has_assert = True
            for key, rx in (("mock_sites", MOCK), ("snapshot_assertions", SNAPSHOT_ASSERT), ("property_tests", PROPERTY),
                            ("fuzz_targets", FUZZ), ("skipped_tests", SKIP), ("flaky_markers", FLAKY), ("sleep_in_tests", SLEEP),
                            ("clock_in_tests", CLOCK), ("random_in_tests", RANDOM), ("network_in_tests", NETWORK),
                            ("shared_state_candidates", SHARED_STATE)):
                if rx.search(line):
                    hits[key].append((relp, i, line.strip()[:160]))
        if current_fn_line and not fn_has_assert:
            weak.append(current_fn_line)
        for l in weak:
            hits["weak_assertion_candidates"].append((relp, l, lines[l - 1].strip()[:160]))
        totals["test_functions"] += test_fns
        totals["assertions"] += asserts
        if is_test or in_inline:
            per_file.append({"file": relp, "lang": lang, "kind": "test-file" if is_test else "inline",
                             "loc": file_loc if is_test else loc([lines[i - 1] for i in sorted(in_inline)]),
                             "test_functions": test_fns, "assertions": asserts})
    totals["snapshot_files"] = snapshot_files
    return hits, per_file, frameworks, test_loc_by_folder, main_loc_by_folder, inline_loc_by_crate, totals


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
    hits, per_file, frameworks, tl, ml, inline, totals = scan(root, set(args.exclude))
    facts = {k: totals.get(k, 0) for k in ("test_files", "test_loc", "main_loc", "inline_test_files", "inline_test_loc",
                                            "test_functions", "assertions", "doc_tests", "snapshot_files")}
    for k in ("mock_sites", "snapshot_assertions", "property_tests", "fuzz_targets", "skipped_tests", "flaky_markers",
              "sleep_in_tests", "clock_in_tests", "random_in_tests", "network_in_tests"):
        facts[k] = len(hits.get(k, []))
    facts["assertion_density"] = round(facts["assertions"] / facts["test_functions"], 2) if facts["test_functions"] else 0
    total_test = facts["test_loc"] + facts["inline_test_loc"]
    facts["test_ratio"] = {"path_based": round(facts["test_loc"] / facts["main_loc"], 2) if facts["main_loc"] else 0,
                           "inline": round(facts["inline_test_loc"] / facts["main_loc"], 2) if facts["main_loc"] else 0,
                           "total": round(total_test / facts["main_loc"], 2) if facts["main_loc"] else 0}
    facts["frameworks"] = {l: sorted(v) for l, v in frameworks.items()}
    leads = {k: len(hits.get(k, [])) for k in ("weak_assertion_candidates", "shared_state_candidates")}
    folders = sorted(set(tl) | set(ml), key=lambda f: -(tl.get(f, 0) + ml.get(f, 0)))
    ratio_by_folder = {f: {"test_loc": tl.get(f, 0), "main_loc": ml.get(f, 0),
                           "ratio": round(tl.get(f, 0) / ml[f], 2) if ml.get(f) else None} for f in folders}

    print(f"Scanned {root}: {facts['test_files']} test files ({facts['test_loc']} LOC) + {facts['inline_test_files']} main files with inline tests "
          f"({facts['inline_test_loc']} LOC) against {facts['main_loc']} main LOC\n")
    print("stats (copy into findings stats):")
    for k, v in facts.items():
        print(f"  {k:26s} {v}")
    print("leads (read before citing; do NOT copy as stats):")
    for k, v in leads.items():
        print(f"  {k:26s} {v}")
    print("\ntest LOC by top-level folder (path-based):")
    for f in folders[: args.top]:
        r = ratio_by_folder[f]
        print(f"  {f:40s} test {r['test_loc']:7d}  main {r['main_loc']:7d}  ratio {r['ratio']}")
    if inline:
        print("\ninline test LOC by crate (Rust #[cfg(test)]):")
        for c, n in sorted(inline.items(), key=lambda kv: -kv[1])[: args.top]:
            print(f"  {n:7d}  {c}")
    print("\nlargest test files:")
    for r in sorted(per_file, key=lambda r: -r["loc"])[: args.top]:
        print(f"  {r['loc']:6d} LOC  {r['test_functions']:4d} fns  {r['assertions']:5d} asserts  {r['file']}")
    for key, rows in sorted(hits.items()):
        if not rows:
            continue
        pf = defaultdict(int)
        for f, _, _ in rows:
            pf[f] += 1
        print(f"\n{key} — top files:")
        for f, n in sorted(pf.items(), key=lambda kv: -kv[1])[: args.top]:
            print(f"  {n:5d}  {f}")
    if args.json:
        Path(args.json).write_text(json.dumps({
            "src_root": str(root),
            "count_rule": "test code = files under test/tests/spec/__tests__/e2e/fixtures dirs or *_test.*/*Test.*/test_*.py/*.spec.*/*.test.*, plus Rust #[cfg(test)] modules inside main files; LOC excludes blank and comment lines; shapes counted inside test code only",
            "stats": facts, "leads": leads, "ratio_by_folder": ratio_by_folder,
            "inline_test_loc_by_crate": dict(inline), "files": per_file,
            "hits": {k: [{"file": f, "line": l, "snippet": s} for f, l, s in v] for k, v in hits.items()},
        }, indent=2))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
