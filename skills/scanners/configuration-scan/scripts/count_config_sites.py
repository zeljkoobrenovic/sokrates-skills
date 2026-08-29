#!/usr/bin/env python3
"""Count configuration-system shapes for the configuration scanner.

Deterministic, standard-library only. Test code is excluded by path (test/tests/spec/mock/fixture
segments, *_test.*, *Test.java, test_*.py) and, for Rust, inside `#[cfg(test)]` modules.

Beyond counts it extracts two surfaces the scanner needs by name: `env_var_names` (every
environment variable the code reads, with where) and `flag_names` (CLI options declared). Those
lists are the raw material for the settings inventory — they are *leads*: drop the ones that are
environment queries rather than configuration (`HOME`, `PATH`, `CI`) and say so in `count_notes`.

Facts are copied into `stats`; leads (`*_candidates`, `*_keyword_files`, the name lists) are
reading lists, never stats.

Usage:
  python3 count_config_sites.py <src-root> [--json out.json] [--top 12] [--exclude DIR ...]
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
    "ruby": {".rb"}, "php": {".php"}, "shell": {".sh", ".bash", ".zsh"},
}
SKIP_DIRS = {"node_modules", "target", "build", "dist", "out", ".git", "vendor", "venv", ".venv",
             "__pycache__", "_sokrates", "_sokrates_landscape", "site-packages"}
TEST_SEGMENT = re.compile(r"(^|[._-])(tests?|spec|specs|mocks?|fixtures?|testdata|test[-_]support)([._-]|$)", re.I)
TEST_FILE = re.compile(r"(_tests?\.\w+$|Tests?\.java$|\.spec\.\w+$|\.test\.\w+$|^test_.*\.\w+$|^tests?\.rs$|"
                       r"^conftest\.py$|^.*_test_(server|client|helper|support)\.\w+$|^mock_.*\.\w+$)", re.I)
COMMENT = re.compile(r"^\s*(//|/\*|\*|#(?!\[)|<!--|--\s)")
RUST_CFG_TEST = re.compile(r"#\[cfg\(test\)\]")
RUST_MOD_OPEN = re.compile(r"^\s*(pub(\([^)]*\))?\s+)?mod\s+\w+\s*\{")

# Config files present in the tree (inventory, by name — not counted as code sites).
CONFIG_FILE_NAMES = re.compile(
    r"^(\.env(\..+)?|\.env\.example|config\.(toml|ya?ml|json|ini)|settings\.(toml|ya?ml|json|py|ini)|"
    r"application(-\w+)?\.(properties|ya?ml)|appsettings(\.\w+)?\.json|"
    r"\.?[\w-]*rc(\.\w+)?|[\w-]*\.conf|[\w-]*\.cfg|[\w-]*\.properties|"
    r"pyproject\.toml|tox\.ini|\.editorconfig|\.npmrc|\.yarnrc(\.yml)?)$", re.I)
CONFIG_FILE_DIRS = re.compile(r"(^|/)(config|conf|configs|settings|etc)/", re.I)

# Extraction regexes for the two named surfaces. A name is only extracted from a *literal* —
# `env::var(key)` passes a variable, not a name, and would otherwise pollute the surface with
# parameter names; those indirect reads are counted separately as a lead instead.
ENV_CALL = (r"""std::env::var(?:_os)?|env::var(?:_os)?|System\.getenv|"""
            r"""Environment\.GetEnvironmentVariable|process\.env\[|os\.environ(?:\.get)?\[|"""
            r"""os\.getenv|\bgetenv|ENV\[|Deno\.env\.get|os\.(?:Getenv|LookupEnv)""")
ENV_NAME = re.compile(r"""(?:%s)\s*\(?\s*["'`]([A-Za-z_][A-Za-z0-9_]{1,64})["'`]""" % ENV_CALL)
# `process.env.FOO` / `process.env?.FOO` — the name is the property, no quotes involved.
ENV_NAME_BARE = re.compile(r"process\.env\??\.([A-Za-z_][A-Za-z0-9_]{1,64})")
# A read whose name is computed at runtime. When the argument is an identifier declared as a
# string constant in the SAME file (the dominant Java/Go idiom — `getenv(ENV_FOO)` with
# `static final String ENV_FOO = "FOO"` above it), resolve it; otherwise it is only counted.
ENV_INDIRECT = re.compile(r"""(?:%s)\s*\(\s*(?!["'`])([A-Za-z_][A-Za-z0-9_.]*)""" % ENV_CALL)
# `static final String NAME = "VALUE"`, `const NAME = "VALUE"`, `NAME: &str = "VALUE"`, `NAME = "VALUE"`
CONST_DECL = re.compile(r"""(?:^|\s)([A-Z][A-Z0-9_]{2,})\s*(?::\s*&?'?\w*\s*str)?\s*=\s*["']([^"']{1,120})["']""")
# A quoted `-xyz` is a flag only when it is the whole string and does not trail a dash — `"-to-"`
# in a concatenated report title is not an option.
FLAG_NAME = re.compile(r"""["'`](--?[a-zA-Z][\w-]{1,40}(?<!-))["'`]|#\[(?:arg|clap|structopt)\([^)]*long\s*=\s*"([\w-]+)"|"""
                       r"""add_argument\(\s*["'](--?[\w-]+)["']|\.option\(\s*["'`]([^"'`]*--[\w-]+)""")
# An option declared from a constant: `new Option(ARG_SRC_ROOT, …)`, `.addOption(ARG_NAME, …)`,
# `StringVar(&x, FLAG_NAME, …)`. Resolved against the same file's constants (see CONST_DECL).
FLAG_CONST = re.compile(r"""(?:new Option\(|\.addOption\(|Option\.builder\(|[A-Za-z]+Var\([^,]*,\s*)\s*([A-Z][A-Z0-9_]{2,})\b""")

# key -> (regex, languages or None for all, note)
PATTERNS = {
    "env_read_sites": (re.compile(r"std::env::var|env::var(_os)?\(|System\.getenv|Environment\.GetEnvironmentVariable|process\.env[.\[]|os\.environ|os\.getenv|\bgetenv\(|ENV\[|Deno\.env\.get|os\.Getenv|os\.LookupEnv"), None, "environment-variable reads"),
    "env_default_sites": (re.compile(r"(env::var|getenv|environ\.get|process\.env\.\w+)[^;\n]*(unwrap_or|ok\(\)\.unwrap_or|\|\||\?\?|,\s*[\"'])|environ\.get\([^)]+,"), None, "env reads with an inline default"),
    "cli_flag_sites": (re.compile(r"#\[(arg|clap|structopt)\(|\.arg\(Arg::|add_argument\(|\.option\(|@Option\(|@Parameter\(|"
                                  r"new Option\(|\.addOption\(|Option\.builder\(|new Options\(\)|OptionParser|"
                                  r"flag\.(String|Bool|Int|Duration)\(|flag\.[A-Za-z]+Var\(|StringVar\(|BoolVar\(|"
                                  r"argparse|clap::|commander|yargs|cobra|docopt|OptionParser\.new"), None, "CLI option declarations"),
    "config_load_sites": (re.compile(r"(read_to_string|readFileSync|open|load|read)\([^)]*(config|settings|\.toml|\.ya?ml|\.ini|\.env|\.properties)|ConfigBuilder|Config::(load|from|builder)|configparser|dotenv|load_dotenv|new Properties\(\)|properties\.load\(|ConfigurationBuilder|AddJsonFile", re.I), None, "config-file load sites"),
    "config_parse_sites": (re.compile(r"toml::(from_str|from_slice)|serde_yaml::from|serde_json::from_(str|slice|reader)[^;\n]*(config|settings)|yaml\.(safe_)?load|json\.load|JSON\.parse[^;\n]*(config|settings)|ObjectMapper[^;\n]*(config|settings)|ini\.read|configparser\.ConfigParser", re.I), None, "config-format parses"),
    "config_library_sites": (re.compile(r"\bfigment\b|\bviper\b|config::(Config|File|Environment)|@ConfigurationProperties|@Value\(\"\$\{|pydantic_settings|BaseSettings|dynaconf|convict|nconf|node-config|dotenv|koanf|envconfig|\bclap\b.*env\s*=|dotenvy"), None, "configuration-library usage"),
    "default_value_sites": (re.compile(r"#\[serde\(default|\bimpl Default for\b|\bDefault::default\(\)|\.unwrap_or(_else|_default)?\(|@Value\([^)]*:[^)]*\)|getOrDefault\(|\.getOrElse\(|os\.environ\.get\([^,]+,|\?\?\s|default\s*[=:]\s*", re.I), None, "default-value shapes (broad; the loader's own defaults are what matter)"),
    "required_value_sites": (re.compile(r"\.expect\([^)]*(config|env|var|key|token|setting)|bail!\([^)]*(config|missing|required)|MissingConfig|required\s*=\s*true|@NotNull|raise\s+\w*Config\w*Error|panic!\([^)]*(config|env)", re.I), None, "required-value checks"),
    # A line that mentions a validation feature may be *disabling* it — counting
    # `FAIL_ON_UNKNOWN_PROPERTIES, false` as validation once turned "no validation" into "partial".
    # Strictness-toggle lines are classified by their value, in the two keys below.
    "validation_sites": (re.compile(r"validate\w*\([^)]*(config|setting|option|profile|toml|yaml|env)|(config|setting|option)\w*\.validate|#\[validate|@Valid\b|assert_valid|jsonschema\.validate|schema\.validate", re.I), None, "validation of configuration values (config-scoped; general-purpose validators are not counted)"),
    "strictness_enabled_sites": (re.compile(r"deny_unknown_fields\b(?!\s*=\s*false)|FAIL_ON_UNKNOWN_PROPERTIES\s*,\s*true|"
                                            r"extra\s*=\s*[\"']forbid|ignoreUnknown\s*=\s*false|strict\s*[:=]\s*[\"']?true", re.I), None,
                                 "strict-parsing switches turned ON (unknown keys rejected)"),
    "strictness_disabled_sites": (re.compile(r"deny_unknown_fields\s*=\s*false|FAIL_ON_UNKNOWN_PROPERTIES\s*,\s*false|"
                                             r"extra\s*=\s*[\"'](ignore|allow)|ignoreUnknown\s*=\s*true|"
                                             r"MissingMemberHandling\.Ignore|strict\s*[:=]\s*[\"']?false", re.I), None,
                                  "strict-parsing switches turned OFF (unknown keys silently dropped) — the opposite of validation, never count these as validation_sites"),
    # A JSON-schema derive is usually on a *protocol* type, not on configuration — counted apart so
    # it never inflates the config-validation figure. Check which of these cover the settings types.
    "json_schema_candidates": (re.compile(r"\bJsonSchema\b|\bjsonschema\b|schemars"), None, "lead: JSON-schema derives/uses (mostly protocol types; only some are the config schema)"),
    "unknown_key_policy_sites": (re.compile(r"deny_unknown_fields|FAIL_ON_UNKNOWN_PROPERTIES|ignoreUnknown|extra\s*=\s*[\"'](forbid|ignore|allow)|strict\s*[:=]\s*true|MissingMemberHandling"), None, "unknown-key policy declarations"),
    # A bare `.merge(` is a Map/tree merge far more often than a config merge — on one Java target
    # all 23 hits were domain-data merges, which implied a precedence story that did not exist.
    # `precedence` is a mandatory slot, so a false positive here is the most expensive one in the
    # script: require config vocabulary on the same line, or a config-library merge call.
    # `.join(` is a path join far more often than a figment layer join, and a function merely *named*
    # `*_with_overrides` is a caller, not the merge. Match the merge primitives themselves.
    "precedence_sites": (re.compile(r"(config|settings?|profile|overrides?|defaults?|toml|yaml)\w*\s*\.\s*merge\(|"
                                    r"\.merge\([^)]*(config|settings?|profile|overrides?|defaults?)|"
                                    r"merge_toml|merge_config|merge_settings|merge_from|merge_with\(|"
                                    r"\.join\(\s*(Env|Toml|Json|Yaml|Serialized)::|"
                                    r"deep_?merge|SetConfigFile|AutomaticEnv|AddEnvironmentVariables|"
                                    r"fn\s+\w*(merge|apply|load)_?(config|settings?|toml|yaml|profile|overrides?|defaults?)\w*\s*[(<]|"
                                    r"figment::|Figment::new|\.admerge\(|\.adjoin\(", re.I), None,
                         "source-merging / precedence sites (the merge primitives themselves; a path .join() and a caller merely named *_with_overrides are not counted)"),
    # `profile` alone matches permission profiles, shell profiles and UI state; require the
    # named-configuration sense (a profile *selector*, or a `[profiles.x]` table).
    "profile_candidates": (re.compile(r"--profile\b|SPRING_PROFILES_ACTIVE|@Profile\(|ASPNETCORE_ENVIRONMENT|\bNODE_ENV\b|"
                                 r"\[profiles?\.|\bprofiles?\s*:\s*\{|(config|active|selected|current|default)_profile|"
                                 r"profile_?name|\bprofiles\b\s*[=:]|get_profile\(|--workspace\b", re.I), None,
                      "lead: named configuration profiles / environment selectors — `profile` is an overloaded word (permission profiles, shell profiles, performance profiles), so read before concluding profiles exist"),
    "feature_flag_sites": (re.compile(r"feature_?flag|is_enabled\(|isFeatureEnabled|\bLaunchDarkly\b|\bstatsig\b|\bunleash\b|\bflagsmith\b|@FeatureFlag|experiment(s)?\.|\bgate\(|checkGate", re.I), None, "feature-flag / experiment checks"),
    "kill_switch_candidates": (re.compile(r"\b(disable|enabled|kill_?switch|opt_?out|opt_?in)\b\s*[=:]|DISABLE_[A-Z_]+|NO_[A-Z_]{3,}", re.I), None, "lead: enable/disable switches"),
    # A bare `reload()` is a UI refresh as often as a config re-read; require config vocabulary or
    # an unambiguous watch mechanism.
    # `Notify::new()` is an async primitive and SIGHUP inside a signal-mask array is shutdown
    # handling — neither reloads configuration. Require the config sense.
    "reload_sites": (re.compile(r"notify::(RecommendedWatcher|Watcher|recommended_watcher)|fsnotify|"
                                r"SIGHUP\s*=>|on\s*SIGHUP|sighup.*reload|reload.*sighup|"
                                r"hot_?reload|\bRefreshScope\b|chokidar|\bwatchman\(|"
                                r"reload_config|config_?reload|reloadConfig|(config|settings?)\w*\.reload\(|"
                                r"\bwatch(er)?\([^)]*(config|settings?|\.toml|\.ya?ml|\.json|\.env)|"
                                r"(config|settings?)\w*\s*\.\s*watch\(", re.I), None,
                     "config reload / file-watch mechanisms (config-scoped; a bare UI reload() is not counted)"),
    "secret_source_sites": (re.compile(r"keyring|keychain|SecretService|CredentialManager|secretsmanager|SecretClient|hashicorp/vault|vault\.|azure\.keyvault|gcp.*secretmanager|libsecret|wincred|dotenv|\.netrc|credentials?_file|auth\.json|token_file", re.I), None, "credential sources (mechanism, not values)"),
    "secret_env_candidates": (re.compile(r"(env::var|getenv|environ|process\.env)[^\n;]{0,40}(TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.I), None, "lead: credential-bearing env vars"),
    "redaction_sites": (re.compile(r"\bredact\w*|\bmask(ed|ing)?\(|Secret(String|Box|Vec)\b|\bSecret<|zeroize|Zeroizing|SecureString|\*{4,}[\"']|\[REDACTED\]|<redacted>", re.I), None, "redaction / secret-wrapping of settings"),
    "config_write_sites": (re.compile(r"(write|save|persist|store|dump)\w*\([^)]*(config|settings)|toml::to_string[^;\n]*(config|settings)|configparser[^\n]*\.write\(", re.I), None, "the tool writing its own configuration back"),
    "deprecated_key_candidates": (re.compile(r"deprecat\w*[^\n]{0,60}(config|setting|option|key|flag)|(config|setting|option|key)[^\n]{0,40}deprecat", re.I), None, "lead: deprecated settings"),
    "settings_doc_keyword_files": (re.compile(r"^\s*#{1,4}\s|^\s*\|", re.M), None, "unused (documentation is read directly)"),
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
    env_names, flag_names = defaultdict(list), defaultdict(list)
    config_files = []
    # Pass 1: every string constant in the workspace. The credential surface is routinely declared
    # in one file (`pub const CODEX_API_KEY_ENV_VAR: &str = "CODEX_API_KEY"`) and used in another,
    # so same-file resolution alone reliably finds the non-settings and misses the settings.
    # A name declared twice with different values is ambiguous and dropped rather than guessed.
    global_consts, ambiguous = {}, set()
    sources = [p for p in sorted(root.rglob("*")) if p.is_file()
               and not any(d in SKIP_DIRS or d in excludes for d in p.relative_to(root).parts[:-1])
               and language_of(p) and not is_test_path(p, root)]
    for path in sources:
        try:
            for m in CONST_DECL.finditer(path.read_text(encoding="utf-8", errors="replace")):
                name, value = m.group(1), m.group(2)
                if name in global_consts and global_consts[name] != value:
                    ambiguous.add(name)
                global_consts[name] = value
        except OSError:
            continue
    for name in ambiguous:
        global_consts.pop(name, None)
    # Constants whose *name* says they hold an env-var name. Some are never passed to a getenv the
    # scanner can see (they reach the environment through a process builder, a client SDK, or a
    # test), so they would be missing from env_var_names entirely — the credential surface is
    # routinely in this group. Surfaced as a lead so the settings surface can be completed by hand.
    env_const_names = {v: k for k, v in global_consts.items()
                       if re.search(r"ENV(_VAR)?$|^ENV_", k) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", v)}

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(p in SKIP_DIRS or p in excludes for p in rel.parts[:-1]):
            continue
        posix = rel.as_posix()
        if (CONFIG_FILE_NAMES.match(path.name) or CONFIG_FILE_DIRS.search(posix)) and \
                path.suffix.lower() in {".toml", ".yaml", ".yml", ".json", ".ini", ".conf", ".cfg",
                                        ".properties", ".env", ""} and not is_test_path(path, root):
            config_files.append(posix)
        lang = language_of(path)
        if not lang or is_test_path(path, root):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files_seen[lang] += 1
        lines = text.splitlines()
        # This file's constants win over the workspace table, so a local shadow resolves correctly.
        consts = dict(global_consts)
        consts.update({m.group(1): m.group(2) for m in CONST_DECL.finditer(text)})
        candidates = rust_non_test(lines) if lang == "rust" else enumerate(lines, 1)
        for lineno, line in candidates:
            if COMMENT.match(line):
                continue
            for key, (rx, langs, _note) in PATTERNS.items():
                if key == "settings_doc_keyword_files":
                    continue
                if langs and lang not in langs:
                    continue
                if rx.search(line):
                    hits[key].append((posix, lineno, line.strip()[:160]))
            snip = line.strip()[:160]
            for m in ENV_NAME.finditer(line):
                env_names[m.group(1)].append((posix, lineno, snip))
            for m in ENV_NAME_BARE.finditer(line):
                env_names[m.group(1)].append((posix, lineno, snip))
            m = ENV_INDIRECT.search(line)
            if m:
                resolved = consts.get(m.group(1).split(".")[-1])
                if resolved:
                    env_names[resolved].append((posix, lineno, snip))
                else:
                    hits["indirect_env_read_candidates"].append((posix, lineno, line.strip()[:160]))
            for m in FLAG_NAME.finditer(line):
                nm = next((g for g in m.groups() if g), None)
                if nm:
                    flag_names[nm.lstrip("-")].append((posix, lineno, snip))
            for m in FLAG_CONST.finditer(line):
                resolved = consts.get(m.group(1))
                if resolved and not resolved.startswith("-") and len(resolved) > 1:
                    flag_names[resolved.lstrip("-")].append((posix, lineno, snip))
    return hits, files_seen, env_names, flag_names, sorted(set(config_files)), env_const_names


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

    hits, files_seen, env_names, flag_names, config_files, env_const_names = scan(root, set(args.exclude))
    stats = {}
    # every key in hits, not just PATTERNS keys — `indirect_env_read_candidates` is added by the
    # scan loop itself and was silently dropped from both stats and leads.
    for k in list(PATTERNS) + [k for k in hits if k not in PATTERNS]:
        if k == "settings_doc_keyword_files":
            continue
        v = hits.get(k, [])
        if not v and k.endswith(("_candidates", "_keyword_files")):
            continue
        stats[k] = len(v)
    stats["config_files_in_tree"] = len(config_files)
    stats["distinct_env_vars_read"] = len(env_names)
    stats["distinct_cli_flags"] = len(flag_names)
    stats = dict(sorted(stats.items()))
    leads = {k: n for k, n in stats.items() if k.endswith(("_candidates", "_keyword_files"))}
    facts = {k: n for k, n in stats.items() if k not in leads}
    notes = {k: PATTERNS[k][2] for k in stats if k in PATTERNS}
    notes["config_files_in_tree"] = "config-looking files in the tree (name or config/ directory)"
    notes["indirect_env_read_candidates"] = ("lead: env reads whose name is computed at runtime "
                                             "(a helper taking the name as a parameter) — these are "
                                             "invisible to env_var_names; read the callers")
    notes["distinct_env_vars_read"] = "distinct env-var names read (a lead list too — drop non-settings)"
    notes["distinct_cli_flags"] = "distinct CLI options declared (includes non-config flags)"

    print(f"Scanned {sum(files_seen.values())} non-test files "
          f"({', '.join(f'{l}: {n}' for l, n in sorted(files_seen.items()))}) under {root}\n")
    print("stats (facts; copy into findings stats after discarding keys you verified as false positives, naming them in count_notes):")
    for k, n in facts.items():
        print(f"  {k:32s} {n:6d}   {notes.get(k, '')}")
    if leads:
        print("leads (read before citing; do NOT copy as stats):")
        for k, n in leads.items():
            print(f"  {k:32s} {n:6d}   {notes.get(k, '')}")
    print()
    print(f"env_var_names ({len(env_names)}) — the env surface; DROP environment queries "
          f"(HOME, PATH, CI, TERM) before counting settings:")
    for name, locs in sorted(env_names.items(), key=lambda kv: (-len(kv[1]), kv[0]))[: args.top * 3]:
        f, l = locs[0][0], locs[0][1]
        print(f"  {len(locs):4d}  {name:34s} first at {f}:{l}")
    print()
    if hits.get("cli_flag_sites") and len(flag_names) < len(hits["cli_flag_sites"]) / 4:
        print(f"note: only {len(flag_names)} flag names extracted from {len(hits['cli_flag_sites'])} option "
              f"declarations. Same-file string constants are resolved, so the rest are named from "
              f"constants declared elsewhere or assembled at runtime. Recover the real surface by "
              f"reading the option declarations in the top cli_flag_sites files below (the "
              f"`Option`/`Arg`/`add_argument` constructors and the constants they reference).\n")
    print(f"flag_names ({len(flag_names)}) — CLI options; only those that SET a value are configuration:")
    for name, locs in sorted(flag_names.items(), key=lambda kv: (-len(kv[1]), kv[0]))[: args.top * 2]:
        f, l = locs[0][0], locs[0][1]
        print(f"  {len(locs):4d}  --{name:32s} first at {f}:{l}")
    print()
    unread = {v: k for v, k in env_const_names.items() if v not in env_names}
    if unread:
        print(f"env_name_constants_no_local_read ({len(unread)}) — constants naming an env var with "
              f"no getenv beside them: the read is in another crate/file, or the value reaches the "
              f"environment via a process builder, an SDK or a test. NOT evidence that the variable "
              f"is unused — never write a dead-constant finding from this list. They are MISSING "
              f"from env_var_names, and the credential surface often lives here, so add the real "
              f"settings by hand:")
        for value, const in sorted(unread.items())[: args.top * 2]:
            print(f"  {value:34s} (declared as {const})")
        print()
    print(f"config_files_in_tree ({len(config_files)}):")
    for f in config_files[: args.top * 2]:
        print(f"  {f}")
    print()
    for key, rows in sorted(hits.items()):
        if not rows:
            continue
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
            "count_rule": "non-test files by path (test/tests/spec/mock/fixture segments, *_test.*, "
                          "*Test.java, test_*.py)"
                          + ("; Rust #[cfg(test)] modules excluded" if "rust" in files_seen else "")
                          + "; single-line regex matches, comment lines skipped",
            "stats": facts, "leads": leads, "notes": notes,
            "config_files": config_files,
            "env_name_constants": env_const_names,
            "env_name_constants_no_local_read": {v: k for v, k in env_const_names.items() if v not in env_names},
            "env_var_names": {n: [{"file": f, "line": l, "snippet": t} for f, l, t in v]
                              for n, v in sorted(env_names.items())},
            "flag_names": {n: [{"file": f, "line": l, "snippet": t} for f, l, t in v]
                           for n, v in sorted(flag_names.items())},
            "hits": {k: [{"file": f, "line": l, "snippet": s} for f, l, s in v] for k, v in hits.items() if v},
        }, indent=2))
        print(f"wrote {args.json} (src_root {root})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
