#!/usr/bin/env python3
"""Shared reader for the Sokrates analysis a repository keeps under `_sokrates/`.

Reads `reports/data/data.zip` (or the loose `reports/data/` files of older analyses) and the
optional `reports/ai-insights/<scanner>.json` findings. Standard library only.
"""

import json
import os
import re
import zipfile
from pathlib import Path


class SokratesData:
    def __init__(self, sokrates_dir="_sokrates"):
        self.root = Path(sokrates_dir)
        self.data_dir = self.root / "reports" / "data"
        self.zip_path = self.data_dir / "data.zip"
        self.ai_dir = self.root / "reports" / "ai-insights"
        if not self.zip_path.exists() and not (self.data_dir / "analysisResults.json").exists():
            raise FileNotFoundError(
                f"no Sokrates analysis under {self.root} (expected {self.zip_path}); run `sokrates analyze` first")
        self._zip = zipfile.ZipFile(self.zip_path) if self.zip_path.exists() else None

    def analyzed_at(self):
        return (self.zip_path if self._zip else self.data_dir / "analysisResults.json").stat().st_mtime

    def read(self, entry):
        if self._zip:
            try:
                return self._zip.read(entry).decode("utf-8", errors="replace")
            except KeyError:
                return None
        path = self.data_dir / entry
        return path.read_text(errors="replace") if path.exists() else None

    def json(self, entry, default=None):
        text = self.read(entry)
        return json.loads(text) if text else default

    def main_paths(self):
        """The relative paths of the main-scope files (the scope every metric here is computed on)."""
        paths = self.json("mainFilesPaths.json", None)
        if isinstance(paths, list):
            return set(paths)
        text = self.read("text/aspect_main.txt") or ""
        return {line.split("\t")[0] for line in text.splitlines()[1:] if line.strip()}

    def units(self):
        return [u for u in self.json("units.json", []) if isinstance(u, dict)]

    def duplicates(self):
        doc = self.json("duplicates.json", {})
        items = doc.get("duplicates", []) if isinstance(doc, dict) else doc
        result = []
        for d in items:
            blocks = d.get("duplicatedFileBlocks", [])
            files = [b.get("file", {}).get("relativePath", "") for b in blocks]
            result.append({"blockSize": int(d.get("blockSize", 0)), "files": files, "blocks": blocks})
        return result

    def files_with_history(self):
        """Per main file: lines of code, commits (all / 90d / 30d), contributors, churn — from text/mainFilesWithHistory.txt."""
        text = self.read("text/mainFilesWithHistory.txt")
        if not text:
            return {}
        lines = text.splitlines()
        header = [h.strip() for h in lines[0].split("\t")]
        def col(name):
            return header.index(name) if name in header else -1
        c_loc, c_commits, c_30, c_90, c_contrib, c_churn = (col("# lines of code"), col("# commits"), col("# commits (30d)"),
                                                            col("# commits (90d)"), col("# contributors"), col("line churn"))
        result = {}
        for line in lines[1:]:
            cells = line.split("\t")
            if len(cells) < 2:
                continue
            def num(i):
                try:
                    return int(cells[i]) if i >= 0 and i < len(cells) else 0
                except ValueError:
                    return 0
            result[cells[0]] = {"loc": num(c_loc), "commits": num(c_commits), "commits30": num(c_30), "commits90": num(c_90),
                                "contributors": num(c_contrib), "churn": num(c_churn)}
        return result

    def metrics(self):
        results = self.json("analysisResults.json", {})
        return {m.get("id"): m.get("value") for m in results.get("metricsList", {}).get("metrics", []) if isinstance(m, dict)}

    def findings(self):
        """All AI scanner findings (sokrates-skills format) in reports/ai-insights, except the combined report."""
        found = []
        if not self.ai_dir.is_dir():
            return found
        for path in sorted(self.ai_dir.glob("*.json")):
            if path.name == "combined-report.json":
                continue
            try:
                doc = json.loads(path.read_text(errors="replace"))
            except Exception:
                continue
            scanner = doc.get("scanner", "")
            if not scanner or scanner == "combined":
                continue
            for f in doc.get("findings", []):
                if isinstance(f, dict):
                    found.append({**f, "scanner": scanner, "_file": path.name})
        return found


SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def severity_rank(severity):
    return SEVERITY_RANK.get(str(severity or "info").lower(), 4)


def is_test_path(path):
    return re.search(r"(^|/)(tests?|__tests__|testdata|spec)/|(_test|\.test|_spec|\.spec)\.|(^|/)test_", path) is not None
