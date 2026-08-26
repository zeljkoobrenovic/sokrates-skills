#!/usr/bin/env python3
"""Validate a Sokrates AI scanner findings file.

Checks two things:
  1. Structure: the file conforms to the common findings schema
     (hand-rolled checks, no external dependencies).
  2. Evidence: every cited snippet actually occurs at the cited
     file/line range under --src-root. This is the hallucination guard:
     a finding whose evidence does not verify is reported as FAILED.

Usage:
  python3 validate_findings.py <findings.json> [--src-root <path>] [--json]

Without --src-root, the source root is taken from the document's
target.src_root, resolved relative to the findings file's directory.

Exit codes: 0 = all findings valid, 1 = validation errors, 2 = bad invocation.
"""

import argparse
import json
import re
import sys
from pathlib import Path

SEVERITIES = ["info", "low", "medium", "high", "critical"]
CONFIDENCES = ["certain", "likely", "possible"]
TOP_REQUIRED = ["scanner", "scanner_version", "analyzed_at", "target", "summary", "findings"]
FINDING_REQUIRED = ["id", "group", "title", "description", "severity", "confidence", "evidence"]
EVIDENCE_REQUIRED = ["file", "start_line", "end_line", "snippet"]
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*/[a-z0-9]+(-[a-z0-9]+)*/[a-z0-9._+]+(-[a-z0-9._+]+)*$")


def norm(text: str) -> str:
    """Collapse all whitespace so formatting differences don't fail verification."""
    return re.sub(r"\s+", " ", text).strip()


def check_structure(doc, errors):
    if not isinstance(doc, dict):
        errors.append("top-level: not a JSON object")
        return []
    for key in TOP_REQUIRED:
        if key not in doc:
            errors.append(f"top-level: missing required field '{key}'")
    target = doc.get("target")
    if isinstance(target, dict):
        for key in ("name", "src_root"):
            if key not in target:
                errors.append(f"target: missing required field '{key}'")
    elif target is not None:
        errors.append("target: must be an object")
    findings = doc.get("findings")
    if not isinstance(findings, list):
        errors.append("findings: must be an array")
        return []

    seen_ids = set()
    for i, f in enumerate(findings):
        where = f"findings[{i}]"
        if not isinstance(f, dict):
            errors.append(f"{where}: not an object")
            continue
        for key in FINDING_REQUIRED:
            if key not in f:
                errors.append(f"{where}: missing required field '{key}'")
        fid = f.get("id", "")
        if fid:
            where = f"findings[{i}] ({fid})"
            if not ID_RE.match(fid):
                errors.append(f"{where}: id does not match <scanner>/<group>/<slug> pattern")
            if fid in seen_ids:
                errors.append(f"{where}: duplicate id")
            seen_ids.add(fid)
            group = f.get("group", "")
            if doc.get("scanner") == "combined":
                # Merged documents (merge_findings.py) keep each finding's
                # original <source-scanner>/<group>/<slug> id — provenance and
                # cross-run diffability depend on it. Require only that the
                # group segment still matches.
                if group and f"/{group}/" not in fid:
                    errors.append(f"{where}: id should be '<source-scanner>/{group}/<slug>'")
            elif group and not fid.startswith(f"{doc.get('scanner', '')}/{group}/"):
                errors.append(f"{where}: id should be '{doc.get('scanner')}/{group}/<slug>'")
        if f.get("severity") not in SEVERITIES:
            errors.append(f"{where}: severity must be one of {SEVERITIES}")
        if f.get("confidence") not in CONFIDENCES:
            errors.append(f"{where}: confidence must be one of {CONFIDENCES}")
        evidence = f.get("evidence")
        if not isinstance(evidence, list):
            errors.append(f"{where}: evidence must be an array")
            continue
        if len(evidence) == 0 and f.get("confidence") != "possible" and not f.get("sokrates_refs"):
            errors.append(f"{where}: has no evidence, so it needs confidence 'possible' "
                          f"or grounding in sokrates_refs")
        for j, ev in enumerate(evidence):
            if not isinstance(ev, dict):
                errors.append(f"{where}.evidence[{j}]: not an object")
                continue
            for key in EVIDENCE_REQUIRED:
                if key not in ev:
                    errors.append(f"{where}.evidence[{j}]: missing required field '{key}'")
            sl, el = ev.get("start_line"), ev.get("end_line")
            if isinstance(sl, int) and isinstance(el, int) and sl > el:
                errors.append(f"{where}.evidence[{j}]: start_line > end_line")
    return findings


def verify_evidence(findings, src_root: Path, errors, warnings):
    """Check every snippet against the actual file content. Returns per-finding results."""
    file_cache = {}
    results = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        fid = f.get("id", "<no id>")
        finding_ok = True
        for j, ev in enumerate(f.get("evidence") or []):
            if not isinstance(ev, dict) or any(k not in ev for k in EVIDENCE_REQUIRED):
                finding_ok = False
                continue
            rel = ev["file"]
            path = src_root / rel
            if rel not in file_cache:
                try:
                    # Split on newlines only: str.splitlines() also breaks on form feeds and other
                    # exotic separators, which would shift line numbers relative to editors/grep.
                    file_cache[rel] = [ln.rstrip("\r") for ln in path.read_text(errors="replace").split("\n")]
                except OSError:
                    file_cache[rel] = None
            lines = file_cache[rel]
            where = f"{fid}.evidence[{j}]"
            if lines is None:
                errors.append(f"{where}: file not found: {rel}")
                finding_ok = False
                continue
            sl, el = ev["start_line"], ev["end_line"]
            if not (isinstance(sl, int) and isinstance(el, int)) or sl < 1 or el > len(lines) or sl > el:
                errors.append(f"{where}: line range {sl}-{el} invalid for {rel} ({len(lines)} lines)")
                finding_ok = False
                continue
            cited = norm(" ".join(lines[sl - 1:el]))
            snippet = norm(ev["snippet"])
            if snippet not in cited:
                # Line drift help: search the whole file for the snippet's first line.
                first = norm(ev["snippet"].strip().splitlines()[0])
                hit = next((n for n, line in enumerate(lines, 1) if first and first in norm(line)), None)
                hint = f" (snippet found near line {hit} instead)" if hit else " (snippet not found anywhere in file)"
                errors.append(f"{where}: snippet does not match {rel}:{sl}-{el}{hint}")
                finding_ok = False
        if not f.get("evidence"):
            basis = "sokrates_refs-grounded" if f.get("sokrates_refs") else "confidence 'possible'"
            warnings.append(f"{fid}: no file/line evidence attached ({basis})")
        results.append({"id": fid, "verified": finding_ok, "evidence_count": len(f.get("evidence") or [])})
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("findings_file")
    ap.add_argument("--src-root", help="Directory that evidence file paths are relative to "
                    "(default: target.src_root resolved against the findings file's directory)")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable report on stdout")
    args = ap.parse_args()

    findings_path = Path(args.findings_file)
    try:
        doc = json.loads(findings_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: cannot read findings file: {e}", file=sys.stderr)
        return 2

    if args.src_root:
        src_root = Path(args.src_root)
    else:
        declared = doc.get("target", {}).get("src_root") if isinstance(doc.get("target"), dict) else None
        if not declared:
            print("error: no --src-root given and no target.src_root in the findings file", file=sys.stderr)
            return 2
        src_root = (findings_path.parent / declared).resolve()
    if not src_root.is_dir():
        print(f"error: src root is not a directory: {src_root}", file=sys.stderr)
        return 2

    errors, warnings = [], []
    findings = check_structure(doc, errors)
    results = verify_evidence(findings, src_root, errors, warnings)

    verified = sum(1 for r in results if r["verified"])
    report = {
        "findings_total": len(results),
        "findings_verified": verified,
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for e in errors:
            print(f"ERROR   {e}")
        for w in warnings:
            print(f"WARNING {w}")
        status = "OK" if not errors else "FAILED"
        print(f"{status}: {verified}/{len(results)} findings fully verified, "
              f"{len(errors)} errors, {len(warnings)} warnings")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
