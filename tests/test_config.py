"""Configuration skills: repository config preview and proposals, landscape checks, people config."""
import json

from tests.support import ALPHA, ALPHA_SOKRATES, LANDSCAPE, FixtureTest, read_json, run, write_json


class PreviewConfigTest(FixtureTest):

    def test_previews_scopes_decompositions_and_concerns(self):
        out = self.tmp / "preview.json"
        result = run("preview_config", self.copy_of(ALPHA) / "_sokrates" / "config.json", "--json", out)
        self.assert_ok(result)
        doc = read_json(out)
        scopes = {name: (s["files"], sorted(s["samples"])) for name, s in doc["scopes"].items()}
        self.assertEqual(scopes["main"], (5, ["src/app/__init__.py", "src/app/legacy.py", "src/app/repo.py", "src/app/service.py", "web/client.js"]))
        self.assertEqual(scopes["test"], (2, ["tests/test_repo.py", "tests/test_service.py"]))
        self.assertEqual(scopes["buildAndDeployment"][0], 3)
        self.assertEqual(scopes["other"][0], 2)
        self.assertEqual(scopes["generated"][0], 0)
        components = {c["name"]: c["files"] for c in doc["decompositions"][0]["components"]}
        self.assertEqual(components, {"src": 4, "web": 1})
        self.assertEqual(doc["concerns"][0]["samples"], ["src/app/service.py"], "the TODO concern")
        self.assertEqual(doc["errors"], [])
        self.assertIn("dead rule", " ".join(doc["warnings"]), "the unconditional _sokrates ignore matches nothing in a tree without reports")
        self.assertIn("Excluded:", result.stdout)

    def test_bad_regex_is_an_error(self):
        sokrates = self.copy_of(ALPHA) / "_sokrates"
        config = read_json(sokrates / "config.json")
        config["ignore"].append({"pathPattern": ".*/(unclosed", "contentPattern": "", "exception": False, "note": ""})
        write_json(sokrates / "config.json", config)
        result = run("preview_config", sokrates / "config.json")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("does not compile", result.stdout)

    def test_folders_above_the_source_root_never_classify_files(self):
        """Sokrates matches scope patterns against the path below the source root (with a leading `/`), and the
        preview mirrors that: the fixture's own location under tests/ must not make `.*/[Tt]ests/.*` claim its files
        (it did before Sokrates matched the whole path as loaded)."""
        out = self.tmp / "preview.json"
        self.assert_ok(run("preview_config", ALPHA_SOKRATES / "config.json", "--json", out))
        doc = read_json(out)
        self.assertEqual(doc["scopes"]["main"]["files"], 5)
        self.assertEqual(doc["scopes"]["test"]["files"], 2)

    def test_missing_src_root_is_an_error(self):
        sokrates = self.tmp / "_sokrates"
        sokrates.mkdir()
        write_json(sokrates / "config.json", {"srcRoot": "../does-not-exist", "extensions": ["py"]})
        result = run("preview_config", sokrates / "config.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not exist", result.stdout)


class ProposeDecompositionsTest(FixtureTest):

    def test_proposals_from_folders_codeowners_and_technology(self):
        out = self.tmp / "d.json"
        result = run("propose_decompositions", self.copy_of(ALPHA) / "_sokrates" / "config.json", "-o", out)
        self.assert_ok(result)
        doc = read_json(out)
        kinds = [p["kind"] for p in doc["proposals"]]
        for kind in ("folder-depth", "ownership", "technology"):
            self.assertIn(kind, kinds)
        self.assertIn("@acme/backend", result.stdout)
        self.assertIn("Python", result.stdout)
        self.assertEqual(doc["existing_decompositions"][0]["name"], "primary")


class ProposeConcernsTest(FixtureTest):

    def test_catalog_candidates_with_file_line_samples(self):
        out = self.tmp / "c.json"
        result = run("propose_concerns", self.copy_of(ALPHA) / "_sokrates" / "config.json", "-o", out, "--min-files", "1")
        self.assert_ok(result)
        doc = read_json(out)
        self.assertEqual((doc["main_files"], len(doc["existing_concerns"])), (5, 1))
        names = {c["name"]: c for c in doc["catalog"]}
        self.assertIn("network and HTTP", names)
        self.assertEqual(names["network and HTTP"]["files"], 2)
        self.assertIn("TODOs and FIXMEs", names)
        self.assertIn("src/app/service.py:66:", result.stdout)


class CheckLandscapeTest(FixtureTest):

    def test_finds_both_repositories_and_the_alias_candidate(self):
        out = self.tmp / "l.json"
        result = run("check_landscape", LANDSCAPE, "--json", out)
        self.assert_ok(result)
        doc = read_json(out)
        self.assertTrue(doc["config_exists"])
        self.assertEqual((doc["included"], doc["excluded"]), (2, 0))
        self.assertEqual([(r["name"], r["main_loc"]) for r in doc["repositories"]], [("Alpha", 131), ("Beta", 26)])
        self.assertEqual(doc["contributors"]["canonical"], 3)
        self.assertEqual(doc["contributors"]["bots"], 1)
        self.assertEqual(doc["contributors"]["alias_candidates"], {"adalovelace": ["12345+ada@users.noreply.github.com", "ada@example.com"]})
        self.assertIn("OK: 0 errors, 0 warnings", result.stdout)

    def test_thresholds_exclude_small_repositories(self):
        conf = self.tmp / "config.json"
        base = read_json(LANDSCAPE / "_sokrates_landscape" / "config.json")
        write_json(conf, {**base, "repositoryThresholdLocMain": 100})
        out = self.tmp / "l.json"
        self.assert_ok(run("check_landscape", LANDSCAPE, "--conf", conf, "--json", out))
        doc = read_json(out)
        self.assertEqual((doc["included"], doc["excluded"]), (1, 1))

    def test_empty_root_is_an_error(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        result = run("check_landscape", empty)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no repository analyses found", result.stdout)


class ProposeVirtualLandscapesTest(FixtureTest):

    def test_technology_and_organisation_groupings(self):
        out = self.tmp / "v.json"
        result = run("propose_virtual_landscapes", LANDSCAPE, "-o", out, "--min-members", "1")
        self.assert_ok(result)
        doc = read_json(out)
        self.assertEqual((doc["repositories"], doc["total_main_loc"]), (2, 157))
        by_kind = {p["kind"]: p for p in doc["proposals"]}
        self.assertEqual(by_kind["technology"]["landscapes"], 2)
        self.assertEqual(by_kind["technology"]["coverage_pct"], 100.0)
        self.assertIn("Python", result.stdout)
        self.assertIn("Java", result.stdout)

    def test_user_grouping_is_measured(self):
        groups = self.tmp / "groups.json"
        write_json(groups, {"Services": ["Alpha"], "Libraries": ["Beta"]})
        out = self.tmp / "v.json"
        self.assert_ok(run("propose_virtual_landscapes", LANDSCAPE, "--groups", groups, "-o", out))
        user = [p for p in read_json(out)["proposals"] if p["kind"] == "user"]
        self.assertEqual(len(user), 1)
        self.assertEqual(user[0]["coverage_pct"], 100.0)


class BuildPeopleConfigTest(FixtureTest):

    def test_repository_merges_adas_two_addresses(self):
        repo = self.copy_of(ALPHA)
        result = run("people", "--repo", repo)
        self.assert_ok(result)
        people = read_json(repo / "_sokrates" / "config-people.json")["people"]
        self.assertEqual(len(people), 1)
        self.assertEqual(people[0]["email"], "ada@example.com")
        self.assertEqual(sorted(people[0]["emailPatterns"]), ["\\Q12345+ada@users.noreply.github.com\\E", "\\Qada@example.com\\E"])
        review = read_json(repo / "_sokrates" / "config-people-for-review.json")
        self.assertEqual(review["summary"]["identities_seen"], 4)
        self.assertEqual(review["summary"]["merged_people"], 1)
        self.assertTrue(any(rule.startswith("R2") for rule in review["merges"][0]["rules"]), "the user-name key rule fired")

    def test_dry_run_writes_only_the_review(self):
        repo = self.copy_of(ALPHA)
        self.assert_ok(run("people", "--repo", repo, "--dry-run"))
        self.assertFalse((repo / "_sokrates" / "config-people.json").exists())
        self.assertTrue((repo / "_sokrates" / "config-people-for-review.json").exists())

    def test_landscape_merges_across_repositories_and_keeps_existing_entries(self):
        landscape = self.copy_of(LANDSCAPE)
        existing = {"people": [{"email": "grace@example.com", "userName": "Grace Hopper", "links": [], "image": "",
                                "emailPatterns": ["\\Qgrace@example.com\\E", "\\Qgrace@acme.example\\E"], "userNamePatterns": []}]}
        write_json(landscape / "_sokrates_landscape" / "config-people.json", existing)
        result = run("people", "--landscape", landscape)
        self.assert_ok(result)
        people = {p["email"]: p for p in read_json(landscape / "_sokrates_landscape" / "config-people.json")["people"]}
        self.assertIn("ada@example.com", people, "Ada's beta identity (noreply) and alpha identity are merged")
        self.assertIn("grace@example.com", people, "a hand-written entry survives a re-run although only one of its addresses has commits")
        self.assertIn("\\Qgrace@acme.example\\E", people["grace@example.com"]["emailPatterns"])
        self.assertIn("\\Qgrace@example.com\\E", people["grace@example.com"]["emailPatterns"])

    def test_an_entry_for_someone_absent_from_the_history_is_kept_verbatim(self):
        repo = self.copy_of(ALPHA)
        gone = {"email": "linus@example.com", "userName": "Linus Torvalds", "links": [], "image": "",
                "emailPatterns": ["\\Qlinus@example.com\\E", "\\Qtorvalds@example.com\\E"], "userNamePatterns": []}
        write_json(repo / "_sokrates" / "config-people.json", {"people": [gone]})
        self.assert_ok(run("people", "--repo", repo))
        people = read_json(repo / "_sokrates" / "config-people.json")["people"]
        self.assertEqual([p["email"] for p in people], ["ada@example.com", "linus@example.com"])
        self.assertEqual(people[1], gone)
