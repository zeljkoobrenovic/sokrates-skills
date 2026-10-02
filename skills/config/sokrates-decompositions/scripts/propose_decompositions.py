#!/usr/bin/env python3
"""Propose logical decompositions (component structures) for a Sokrates repository analysis.

Reads `_sokrates/config.json` (for srcRoot, extensions, ignore and test/generated/build/other
scope rules) and the source tree, and emits candidate `logicalDecompositions` entries, each
ready to paste into the config, with the evidence behind it:

  folder-depth     depth 1..4 evaluated with a balance score (largest component share, tiny
                   components, component count) and the recommended depth
  build-modules    one component per build-system module: Cargo packages, Maven/Gradle modules,
                   npm/pnpm/yarn workspaces, Bazel packages, Go modules, Python packages, .NET
                   projects — nested modules get exception filters so components stay disjoint
  ownership        CODEOWNERS (GitHub/GitLab) patterns turned into one component per owner
  layers           recurring folder names across the tree (api, domain, service, ui, db, …)
                   turned into a cross-cutting by-layer decomposition
  technology       one component per language/extension family

Usage:
  python3 propose_decompositions.py <path/to/_sokrates/config.json> [-o proposals.json]
                                    [--max-files 200000] [--min-loc-share 0.5]

Component filters follow Sokrates semantics: pathPattern is a Java regex matched against the
ENTIRE path below the source root, with a leading `/` (hence the leading `.*`), `exception: true` vetoes.
The AI running the skill chooses, merges and names the proposals; this script only measures.
"""

import argparse
import fnmatch
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SKIP_DIRS = {".git", ".hg", ".svn", "_sokrates", "_sokrates_landscape"}
TEST_DIR_RE = re.compile(r"(^|/)(tests?|testdata|fixtures?|__tests__|benches?|examples?)(/|$)")
LAYER_WORDS = {
    "api", "apis", "rest", "graphql", "grpc", "rpc", "handlers", "handler", "controllers", "controller", "routes", "router", "endpoints",
    "service", "services", "usecase", "usecases", "application", "app", "core", "domain", "model", "models", "entities", "entity",
    "repository", "repositories", "repo", "dao", "persistence", "db", "database", "storage", "store", "migrations", "sql", "schema",
    "ui", "views", "view", "components", "pages", "screens", "widgets", "frontend", "client", "web", "cli", "tui",
    "infra", "infrastructure", "adapters", "adapter", "ports", "gateway", "gateways", "integration", "integrations",
    "utils", "util", "utilities", "common", "shared", "lib", "libs", "helpers", "internal", "pkg", "cmd", "config", "configuration",
    "auth", "security", "sandbox", "protocol", "proto", "events", "messaging", "queue", "workers", "jobs", "scheduler", "tasks",
    "plugins", "plugin", "extensions", "ext", "tools", "scripts", "bin", "server", "runtime", "engine", "analysis", "reports", "exec",
}
TECH_FAMILIES = [
    ("Rust", {"rs"}), ("Java", {"java"}), ("Kotlin", {"kt", "kts"}), ("Scala", {"scala", "sbt"}), ("Go", {"go"}),
    ("TypeScript", {"ts", "tsx"}), ("JavaScript", {"js", "jsx", "mjs", "cjs"}), ("Python", {"py", "pyi"}), ("C#", {"cs"}),
    ("C/C++", {"c", "h", "cc", "cpp", "cxx", "hpp", "hh"}), ("Swift", {"swift"}), ("Objective-C", {"m", "mm"}), ("Ruby", {"rb"}),
    ("PHP", {"php"}), ("Dart", {"dart"}), ("Shell", {"sh", "bash", "zsh", "ps1", "bat"}), ("SQL", {"sql"}),
    ("Web (HTML/CSS)", {"html", "htm", "css", "scss", "sass", "less", "vue", "svelte"}), ("Protobuf/IDL", {"proto", "thrift", "avdl"}),
    ("Config (YAML/TOML/JSON)", {"yaml", "yml", "toml", "json", "jsonl"}), ("Docs (Markdown)", {"md", "mdx", "rst", "adoc", "txt"}),
    ("Build (Bazel/Make/Gradle)", {"bzl", "bazel", "gradle", "mk", "cmake", "nix"}),
]
MANIFESTS = [  # (file name regex, module type, how to read the module name)
    (r"^Cargo\.toml$", "cargo", "cargo"), (r"^pom\.xml$", "maven", "pom"), (r"^build\.gradle(\.kts)?$", "gradle", "dir"),
    (r"^package\.json$", "npm", "npm"), (r"^BUILD(\.bazel)?$", "bazel", "dir"), (r"^go\.mod$", "go", "gomod"),
    (r"^(pyproject\.toml|setup\.py|setup\.cfg)$", "python", "dir"), (r".*\.csproj$", "dotnet", "stem"), (r"^CMakeLists\.txt$", "cmake", "dir"),
    (r"^Package\.swift$", "swiftpm", "dir"), (r"^mix\.exs$", "mix", "dir"), (r"^composer\.json$", "composer", "dir"), (r"^Gemfile$", "bundler", "dir"),
]


class Rule:
    def __init__(self, raw):
        self.path_pattern = raw.get("pathPattern", "") or ""
        self.content_pattern = raw.get("contentPattern", "") or ""
        self.exception = bool(raw.get("exception", False))
        try:
            self.path_re = re.compile(self.path_pattern) if self.path_pattern.strip() else None
        except re.error:
            self.path_re = re.compile(r"(?!x)x")  # never matches, like Sokrates
        self.has_content = bool(self.content_pattern.strip())

    def path_matches(self, full_path):
        if self.has_content:
            return False   # content rules are not evaluated here (would need to read every file); treated as non-matching
        return self.path_re is None or bool(self.path_re.fullmatch(full_path))


def resolve_src_root(config_path: Path, src_root: str) -> Path:
    cand = config_path.parent.parent / src_root[2:].lstrip("/\\") if src_root.startswith("..") else config_path.parent / src_root
    return cand if cand.exists() else Path(src_root)


def rx_escape_path(p: str) -> str:
    return re.escape(p).replace("\\/", "/")


def glob_to_regex(pattern: str) -> str:
    """CODEOWNERS glob -> Sokrates whole-path regex (matched against .*<relative>)."""
    p = pattern.strip()
    anchored = p.startswith("/")
    p = p.lstrip("/")
    directory = p.endswith("/")
    p = p.rstrip("/")
    out = ""
    i = 0
    while i < len(p):
        c = p[i]
        if p.startswith("**", i):
            out += ".*"; i += 2; continue
        if c == "*":
            out += "[^/]*"
        elif c == "?":
            out += "[^/]"
        else:
            out += re.escape(c)
        i += 1
    suffix = "/.*" if directory else "(/.*)?"
    return ".*/" + out + suffix


UNASSIGNED = {"(no module)", "(unowned)", "(no layer folder)", "ROOT"}


def walk_main_files(src_root, config, max_files):
    """Approximate main files (extension, not ignored, not test/generated/build/other by path, within size limits) with
    their LOC; the build manifests and the CODEOWNERS file met on the way."""
    src_root_str = str(src_root)
    extensions = {e.lower() for e in config.get("extensions") or []}
    ignore = [Rule(r) for r in config.get("ignore") or []]
    non_main = {s: [Rule(r) for r in (config.get(s) or {}).get("sourceFileFilters") or []]
                for s in ("test", "generated", "buildAndDeployment", "other")}
    content_rules = any(r.has_content for rs in [ignore, *non_main.values()] for r in rs)
    analysis = config.get("analysis") or {}
    max_bytes = int(analysis.get("maxFileSizeBytes", 1000000)); max_lines = int(analysis.get("maxLines", 10000)); max_line_len = int(analysis.get("maxLineLength", 1000))
    files = {}          # rel -> loc
    manifests = []      # (rel_dir, type, how, rel)
    codeowners = None
    total = 0
    for root, dirs, fns in os.walk(src_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel_dir = os.path.relpath(root, src_root).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        for fn in fns:
            total += 1
            if total > max_files:
                break
            rel = f"{rel_dir}/{fn}" if rel_dir else fn
            for pat, mtype, how in MANIFESTS:
                if re.match(pat, fn):
                    manifests.append((rel_dir, mtype, how, rel))
            if fn == "CODEOWNERS" and (rel_dir in ("", ".github", "docs", ".gitlab")):
                codeowners = rel
            ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
            if ext not in extensions:
                continue
            full = os.path.join(src_root_str, rel)
            matched = "/" + rel       # what Sokrates matches: the path below the source root, with a leading separator
            if any(r.path_matches(matched) for r in ignore):
                continue
            scoped_out = False
            for rules in non_main.values():
                inc = any(r.path_matches(matched) and not r.exception for r in rules)
                exc = any(r.path_matches(matched) and r.exception for r in rules)
                if inc and not exc:
                    scoped_out = True; break
            if scoped_out:
                continue
            try:
                if os.path.getsize(full) > max_bytes:
                    continue
                with open(full, "rb") as fh:
                    lines = fh.read().split(b"\n")
            except OSError:
                continue
            if len(lines) > max_lines or any(len(ln) > max_line_len for ln in lines):
                continue   # Sokrates excludes these before scoping
            files[rel] = sum(1 for ln in lines if ln.strip())
    sokrates_unignored = (src_root / "_sokrates").is_dir() and not any("_sokrates" in r.path_pattern for r in ignore)
    return files, manifests, codeowners, content_rules, sokrates_unignored


def component_rows(assign, files, total_loc):
    comps = defaultdict(lambda: [0, 0])
    for rel, name in assign.items():
        comps[name][0] += 1; comps[name][1] += files[rel]
    rows = [{"name": n, "files": c[0], "loc": c[1], "loc_share_pct": round(100 * c[1] / total_loc, 1)}
            for n, c in comps.items()]
    rows.sort(key=lambda r: -r["loc"])
    return rows


def score(rows, min_loc_share):
    """A balance score: one dominant component, too many or too few components, dust, a large unassigned share all cost points."""
    if not rows:
        return 0.0
    largest = rows[0]["loc_share_pct"]
    unassigned = sum(r["loc_share_pct"] for r in rows if r["name"] in UNASSIGNED)
    tiny = sum(1 for r in rows if r["loc_share_pct"] < min_loc_share)
    n = len(rows)
    s = 100.0
    s -= max(0, largest - 40) * 1.2            # one dominant component
    s -= max(0, n - 25) * 2                    # too many components
    s -= tiny * 3                              # dust
    s -= max(0, 4 - n) * 10                    # too few
    s -= max(0, unassigned - 20) * 2           # a large share outside any real component
    return round(max(0, s), 1)


def folder_filter(folder, note="", exception=False):
    return {"pathPattern": f".*/{rx_escape_path(folder)}/.*", "contentPattern": "", "exception": exception, "note": note}


def explicit_decomposition(name, components):
    return {"name": name, "scope": "main", "componentsFolderDepth": 0, "minComponentsCount": 0, "includeRemainingFiles": True, "components": components}


def folder_depth_proposal(files, total_loc, min_loc_share):
    """Depth 1..4 as Sokrates would derive the components (common prefix stripped), scored; the recommended depth."""
    depth_options = []
    for depth in range(1, 5):
        assign = {}
        for rel in files:
            parts = rel.split("/")
            assign[rel] = "/".join(parts[:min(depth, len(parts) - 1)]) or "ROOT"
        names = set(assign.values())
        prefix = os.path.commonprefix([n + "/" for n in names]) if len(names) > 1 else ""
        prefix = prefix[:prefix.rfind("/") + 1] if "/" in prefix else ""
        if prefix:
            assign = {r: (n[len(prefix):] if n.startswith(prefix) else n) or "ROOT" for r, n in assign.items()}
        rows = component_rows(assign, files, total_loc)
        depth_options.append({"componentsFolderDepth": depth, "components": len(rows), "score": score(rows, min_loc_share),
                              "largest": rows[0] if rows else None, "tiny_components": sum(1 for r in rows if r["loc_share_pct"] < min_loc_share),
                              "rows": rows})
    best = max(depth_options, key=lambda d: d["score"])
    usable = best["score"] >= 40
    return {"kind": "folder-depth", "recommended_depth": best["componentsFolderDepth"] if usable else None,
            "verdict": "usable" if usable else "no folder depth gives a balanced decomposition — use mixed-depth, grouped-modules or explicit components",
            "options": depth_options,
            "config": {"name": "primary", "scope": "main", "componentsFolderDepth": best["componentsFolderDepth"],
                       "minComponentsCount": 0, "components": []}}


def module_name(src_root, rel_dir, how, rel):
    """The module's own name from its manifest; None when the manifest is an aggregator, a workspace root or vendored."""
    if not rel_dir:
        return "root"
    fallback = rel_dir.rsplit("/", 1)[-1]
    if how == "cargo":
        try:
            txt = (src_root / rel).read_text(errors="replace")
            if not re.search(r"^\[package\]", txt, re.M):
                return None  # workspace root or virtual manifest, not a package
            m = re.search(r'^\s*name\s*=\s*"([^"]+)"', txt, re.M); return m.group(1) if m else fallback
        except OSError:
            return fallback
    if how == "pom":
        try:
            txt = (src_root / rel).read_text(errors="replace")
            if "<modules>" in txt and "<packaging>pom</packaging>" in txt:
                return None  # aggregator
            m = re.search(r"<artifactId>([^<]+)</artifactId>", txt.split("<dependencies>")[0]); return m.group(1) if m else fallback
        except OSError:
            return fallback
    if how == "npm":
        if "node_modules" in rel_dir:
            return None
        try:
            d = json.loads((src_root / rel).read_text(errors="replace")); name = d.get("name") or fallback
            if d.get("workspaces") and not rel_dir:
                return None
            return name
        except (OSError, json.JSONDecodeError):
            return fallback
    if how == "gomod":
        try:
            m = re.search(r"^module\s+(\S+)", (src_root / rel).read_text(errors="replace"), re.M); return m.group(1).rsplit("/", 1)[-1] if m else fallback
        except OSError:
            return fallback
    if how == "stem":
        return rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return fallback


def detect_modules(manifests, src_root):
    """Build-system modules: dir -> {dir, type, name}; test-support modules dropped, a real manifest beats a BUILD file."""
    mods = {}
    for rel_dir, mtype, how, rel in manifests:
        name = module_name(src_root, rel_dir, how, rel)
        if name is None:
            continue
        if TEST_DIR_RE.search(rel_dir):
            continue  # test-support crates/packages belong to their parent module
        if rel_dir not in mods or mods[rel_dir]["type"] == "bazel":  # a real manifest beats a BUILD file in the same dir
            mods[rel_dir] = {"dir": rel_dir, "type": mtype, "name": name}
    return mods


def mixed_depth_proposal(files, total_loc, mods, min_loc_share):
    """Dominant depth-1 folders opened one level deeper (tiny children folded into "<folder> (other)"), the rest kept whole."""
    d1 = {}
    for rel in files:
        parts = rel.split("/")
        d1[rel] = parts[0] if len(parts) > 1 else "ROOT"
    d1_loc = Counter()
    for rel, name in d1.items():
        d1_loc[name] += files[rel]
    dominant = [n for n, l in d1_loc.items() if n != "ROOT" and 100 * l / total_loc >= 40]
    if not dominant:
        return None
    assign = {}
    components = []
    for rel, top in d1.items():
        if top in dominant:
            parts = rel.split("/")
            assign[rel] = "/".join(parts[:2]) if len(parts) > 2 else f"{top} (other)"
        else:
            assign[rel] = top
    # a depth-2 child that is itself a folder of modules (ext/, utils/, memories/) is opened one level more
    module_dirs = [d for d in mods if d]
    for rel in list(assign):
        parts = rel.split("/")
        if len(parts) > 3 and parts[0] in dominant:
            child = "/".join(parts[:2])
            if sum(1 for d in module_dirs if d.startswith(child + "/") and d.count("/") == 2) >= 3:
                assign[rel] = "/".join(parts[:3])
    # fold tiny children of a dominant folder into "<folder> (other)"
    child_loc = Counter()
    for rel, name in assign.items():
        child_loc[name] += files[rel]
    big_children = defaultdict(list)
    for rel, name in list(assign.items()):
        top = rel.split("/")[0]
        if top in dominant and name != f"{top} (other)":
            if 100 * child_loc[name] / total_loc < min_loc_share:
                assign[rel] = f"{top} (other)"
            elif name not in big_children[top]:
                big_children[top].append(name)
    # a grandchild component makes its parent folder a partial parent: keep them disjoint
    for top in dominant:
        deep = [c for c in big_children[top] if c.count("/") == 2]
        for c in deep:
            parent = c.rsplit("/", 1)[0]
            if parent in big_children[top]:
                big_children[top].remove(parent)
                for rel, name in list(assign.items()):
                    if name == parent:
                        assign[rel] = f"{top} (other)"
    rows = component_rows(assign, files, total_loc)
    for top in sorted(d1_loc, key=lambda n: -d1_loc[n]):
        if top == "ROOT":
            continue
        if top in dominant:
            for child in sorted(big_children[top]):
                components.append({"name": child, "sourceFileFilters": [folder_filter(child)], "files": []})
            filters = [folder_filter(top, "remaining files of the folder")]
            filters += [folder_filter(child, exception=True) for child in sorted(big_children[top])]
            components.append({"name": f"{top} (other)", "sourceFileFilters": filters, "files": []})
        else:
            components.append({"name": top, "sourceFileFilters": [folder_filter(top)], "files": []})
    return {"kind": "mixed-depth", "opened_folders": dominant, "score": score(rows, min_loc_share), "rows": rows,
            "note": "explicit components: dominant top folders split one level deeper (tiny children folded into '<folder> (other)'), every other top folder kept whole; ROOT files become Unclassified",
            "config": explicit_decomposition("primary", components)}


def build_modules_proposal(files, total_loc, mods, min_loc_share, warnings):
    """One component per build-system module, nested modules carved out with exception filters."""
    if not (len(mods) > 1 or (mods and "" not in mods)):
        return None
    mod_dirs = sorted(mods, key=len, reverse=True)
    assign = {}
    for rel in files:
        d = next((m for m in mod_dirs if m and (rel.startswith(m + "/"))), "")
        if d or "" in mods:
            assign[rel] = mods[d]["name"] if d in mods else "(no module)"
    rows = component_rows(assign, files, total_loc)
    by_type = Counter(m["type"] for m in mods.values())
    components = []
    for d in sorted(mods):
        if not d:
            continue
        nested = [o for o in mods if o != d and o.startswith(d + "/")]
        filters = [folder_filter(d, f"{mods[d]['type']} module")]
        filters += [folder_filter(o, "nested module", exception=True) for o in nested]
        components.append({"name": mods[d]["name"], "sourceFileFilters": filters, "files": []})
    if len(components) > 60:
        warnings.append(f"build-modules: {len(components)} modules — consider grouping them (by folder or by prefix) rather than one component each")
    return {"kind": "build-modules", "module_types": dict(by_type), "modules": len(components), "score": score(rows, min_loc_share), "rows": rows,
            "config": explicit_decomposition("build-modules", components)}


def grouped_modules_proposal(files, total_loc, mods, min_loc_share):
    """Many modules grouped by parent folder (>= 3 modules), else by shared name prefix (>= 3), else kept alone."""
    if len(mods) <= 25:
        return None
    module_dirs = [d for d in mods if d]
    parent_count = Counter(d.rsplit("/", 1)[0] for d in module_dirs if "/" in d)
    # strip a name prefix shared by most modules (codex-*, @openai/*) before grouping by the next token
    tokens = Counter(re.split(r"[-_/]", mods[d]["name"].lstrip("@"), maxsplit=1)[0] for d in module_dirs)
    common = tokens.most_common(1)[0][0] if tokens and tokens.most_common(1)[0][1] >= 0.6 * len(module_dirs) else None
    def prefix_of(name):
        n = name.lstrip("@")
        if common and re.match(re.escape(common) + r"[-_/]", n):
            n = re.split(r"[-_/]", n, maxsplit=1)[1]
        return re.split(r"[-_]", n, maxsplit=1)[0]
    prefix_count = Counter(prefix_of(mods[d]["name"]) for d in module_dirs)
    group_of = {}
    for d in module_dirs:
        parent = d.rsplit("/", 1)[0] if "/" in d else ""
        if parent and parent_count[parent] >= 3 and parent.count("/") >= 1:
            group_of[d] = parent + "/*"
        elif prefix_count[prefix_of(mods[d]["name"])] >= 3:
            group_of[d] = prefix_of(mods[d]["name"]) + "-*"
        else:
            group_of[d] = mods[d]["name"]
    mod_dirs_sorted = sorted(module_dirs, key=len, reverse=True)
    assign = {}
    for rel in files:
        d = next((m for m in mod_dirs_sorted if rel.startswith(m + "/")), None)
        assign[rel] = group_of[d] if d else "(no module)"
    rows = component_rows(assign, files, total_loc)
    groups = defaultdict(list)
    for d, g in group_of.items():
        groups[g].append(d)
    components = []
    for g, dirs in sorted(groups.items(), key=lambda kv: -sum(1 for r, n in assign.items() if n == kv[0])):
        filters = []
        for d in sorted(dirs):
            filters.append(folder_filter(d, f"{mods[d]['type']} module {mods[d]['name']}"))
            for o in module_dirs:
                if o != d and o.startswith(d + "/") and group_of[o] != g:
                    filters.append(folder_filter(o, "nested module of another group", exception=True))
        components.append({"name": g, "sourceFileFilters": filters, "files": []})
    return {"kind": "grouped-modules", "groups": len(components), "score": score(rows, min_loc_share), "rows": rows,
            "note": "mechanical grouping (parent folder, then name prefix); rename groups with the repository's vocabulary and merge further by hand — an architecture-scan component map is the best key",
            "config": explicit_decomposition("primary", components)}


def ownership_proposal(files, total_loc, src_root, codeowners, min_loc_share):
    """One component per CODEOWNERS owner set (last matching rule wins, as on GitHub)."""
    owners = []
    for ln in (src_root / codeowners).read_text(errors="replace").splitlines():
        ln = ln.split("#", 1)[0].strip()
        if not ln:
            continue
        parts = ln.split()
        if len(parts) >= 2:
            owners.append((parts[0], parts[1:]))
    assign = {}
    for rel in files:
        owner = None
        for pattern, who in owners:            # last match wins, as in GitHub
            p = pattern.lstrip("/")
            if fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, p.rstrip("/") + "/*") or rel.startswith(p.rstrip("/") + "/") or fnmatch.fnmatch("/" + rel, pattern if pattern.startswith("/") else "*/" + p):
                owner = ", ".join(who)
        assign[rel] = owner or "(unowned)"
    rows = component_rows(assign, files, total_loc)
    components = []
    for pattern, who in owners:
        name = ", ".join(who)
        comp = next((c for c in components if c["name"] == name), None)
        if comp is None:
            comp = {"name": name, "sourceFileFilters": [], "files": []}; components.append(comp)
        comp["sourceFileFilters"].append({"pathPattern": glob_to_regex(pattern), "contentPattern": "", "exception": False, "note": f"CODEOWNERS {pattern}"})
    return {"kind": "ownership", "source": codeowners, "rules": len(owners), "score": score(rows, min_loc_share), "rows": rows,
            "note": "later CODEOWNERS rules override earlier ones; Sokrates filters have no order, so overlapping owners will show as Multiple Classifications — add exception filters or keep only the specific rules",
            "config": explicit_decomposition("ownership", components)}


def layers_proposal(files, total_loc, mods, min_loc_share):
    """Recurring layer folder names across the tree (api, domain, service, ui, db, ...) as a cross-cutting decomposition."""
    dir_counts = Counter()
    dir_loc = Counter()
    for rel, loc in files.items():
        segs = rel.split("/")[:-1]
        for s in set(segs):
            if s.lower() in LAYER_WORDS:
                dir_counts[s.lower()] += 1; dir_loc[s.lower()] += loc
    module_basenames = {d.rsplit("/", 1)[-1].lower() for d in mods if d}
    layer_names = [n for n, c in dir_counts.most_common(14) if c >= 10 and dir_loc[n] * 100 / total_loc >= 1 and n not in module_basenames]
    if len(layer_names) < 3:
        return None
    assign = {}
    for rel in files:
        segs = [s.lower() for s in rel.split("/")[:-1]]
        hit = next((s for s in reversed(segs) if s in layer_names), None)   # innermost layer folder wins
        assign[rel] = hit or "(no layer folder)"
    rows = component_rows(assign, files, total_loc)
    components = [{"name": n, "sourceFileFilters": [{"pathPattern": f".*/{n}/.*", "contentPattern": "", "exception": False, "note": "layer folder"}], "files": []}
                  for n in layer_names]
    return {"kind": "layers", "layer_folders": [(n, dir_counts[n], round(100 * dir_loc[n] / total_loc, 1)) for n in layer_names],
            "score": score(rows, min_loc_share), "rows": rows,
            "note": "folder-name filters overlap when a path contains several layer words (e.g. api/services/…); Sokrates reports those as Multiple Classifications — decide the precedence and add exception filters, or use metaComponents with `use: path` + nameOperations",
            "config": explicit_decomposition("layers", components)}


def technology_proposal(files, total_loc):
    """One component per language family present."""
    ext_loc = Counter()
    for rel, loc in files.items():
        ext_loc[rel.rsplit(".", 1)[-1].lower() if "." in rel else ""] += loc
    fam_rows = []
    components = []
    for fam, exts in TECH_FAMILIES:
        present = sorted(e for e in exts if ext_loc.get(e))
        loc = sum(ext_loc[e] for e in present)
        if loc:
            fam_rows.append({"name": fam, "extensions": present, "loc": loc, "loc_share_pct": round(100 * loc / total_loc, 1)})
            components.append({"name": fam, "sourceFileFilters": [{"pathPattern": ".*[.](" + "|".join(present) + ")", "contentPattern": "", "exception": False, "note": ""}], "files": []})
    fam_rows.sort(key=lambda r: -r["loc"])
    if len(fam_rows) < 2:
        return None
    return {"kind": "technology", "rows": fam_rows, "config": explicit_decomposition("technology", components)}


def print_rows(rows, limit):
    for r in rows[:limit]:
        print(f"  {r['name'][:48]:<48} {r['files']:>6} files {r['loc']:>9} LOC {r['loc_share_pct']:>5}%")


def print_summary(out, config_path):
    print(f"Decomposition proposals — {config_path}  ({out['main_files_estimate']} main files, {out['main_loc_estimate']} LOC, approx.)")
    print(f"existing: {out['existing_decompositions']}")
    for p in out["proposals"]:
        k = p["kind"]
        if k == "folder-depth":
            print(f"\n[folder-depth] " + (f"recommended componentsFolderDepth = {p['recommended_depth']}" if p['recommended_depth'] else p['verdict']))
            for o in p["options"]:
                lg = o["largest"]
                print(f"  depth {o['componentsFolderDepth']}: {o['components']:>3} components, score {o['score']:>5}, largest {lg['name'] if lg else '-'} {lg['loc_share_pct'] if lg else 0}%, tiny {o['tiny_components']}")
        elif k == "mixed-depth":
            print(f"\n[mixed-depth] score {p['score']}  opened: {p['opened_folders']}  ({len(p['config']['components'])} explicit components)")
            print_rows(p["rows"], 14)
        elif k == "grouped-modules":
            print(f"\n[grouped-modules] score {p['score']}  {p['groups']} groups (parent folder / name prefix)")
            print_rows(p["rows"], 14)
        elif k == "technology":
            print(f"\n[technology] " + ", ".join(f"{r['name']} {r['loc_share_pct']}%" for r in p["rows"][:8]))
        else:
            extra = p.get("module_types") or p.get("layer_folders") or p.get("source")
            print(f"\n[{k}] score {p['score']}  {extra}  (all rows in the JSON output)")
            print_rows(p["rows"], 12)
            if p.get("note"):
                print(f"  note: {p['note']}")
    for w in out["warnings"]:
        print(f"WARNING: {w}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("-o", "--output")
    ap.add_argument("--max-files", type=int, default=200000)
    ap.add_argument("--min-loc-share", type=float, default=0.5, help="components below this %% of LOC count as tiny")
    args = ap.parse_args()

    config_path = Path(args.config)
    try:
        config = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr); return 2
    src_root = resolve_src_root(config_path, config.get("srcRoot", ".."))
    if not src_root.is_dir():
        print(f"error: srcRoot {src_root} not found", file=sys.stderr); return 2
    warnings = []
    files, manifests, codeowners, content_rules, sokrates_unignored = walk_main_files(src_root, config, args.max_files)
    if content_rules:
        warnings.append("some scope rules use contentPattern; those are not evaluated here (treated as non-matching), so main-file counts are approximate")
    if sokrates_unignored:
        warnings.append("`.*/_sokrates/.*` is missing from ignore — Sokrates will count its own output as main (this script skips the folder)")
    total_loc = sum(files.values()) or 1
    share = args.min_loc_share
    mods = detect_modules(manifests, src_root)
    candidates = [folder_depth_proposal(files, total_loc, share),
                  mixed_depth_proposal(files, total_loc, mods, share),
                  build_modules_proposal(files, total_loc, mods, share, warnings),
                  grouped_modules_proposal(files, total_loc, mods, share),
                  ownership_proposal(files, total_loc, src_root, codeowners, share) if codeowners else None,
                  layers_proposal(files, total_loc, mods, share),
                  technology_proposal(files, total_loc)]
    proposals = [p for p in candidates if p is not None]
    existing = [{"name": d.get("name"), "componentsFolderDepth": d.get("componentsFolderDepth"), "explicit_components": len(d.get("components") or []),
                 "metaComponents": len(d.get("metaComponents") or [])} for d in config.get("logicalDecompositions") or []]
    out = {"config": str(config_path), "srcRoot": str(src_root), "main_files_estimate": len(files), "main_loc_estimate": total_loc,
           "existing_decompositions": existing, "proposals": proposals, "warnings": warnings}
    if args.output:
        Path(args.output).write_text(json.dumps(out, indent=2))
    print_summary(out, config_path)
    if args.output:
        print(f"\nwrote {args.output}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
