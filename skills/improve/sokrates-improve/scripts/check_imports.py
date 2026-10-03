#!/usr/bin/env python3
"""Flag unused imports in the files a change touched (Java and Python), before the change is measured.

  check_imports.py [<file> ...] [--base <git ref>]

Without files, the changed and new files of the working tree are checked: `git diff --name-only <base>` (default
base: the merge base with the default branch, else HEAD) plus untracked files. A class extracted from a bigger file
tends to inherit that file's whole import list; this names every import whose simple name the file never uses, so the
cleanup happens in the same change. Heuristic, not a compiler: a wildcard import, a static import whose member is used,
or a name used only in a comment is judged by text. Exit code 1 when anything is flagged, 0 when the files are clean.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

JAVA_IMPORT = re.compile(r"^import\s+(static\s+)?([\w.]+)\.(\w+|\*)\s*;", re.M)
PY_IMPORT = re.compile(r"^(?:from\s+[\w.]+\s+import\s+(.+)|import\s+(.+))$", re.M)


def strip_comments(text, suffix):
    """The code without its comments, string literals kept as is: a `/*`, `//` or `#` inside a string is not a comment."""
    out = []
    i, n = 0, len(text)
    line_comment, block_open, block_close = ("//", "/*", "*/") if suffix == ".java" else ("#", None, None)
    while i < n:
        c = text[i]
        if c in "\"'":
            quote = text[i:i + 3] if suffix == ".py" and text[i:i + 3] in ('"""', "\'\'\'") else c
            j = i + len(quote)
            while j < n and text[j:j + len(quote)] != quote:
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + len(quote)])
            i = j + len(quote)
        elif text.startswith(line_comment, i):
            while i < n and text[i] != "\n":
                i += 1
        elif block_open and text.startswith(block_open, i):
            end = text.find(block_close, i + 2)
            i = n if end < 0 else end + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def used(name, body):
    return re.search(r"(?<![\w.])" + re.escape(name) + r"\b", body) is not None


def unused_java(text):
    body = strip_comments(JAVA_IMPORT.sub("", text), ".java")
    out = []
    for static, package, name in JAVA_IMPORT.findall(text):
        if name == "*":
            continue
        if not used(name, body):
            out.append(f"import {'static ' if static else ''}{package}.{name}")
    return out


def unused_python(text):
    body = strip_comments(PY_IMPORT.sub("", text), ".py")
    out = []
    for from_names, plain_names in PY_IMPORT.findall(text):
        names = from_names or plain_names
        if names.strip() == "*":
            continue
        for item in re.split(r"\s*,\s*", names.strip().strip("()")):
            item = item.strip()
            if not item:
                continue
            alias = item.split(" as ")[-1].strip() if " as " in item else item.split(".")[0].strip()
            if alias and not used(alias, body):
                out.append(f"{'from … import ' if from_names else 'import '}{item}")
    return out


def check(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".java":
        return unused_java(text)
    if path.suffix == ".py":
        return unused_python(text)
    return []


def changed_files(base):
    def git(*args):
        return subprocess.run(["git", *args], capture_output=True, text=True).stdout.split()
    if not base:
        for candidate in ("origin/main", "origin/master", "main", "master"):
            merge_base = subprocess.run(["git", "merge-base", "HEAD", candidate], capture_output=True, text=True)
            if merge_base.returncode == 0:
                base = merge_base.stdout.strip()
                break
    files = set(git("diff", "--name-only", base or "HEAD")) | set(git("ls-files", "--others", "--exclude-standard"))
    return sorted(Path(f) for f in files if f.endswith((".java", ".py")) and Path(f).is_file())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*")
    parser.add_argument("--base", help="the git ref the changed files are listed against (default: the merge base with the default branch)")
    args = parser.parse_args()
    files = [Path(f) for f in args.files] if args.files else changed_files(args.base)
    flagged = 0
    for path in files:
        if not path.is_file():
            print(f"ERROR: {path} is not a file", file=sys.stderr)
            return 2
        for item in check(path):
            print(f"{path}: unused {item}")
            flagged += 1
    print(f"{flagged} unused import(s) in {len(files)} file(s)")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
