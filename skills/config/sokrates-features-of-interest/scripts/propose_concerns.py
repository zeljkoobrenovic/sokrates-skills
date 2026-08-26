#!/usr/bin/env python3
"""Propose features of interest (Sokrates concerns) for a repository analysis.

Reads `_sokrates/config.json` (srcRoot, extensions, ignore and scope rules, size limits) and scans the
main files for candidate cross-cutting concerns, each defined by Sokrates-style regexes:

  catalog      technical-debt markers, deprecations, feature flags, security-sensitive code, unsafe /
               dynamic execution, swallowed errors, concurrency, persistence, network calls, telemetry,
               configuration & environment access, platform-specific code, generated markers, …
  libraries    repository-specific candidates: the most imported external libraries/crates/packages,
               each as an "integration" concern (files that touch it)
  existing     what the config's current concerns match today

For every candidate: files matched, LOC of those files, number of matching lines, sample file:line
hits, and a ready `concern` object (path/content filters with Sokrates semantics: contentPattern must
match an ENTIRE line, hence the `.*…*` wrapping; pathPattern matches the entire path incl. srcRoot).

Usage:
  python3 propose_concerns.py <path/to/_sokrates/config.json> [-o proposals.json] [--min-files 3]
                              [--max-files 200000] [--samples 4]
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SKIP_DIRS = {".git", ".hg", ".svn", "_sokrates", "_sokrates_landscape"}

# (group, concern name, content regex (Python; Sokrates-compatible), path regex or None, description)
CATALOG = [
    ("technical debt", "TODOs and FIXMEs", r".*\b(TODO|FIXME|XXX|HACK)\b.*", None, "explicit markers of unfinished or hacky code"),
    ("technical debt", "deprecated code", r".*(@[Dd]eprecated|#\[deprecated|\bDEPRECATED\b|@deprecated|\[Obsolete).*", None, "APIs marked deprecated/obsolete — migration debt"),
    ("technical debt", "suppressed warnings", r".*(#\[allow\(|@SuppressWarnings|# noqa|// eslint-disable|# type: ignore|#pragma warning disable|// nolint).*", None, "places where linters/compilers are silenced"),
    ("technical debt", "feature flags", r".*(feature[_ -]?flag|isFeatureEnabled|is_feature_enabled|FeatureToggle|LaunchDarkly|unleash|flagsmith|\bflags?\.(is_enabled|enabled)|features\.enabled\(|\.is_enabled\(|\bFeature::[A-Z]\w+|cfg!\(feature).*", None, "runtime or compile-time feature toggles"),
    ("security", "secrets and credentials", r".*\b(password|passwd|secret|api[_-]?key|access[_-]?token|private[_-]?key|credential)s?\b.*", None, "code handling passwords, keys, tokens"),
    ("security", "cryptography", r".*\b(aes|rsa|hmac|bcrypt|argon2|pbkdf2|encrypt|decrypt|cipher|x509|rustls|openssl|boringssl|ring::|Sha256::|Md5::|hashlib|MessageDigest|crypto\.(subtle|createHash))\b.*", None, "crypto primitives and TLS implementation (hash strings in lockfiles excluded)"),
    ("security", "authentication", r".*\b(authenticat\w*|oauth\w*|jwt|login|logout|refresh_token|id_token|session[_ ]?token|api_key_auth|bearer)\b.*", None, "identity: login, tokens, OAuth"),
    ("security", "authorization and policy", r".*\b(authoriz\w*|permission[s_]?\w*|is_admin|require_auth|policy_check|\w*Policy\b|ReviewDecision|AskForApproval|approval[_ ]?(mode|policy|request))\b.*", None, "permission and approval decisions"),
    ("security", "sandboxing and privilege", r".*\b(sandbox\w*|seatbelt|landlock|seccomp|bwrap|chroot|setuid|setgid|privilege\w*|apparmor|restricted[_ ]token|job[_ ]object)\b.*", None, "isolation and privilege boundaries"),
    ("security", "unsafe and dynamic execution", r".*(\bunsafe\s*\{|\beval\(|\bexec\(|Runtime\.getRuntime\(\)\.exec|subprocess\.(run|Popen|call)|std::process::Command|child_process|os\.system\(|ProcessBuilder).*", None, "unsafe blocks, eval/exec, process spawning"),
    ("security", "input validation", r".*\b(sanitize\w*\(|validate_(input|path|url|args|request)\w*\(|escape_html\(|canonicalize\(|path_traversal|normalize_path\()\b.*", None, "validation, sanitisation, canonicalisation (call sites, not every validate_* method)"),
    ("robustness", "swallowed errors", r".*(catch\s*\([^)]*\)\s*\{\s*\}|except\s*:\s*pass|except\s+Exception\s*:\s*pass|^\s*let _ = .*;|\.ok\(\);|\.catch\(\(\) => \{\}\)).*", None, "empty catch blocks, discarded results"),
    ("robustness", "panics and hard exits", r".*(\bpanic!\(|\.unwrap\(\)|System\.exit\(|sys\.exit\(|process\.exit\(|\bunreachable!\(|\btodo!\(|\bunimplemented!\().*", None, "explicit crash/exit points (`.expect(` with its justification is left out)"),
    ("robustness", "retries and timeouts", r".*\b(with_retry|retry\(|retry_with|backoff|Backoff|circuit_breaker|CircuitBreaker|timeout\(|with_timeout|deadline\()\b.*", None, "resilience mechanisms (call sites, not every variable named retry_count)"),
    ("robustness", "concurrency", r".*\b(Mutex|RwLock|Semaphore|AtomicU|AtomicBool|synchronized|threading\.|std::thread|tokio::spawn|go func|ConcurrentHashMap|Arc<|volatile)\b.*", None, "locks, atomics, spawned threads/tasks"),
    ("data", "persistence and SQL", r".*\b(SELECT|INSERT INTO|UPDATE .* SET|DELETE FROM|CREATE TABLE|sqlx|rusqlite|jdbc|hibernate|sqlalchemy|prisma|mongoose|redis)\b.*", None, "database access and SQL"),
    ("data", "serialization", r".*\b(serde|Serialize|Deserialize|ObjectMapper|json\.(loads|dumps)|JSON\.(parse|stringify)|protobuf|prost::|Gson|pickle)\b.*", None, "wire formats and (de)serialisation"),
    ("data", "file system access", r".*\b(std::fs|fs::|File::(open|create)|open\(.*['\"][rwa]|FileReader|FileWriter|os\.path|pathlib|readFile|writeFile|shutil)\b.*", None, "direct file I/O"),
    ("integration", "network and HTTP", r".*\b(reqwest|hyper::|http::|HttpClient|fetch\(|axios|urllib|requests\.(get|post)|TcpStream|WebSocket|socket\()\b.*", None, "outbound/inbound network code"),
    ("integration", "external services and APIs", r".*\b(api\.openai\.com|api\.anthropic\.com|boto3|aws_sdk|google\.cloud|googleapis\.com|azure\.com|stripe\.com|twilio|sendgrid|api\.github\.com|hooks\.slack\.com)\b.*", None, "third-party service endpoints and SDKs (first-party names such as a crate called openai are not counted)"),
    ("integration", "process and shell", r".*\b(std::process|subprocess|child_process|ProcessBuilder|Runtime\.exec|os\.system|sh -c|bash -c)\b.*", None, "spawning external processes"),
    ("observability", "logging", r".*\b(log::(info|warn|error|debug|trace)|tracing::(info|warn|error|debug)|logger\.|logging\.(info|warning|error)|console\.(log|error|warn)|println!|eprintln!|System\.out\.println|slf4j|log4j)\b.*", None, "log emission"),
    ("observability", "metrics and tracing", r".*\b(metrics::|counter!|histogram!|gauge!|prometheus|opentelemetry|otel|tracing::instrument|#\[instrument|statsd|datadog|sentry)\b.*", None, "telemetry emission"),
    ("configuration", "environment and configuration access", r".*\b(std::env::var|env::var|os\.environ|getenv|process\.env|System\.getenv|dotenv|config\.toml|settings\.yaml)\b.*", None, "reads of environment variables and config files"),
    ("configuration", "platform-specific code", r".*(#\[cfg\((target_os|windows|unix)|cfg!\(target_os|os\.name ==|platform\.system\(\)|process\.platform|sys\.platform|#if(def)? _WIN32|runtime\.GOOS).*", None, "OS-conditional branches"),
    ("lifecycle", "generated code markers", r".*(GENERATED CODE|DO NOT EDIT|auto-generated|autogenerated|@generated|Code generated by).*", None, "generated files that slipped into main"),
    ("lifecycle", "experimental and unstable", r".*\b(experimental|unstable|work in progress|wip)\b.*", None, "self-declared unfinished areas (preview/beta/alpha dropped: version strings)"),
    ("lifecycle", "compatibility shims", r".*\b(legacy|backward[s]? compat|compat(ibility)?[_ ]?shim|polyfill|fallback for|migration from)\b.*", None, "code kept for older versions"),
    ("testing in main", "test code inside main scope", r".*(#\[test\]|#\[cfg\(test\)\]|@Test\b|^\s*def test_|^\s*(it|test|describe)\(['\"]).*", None, "tests living in main files — a scope gap for separate test files, but idiomatic inline test modules in Rust (#[cfg(test)]) and Go: usually not a concern"),
]

IMPORT_RES = [  # (extension set, regex with one group = library root name)
    ({"rs"}, re.compile(r"^\s*use\s+([a-z_][a-z0-9_]*)(::|;)")),
    ({"py"}, re.compile(r"^\s*(?:from\s+([a-zA-Z_][\w]*)|import\s+([a-zA-Z_][\w]*))")),
    ({"ts", "tsx", "js", "jsx", "mjs", "cjs"}, re.compile(r"^\s*import\b.*?from\s+['\"](@?[^'\"/]+)")),
    ({"java", "kt", "kts", "scala"}, re.compile(r"^\s*import\s+(?:static\s+)?([a-zA-Z_][\w]*\.[a-zA-Z_][\w]*)")),
    ({"go"}, re.compile(r"^\s*\"([^\"/]+(?:/[^\"/]+)?)")),
    ({"cs"}, re.compile(r"^\s*using\s+([A-Z][\w]*(?:\.[A-Z][\w]*)?)")),
]
STDLIB_HINT = {"std", "core", "alloc", "crate", "super", "self", "os", "sys", "re", "json", "typing", "pathlib", "collections", "itertools",
               "functools", "datetime", "time", "math", "subprocess", "logging", "java.util", "java.io", "java.lang", "java.nio", "java.time",
               "fmt", "os", "io", "strings", "errors", "context", "System", "System.Collections", "System.IO", "System.Linq", "React", "react"}


class Rule:
    def __init__(self, raw):
        self.path_pattern = raw.get("pathPattern", "") or ""
        self.has_content = bool((raw.get("contentPattern", "") or "").strip())
        self.exception = bool(raw.get("exception", False))
        try:
            self.path_re = re.compile(self.path_pattern) if self.path_pattern.strip() else None
        except re.error:
            self.path_re = re.compile(r"(?!x)x")

    def path_matches(self, full):
        if self.has_content:
            return False
        return self.path_re is None or bool(self.path_re.fullmatch(full))


def resolve_src_root(config_path: Path, src_root: str) -> Path:
    cand = config_path.parent.parent / src_root[2:].lstrip("/\\") if src_root.startswith("..") else config_path.parent / src_root
    return cand if cand.exists() else Path(src_root)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("-o", "--output")
    ap.add_argument("--min-files", type=int, default=3, help="drop candidates matching fewer files")
    ap.add_argument("--max-files", type=int, default=200000)
    ap.add_argument("--samples", type=int, default=4)
    args = ap.parse_args()

    config_path = Path(args.config)
    try:
        config = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr); return 2
    src_root = resolve_src_root(config_path, config.get("srcRoot", ".."))
    if not src_root.is_dir():
        print(f"error: srcRoot {src_root} not found", file=sys.stderr); return 2
    src_root_str = str(src_root)
    extensions = {e.lower() for e in config.get("extensions") or []}
    ignore = [Rule(r) for r in config.get("ignore") or []]
    non_main = [Rule(r) for s in ("test", "generated", "buildAndDeployment", "other") for r in (config.get(s) or {}).get("sourceFileFilters") or []]
    analysis = config.get("analysis") or {}
    max_bytes = int(analysis.get("maxFileSizeBytes", 1000000)); max_lines = int(analysis.get("maxLines", 10000)); max_line_len = int(analysis.get("maxLineLength", 1000))
    warnings = []

    # ---- collect main files with their lines
    files = {}
    total = 0
    for root, dirs, fns in os.walk(src_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in fns:
            total += 1
            if total > args.max_files:
                break
            rel = os.path.relpath(os.path.join(root, fn), src_root).replace(os.sep, "/")
            ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
            if ext not in extensions:
                continue
            full = os.path.join(src_root_str, rel)
            if any(r.path_matches(full) for r in ignore):
                continue
            inc = any(r.path_matches(full) and not r.exception for r in non_main)
            exc = any(r.path_matches(full) and r.exception for r in non_main)
            if inc and not exc:
                continue
            try:
                if os.path.getsize(full) > max_bytes:
                    continue
                text = Path(full).read_text(errors="replace")
            except OSError:
                continue
            lines = text.split("\n")
            if len(lines) > max_lines or any(len(ln) > max_line_len for ln in lines):
                continue
            files[rel] = lines
    if (src_root / "_sokrates").is_dir() and not any("_sokrates" in (r.path_pattern or "") for r in ignore):
        warnings.append("`.*/_sokrates/.*` is missing from ignore — Sokrates will count its own output as main (this script skips the folder)")
    loc = {rel: sum(1 for ln in lines if ln.strip()) for rel, lines in files.items()}
    total_loc = sum(loc.values()) or 1

    TEST_REGION_START = re.compile(r"^\s*#\[cfg\(test\)\]")   # Rust inline test modules: everything after this marker
    test_region_start = {}
    for rel, lines in files.items():
        if rel.endswith(".rs"):
            for i, ln in enumerate(lines):
                if TEST_REGION_START.match(ln):
                    test_region_start[rel] = i
                    break

    def evaluate(name, content_re, path_re):
        """Returns hit files, hit lines, samples, hits inside test regions, matched-token counter."""
        hit_files, hit_lines, hits_in_tests = set(), 0, 0
        tokens = Counter()
        first_hit = {}
        for rel, lines in files.items():
            if path_re is not None and not path_re.fullmatch(os.path.join(src_root_str, rel)):
                continue
            tstart = test_region_start.get(rel, 10**9)
            for i, ln in enumerate(lines, 1):
                m = content_re.fullmatch(ln)
                if m:
                    hit_lines += 1
                    if i - 1 >= tstart:
                        hits_in_tests += 1
                    tok = next((g for g in m.groups() if g), None) if m.groups() else None
                    tokens[(tok or ln.strip())[:60]] += 1
                    if rel not in hit_files:
                        hit_files.add(rel)
                        first_hit[rel] = f"{rel}:{i}: {ln.strip()[:110]}"
        ordered = sorted(first_hit)
        step = max(1, len(ordered) // max(1, args.samples))
        samples = [first_hit[r] for r in ordered[::step][:args.samples]]   # stratified over the sorted tree, not the first N
        return hit_files, hit_lines, samples, hits_in_tests, tokens

    # ---- catalog
    proposals = []
    for group, name, content, path, desc in CATALOG:
        try:
            content_re = re.compile(content)
            path_re = re.compile(path) if path else None
        except re.error as e:
            warnings.append(f"catalog pattern for `{name}` failed to compile: {e}"); continue
        hit_files, hit_lines, samples, hits_in_tests, tokens = evaluate(name, content_re, path_re)
        if len(hit_files) < args.min_files:
            continue
        files_loc = sum(loc[f] for f in hit_files)
        by_top = Counter("/".join(f.split("/")[:2]) if f.count("/") >= 2 else (f.split("/")[0] if "/" in f else "(root)") for f in hit_files)
        proposals.append({
            "kind": "catalog", "group": group, "name": name, "description": desc,
            "files": len(hit_files), "files_pct": round(100 * len(hit_files) / max(1, len(files)), 1),
            "loc_of_files": files_loc, "loc_pct": round(100 * files_loc / total_loc, 1), "matching_lines": hit_lines,
            "spread_depth2_folders": by_top.most_common(6), "samples": samples,
            "hits_in_test_regions_pct": round(100 * hits_in_tests / max(1, hit_lines), 1),
            "top_matched_tokens": tokens.most_common(8),
            "config": {"name": name, "sourceFileFilters": [{"pathPattern": path or "", "contentPattern": content, "exception": False, "note": desc}], "files": [], "textOperations": []},
        })

    # ---- libraries (repository-specific integration concerns)
    lib_files = defaultdict(set)
    lib_lines = Counter()
    for rel, lines in files.items():
        ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
        for exts, rx_ in IMPORT_RES:
            if ext in exts:
                limit = min(400, test_region_start.get(rel, 400)) if ext == "rs" else 400
                for ln in lines[:limit]:
                    m = rx_.match(ln)
                    if m:
                        lib = next((g for g in m.groups() if g), None)
                        if lib and lib not in STDLIB_HINT and not lib.startswith((".", "/")):
                            lib_files[lib].add(rel); lib_lines[lib] += 1
                break
    # drop first-party: a library whose name matches a top-level folder or a workspace crate name is internal
    top_names = {p.split("/")[0].lower().replace("-", "_") for p in files} | {p.split("/")[1].lower().replace("-", "_") for p in files if p.count("/") >= 2}
    lib_rows = []
    for lib, fs in sorted(lib_files.items(), key=lambda kv: -len(kv[1])):
        internal = lib.lower().replace("-", "_") in top_names or lib.lower().startswith(("codex", "crate"))
        if internal or len(fs) < max(args.min_files, 5):
            continue
        lib_rows.append({"library": lib, "files": len(fs), "files_pct": round(100 * len(fs) / max(1, len(files)), 1),
                         "import_lines": lib_lines[lib], "samples": sorted(fs)[:args.samples]})
    lib_rows = lib_rows[:25]
    lib_concerns = []
    for r in lib_rows[:12]:
        lib = r["library"]
        esc = re.escape(lib)
        lib_concerns.append({"name": f"uses {lib}", "sourceFileFilters": [{"pathPattern": "", "contentPattern": f".*\\b{esc}\\b.*", "exception": False, "note": f"files referencing {lib}"}], "files": [], "textOperations": []})

    # ---- existing concerns
    existing = []
    for grp in config.get("concernGroups") or config.get("concerns") or []:
        for c in grp.get("concerns") or []:
            hit = set()
            for f in c.get("sourceFileFilters") or []:
                try:
                    cre = re.compile(f.get("contentPattern") or "") if (f.get("contentPattern") or "").strip() else None
                    pre = re.compile(f.get("pathPattern") or "") if (f.get("pathPattern") or "").strip() else None
                except re.error as e:
                    warnings.append(f"existing concern `{c.get('name')}` has a regex that does not compile ({e}) — Sokrates silently matches nothing"); continue
                if cre is None and pre is None:
                    continue
                hf, _, _, _, _ = evaluate(c.get("name"), cre or re.compile(".*"), pre)
                hit |= hf
            existing.append({"group": grp.get("name"), "name": c.get("name"), "files": len(hit), "loc_pct": round(100 * sum(loc[f] for f in hit) / total_loc, 1)})
            if "(TODO|FIXME)" in json.dumps(c.get("sourceFileFilters") or []):
                broad = next((p for p in proposals if p["name"] == "TODOs and FIXMEs"), None)
                if broad and broad["files"] > len(hit):
                    warnings.append(f"existing concern `{c.get('name')}` matches {len(hit)} files but a word-boundary pattern matches {broad['files']} — this codebase writes TODO(name)-style markers; replace the pattern with `.*\\b(TODO|FIXME|XXX|HACK)\\b.*`")

    # ---- assemble suggested config
    groups = defaultdict(list)
    for p in proposals:
        groups[p["group"]].append(p["config"])
    suggested = [{"name": g, "concerns": cs, "metaConcerns": []} for g, cs in groups.items()]
    if lib_concerns:
        suggested.append({"name": "integration libraries", "concerns": lib_concerns, "metaConcerns": []})

    out = {"config": str(config_path), "srcRoot": src_root_str, "main_files": len(files), "main_loc": total_loc,
           "existing_concerns": existing, "catalog": proposals, "libraries": lib_rows,
           "suggested_concernGroups": suggested, "warnings": warnings,
           "notes": ["contentPattern must match a whole line — keep the `.*…*` wrapping", "concerns are evaluated against main files only",
                     "a concern touching > 60% of files is not a feature of interest but a property of the codebase — narrow it or drop it"]}
    if args.output:
        Path(args.output).write_text(json.dumps(out, indent=2))

    print(f"Features-of-interest proposals — {config_path}  ({len(files)} main files, {total_loc} LOC; % LOC = LOC of matched files / main LOC)")
    if existing:
        print("existing concerns: " + ", ".join(f"{e['group']}/{e['name']} ({e['files']} files, {e['loc_pct']}% LOC)" for e in existing))
    print("\nCandidates (files matched, % of main files, matching lines):")
    for p in sorted(proposals, key=lambda p: (-p["files"])):
        flag = "  ← too broad?" if p["files_pct"] > 60 else ""
        tests = f"  (tests {p['hits_in_test_regions_pct']}%)" if p["hits_in_test_regions_pct"] >= 25 else ""
        print(f"  {p['group']:<16} {p['name']:<38} {p['files']:>6} files {p['files_pct']:>5}% {p['matching_lines']:>7} lines{tests}{flag}")
        print(f"      tokens: " + ", ".join(f"{t} ({n})" for t, n in p["top_matched_tokens"][:5]))
        for smp in p["samples"][:2]:
            print(f"      {smp}")
    if lib_rows:
        print("\nMost used external libraries (candidate integration concerns): " + ", ".join(f"{r['library']} ({r['files']})" for r in lib_rows[:15]))
    for w in warnings:
        print(f"WARNING: {w}")
    if args.output:
        print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
