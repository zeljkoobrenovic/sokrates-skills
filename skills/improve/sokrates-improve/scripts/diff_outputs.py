#!/usr/bin/env python3
"""Prove a refactoring on its outputs: compare two folders of generated files (Sokrates reports, data zips, or any
JSON/text/HTML a tool writes) and report every difference that is not a timestamp or a timing.

  diff_outputs.py <before-folder> <after-folder> [--ignore <glob> ...] [--volatile-key <name> ...]

Both folders are walked recursively; every file present in either is compared:
  *.html      text compared after the timestamps are masked; a Sokrates page that embeds a base64 zip
              (`var SOKRATES_ARCHIVE = "..."`, the viewers, visuals and contributor pages) has that archive
              extracted and compared entry by entry, so a changed source snippet or chart is named, not hidden
              in one giant line
  *.zip       compared entry by entry (nested zips by byte)
  *.json      compared as canonical JSON (key order ignored, volatile keys dropped), also inside zips
  *.txt, .md  compared as text with dates masked, also inside zips
  other       compared by bytes
Timings and timestamps are masked by default (`generated on …`, `<i>2026-…</i>`, `analysisStartTimeMs`,
`startMs`/`endMs`/`durationMs`, `timestamp`, `TOTAL_ANALYSIS_TIME…` lines); Sokrates' executionTimes.*,
text/metrics.txt and text/textualSummary.txt carry only timings and are ignored. Exit code 0 when the
outputs are equivalent, 1 when they differ (each difference printed as `path [entry]`), 2 on a usage error.

The recipe (sokrates-improve step 6): build the program as it was before the change, generate the outputs
on a fixed input, change the code, build and generate again into a second folder, then run this script.
The tests prove the cases someone thought of; the output diff proves everything the input exercises.
"""
import argparse
import base64
import fnmatch
import io
import json
import re
import sys
import zipfile
from pathlib import Path

VOLATILE_KEYS = {"timestamp", "analysisStartTimeMs", "startMs", "endMs", "durationMs", "analyzed_at", "generatedAt"}
IGNORED = ["executionTimes.json", "executionTimes.txt", "text/metrics.txt", "text/textualSummary.txt", "metrics.txt", "textualSummary.txt"]
TEXT_SUFFIXES = (".txt", ".md", ".csv", ".tsv")
ARCHIVE_RE = re.compile(r'SOKRATES_ARCHIVE = "([A-Za-z0-9+/=]{40,})"')
DATE_RE = re.compile(r"\d{4}-\d\d-\d\d[ T]\d\d:\d\d(:\d\d)?")


def mask_text(text):
    text = re.sub(r"(generated on|updated on|analyzed on|analysed on)[^<\n]*", r"\1", text, flags=re.I)
    text = re.sub(r"<i>\d{4}-\d\d-\d\d \d\d:\d\d</i>", "<i>date</i>", text)
    text = re.sub(r"TOTAL_ANALYSIS_TIME[^<\n]*", "TOTAL_ANALYSIS_TIME", text)
    # the analysis-time metric's value, wherever a metrics table shows it (the name, some markup, the number)
    text = re.sub(r"(TOTAL_ANALYSIS_TIME(?:(?!\d).){0,400}?)\d+", r"\1N", text, flags=re.S)
    return DATE_RE.sub("DATE", text)


def strip_volatile(doc, volatile):
    if isinstance(doc, dict):
        if "value" in doc and "TIME" in str(doc.get("id", "")).upper():
            doc = {k: v for k, v in doc.items() if k != "value"}     # a timing metric (TOTAL_ANALYSIS_TIME_IN_MILLIS): its value is noise
        return {k: strip_volatile(v, volatile) for k, v in doc.items() if k not in volatile}
    if isinstance(doc, list):
        return [strip_volatile(x, volatile) for x in doc]
    return doc


def canonical(name, data, volatile, nested=False):
    """One comparable value for a file or zip entry: canonical JSON, masked text, or the bytes. An HTML page found inside
    an archive is compared as masked text (its own embedded archive is not opened again: a data preview folded into a
    data zip would otherwise nest without end)."""
    lower = name.lower()
    if lower.endswith(".json"):
        try:
            return json.dumps(strip_volatile(json.loads(data.decode("utf-8")), volatile), sort_keys=True)
        except (ValueError, UnicodeDecodeError):
            return data
    if lower.endswith(TEXT_SUFFIXES):
        return mask_text(data.decode("utf-8", errors="replace"))
    if lower.endswith(".html"):
        html = data.decode("utf-8", errors="replace")
        return mask_text(ARCHIVE_RE.sub('SOKRATES_ARCHIVE = "<archive>"', html)) if nested else html_parts(html, volatile)
    if lower.endswith(".zip"):
        return zip_parts(data, volatile)
    return data


def zip_parts(data, volatile):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return data
    return {name: canonical(name, archive.read(name), volatile, nested=True) for name in archive.namelist() if not name.endswith("/")}


def html_parts(html, volatile):
    """The page text (timestamps masked, embedded archives replaced by a marker) plus each embedded archive entry."""
    parts = {}

    def extract(match):
        try:
            archive = zipfile.ZipFile(io.BytesIO(base64.b64decode(match.group(1))))
            for name in archive.namelist():
                parts["archive:" + name] = canonical(name, archive.read(name), volatile, nested=True)
        except Exception as e:  # noqa: BLE001 - a broken archive is itself a difference worth naming
            parts["archive:<unreadable>"] = str(e)
        return 'SOKRATES_ARCHIVE = "<archive>"'

    parts["page"] = mask_text(ARCHIVE_RE.sub(extract, html))
    return parts


def differences(a, b, label=""):
    """The names of the parts that differ between two canonical values (empty when equivalent)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            if key not in a:
                out.append(f"{label}{key} (only after)")
            elif key not in b:
                out.append(f"{label}{key} (only before)")
            else:
                out.extend(differences(a[key], b[key], f"{label}{key}: "))
        return out
    return [] if a == b else [label.rstrip(": ") or "content"]


def ignored(relative, patterns):
    return any(fnmatch.fnmatch(relative, p) or relative.endswith(p) for p in patterns)


def compare_folders(before, after, ignore, volatile):
    files = {p.relative_to(before).as_posix() for p in before.rglob("*") if p.is_file()} | \
            {p.relative_to(after).as_posix() for p in after.rglob("*") if p.is_file()}
    report = []
    for relative in sorted(files):
        if ignored(relative, ignore):
            continue
        x, y = before / relative, after / relative
        if not x.exists():
            report.append((relative, ["only after"]))
            continue
        if not y.exists():
            report.append((relative, ["only before"]))
            continue
        a = canonical(relative, x.read_bytes(), volatile)
        b = canonical(relative, y.read_bytes(), volatile)
        diffs = [d for d in differences(a, b) if not ignored(d.split(" (")[0].replace("archive:", ""), ignore)]
        if diffs:
            report.append((relative, diffs))
    return len(files), report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--ignore", action="append", default=[], help="a file or entry name (or glob) to skip, besides the timing files")
    parser.add_argument("--volatile-key", action="append", default=[], help="a JSON key to drop before comparing, besides the timing keys")
    args = parser.parse_args()
    before, after = Path(args.before), Path(args.after)
    if not before.is_dir() or not after.is_dir():
        print(f"ERROR: both arguments must be folders ({before}, {after})", file=sys.stderr)
        return 2
    total, report = compare_folders(before, after, IGNORED + args.ignore, VOLATILE_KEYS | set(args.volatile_key))
    for relative, diffs in report:
        shown = ", ".join(diffs[:6]) + (f", … {len(diffs) - 6} more" if len(diffs) > 6 else "")
        print(f"DIFFERS: {relative} [{shown}]")
    print(f"{len(report)} of {total} files differ (timestamps, timings and JSON key order ignored; embedded archives compared entry by entry)")
    return 1 if report else 0


if __name__ == "__main__":
    sys.exit(main())
