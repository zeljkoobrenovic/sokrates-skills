"""Scripts that pre-compute digests from the extracted Sokrates data: hotspots, maintainability drivers, the evolution timeline."""
from tests.support import ALPHA, ALPHA_DATA_ZIP, FixtureTest, find_values, read_json, run


class SelectHotspotsTest(FixtureTest):

    def test_shortlist_from_extracted_data(self):
        data = self.extracted_data()
        out = self.tmp / "hotspots.json"
        self.assert_ok(run("hotspots", "--data", data, "--src-root", ALPHA, "-o", out))
        doc = read_json(out)
        self.assertEqual(doc["stats"], {"main_files_analyzed": 4, "units_analyzed": 12, "contributors_total": 4, "history_data": "present"})
        paths = {h.get("path") for h in doc["hotspots"]}
        self.assertIn("src/app/service.py", paths)
        top = doc["knowledge_risk"]["bus_factor_top_contributors"]
        self.assertEqual([c["contributor"] for c in top[:2]], ["ada@example.com", "grace@example.com"])
        self.assertEqual(top[0]["share_pct"], 33)

    def test_requires_the_text_exports(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        result = run("hotspots", "--data", empty)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing", result.stderr)


class ComputeMaintainabilityTest(FixtureTest):

    def test_drivers_with_provenance(self):
        data = self.extracted_data()
        out = self.tmp / "m.json"
        result = run("maintainability", data, "--commits", ALPHA / "git-commits.txt", "--json", out)
        self.assert_ok(result)
        self.assertIn("2 components, 131 main LOC", result.stdout)
        doc = read_json(out)
        self.assertEqual(doc["decomposition"], "primary")
        self.assertEqual(find_values(doc, "duplicate_blocks"), [1])
        self.assertEqual(find_values(doc, "cross_component_duplicate_blocks"), [0], "both copies of normalize_rows are in src")
        self.assertIn(131, find_values(doc, "main_loc"))

    def test_requires_files_json(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        result = run("maintainability", empty)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("files.json not found", result.stderr)


class EvolutionTimelineTest(FixtureTest):

    def test_timeline_from_the_git_exports(self):
        data = self.extracted_data()
        out = self.tmp / "e.json"
        result = run("evolution", "--src-root", ALPHA, "--data", data, "-o", out)
        self.assert_ok(result)
        doc = read_json(out)
        stats = doc["stats"]
        self.assertEqual((stats["commits"], stats["authors"]), (6, 3))
        self.assertEqual(stats["history_span"]["first_commit"], "2024-06-15")
        self.assertEqual(stats["history_span"]["last_commit"], "2025-08-02")
        self.assertEqual(stats["identity_merges"], [{"canonical": "ada@example.com", "aliases": ["12345+ada@users.noreply.github.com"], "name_key": "adalovelace"}])
        self.assertTrue(stats["messages_available"])
        self.assertEqual(doc["lifecycle"]["files_deleted"], 1, "old_cache.py was added and later removed")
        self.assertEqual(doc["lifecycle"]["deleted_by_area"], [{"area": "src/app", "files": 1}])
        self.assertEqual(stats["themes_overall"]["deps-chore"], 1, "the dependabot bump")

    def test_falls_back_to_the_history_zip_inside_the_data(self):
        data = self.extracted_data()
        no_source = self.tmp / "no-source"
        no_source.mkdir()
        out = self.tmp / "e.json"
        result = run("evolution", "--src-root", no_source, "--data", data, "-o", out)
        self.assert_ok(result)
        doc = read_json(out)
        self.assertEqual(doc["stats"]["commits"], 6)
        self.assertIn("git-history.zip", doc["stats"]["history_source"])

    def test_no_history_exits_three(self):
        no_source = self.tmp / "no-source"
        no_source.mkdir()
        result = run("evolution", "--src-root", no_source)
        self.assertEqual(result.returncode, 3)
        self.assertIn("no git history found", result.stderr)


class DataZipAcceptedDirectlyTest(FixtureTest):
    """The scripts that read the extracted data folder also take data.zip itself, or the folder holding it."""

    def test_hotspots_from_the_zip(self):
        out = self.tmp / "h.json"
        self.assert_ok(run("hotspots", "--data", ALPHA_DATA_ZIP, "-o", out))
        self.assertEqual(read_json(out)["stats"]["units_analyzed"], 12)

    def test_maintainability_from_the_sokrates_folder(self):
        out = self.tmp / "m.json"
        result = run("maintainability", ALPHA / "_sokrates", "--json", out)
        self.assert_ok(result)
        self.assertIn("131 main LOC", result.stdout)

    def test_evolution_from_the_zip(self):
        no_source = self.tmp / "no-source"
        no_source.mkdir()
        out = self.tmp / "e.json"
        self.assert_ok(run("evolution", "--src-root", no_source, "--data", ALPHA_DATA_ZIP, "-o", out))
        self.assertEqual(read_json(out)["stats"]["commits"], 6)

    def test_testing_counter_components_from_the_reports_folder(self):
        out = self.tmp / "t.json"
        result = run("count_test", ALPHA, "--components-dir", ALPHA / "_sokrates" / "reports", "--json", out)
        self.assert_ok(result)
        self.assertIn("test LOC by Sokrates component", result.stdout)
