"""sokrates-improve: the data reader, the target shortlist and the before/after measurement."""
import importlib.util
import json
import sys

from tests.support import ALPHA, ALPHA_SOKRATES, LANDSCAPE, FixtureTest, SCRIPTS, read_json, run, write_json

UNIT = "unit:src/app/service.py#def fetch_orders()"


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS[name])
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS[name].parent))
    spec.loader.exec_module(module)
    return module


class SokratesDataTest(FixtureTest):

    def test_reads_the_analysis_from_data_zip(self):
        sokrates_data = load_module("select_targets").SokratesData
        data = sokrates_data(ALPHA_SOKRATES)
        self.assertEqual(sorted(data.main_paths()), ["src/app/__init__.py", "src/app/legacy.py", "src/app/repo.py", "src/app/service.py", "web/client.js"])
        self.assertEqual(len(data.units()), 12)
        self.assertEqual(data.metrics()["LINES_OF_CODE_MAIN"], 131)
        duplicates = data.duplicates()
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["blockSize"], 13)
        self.assertEqual(sorted(duplicates[0]["files"]), ["src/app/legacy.py", "src/app/repo.py"])
        history = data.files_with_history()
        self.assertEqual(history["src/app/service.py"]["loc"], 66)
        self.assertEqual(history["src/app/service.py"]["commits"], 1)
        findings = data.findings()
        self.assertEqual(len(findings), 6)
        self.assertEqual(sorted({f["scanner"] for f in findings}), ["reliability-scan", "security-scan"])

    def test_missing_analysis_is_a_clear_error(self):
        result = run("select_targets", "--sokrates", self.tmp / "nothing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("run `sokrates analyze` first", result.stderr)


class SelectTargetsTest(FixtureTest):

    def test_shortlist(self):
        out = self.tmp / "targets.json"
        result = run("select_targets", "--sokrates", ALPHA_SOKRATES, "--json", out)
        self.assert_ok(result)
        doc = read_json(out)
        self.assertEqual(doc["units"][0]["id"], UNIT + "@23", "the id names the overload by its start line")
        self.assertEqual((doc["units"][0]["mcCabe"], doc["units"][0]["loc"]), (19, 48))
        self.assertEqual(doc["duplicates"][0]["id"], "duplicate:0")
        self.assertEqual((doc["duplicates"][0]["blockSize"], doc["duplicates"][0]["copies"], doc["duplicates"][0]["duplicatedLines"]), (13, 2, 13))
        self.assertEqual(doc["hotspots"], [], "no main file is big enough to be a hotspot")
        findings = doc["findings"]
        self.assertEqual([f["id"] for f in findings], ["finding:security-scan/infrastructure/public-cache-bucket",
                                                        "finding:reliability-scan/error-handling/swallowed-cache-write-error",
                                                        "finding:reliability-scan/retries/fixed-sleep-retry"],
                         "findings with a recommendation, above info, by severity")
        self.assertEqual(findings[0]["evidence"], ["infra/main.tf:18-18"])
        self.assertIn("== units", result.stdout)

    def test_one_kind(self):
        result = run("select_targets", "--sokrates", ALPHA_SOKRATES, "--kind", "duplicates", "--top", "1")
        self.assert_ok(result)
        self.assertIn("duplicate:0", result.stdout)
        self.assertNotIn("== units", result.stdout)


class MeasureTest(FixtureTest):

    def snapshot(self, target, name, **extra):
        out = self.tmp / name
        args = ["snapshot", "--sokrates", ALPHA_SOKRATES, "-o", out]
        for key, value in extra.items():
            args += [f"--{key}", value]
        if target:
            args += ["--target", target]
        return run("measure", *args), out

    def test_unit_snapshot(self):
        result, out = self.snapshot(UNIT, "before.json")
        self.assert_ok(result)
        doc = read_json(out)
        measured = {k: v for k, v in doc["measured"].items() if k != "fileUnits"}
        self.assertEqual(measured, {"found": True, "mcCabe": 19, "loc": 48, "lines": "23-72", "unitsInFile": 3})
        self.assertEqual([u["name"] for u in doc["measured"]["fileUnits"]][:1], ["def fetch_orders()"])
        self.assertEqual(doc["spec"]["parameters"], 5)
        self.assertEqual(doc["totals"]["mainLinesOfCode"], 131)
        self.assertEqual(doc["totals"]["duplicatedLines"], 13)
        self.assertEqual(doc["totals"]["unitsMcCabeOver10"], 1)

    def test_verdicts_and_exit_codes(self):
        _, before = self.snapshot(UNIT, "before.json")
        base = read_json(before)
        cases = {
            "improved": ({"found": True, "mcCabe": 8, "loc": 30, "lines": "23-50", "unitsInFile": 5}, 0),
            "unchanged": (base["measured"], 1),
            "worse": ({**base["measured"], "mcCabe": 25}, 1),
            "not found": ({"found": False}, 2),
        }
        for verdict, (measured, code) in cases.items():
            with self.subTest(verdict=verdict):
                after = self.tmp / f"after-{code}.json"
                write_json(after, {**base, "measured": measured, "analysisAt": "later"})
                result = run("measure", "compare", before, after, "--markdown")
                self.assertEqual(result.returncode, code, result.stdout)
                self.assertIn(f"**{verdict}**", result.stdout)
                self.assertIn("| mcCabe | 19 |", result.stdout)
                self.assertNotIn("WARNING", result.stderr)

    def test_warnings_about_invalid_comparisons(self):
        _, before = self.snapshot(UNIT, "before.json")
        base = read_json(before)
        same = self.tmp / "same.json"
        write_json(same, base)
        result = run("measure", "compare", before, same)
        self.assertIn("both snapshots come from the same analysis", result.stderr)
        drifted = self.tmp / "drifted.json"
        write_json(drifted, {**base, "analysisAt": "later", "totals": {**base["totals"], "mainLinesOfCode": 500}})
        result = run("measure", "compare", before, drifted)
        self.assertIn("the analysis scope changed between the snapshots (main lines of code 131 -> 500)", result.stderr)

    def test_duplicate_target_keeps_its_files_for_the_second_snapshot(self):
        result, before = self.snapshot("duplicate:0", "before.json")
        self.assert_ok(result)
        doc = read_json(before)
        self.assertEqual(doc["spec"]["files"], ["src/app/legacy.py", "src/app/repo.py"])
        self.assertEqual(doc["measured"]["duplicatedLines"], 13)
        result, after = self.snapshot(None, "after.json", like=str(before))
        self.assert_ok(result)
        self.assertEqual(read_json(after)["spec"], doc["spec"])
        self.assertEqual(read_json(after)["target"], "duplicate:0")
        self.assertEqual(run("measure", "compare", before, after).returncode, 1, "nothing changed")

    def test_hotspot_and_finding_targets(self):
        result, out = self.snapshot("hotspot:src/app/service.py", "h.json")
        self.assert_ok(result)
        self.assertEqual(read_json(out)["measured"]["loc"], 66)
        self.assertEqual(read_json(out)["measured"]["maxMcCabe"], 19)
        result, _ = self.snapshot("hotspot:src/app/missing.py", "h2.json")
        self.assertEqual(result.returncode, 2)
        result, out = self.snapshot("finding:security-scan/containers/runs-as-root", "f.json")
        self.assert_ok(result)
        self.assertEqual(read_json(out)["measured"], {"found": True, "present": True, "severity": "medium", "confidence": "certain", "title": "Container runs as root", "evidence": "intact"})

    def test_bad_target_and_out_of_range_duplicate(self):
        result, _ = self.snapshot("thing:x", "x.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("unknown target", result.stderr)
        result, _ = self.snapshot("duplicate:9", "y.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("out of range", result.stderr)

    def test_unit_matching_tolerates_a_leading_folder(self):
        measure = load_module("measure")
        self.assertTrue(measure.same_file("sokrates/src/app/service.py", "src/app/service.py"))
        self.assertTrue(measure.same_file("src/app/service.py", "src/app/service.py"))
        self.assertFalse(measure.same_file("src/app/service.py", "src/app/legacy.py"))
        self.assertFalse(measure.same_file("xservice.py", "service.py"))


class FindingEvidenceStateTest(FixtureTest):
    """measure.py: a finding target reports whether its cited code changed, and asks for the re-check when it did."""

    def test_intact_finding_is_unchanged_and_gone_evidence_needs_a_recheck(self):
        repo = self.copy_of(ALPHA)
        sokrates = repo / "_sokrates"
        target = "finding:security-scan/containers/runs-as-root"
        before = self.tmp / "before.json"
        self.assert_ok(run("measure", "snapshot", "--sokrates", sokrates, "--target", target, "-o", before))
        self.assertEqual(read_json(before)["measured"]["evidence"], "intact")
        after = self.tmp / "after.json"
        self.assert_ok(run("measure", "snapshot", "--sokrates", sokrates, "--like", before, "-o", after))
        write_json(after, {**read_json(after), "analysisAt": "later"})
        result = run("measure", "compare", before, after, "--markdown")
        self.assertEqual(result.returncode, 1)
        self.assertIn("**unchanged**", result.stdout)
        self.assertIn("| evidence | intact | intact |", result.stdout)
        # the fix: the Dockerfile no longer runs as root, but nobody re-checked the finding yet
        docker = repo / "Dockerfile"
        docker.write_text(docker.read_text().replace("USER root\n", "USER app\n"))
        self.assert_ok(run("measure", "snapshot", "--sokrates", sokrates, "--like", before, "-o", after))
        write_json(after, {**read_json(after), "analysisAt": "later"})
        result = run("measure", "compare", before, after, "--markdown")
        self.assertEqual(result.returncode, 3)
        self.assertIn("**needs re-check**", result.stdout)
        self.assertIn("| evidence | intact | gone |", result.stdout)
        self.assertIn("recheck_findings.py --prompt", result.stderr)


class EffortAndPriorityTest(FixtureTest):
    """select_targets.py: every target carries an effort; findings are ordered by severity-for-the-smallest-change."""

    def test_effort_and_priority(self):
        out = self.tmp / "targets.json"
        self.assert_ok(run("select_targets", "--sokrates", ALPHA_SOKRATES, "--json", out))
        doc = read_json(out)
        self.assertEqual(doc["units"][0]["effort"], "medium", "48 lines in one file")
        self.assertEqual(doc["units"][1]["effort"], "small")
        self.assertEqual(doc["duplicates"][0]["effort"], "small", "13 lines x 2 copies in 2 files")
        self.assertIn("; effort medium", doc["units"][0]["why"])
        findings = doc["findings"]
        self.assertEqual([f["effort"] for f in findings], ["small", "small", "small"])
        self.assertEqual(findings[0]["id"], "finding:security-scan/infrastructure/public-cache-bucket", "high severity, one line: first either way")

    def test_priority_prefers_a_small_medium_over_a_large_high(self):
        sokrates = self.copy_of(ALPHA) / "_sokrates"
        insights = sokrates / "reports" / "ai-insights"
        doc = read_json(insights / "security-scan.json")
        bucket = next(f for f in doc["findings"] if f["id"].endswith("public-cache-bucket"))
        bucket["evidence"] = []           # a design-level high finding with nothing concrete to change at: large effort
        write_json(insights / "security-scan.json", doc)
        out = self.tmp / "targets.json"
        self.assert_ok(run("select_targets", "--sokrates", sokrates, "--kind", "findings", "--json", out))
        ids = [f["id"] for f in read_json(out)["findings"]]
        self.assertEqual(ids[0], "finding:reliability-scan/error-handling/swallowed-cache-write-error", "medium + small beats high + large")
        self.assertEqual(ids[1], "finding:security-scan/infrastructure/public-cache-bucket", "high + large ties with low + small; severity breaks the tie")
        self.assertEqual(ids[2], "finding:reliability-scan/retries/fixed-sleep-retry")
        self.assert_ok(run("select_targets", "--sokrates", sokrates, "--kind", "findings", "--order", "severity", "--json", out))
        self.assertEqual(read_json(out)["findings"][0]["id"], "finding:security-scan/infrastructure/public-cache-bucket", "strict severity order on request")


class LandscapeRankingTest(FixtureTest):
    """select_targets.py --landscape ranks the targets of every repository analysis under a landscape root together."""

    def test_targets_across_the_landscape_name_their_repository(self):
        out = self.tmp / "targets.json"
        result = run("select_targets", "--landscape", LANDSCAPE, "--json", out)
        self.assert_ok(result)
        self.assertIn("2 repositories ranked together", result.stdout)
        doc = read_json(out)
        units = doc["units"]
        self.assertEqual((units[0]["repo"], units[0]["mcCabe"]), ("Alpha", 19))
        self.assertIn("Beta", [u["repo"] for u in units], "Beta's calculator is in the merged ranking")
        self.assertTrue(units[0]["analysis"].endswith("acme/alpha"))
        self.assertEqual(doc["duplicates"][0]["repo"], "Alpha")
        self.assertIn("[Alpha]", result.stdout)

    def test_no_analyses_is_an_error(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        result = run("select_targets", "--landscape", empty)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no repository analyses", result.stderr)


class OverloadsAndHelpersTest(FixtureTest):
    """measure.py: overloads are told apart by line and parameter count; new helpers show in the compare table."""

    def write_analysis(self, units):
        import zipfile
        sokrates = self.tmp / "_sokrates"
        (sokrates / "reports" / "data").mkdir(parents=True)
        with zipfile.ZipFile(sokrates / "reports" / "data" / "data.zip", "w") as z:
            z.writestr("units.json", json.dumps(units))
            z.writestr("metrics.json", json.dumps({"metrics": [{"id": "LINES_OF_CODE_MAIN", "value": 100}]}))
            z.writestr("duplicates.json", json.dumps({"duplicates": []}))
            z.writestr("mainFilesPaths.json", json.dumps(["src/Service.java"]))
        return sokrates

    @staticmethod
    def unit(name, start, parameters, mccabe, loc):
        return {"relativeFileName": "src/Service.java", "shortName": name, "startLine": start, "endLine": start + loc,
                "numberOfParameters": parameters, "mcCabeIndex": mccabe, "linesOfCode": loc}

    def test_bare_name_warns_and_line_picks_the_overload(self):
        sokrates = self.write_analysis([self.unit("public void load()", 10, 1, 3, 5), self.unit("public void load()", 40, 3, 15, 60)])
        out = self.tmp / "bare.json"
        result = run("measure", "snapshot", "--sokrates", sokrates, "--target", "unit:src/Service.java#public void load()", "-o", out)
        self.assert_ok(result)
        self.assertIn("2 units named", result.stderr)
        self.assertIn("@40", result.stderr)
        self.assertEqual(read_json(out)["measured"]["mcCabe"], 15, "the most complex overload is measured")
        out = self.tmp / "line.json"
        self.assert_ok(run("measure", "snapshot", "--sokrates", sokrates, "--target", "unit:src/Service.java#public void load()@10", "-o", out))
        doc = read_json(out)
        self.assertEqual((doc["measured"]["mcCabe"], doc["spec"]["parameters"]), (3, 1))
        result = run("measure", "snapshot", "--sokrates", sokrates, "--target", "unit:src/Service.java#public void load()@ten", "-o", out)
        self.assertEqual(result.returncode, 1)
        self.assertIn("start line", result.stderr)

    def test_like_follows_the_overload_by_parameter_count_after_the_lines_shift(self):
        before_data = self.write_analysis([self.unit("public void load()", 10, 1, 3, 5), self.unit("public void load()", 40, 3, 15, 60)])
        before = self.tmp / "before.json"
        self.assert_ok(run("measure", "snapshot", "--sokrates", before_data, "--target", "unit:src/Service.java#public void load()@40", "-o", before))
        # after the change the 3-parameter overload starts 30 lines later, is simpler, and two helpers appeared
        import shutil
        shutil.rmtree(before_data)
        after_data = self.write_analysis([self.unit("public void load()", 10, 1, 3, 5), self.unit("public void load()", 70, 3, 6, 20),
                                          self.unit("private void loadRows()", 95, 2, 6, 25), self.unit("private String label()", 125, 1, 5, 12)])
        after = self.tmp / "after.json"
        self.assert_ok(run("measure", "snapshot", "--sokrates", after_data, "--like", before, "-o", after))
        self.assertEqual(read_json(after)["measured"]["lines"], "70-90", "the same overload, found by its parameter count")
        result = run("measure", "compare", before, after, "--markdown")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("| mcCabe | 15 | 6 |", result.stdout)
        self.assertIn("| new helpers in the file | - | 2 (private void loadRows(), private String label()) |", result.stdout)
        self.assertIn("| mcCabe incl. new helpers | 15 | 15 |", result.stdout, "the 9 lost decisions moved into the helpers (5 + 4)")
        self.assertIn("| loc incl. new helpers | 60 | 57 |", result.stdout)
        self.assertIn("moved into 2 new helper(s)", result.stderr)

    def test_shorter_but_not_simpler_gets_the_decision_hint(self):
        before_data = self.write_analysis([self.unit("public void load()", 10, 2, 9, 41)])
        before = self.tmp / "before.json"
        self.assert_ok(run("measure", "snapshot", "--sokrates", before_data, "--target", "unit:src/Service.java#public void load()", "-o", before))
        import shutil
        shutil.rmtree(before_data)
        after_data = self.write_analysis([self.unit("public void load()", 10, 2, 10, 33)])
        after = self.tmp / "after.json"
        self.assert_ok(run("measure", "snapshot", "--sokrates", after_data, "--like", before, "-o", after))
        result = run("measure", "compare", before, after)
        self.assertEqual(result.returncode, 1)
        self.assertIn("worse", result.stdout)
        self.assertIn("&& / || / ?: as a decision", result.stderr)


class DiffOutputsTest(FixtureTest):
    """diff_outputs.py: two output folders are equivalent when only timestamps, timings and key order differ."""

    @staticmethod
    def archive_page(entries):
        import base64, io, zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            for name, content in entries.items():
                z.writestr(name, content)
        return f'<html><script>var SOKRATES_ARCHIVE = "{base64.b64encode(buffer.getvalue()).decode()}";</script><p>generated on 2026-10-03 12:00</p></html>'

    def write(self, folder, files):
        import zipfile
        for name, content in files.items():
            path = self.tmp / folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if name.endswith(".zip"):
                with zipfile.ZipFile(path, "w") as z:
                    for entry, data in content.items():
                        z.writestr(entry, data)
            else:
                path.write_text(content)
        return self.tmp / folder

    def test_equivalent_outputs(self):
        before = self.write("before", {"index.html": "<p>generated on 2026-10-02 09:00</p><i>2026-10-02 09:00</i>",
                                       "data/data.zip": {"analysisResults.json": '{"a": 1, "analysisStartTimeMs": 5, "b": [1, 2]}', "executionTimes.json": "[1]", "text/x.txt": "ok 2026-10-02 09:00:01"},
                                       "visuals/chart.html": self.archive_page({"main.json": '{"x": 1}'})})
        after = self.write("after", {"index.html": "<p>generated on 2026-10-03 17:30</p><i>2026-10-03 17:30</i>",
                                     "data/data.zip": {"analysisResults.json": '{"b": [1, 2], "a": 1, "analysisStartTimeMs": 9}', "executionTimes.json": "[2]", "text/x.txt": "ok 2026-10-03 17:30:02"},
                                     "visuals/chart.html": self.archive_page({"main.json": '{"x": 1}'})})
        result = run("diff_outputs", before, after)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("0 of 3 files differ", result.stdout)

    def test_timing_metrics_and_nested_pages_are_noise(self):
        inner = self.archive_page({"analysisResults.json": '{"metricsList": {"metrics": [{"id": "TOTAL_ANALYSIS_TIME_IN_MILLIS", "value": 129}, {"id": "LINES_OF_CODE_MAIN", "value": 5}]}}'})
        before = self.write("before", {"html/Metrics.html": "<td><b>TOTAL_ANALYSIS_TIME_IN_MILLIS</b></td><td>129</td><td>LINES</td><td>5</td>",
                                       "data/data.zip": {"analysisResults.json": '{"metricsList": {"metrics": [{"id": "TOTAL_ANALYSIS_TIME_IN_MILLIS", "value": 129}]}}', "data-preview.html": inner}})
        inner2 = self.archive_page({"analysisResults.json": '{"metricsList": {"metrics": [{"id": "TOTAL_ANALYSIS_TIME_IN_MILLIS", "value": 126}, {"id": "LINES_OF_CODE_MAIN", "value": 5}]}}'})
        after = self.write("after", {"html/Metrics.html": "<td><b>TOTAL_ANALYSIS_TIME_IN_MILLIS</b></td><td>126</td><td>LINES</td><td>5</td>",
                                     "data/data.zip": {"analysisResults.json": '{"metricsList": {"metrics": [{"id": "TOTAL_ANALYSIS_TIME_IN_MILLIS", "value": 126}]}}', "data-preview.html": inner2}})
        result = run("diff_outputs", before, after)
        self.assertEqual(result.returncode, 0, result.stdout)
        after2 = self.write("after2", {"html/Metrics.html": "<td><b>TOTAL_ANALYSIS_TIME_IN_MILLIS</b></td><td>126</td><td>LINES</td><td>6</td>",
                                       "data/data.zip": {"analysisResults.json": '{"metricsList": {"metrics": [{"id": "TOTAL_ANALYSIS_TIME_IN_MILLIS", "value": 126}]}}', "data-preview.html": inner2}})
        result = run("diff_outputs", before, after2)
        self.assertEqual(result.returncode, 1)
        self.assertIn("DIFFERS: html/Metrics.html [page]", result.stdout, "a real metric change is still reported")

    def test_real_differences_are_named_by_file_and_entry(self):
        before = self.write("before", {"index.html": "<p>12 files</p>", "data/data.zip": {"files.json": '[{"path": "a"}]', "extra.txt": "x"},
                                       "visuals/chart.html": self.archive_page({"main.json": '{"x": 1}', "test.json": '{"y": 2}'}), "only-before.txt": "gone"})
        after = self.write("after", {"index.html": "<p>13 files</p>", "data/data.zip": {"files.json": '[{"path": "b"}]'},
                                     "visuals/chart.html": self.archive_page({"main.json": '{"x": 2}', "test.json": '{"y": 2}'})})
        result = run("diff_outputs", before, after)
        self.assertEqual(result.returncode, 1)
        self.assertIn("DIFFERS: index.html [page]", result.stdout)
        self.assertIn("DIFFERS: data/data.zip [extra.txt (only before), files.json]", result.stdout)
        self.assertIn("DIFFERS: visuals/chart.html [archive:main.json]", result.stdout)
        self.assertIn("DIFFERS: only-before.txt [only before]", result.stdout)
        self.assertIn("4 of 4 files differ", result.stdout)
        result = run("diff_outputs", before, after, "--ignore", "only-before.txt", "--ignore", "extra.txt")
        self.assertNotIn("only-before", result.stdout)
        self.assertNotIn("extra.txt", result.stdout)


class FileSplitsTest(FixtureTest):
    """measure.py: a hotspot split shows the new files of the folder and the lines including them; --for-commit prints the block to paste."""

    def write_analysis(self, files, units=()):
        import zipfile
        sokrates = self.tmp / "_sokrates"
        if sokrates.exists():
            import shutil
            shutil.rmtree(sokrates)
        (sokrates / "reports" / "data").mkdir(parents=True)
        with zipfile.ZipFile(sokrates / "reports" / "data" / "data.zip", "w") as z:
            z.writestr("files.json", json.dumps([{"relativePath": path, "linesOfCode": loc} for path, loc in files.items()]))
            z.writestr("units.json", json.dumps(list(units)))
            z.writestr("metrics.json", json.dumps({"metrics": [{"id": "LINES_OF_CODE_MAIN", "value": sum(files.values())}]}))
            z.writestr("duplicates.json", json.dumps({"duplicates": []}))
            z.writestr("mainFilesPaths.json", json.dumps(list(files)))
        return sokrates

    def test_split_rows_and_the_copy_warning(self):
        before_data = self.write_analysis({"src/report/Exporter.java": 760, "src/report/Other.java": 100})
        before = self.tmp / "before.json"
        self.assert_ok(run("measure", "snapshot", "--sokrates", before_data, "--target", "hotspot:src/report/Exporter.java", "-o", before))
        self.assertEqual([f["path"] for f in read_json(before)["measured"]["folderFiles"]], ["src/report/Exporter.java", "src/report/Other.java"])
        after_data = self.write_analysis({"src/report/Exporter.java": 520, "src/report/Other.java": 100, "src/report/ActivityTab.java": 160, "src/report/DataTab.java": 100})
        after = self.tmp / "after.json"
        self.assert_ok(run("measure", "snapshot", "--sokrates", after_data, "--like", before, "-o", after))
        result = run("measure", "compare", before, after, "--markdown")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("| new files in the folder | - | 2: ActivityTab.java (160), DataTab.java (100) |", result.stdout)
        self.assertIn("| loc incl. new files | 760 | 780 |", result.stdout)
        self.assertNotIn("more code was written than moved", result.stderr, "20 lines of class headers are a move")
        copied = self.write_analysis({"src/report/Exporter.java": 520, "src/report/Other.java": 100, "src/report/ActivityTab.java": 400, "src/report/DataTab.java": 100})
        after2 = self.tmp / "after2.json"
        self.assert_ok(run("measure", "snapshot", "--sokrates", copied, "--like", before, "-o", after2))
        result = run("measure", "compare", before, after2)
        self.assertIn("more code was written than moved", result.stderr)
        result = run("measure", "compare", before, after, "--for-commit")
        self.assertIn("Exporter.java: 760 -> 520 lines (+160 +100 new), longest unit 0 -> 0, max McCabe 0 -> 0 (improved)", result.stdout)
        self.assertIn("| Exporter.java | 760 -> 520 (+160 +100 new) | 0 -> 0 |", result.stdout)

    def test_for_commit_on_a_unit(self):
        result, before = self.snapshot_alpha("before.json")
        self.assert_ok(result)
        base = read_json(before)
        after = self.tmp / "after.json"
        write_json(after, {**base, "measured": {**base["measured"], "mcCabe": 6, "loc": 21, "lines": "23-45"}, "analysisAt": "later"})
        result = run("measure", "compare", before, after, "--for-commit")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("def fetch_orders(): McCabe 19 -> 6, lines 48 -> 21 (improved)", result.stdout)
        self.assertIn("| def fetch_orders() | 19 -> 6 | 48 -> 21 |", result.stdout)

    def snapshot_alpha(self, name):
        out = self.tmp / name
        return run("measure", "snapshot", "--sokrates", ALPHA_SOKRATES, "--target", UNIT, "-o", out), out


class CheckImportsTest(FixtureTest):
    """check_imports.py: imports whose simple name the file never uses are flagged, per file, with exit code 1."""

    def test_java_and_python(self):
        java = self.tmp / "Report.java"
        java.write_text("package a;\n\nimport java.util.List;\nimport java.util.Map;\nimport java.io.File;\nimport static org.junit.Assert.*;\nimport org.apache.commons.lang3.StringUtils;\n\n"
                        "// a Map in a comment does not count\nclass Report {\n    List<File> files;\n    String s = StringUtils.trim(\"x\");\n}\n")
        py = self.tmp / "tool.py"
        py.write_text("import os\nimport sys, json\nfrom pathlib import Path, PurePath\nfrom typing import List as L\n\n# sys in a comment\nprint(os.getcwd(), json.dumps({}), Path('.'), L)\n")
        clean = self.tmp / "Clean.java"
        clean.write_text("import java.util.List;\nclass Clean { List<String> x; }\n")
        result = run("check_imports", java, py, clean)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Report.java: unused import java.util.Map", result.stdout)
        self.assertNotIn("java.util.List", result.stdout)
        self.assertNotIn("StringUtils", result.stdout)
        self.assertNotIn("org.junit", result.stdout, "a wildcard import is not judged")
        self.assertIn("tool.py: unused import sys", result.stdout)
        self.assertIn("tool.py: unused from … import PurePath", result.stdout)
        self.assertNotIn("import os", result.stdout)
        self.assertNotIn("List as L", result.stdout)
        self.assertIn("3 unused import(s) in 3 file(s)", result.stdout)
        self.assertEqual(run("check_imports", clean).returncode, 0)
