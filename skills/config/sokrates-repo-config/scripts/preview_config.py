#!/usr/bin/env python3
"""Preview what a Sokrates `_sokrates/config.json` will do — before running Sokrates.

Re-implements Sokrates' scoping rules (read from CodeConfiguration / SourceCodeFiles /
SourceCodeAspectUtils) and applies them to the real source tree:

  1. extension filter, size limits (maxFileSizeBytes / maxLines / maxLineLength), `ignore` rules
  2. scope classification with Sokrates' precedence: generated > other > test > build > main
  3. logical decompositions: folder-depth components (common-prefix stripping, minComponentsCount),
     explicit components, Unclassified / Multiple Classifications
  4. concerns matched against main files
  5. lint: regexes that do not compile (Sokrates silently treats them as non-matching), rules that
     match nothing, main files that look like tests/generated code, extensions present in the tree
     but absent from the config, oversized components, unknown keys

Usage:
  python3 preview_config.py <path/to/_sokrates/config.json> [--json out.json] [--samples 5]
                            [--max-files 200000] [--no-content]

Exit code: 0 ok, 1 when errors were found (malformed regex, missing srcRoot, invalid JSON).
Semantics notes: path patterns must match the ENTIRE path below the source root, with a leading
`/` (`/src/app/service.py` — the folders above the repository never take part; Sokrates builds
since 2026-10-02, earlier ones matched the whole path as loaded); content patterns must match an
ENTIRE line. Both are Java regexes; Python's `re` is
close enough for the patterns Sokrates uses, differences are reported as warnings.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

KNOWN_TOP_KEYS = {"metadata", "summary", "srcRoot", "extensions", "ignore", "main", "test", "generated",
                  "buildAndDeployment", "other", "logicalDecompositions", "concernGroups", "concerns",
                  "goalsAndControls", "fileHistoryAnalysis", "analysis", "tagRules", "customTabs"}
KNOWN_COAUTHOR_KEYS = {"enabled", "trailerKeys", "aiAgents"}
SCOPES = ["main", "test", "generated", "buildAndDeployment", "other"]
TESTLIKE_RE = re.compile(r"(^|/)(tests?|__tests__|spec|specs|e2e|mocks?|fixtures?|testdata)/|(_test|_tests|\.test|\.spec)\.|(^|/)test_|\.snap$", re.I)
GENLIKE_RE = re.compile(r"(^|/)(generated|__generated__|gen|build|dist|out|target|node_modules|vendor)/|\.generated\.|\.pb\.|\.min\.(js|css)$|package-lock\.json$|\.designer\.(cs|vb)$", re.I)
SKIP_DIRS = {".git", ".hg", ".svn"}


class Rule:
    """A compiled SourceFileFilter."""

    def __init__(self, owner, raw, index):
        self.owner = owner
        self.index = index
        self.path_pattern = raw.get("pathPattern", "") or ""
        self.content_pattern = raw.get("contentPattern", "") or ""
        self.exception = bool(raw.get("exception", False))
        self.note = raw.get("note", "") or ""
        self.path_re = self.content_re = None
        self.error = None
        self.hits = 0
        try:
            self.path_re = re.compile(self.path_pattern) if self.path_pattern.strip() else None
            self.content_re = re.compile(self.content_pattern) if self.content_pattern.strip() else None
        except re.error as e:
            self.error = str(e)

    def label(self):
        p = self.path_pattern or "(any path)"
        c = f" content={self.content_pattern!r}" if self.content_pattern else ""
        return f"{self.owner}[{self.index}] {p}{c}{' (exception)' if self.exception else ''}"

    def matches(self, full_path, lines_getter):
        if self.error:
            return False
        if self.path_re is not None:
            if not (self.path_re.fullmatch(full_path) or self.path_re.fullmatch(full_path.replace("\\", "/"))):
                return False
        if self.content_re is not None:
            lines = lines_getter()
            if lines is None:
                return False
            rx = self.content_re
            if not any(rx.fullmatch(ln) for ln in lines):
                return False
        self.hits += 1
        return True


def resolve_src_root(config_path: Path, src_root: str) -> Path:
    if src_root.startswith(".."):
        candidate = config_path.parent.parent / src_root[2:].lstrip("/\\")
    else:
        candidate = config_path.parent / src_root
    return candidate if candidate.exists() else Path(src_root)


def compile_rules(config, errors, warnings):
    rules = {}
    def add(owner, lst):
        out = []
        for i, raw in enumerate(lst or []):
            if not isinstance(raw, dict):
                errors.append(f"{owner}[{i}]: filter is not an object")
                continue
            r = Rule(owner, raw, i)
            if r.error:
                errors.append(f"{r.label()}: regex does not compile ({r.error}) — Sokrates would silently treat it as matching nothing")
            elif r.path_pattern and not re.match(r"^(\.\*|\(|\[|\^|\\)", r.path_pattern.strip()):
                warnings.append(f"{r.label()}: pathPattern does not start with `.*` — it must match the whole path below the source root (`/src/app/x.py`), so it will probably never match")
            out.append(r)
        return out
    rules["ignore"] = add("ignore", config.get("ignore"))
    for s in SCOPES:
        aspect = config.get(s) or {}
        rules[s] = add(s, aspect.get("sourceFileFilters"))
    return rules


def aspect_files(aspect_rules, explicit_files, candidates, full_path_of, lines_of):
    """Sokrates' SourceCodeFiles.getSourceFiles: explicit files or any inclusive match, minus any exception match."""
    explicit = set(explicit_files or [])
    out = set()
    for rel in candidates:
        included = rel in explicit
        excluded = False
        fp = full_path_of(rel)
        for r in aspect_rules:
            if r.matches(fp, lambda: lines_of(rel)):
                if r.exception:
                    excluded = True
                else:
                    included = True
        if included and not excluded:
            out.add(rel)
    return out


def folder_components(rel_paths, depth, min_count):
    """SourceCodeAspectUtils.getComponentsBasedOnFolderDepth, incl. common-prefix stripping and minComponentsCount."""
    if depth <= 0 and min_count <= 0:
        return {}
    start = max(1, depth)
    result = {}
    for d in range(start, 21):
        comps = defaultdict(set)
        names = {}
        for rel in rel_paths:
            parts = rel.split("/")
            folder = "/".join(parts[:min(d, len(parts) - 1)])
            names[rel] = folder
        # strip greatest common folder prefix
        distinct = set(names.values())
        prefix = os.path.commonprefix([n + "/" for n in distinct]) if len(distinct) > 1 else ""
        prefix = prefix[:prefix.rfind("/") + 1] if "/" in prefix else ""
        for rel, folder in names.items():
            name = folder[len(prefix):] if prefix and folder.startswith(prefix) else folder
            comps[name or "ROOT"].add(rel)
        result = dict(comps)
        if min_count <= 0 or len(result) >= min_count:
            break
    return result


def load_config(config_path, errors, warnings, notes):
    """The parsed configuration, or None after printing why it cannot be used; lints the keys Sokrates ignores."""
    try:
        config = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot read config: {e}")
        return None
    if not isinstance(config, dict):
        print("ERROR: config is not a JSON object")
        return None
    for k in config:
        if k not in KNOWN_TOP_KEYS:
            warnings.append(f"unknown top-level key `{k}` — Sokrates ignores unknown keys silently")
    if "concerns" in config and "concernGroups" not in config:
        notes.append("`concerns` is a legacy alias of `concernGroups` (accepted, rewritten on save)")
    analysis = config.get("analysis") or {}
    for k in ("trendAnalysis", "compareResultsWith", "excludeFiles", "maxFileSize"):
        if k in config or k in analysis:
            warnings.append(f"`{k}` is not a Sokrates field (documentation mentions it, the model does not) — it has no effect")
    return config


def matching_path(rel):
    return "/" + rel          # what Sokrates matches: the path below the source root, with a leading separator


def walk_tree(src_root, ext_set, max_files, warnings):
    """Every file under the source root: extension counts, the candidates with a configured extension, the excluded rest."""
    all_ext_counts = Counter()
    candidates = []          # relative paths passing the extension filter
    excluded = defaultdict(list)
    total_files = 0
    for root, dirs, files in os.walk(src_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            total_files += 1
            if total_files > max_files:
                break
            rel = os.path.relpath(os.path.join(root, fn), src_root).replace(os.sep, "/")
            ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
            all_ext_counts[ext] += 1
            if ext in ext_set:
                candidates.append(rel)
            else:
                excluded["extension"].append(rel)
    if total_files > max_files:
        warnings.append(f"stopped after {max_files} files (--max-files); counts are partial")
    return all_ext_counts, candidates, excluded, total_files


def broad_scope(candidates, src_root, limits, ignore_rules, line_cache, no_content, excluded):
    """Size limits then ignore rules, in SourceCodeFiles.createBroadScope order: the files Sokrates loads, and their LOC."""
    max_bytes, max_lines, max_line_len = limits
    broad = []
    loc = {}
    for rel in candidates:
        p = src_root / rel
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size > max_bytes:
            excluded[f"too large (> {max_bytes} bytes)"].append(rel); continue
        lines = None
        try:
            lines = p.read_text(errors="replace").split("\n")
        except OSError:
            continue
        if len(lines) > max_lines:
            excluded[f"too many lines (> {max_lines})"].append(rel); continue
        if any(len(ln) > max_line_len for ln in lines):
            excluded[f"too long lines (> {max_line_len} chars)"].append(rel); continue
        if not no_content:
            line_cache[rel] = lines
        loc[rel] = sum(1 for ln in lines if ln.strip())
        fp = matching_path(rel)
        ignored_by = next((r for r in ignore_rules if r.matches(fp, lambda: lines)), None)
        if ignored_by:
            excluded[f"ignore: {ignored_by.path_pattern or ignored_by.content_pattern}"].append(rel); continue
        broad.append(rel)
    return broad, loc


def line_reader(src_root, line_cache, no_content):
    def lines_of(rel):
        if no_content:
            return None
        if rel not in line_cache:
            try:
                line_cache[rel] = (src_root / rel).read_text(errors="replace").split("\n")
            except OSError:
                line_cache[rel] = None
        return line_cache[rel]
    return lines_of


def scope_files(config, rules, broad, lines_of):
    """The five scopes with Sokrates' precedence (generated > other > test > build > main)."""
    scope_sets = {}
    for s in SCOPES:
        aspect = config.get(s) or {}
        scope_sets[s] = aspect_files(rules[s], aspect.get("files"), broad, matching_path, lines_of)
    m, t, g, b, o = (scope_sets[s] for s in SCOPES)
    m -= t | g | b | o
    b -= o | g | t
    t -= o | g
    return scope_sets


def lint_scopes(rules, scope_sets, broad, warnings, notes):
    m, t, g, b, o = (scope_sets[s] for s in SCOPES)
    for s in SCOPES + ["ignore"]:
        for r in rules[s]:
            if not r.error and r.hits == 0:
                warnings.append(f"{r.label()}: matches no file — dead rule (harmless, but check the intent)")
    testlike_in_main = sorted(f for f in m if TESTLIKE_RE.search(f))
    genlike_in_main = sorted(f for f in m if GENLIKE_RE.search(f))
    if testlike_in_main:
        warnings.append(f"{len(testlike_in_main)} main files look like tests (e.g. {', '.join(testlike_in_main[:3])}) — add test filters?")
    if genlike_in_main:
        warnings.append(f"{len(genlike_in_main)} main files look generated/vendored (e.g. {', '.join(genlike_in_main[:3])}) — add generated/ignore filters?")
    overlap_go = g & o
    if overlap_go:
        notes.append(f"{len(overlap_go)} files are in both generated and other (Sokrates allows this overlap)")
    unscoped = set(broad) - (m | t | g | b | o)
    if unscoped:
        warnings.append(f"{len(unscoped)} files pass ignore but land in no scope (main has no `.*` filter?)")


def compile_filters(label, raws, errors):
    rules = []
    for j, raw in enumerate(raws or []):
        r = Rule(label, raw, j); rules.append(r)
        if r.error: errors.append(f"{r.label()}: regex does not compile ({r.error})")
    return rules


def component_row(name, files, loc, total_loc, samples):
    c_loc = sum(loc.get(f, 0) for f in files)
    return {"name": name, "files": len(files), "loc": c_loc, "loc_share_pct": round(100 * c_loc / total_loc, 1), "samples": sorted(files)[:samples]}


def decomposition_report(d, scope_sets, loc, lines_of, samples, errors, warnings):
    """One logical decomposition applied as Sokrates does: filters, folder-depth components, explicit components,
    Unclassified and Multiple Classifications, plus the lints on the result."""
    scope_name = str(d.get("scope", "main")).lower().replace(" ", "")
    scope_key = {"main": "main", "test": "test", "generated": "generated", "buildanddeployment": "buildAndDeployment", "other": "other"}.get(scope_name, "main")
    base = set(scope_sets[scope_key])
    d_rules = compile_filters(f"decomposition {d.get('name')}.filters", d.get("filters"), errors)
    in_scope = base
    remaining = set()
    if d_rules:
        in_scope = {f for f in base if any(r.matches(matching_path(f), lambda: lines_of(f)) and not r.exception for r in d_rules)}
        in_scope -= {f for f in base if any(r.matches(matching_path(f), lambda: lines_of(f)) and r.exception for r in d_rules)}
        if d.get("includeRemainingFiles", True):
            remaining = base - in_scope
    comps = folder_components(in_scope, int(d.get("componentsFolderDepth", 1)), int(d.get("minComponentsCount", 0)))
    for i, c in enumerate(d.get("components") or []):
        c_rules = compile_filters(f"component {c.get('name')}", c.get("sourceFileFilters"), errors)
        files = aspect_files(c_rules, c.get("files"), in_scope, matching_path, lines_of)
        comps[c.get("name") or f"component-{i}"] = set(files) | comps.get(c.get("name"), set())
        for r in c_rules:
            if not r.error and r.hits == 0:
                warnings.append(f"{r.label()}: matches no file in scope `{scope_key}`")
    membership = Counter()
    for files in comps.values():
        for f in files:
            membership[f] += 1
    multiple = {f for f, n in membership.items() if n > 1}
    unclassified = (in_scope - set(membership)) | remaining
    total_loc = sum(loc.get(f, 0) for f in in_scope) or 1
    comp_rows = []
    for name, files in sorted(comps.items(), key=lambda kv: -sum(loc.get(f, 0) for f in kv[1])):
        files = files - multiple
        if files:
            comp_rows.append(component_row(name, files, loc, total_loc, samples))
    if unclassified:
        comp_rows.append(component_row("Unclassified", unclassified, loc, total_loc, samples))
    if multiple:
        comp_rows.append(component_row("Multiple Classifications", multiple, loc, total_loc, samples))
    dname = d.get("name", "?")
    real = [c for c in comp_rows if c["name"] not in ("Unclassified", "Multiple Classifications")]
    if len(real) == 1:
        warnings.append(f"decomposition `{dname}`: a single component ({real[0]['name']}) — raise componentsFolderDepth or add explicit components")
    if len(real) > 40:
        warnings.append(f"decomposition `{dname}`: {len(real)} components — diagrams will be unreadable; lower the depth or group with explicit components")
    if real and real[0]["loc_share_pct"] > 60 and len(real) > 1:
        warnings.append(f"decomposition `{dname}`: `{real[0]['name']}` holds {real[0]['loc_share_pct']}% of LOC — consider splitting it")
    if unclassified and len(unclassified) * 10 > max(1, len(in_scope)):
        warnings.append(f"decomposition `{dname}`: {len(unclassified)} files Unclassified ({round(100*len(unclassified)/max(1,len(in_scope)))}%)")
    if multiple:
        warnings.append(f"decomposition `{dname}`: {len(multiple)} files match several components — add exception filters so components are disjoint")
    return {"name": dname, "scope": scope_key, "componentsFolderDepth": d.get("componentsFolderDepth", 1),
            "files_in_scope": len(in_scope), "components": comp_rows,
            "real_components": len(real), "multiple_classifications": len(multiple), "unclassified": len(unclassified)}


def derive_name(value, ops):
    """A meta-rule's nameOperations as MetaRulesProcessor + ComplexOperation apply them (extract = whole first match)."""
    for op, params in ops:
        if op == "extract" and params:
            mm = re.search(params[0], value); value = mm.group(0) if mm else ""
        elif op == "remove" and params:
            value = re.sub(params[0], "", value)
        elif op == "replace" and len(params) >= 2:
            value = re.sub(params[0], params[1], value)
        elif op == "trim":
            value = value.strip()
        elif op == "lowercase":
            value = value.lower()
        elif op == "uppercase":
            value = value.upper()
        elif op == "append" and params:
            value = value + params[0]
        elif op == "prepend" and params:
            value = params[0] + value
    return value


def meta_concern_report(group_name, mi, mr, main_files, lines_of, errors, warnings):
    """The names a meta concern derives from the main files; None when one of its regexes does not compile."""
    ops = [(str(o.get("op", "")).lower(), o.get("params") or []) for o in mr.get("nameOperations") or []]
    try:
        cre = re.compile(mr.get("contentPattern") or "") if (mr.get("contentPattern") or "").strip() else None
        pre = re.compile(mr.get("pathPattern") or "") if (mr.get("pathPattern") or "").strip() else None
        for op, params in ops:
            if op in ("extract", "remove", "replace") and params:
                re.compile(params[0])
    except re.error as e:
        errors.append(f"metaConcern {group_name}[{mi}]: regex does not compile ({e})")
        return None
    names = Counter()
    use_path = str(mr.get("use", "content")).lower() == "path"
    for f in main_files:
        if pre is not None and not pre.fullmatch(matching_path(f)):
            continue
        if use_path:
            nm = derive_name(f, ops)
            if nm: names[nm] += 1
            continue
        if cre is None:
            continue
        for ln in (lines_of(f) or []):
            if cre.fullmatch(ln):
                nm = derive_name(ln, ops)
                if nm: names[nm] += 1
                break
    if not names:
        warnings.append(f"metaConcern {group_name}[{mi}] derives no names — check contentPattern and nameOperations (extract keeps the whole match)")
    elif any(len(n) > 60 for n in names):
        warnings.append(f"metaConcern {group_name}[{mi}] derives very long names (e.g. `{max(names, key=len)[:70]}…`) — `extract` returns the whole match; narrow its regex or add a `remove`/`replace` op")
    return {"group": group_name, "concern": f"[meta {mi}] {len(names)} derived names", "files": sum(names.values()),
            "loc": 0, "loc_pct": 0.0, "samples": [f"{n} ({k})" for n, k in names.most_common(8)]}


def concerns_report(config, main_files, loc, lines_of, samples, errors, warnings):
    """Every concern and meta concern matched against the main scope."""
    out = []
    main_sorted = sorted(main_files)
    main_loc = max(1, sum(loc.get(f, 0) for f in main_files))
    for grp in config.get("concernGroups") or config.get("concerns") or []:
        for c in grp.get("concerns") or []:
            c_rules = compile_filters(f"concern {c.get('name')}", c.get("sourceFileFilters"), errors)
            files = aspect_files(c_rules, c.get("files"), main_sorted, matching_path, lines_of)
            c_loc = sum(loc.get(f, 0) for f in files)
            out.append({"group": grp.get("name"), "concern": c.get("name"), "files": len(files),
                        "loc": c_loc, "loc_pct": round(100 * c_loc / main_loc, 1), "samples": sorted(files)[:samples]})
            if not files:
                warnings.append(f"concern `{c.get('name')}` matches no main file")
            elif len(files) * 100 > 60 * max(1, len(main_files)):
                warnings.append(f"concern `{c.get('name')}` matches {round(100*len(files)/max(1,len(main_files)))}% of main files — a property of the codebase rather than a feature of interest; narrow it")
        for mi, mr in enumerate(grp.get("metaConcerns") or []):
            row = meta_concern_report(grp.get("name"), mi, mr, main_sorted, lines_of, errors, warnings)
            if row is not None:
                out.append(row)
    return out


def lint_history_and_tabs(config, config_path, warnings, notes):
    """The co-author settings, the custom tabs, and whether the git history import exists."""
    fha = config.get("fileHistoryAnalysis") or {}
    co = fha.get("coAuthors")
    if isinstance(co, dict):
        for k in co:
            if k not in KNOWN_COAUTHOR_KEYS:
                warnings.append(f"fileHistoryAnalysis.coAuthors: unknown key `{k}` (known: enabled, trailerKeys, aiAgents)")
        if "aiAgents" in co and len(co.get("aiAgents") or []) < 5:
            warnings.append("fileHistoryAnalysis.coAuthors.aiAgents replaces the built-in list (Claude Code, Copilot, Cursor, Codex, Aider, Gemini, Devin, Jules) — a short list drops the others")
        for a in co.get("aiAgents") or []:
            if not isinstance(a, dict) or not a.get("name") or not a.get("patterns"):
                warnings.append("fileHistoryAnalysis.coAuthors.aiAgents entries need `name` and `patterns`")
    for i, tab in enumerate(config.get("customTabs") or []):
        if not isinstance(tab, dict) or not str(tab.get("label", "")).strip() or not str(tab.get("iframeLink", "")).strip():
            warnings.append(f"customTabs[{i}]: label and iframeLink are both required — Sokrates skips blank entries")
        elif str(tab.get("iframeLink")).startswith("../../findings/"):
            warnings.append(f"customTabs[{i}]: iframeLink points at the old findings/ location — AI insights now live in reports/ai-insights (use ../ai-insights/index.html)")
    labels = [str(t.get("label", "")).strip().lower() for t in (config.get("customTabs") or []) if isinstance(t, dict)]
    if len(labels) != len(set(labels)):
        warnings.append("customTabs: duplicate labels (compared trimmed, case-insensitively) — addCustomTab would overwrite, a hand edit leaves both")
    import_path = fha.get("importPath", "../git-history.txt")
    history_file = (config_path.parent / import_path)
    history = {"importPath": import_path, "exists": history_file.is_file(),
               "size": history_file.stat().st_size if history_file.is_file() else 0}
    if not history["exists"]:
        notes.append(f"no git history at {history_file} — churn/contributor analyses will be skipped (run `sokrates extractGitHistory` in the repo)")
    return history


def print_brief(out, config_path):
    scopes_line = ", ".join(f"{name} {s['files']} files/{s['loc']} LOC" for name, s in out["scopes"].items())
    print(f"Sokrates config preview — {config_path}: {scopes_line}")
    for e in out["errors"]:
        print(f"ERROR: {e}")
    for w in out["warnings"]:
        print(f"warning: {w}")


def print_report(out, config_path):
    print(f"Sokrates config preview — {config_path}")
    print(f"srcRoot: {out['srcRoot']}   extensions: {', '.join(out['extensions'])}")
    tr = out["tree"]
    print(f"files in tree: {tr['files_total']}  with configured extension: {tr['files_with_configured_extension']}  "
          f"in broad scope: {tr['files_in_broad_scope']} ({tr['loc_in_broad_scope']} LOC)")
    print("\nExcluded:")
    for k, v in sorted(out["excluded"].items(), key=lambda kv: -kv[1]["files"]):
        print(f"  {v['files']:>7}  {k}   e.g. {', '.join(v['samples'][:2])}")
    missing_ext = out["extensions_in_tree_not_configured"]
    if missing_ext:
        print("\nExtensions present in the tree but not configured (files): " + ", ".join(f"{e} ({n})" for e, n in missing_ext))
    print("\nScopes:")
    for s in SCOPES:
        r = out["scopes"][s]
        print(f"  {s:<19} {r['files']:>7} files {r['loc']:>9} LOC   top: {', '.join(f'{e}:{n}' for e, n in r['top_extensions'][:5])}")
        for smp in r["samples"][:3]:
            print(f"      {smp}")
    for d in out["decompositions"]:
        print(f"\nDecomposition `{d['name']}` (scope {d['scope']}, depth {d['componentsFolderDepth']}, {d['files_in_scope']} files):")
        for c in d["components"][:40]:
            print(f"  {c['name']:<40} {c['files']:>6} files {c['loc']:>9} LOC {c['loc_share_pct']:>5}%   e.g. {c['samples'][0] if c['samples'] else ''}")
        if len(d["components"]) > 40:
            print(f"  … {len(d['components']) - 40} more")
        print(f"  → {d['real_components']} components, disjoint: {'yes' if not d['multiple_classifications'] else 'NO (' + str(d['multiple_classifications']) + ' files in several)'}, unclassified: {d['unclassified']}")
    if out["concerns"]:
        print("\nConcerns (matched against main):")
        for c in out["concerns"]:
            ex = ", ".join(c["samples"][:4]) if c["concern"].startswith("[meta") else (c["samples"][0] if c["samples"] else "-")
            print(f"  {c['group']}/{c['concern']:<40} {c['files']:>6} files {c['loc']:>9} LOC {c['loc_pct']:>5}%   e.g. {ex}")
    history = out["history"]
    print(f"\nGit history: {history['importPath']} — {'found' if history['exists'] else 'MISSING'}")
    for level, items in (("ERROR", out["errors"]), ("WARNING", out["warnings"]), ("note", out["notes"])):
        for it in items:
            print(f"{level}: {it}")
    print(f"\n{'FAILED' if out['errors'] else 'OK'}: {len(out['errors'])} errors, {len(out['warnings'])} warnings")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("--json", help="write the full preview as JSON here")
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--max-files", type=int, default=200000)
    ap.add_argument("--no-content", action="store_true", help="skip content-pattern matching (fast, but content rules are treated as non-matching)")
    ap.add_argument("--brief", action="store_true", help="print only the scope counts, errors and warnings (what an agent needs mid-task)")
    args = ap.parse_args()

    errors, warnings, notes = [], [], []
    config_path = Path(args.config)
    config = load_config(config_path, errors, warnings, notes)
    if config is None:
        return 1
    analysis = config.get("analysis") or {}
    src_root_raw = config.get("srcRoot", "..")
    src_root = resolve_src_root(config_path, src_root_raw)
    if not src_root.is_dir():
        print(f"ERROR: srcRoot `{src_root_raw}` resolves to {src_root}, which does not exist")
        return 1
    extensions = [e.lower() for e in (config.get("extensions") or [])]
    if not extensions:
        errors.append("`extensions` is empty — Sokrates would analyse nothing")
    limits = (int(analysis.get("maxFileSizeBytes", 1000000)), int(analysis.get("maxLines", 10000)), int(analysis.get("maxLineLength", 1000)))
    rules = compile_rules(config, errors, warnings)

    all_ext_counts, candidates, excluded, total_files = walk_tree(src_root, set(extensions), args.max_files, warnings)
    line_cache = {}
    lines_of = line_reader(src_root, line_cache, args.no_content)
    broad, loc = broad_scope(candidates, src_root, limits, rules["ignore"], line_cache, args.no_content, excluded)
    scope_sets = scope_files(config, rules, broad, lines_of)
    lint_scopes(rules, scope_sets, broad, warnings, notes)
    main_files = scope_sets["main"]

    def scope_report(files):
        exts = Counter(f.rsplit(".", 1)[-1].lower() if "." in f else "" for f in files)
        return {"files": len(files), "loc": sum(loc.get(f, 0) for f in files),
                "top_extensions": sorted(exts.items(), key=lambda kv: (-kv[1], kv[0]))[:8],   # ties by name: the same output on every run
                "samples": sorted(files)[:args.samples]}

    out = {
        "config": str(config_path), "srcRoot": str(src_root), "extensions": extensions,
        "tree": {"files_total": total_files, "files_with_configured_extension": len(candidates),
                 "files_in_broad_scope": len(broad), "loc_in_broad_scope": sum(loc[f] for f in broad)},
        "excluded": {k: {"files": len(v), "samples": sorted(v)[:args.samples]} for k, v in excluded.items()},
        "extensions_in_tree_not_configured": [(e, n) for e, n in all_ext_counts.most_common() if e and e not in set(extensions) and n >= 5][:15],
        "scopes": {s: scope_report(scope_sets[s]) for s in SCOPES},
        "decompositions": [decomposition_report(d, scope_sets, loc, lines_of, args.samples, errors, warnings) for d in config.get("logicalDecompositions") or []],
        "concerns": concerns_report(config, main_files, loc, lines_of, args.samples, errors, warnings),
        "history": lint_history_and_tabs(config, config_path, warnings, notes),
        "errors": errors, "warnings": warnings, "notes": notes,
    }
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2))
    if args.brief:
        print_brief(out, config_path)
    else:
        print_report(out, config_path)
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(main())
