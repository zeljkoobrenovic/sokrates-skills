"""The scanners' count_*_sites.py helpers: regex site counters over a source tree."""
from tests.support import ALPHA, FixtureTest, read_json, run

# counter -> files that must carry at least one hit (the fixture was written to trigger them)
EXPECTED_HITS = {
    "count_network": ["src/app/service.py", "web/client.js"],       # requests.get, fetch, WebSocket
    "count_storage": ["src/app/repo.py", "src/app/service.py"],     # sqlite / SQL, file write
    "count_config": ["src/app/service.py"],                         # os.environ reads
    "count_iac": ["infra/main.tf", "Dockerfile"],                   # terraform resource, public acl, root user
    "count_handling": ["src/app/service.py"],                       # bare except that passes
    "count_perf": [],
    "count_test": ["tests/test_service.py"],
}


class CountersTest(FixtureTest):

    def run_counter(self, name, *extra):
        out = self.tmp / f"{name}.json"
        result = run(name, ALPHA, "--json", out, *extra)
        self.assert_ok(result, name)
        return read_json(out), result

    def test_every_counter_runs_and_cites_real_lines(self):
        source_lines = {}
        for name, expected_files in EXPECTED_HITS.items():
            with self.subTest(counter=name):
                doc, result = self.run_counter(name)
                self.assertIn("hits", doc)
                self.assertIn("wrote", result.stdout)
                hit_files = set()
                for shape, hits in doc["hits"].items():
                    for hit in hits:
                        if not isinstance(hit, dict) or "file" not in hit:
                            continue
                        hit_files.add(hit["file"])
                        path = ALPHA / hit["file"]
                        self.assertTrue(path.is_file(), f"{name}/{shape} cites a file that does not exist: {hit['file']}")
                        if isinstance(hit.get("line"), int) and "snippet" in hit:
                            lines = source_lines.setdefault(hit["file"], path.read_text(errors="replace").split("\n"))
                            self.assertLessEqual(hit["line"], len(lines), f"{name}/{shape}: line beyond the file")
                            self.assertIn(hit["snippet"].strip()[:30], lines[hit["line"] - 1],
                                          f"{name}/{shape}: snippet is not on the cited line of {hit['file']}")
                for expected in expected_files:
                    self.assertIn(expected, hit_files, f"{name} should find a site in {expected}")

    def test_test_code_is_not_counted_as_production_handling(self):
        doc, _ = self.run_counter("count_handling")
        self.assertEqual(doc["files_scanned"], {"js": 1, "python": 4})
        self.assertEqual(len(doc["hits"]["catch_all_sites"]), 1)
        self.assertEqual(doc["hits"]["catch_all_sites"][0]["file"], "src/app/service.py")

    def test_exclude_drops_a_folder(self):
        doc, _ = self.run_counter("count_network", "--exclude", "web")
        files = {hit["file"] for hits in doc["hits"].values() for hit in hits if isinstance(hit, dict)}
        self.assertNotIn("web/client.js", files)
        self.assertIn("src/app/service.py", files)

    def test_iac_flags_the_public_bucket_and_the_root_user(self):
        doc, _ = self.run_counter("count_iac")
        self.assertEqual([h["file"] for h in doc["hits"]["public_access_candidates"]], ["infra/main.tf"])
        self.assertEqual([h["file"] for h in doc["hits"]["root_user_candidates"]], ["Dockerfile"])
        self.assertEqual(len(doc["hits"]["terraform_resources"]), 1)

    def test_testing_counter_maps_tests_to_sokrates_components(self):
        data = self.extracted_data()
        doc, result = self.run_counter("count_test", "--components-dir", data)
        self.assertIn("test LOC by Sokrates component", result.stdout)
        self.assertIn("by_component", doc)
        self.assertTrue(any("tests/test_service.py" in str(v) for v in doc["files"].values()) if isinstance(doc["files"], dict)
                        else any("tests/test_service.py" in str(v) for v in doc["files"]))

    def test_not_a_directory(self):
        self.assertNotEqual(run("count_network", self.tmp / "missing").returncode, 0)
