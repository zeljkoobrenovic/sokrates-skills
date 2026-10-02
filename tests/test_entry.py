"""The entry skill: situation.py classifies a folder and ranks the next steps."""
import json
import os

from tests.support import ALPHA, BETA, LANDSCAPE, FixtureTest, read_json, run

def situation(self, *args, env=None):
    out = self.tmp / "situation.json"
    result = run("situation", *args, "--json", out, env=env)
    self.assert_ok(result)
    return read_json(out), result


class SituationTest(FixtureTest):

    def test_analyzed_repository_with_findings_is_routed_to_improve(self):
        doc, result = situation(self, ALPHA)
        s = doc["situation"]
        self.assertEqual(s["kind"], "repository")
        self.assertTrue(s["analysis"])
        self.assertEqual(s["metrics"]["LINES_OF_CODE_MAIN"], 131)
        self.assertEqual(sorted(s["findings"]), ["reliability-scan", "security-scan"])
        self.assertEqual(s["findings_total"], 6)
        self.assertEqual(s["findings_with_recommendation"], 3)
        self.assertEqual(s["contributors"], 4)
        self.assertFalse(s["people_config"])
        skills = [st["skill"] for st in doc["steps"]]
        self.assertIn("sokrates-improve", skills)
        self.assertIn("sokrates-people-config", skills, "four identities and no config-people.json")
        self.assertIn("sokrates-decompositions", skills, "one depth-1 decomposition whose largest component holds most of the code")
        self.assertIn("sokrates-features-of-interest", skills, "only the default TODOs concern")
        self.assertIn("sokrates-scan-core", skills, "findings but no explorer page")
        self.assertNotIn("analyze", skills, "the analysis exists and there is no git history to call it stale")
        self.assertIn("Repository Alpha", result.stdout)
        self.assertIn("AI findings: 6 from 2 scanners (4 above info)", result.stdout)
        self.assertIn("Next steps, in order:", result.stdout)

    def test_analyzed_repository_without_findings_is_routed_to_a_scan(self):
        doc, _ = situation(self, BETA)
        skills = [st["skill"] for st in doc["steps"]]
        self.assertIn("full-scan", skills)
        self.assertNotIn("sokrates-improve", skills)
        self.assertNotIn("sokrates-people-config", skills, "a single identity needs no merging")

    def test_unanalyzed_repository_is_told_to_analyze_first(self):
        repo = self.tmp / "fresh"
        (repo / "src").mkdir(parents=True)
        for name in ("a.py", "b.py", "c.py"):
            (repo / "src" / name).write_text("x = 1\n")
        doc, result = situation(self, repo)
        self.assertEqual(doc["situation"]["kind"], "repository")
        self.assertEqual(doc["steps"][0]["skill"] if doc["tooling"]["run"] else doc["steps"][1]["skill"], "analyze")
        self.assertIn("analyze", doc["steps"][0]["command"] or doc["steps"][1]["command"])
        self.assertIn("no analysis, no configuration", result.stdout)

    def test_empty_folder(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        doc, result = situation(self, empty)
        self.assertEqual(doc["situation"]["kind"], "empty")
        self.assertEqual(doc["steps"][0]["skill"], "none")
        self.assertIn("no source files", result.stdout)

    def test_landscape_root(self):
        doc, result = situation(self, LANDSCAPE)
        s = doc["situation"]
        self.assertEqual(s["kind"], "landscape")
        self.assertEqual(s["repositories"], 2)
        self.assertEqual(sorted(s["repository_folders"]), ["acme/alpha", "acme/beta"])
        self.assertTrue(s["data"])
        self.assertEqual(s["repositories_with_findings"], 0, "the landscape fixture carries no ai-insights")
        skills = [st["skill"] for st in doc["steps"]]
        self.assertEqual(skills[0], "sokrates-landscape-config")
        self.assertIn("sokrates-people-config", skills)
        self.assertIn("full-scan", skills)
        self.assertNotIn("sokrates-virtual-landscapes", skills, "two repositories are too few to group")
        self.assertIn("2 repository analyses", result.stdout)

    def test_folder_of_analyses_without_landscape_folder_counts_as_landscape(self):
        doc, _ = situation(self, LANDSCAPE / "acme")
        self.assertEqual(doc["situation"]["kind"], "landscape")
        self.assertEqual(doc["steps"][0]["skill"], "analyzeLandscape")

    def test_tooling_detection_is_reported(self):
        doc, result = situation(self, ALPHA, env={"PATH": "/nonexistent", "SOKRATES_JAR": ""})
        self.assertIsNone(doc["tooling"]["run"])
        self.assertEqual(doc["steps"][0]["skill"], "install")
        self.assertIn("NOT FOUND", result.stdout)
        jar = self.tmp / "sokrates.jar"
        jar.write_bytes(b"")
        doc, _ = situation(self, ALPHA, env={"PATH": "/nonexistent", "SOKRATES_JAR": str(jar)})
        self.assertEqual(doc["tooling"]["run"], f"java -jar {jar}")

    def test_not_a_directory(self):
        from tests.support import run as run_script
        self.assertEqual(run_script("situation", self.tmp / "missing").returncode, 2)
