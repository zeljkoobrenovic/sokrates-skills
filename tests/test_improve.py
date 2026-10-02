"""sokrates-improve: the data reader, the target shortlist and the before/after measurement."""
import importlib.util
import json
import sys

from tests.support import ALPHA, ALPHA_SOKRATES, FixtureTest, SCRIPTS, read_json, run, write_json

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
        self.assertEqual(doc["units"][0]["id"], UNIT)
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
        self.assertEqual(doc["measured"], {"found": True, "mcCabe": 19, "loc": 48, "lines": "23-72", "unitsInFile": 3})
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
        self.assertEqual(read_json(out)["measured"], {"found": True, "present": True, "severity": "medium", "confidence": "certain", "title": "Container runs as root"})

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
