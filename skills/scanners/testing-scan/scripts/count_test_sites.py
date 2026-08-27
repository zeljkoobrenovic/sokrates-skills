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
    "java": re.compile(r"^\s*@(Test|ParameterizedTest|RepeatedTest|Property|TestFactory)\b|^\s*fun `"),
    "csharp": re.compile(r"^\s*\[(Fact|Theory|Test|TestMethod|TestCase)\b"),
    "js": re.compile(r"^\s*(it|test|it\.each|test\.each)\s*\(|^\s*(it|test)\.(only|skip|todo|concurrent)\s*\("),
    "python": re.compile(r"^\s*(async\s+)?def test_\w+\(|^\s*@given\(|^\s*@hypothesis"),
    "go": re.compile(r"^func (Test|Example|Fuzz|Benchmark)\w*\("),
}
ASSERT_COMMON = r"\bassert[A-Za-z_]*!?\s*[\(\[]|\bfail\s*\(|@Test\s*\(\s*expected|assertThrows|assertRaises|pytest\.raises|#\[should_panic|\bassertThat\b|\bverify\s*\(|\bassert_snapshot|\binsta::|\bexpect_that\b|\.should\b"
ASSERT = {
    "rust": re.compile(ASSERT_COMMON + r"|\bpretty_assertions|\bexpect_test::|\bassert_matches!"),
    "java": re.compile(ASSERT_COMMON + r"|\bassertj|\bMatcherAssert"),
    "csharp": re.compile(ASSERT_COMMON + r"|\bAssert\.|\.Should\(\)"),
    "js": re.compile(ASSERT_COMMON + r"|\bexpect\s*\(|\.toBe|\.toEqual|\.toMatch|\.toThrow|\.toHaveBeen|\.rejects\.|expectThrows|\bassert\.\w+\("),
    "python": re.compile(ASSERT_COMMON + r"|^\s*assert\b|self\.assert\w*\(|\bassert_that\("),
    "go": re.compile(ASSERT_COMMON + r"|\bt\.(Error|Fatal|Errorf|Fatalf)\(|\bif .* != .* \{\s*t\.|require\.\w+\(|assert\.\w+\("),
}
MOCK = re.compile(r"\bmock(ito|k|all)?\b|Mockito\.|@Mock\b|\bMock<|\bmock!\(|\bautomock\b|\bunittest\.mock|\bmonkeypatch|\bjest\.(fn|mock|spyOn)\(|\bsinon\.|\bvi\.(fn|mock|spyOn)\(|\bwiremock|\bMockServer|\bhttpmock|\bmockito::|\bnock\(|\bresponses\.(add|activate)|\bFake\w+\(|\bStub\w+\(|\bspy\(")
SNAPSHOT_ASSERT = re.compile(r"assert_snapshot!|assert_debug_snapshot!|insta::|toMatchSnapshot\(|toMatchInlineSnapshot\(|expect_file!|\.approved|Approvals\.verify|assertSnapshot|snapshot\.assert|assertGolden|readGolden|golden\(|expectedFile|\.expected\b")
PROPERTY = re.compile(r"proptest!|#\[proptest|quickcheck|@given\(|hypothesis|fast-check|fc\.assert|jqwik|@Property\b|testing/quick|rapid\.Check")
FUZZ = re.compile(r"fuzz_target!|cargo-fuzz|libfuzzer|^func Fuzz\w+\(|@FuzzTest|atheris")
SKIP = re.compile(r"#\[ignore\b|\bskip_if_\w+!\(|\bskip_unless_\w+!\(|@Ignore\b|@Disabled\b|assumeTrue\(|assumeFalse\(|Assume\.|Assumptions\.|@EnabledIf|@DisabledIf|@EnabledOnOs|@pytest\.mark\.skip|@unittest\.skip|pytest\.skip\(|\b(it|test|describe)\.skip\(|\bxit\(|\bxtest\(|\bxdescribe\(|@pytest\.mark\.xfail|t\.Skip\(|\[Ignore\b|\.todo\(|SKIP:|TODO: enable|#\[cfg_attr\([^)]*ignore")
FLAKY = re.compile(r"\bflaky\b|\bflakey\b|@pytest\.mark\.flaky|@RetryingTest|@Retry\b|jest\.retryTimes|test\.retry\(|nondeterministic|intermittent|#\[ignore = \"[^\"]*(flak|timing|race)", re.I)
SLEEP = re.compile(r"\bsleep\(|\bthread::sleep|Thread\.sleep\(|time\.sleep\(|asyncio\.sleep\(|tokio::time::sleep\(|setTimeout\(|await new Promise\(r|\bdelay\(|time\.Sleep\(")
CLOCK = re.compile(r"\bInstant::now\(|SystemTime::now\(|\bDate\.now\(|new Date\(\)|\bLocalDate(Time)?\.now\(|System\.currentTimeMillis\(|datetime\.now\(|time\.time\(\)|time\.Now\(\)|Utc::now\(|Local::now\(")
RANDOM = re.compile(r"\brand::|thread_rng\(|Math\.random\(|new Random\(\)|random\.(random|randint|choice)\(|rand\.Int|faker|Faker\(|uuid::Uuid::new_v4|UUID\.randomUUID|crypto\.randomUUID")
NETWORK = re.compile(r"reqwest::(get|Client)|requests\.(get|post)\(|\bfetch\(\s*['\"]https?://(?!localhost|127)|HttpClient\.new|HttpURLConnection|\.openConnection\(\)|new URL\([^)]*https?://(?!localhost|127)|TcpStream::connect\(\s*\"(?!127|localhost)|urllib\.request\.urlopen|httpx\.(get|Client)|axios\.(get|post)\(\s*['\"]https?://(?!localhost|127)")
URL_LITERAL = re.compile(r"https?://(?!localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|example\.com|test\.local|www\.w3\.org)[a-zA-Z0-9.-]+\.[a-z]{2,}")
DOC_TEST = re.compile(r"^\s*///\s*```|>>> ")
TIER = re.compile(r"@Tag\(|@Category\(|#\[ignore = \"slow|@pytest\.mark\.(slow|integration|e2e)|describe\.(slow|integration)|\[Trait\(|\[Category\(")
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
        folder = next((p for p in rel.parts[:-1] if p not in ("src", "lib", "main", "test", "tests", "java", "kotlin", "python", "app")), ".")
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
            if ASSERT[lang].search(line):
                asserts += 1; fn_has_assert = True
            for key, rx in (("mock_sites", MOCK), ("snapshot_assertions", SNAPSHOT_ASSERT), ("property_tests", PROPERTY),
                            ("fuzz_targets", FUZZ), ("skipped_tests", SKIP), ("flaky_markers", FLAKY), ("sleep_in_tests", SLEEP),
                            ("clock_in_tests", CLOCK), ("random_in_tests", RANDOM), ("network_in_tests", NETWORK),
                            ("url_literal_candidates", URL_LITERAL), ("tier_markers", TIER), ("shared_state_candidates", SHARED_STATE)):
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
    ap.add_argument("--components-dir", help="unzipped Sokrates data dir: maps every test file and inline test module to the component whose main-file directories it lives under (text/aspect_component_<decomposition>_*.txt) and prints test/main LOC per component")
    ap.add_argument("--decomposition", default="primary", help="which logical decomposition's aspect files to use (default: primary)")
    ap.add_argument("--refs-file", help="text file with one main-source path per line (e.g. hotspot files from risk-synthesis evidence, or an aspect_component_*.txt); emits how many test files/inline test modules reference each file's type/module name")
    args = ap.parse_args(argv)
    root = Path(args.src_root).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2
    hits, per_file, frameworks, tl, ml, inline, totals = scan(root, set(args.exclude))
    facts = {k: totals.get(k, 0) for k in ("test_files", "test_loc", "main_loc", "inline_test_files", "inline_test_loc",
                                            "test_functions", "assertions", "doc_tests", "snapshot_files")}
    for k in ("mock_sites", "snapshot_assertions", "property_tests", "fuzz_targets", "skipped_tests", "flaky_markers",
              "sleep_in_tests", "clock_in_tests", "random_in_tests", "network_in_tests", "tier_markers"):
        facts[k] = len(hits.get(k, []))
    facts["assertion_density"] = round(facts["assertions"] / facts["test_functions"], 2) if facts["test_functions"] else 0
    total_test = facts["test_loc"] + facts["inline_test_loc"]
    facts["test_ratio"] = {"path_based": round(facts["test_loc"] / facts["main_loc"], 2) if facts["main_loc"] else 0,
                           "inline": round(facts["inline_test_loc"] / facts["main_loc"], 2) if facts["main_loc"] else 0,
                           "total": round(total_test / facts["main_loc"], 2) if facts["main_loc"] else 0}
    facts["frameworks"] = {l: sorted(v) for l, v in frameworks.items()}
    leads = {k: len(hits.get(k, [])) for k in ("weak_assertion_candidates", "shared_state_candidates", "url_literal_candidates")}
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
    print("\nlargest test files (with test functions; fixture/helper files without tests are listed in the JSON):")
    for r in sorted([r for r in per_file if r["test_functions"] > 0], key=lambda r: -r["loc"])[: args.top]:
        print(f"  {r['loc']:6d} LOC  {r['test_functions']:4d} fns  {r['assertions']:5d} asserts  [{r['kind']}]  {r['file']}")
    doctest_off = sum(1 for c in root.rglob("Cargo.toml") if not any(d in c.parts for d in SKIP_DIRS) and re.search(r"doctest\s*=\s*false", c.read_text(errors="replace")))
    if doctest_off:
        facts["crates_with_doctest_disabled"] = doctest_off
        print(f"\n{doctest_off} Cargo.toml files set doctest = false — doc_tests above are fenced examples, not executed tests")
    for key, rows in sorted(hits.items()):
        if not rows:
            continue
        pf = defaultdict(int)
        for f, _, _ in rows:
            pf[f] += 1
        print(f"\n{key} — top files:")
        for f, n in sorted(pf.items(), key=lambda kv: -kv[1])[: args.top]:
            print(f"  {n:5d}  {f}")
    by_component = {}
    if args.components_dir:
        comp_dirs, comp_main_loc, comp_files = {}, {}, {}
        for f in sorted(Path(args.components_dir).glob(f"text/aspect_component_{args.decomposition}_*.txt")):
            name = f.stem[len(f"aspect_component_{args.decomposition}_"):]
            files, total = [], 0
            for line in f.read_text(errors="replace").splitlines()[1:]:
                parts = line.split("\t")
                if not parts[0].strip():
                    continue
                files.append(parts[0].strip())
                try:
                    total += int(parts[1])
                except (IndexError, ValueError):
                    pass
            comp_files[name] = set(files)
            comp_main_loc[name] = total
            comp_dirs[name] = {str(Path(x).parent) for x in files}
        def component_of(path):
            if any(path in fs for fs in comp_files.values()):
                return next(n for n, fs in comp_files.items() if path in fs)
            parts = Path(path).parent.parts
            best, best_len = None, -1
            for name, dirs in comp_dirs.items():
                for k in range(len(parts), 0, -1):
                    if "/".join(parts[:k]) in dirs and k > best_len:
                        best, best_len = name, k
                        break
            return best or "(unmapped)"
        for r in per_file:
            c = component_of(r["file"])
            e = by_component.setdefault(c, {"main_loc": comp_main_loc.get(c, 0), "test_loc": 0, "inline_test_loc": 0, "test_functions": 0, "test_files": 0})
            e["test_loc" if r["kind"] == "test-file" else "inline_test_loc"] += r["loc"]
            e["test_functions"] += r["test_functions"]
            e["test_files"] += 1
        for c, e in by_component.items():
            e["ratio_path_based"] = round(e["test_loc"] / e["main_loc"], 2) if e["main_loc"] else None
            e["ratio_total"] = round((e["test_loc"] + e["inline_test_loc"]) / e["main_loc"], 2) if e["main_loc"] else None
        print(f"\ntest LOC by Sokrates component ({args.decomposition}; main LOC from the aspect lists, test files mapped by directory):")
        for c, e in sorted(by_component.items(), key=lambda kv: -(kv[1]["main_loc"] or 0)):
            print(f"  {c:40s} main {e['main_loc']:7d}  test {e['test_loc']:7d}  inline {e['inline_test_loc']:6d}  fns {e['test_functions']:5d}  ratio {e['ratio_total']}")
    refs = {}
    if args.refs_file:
        targets = [l.split("\t")[0].strip() for l in Path(args.refs_file).read_text().splitlines() if l.strip() and not l.lower().startswith("path")]
        test_texts = []
        for r in per_file:
            try:
                test_texts.append((r["file"], (root / r["file"]).read_text(encoding="utf-8", errors="replace")))
            except OSError:
                pass
        print("\ntest references per main file (test files or inline modules mentioning the type/module name):")
        for t in targets:
            stem = Path(t).stem
            if stem in ("mod", "lib", "main", "index", "__init__"):
                stem = Path(t).parent.name
            rx = re.compile(r"\b" + re.escape(stem) + r"\b")
            hits_for = [f for f, txt in test_texts if f != t and rx.search(txt)]
            refs[t] = {"name": stem, "test_files_referencing": len(hits_for), "examples": hits_for[:3]}
            print(f"  {len(hits_for):4d}  {t}")
    if args.json:
        Path(args.json).write_text(json.dumps({
            "test_references": refs, "by_component": by_component,
            "src_root": str(root),
            "count_rule": "test code = files under test/tests/spec/__tests__/e2e/fixtures dirs or *_test.*/*Test.*/test_*.py/*.spec.*/*.test.*"
                          + ("; plus Rust #[cfg(test)] modules inside main files" if inline else "")
                          + "; LOC excludes blank and comment lines; shapes counted inside test code only; test functions = annotated/declared test cases",
            "stats": facts, "leads": leads, "ratio_by_folder": ratio_by_folder,
            "inline_test_loc_by_crate": dict(inline), "files": per_file,
            "hits": {k: [{"file": f, "line": l, "snippet": s} for f, l, s in v] for k, v in hits.items()},
        }, indent=2))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
