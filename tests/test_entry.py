"""The entry skill: situation.py classifies a folder and ranks the next steps."""
import json
import os

from tests.support import ALPHA, ALPHA_DATA_ZIP, BETA, FIXTURES, LANDSCAPE, FixtureTest, read_json, run, write_json

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


class CapabilitiesTest(FixtureTest):
    """capabilities.py: probes the installed Sokrates through its usage output."""

    def fake_sokrates(self, usage_text, jar_line=True):
        """A `sokrates` wrapper on a private PATH that prints the given usage; names a jar like the real wrapper does."""
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        usage = self.tmp / "usage.txt"
        usage.write_text(usage_text)
        jar = self.tmp / "sokrates-LATEST.jar"
        jar.write_bytes(b"")
        script = bin_dir / "sokrates"
        script.write_text("#!/bin/sh\n" + (f"# java -jar {jar} \"$@\"\n" if jar_line else "") + f"cat '{usage}'\n")
        script.chmod(0o755)
        return {"PATH": f"{bin_dir}:/usr/bin:/bin", "SOKRATES_JAR": ""}, jar

    def test_current_build_has_every_capability(self):
        env, jar = self.fake_sokrates((FIXTURES / "sokrates-usage.txt").read_text())
        out = self.tmp / "caps.json"
        result = run("capabilities", "--data", ALPHA_DATA_ZIP, "--json", out, env=env)
        self.assert_ok(result)
        doc = read_json(out)
        self.assertEqual(doc["run"], "sokrates")
        self.assertEqual(doc["jar"], str(jar))
        self.assertIn("analyzeGitHubOrg", doc["commands"])
        self.assertIn("-dataOnly", doc["commands"]["generateReports"])
        self.assertTrue(all(doc["capabilities"].values()), doc["capabilities"])
        self.assertTrue(doc["data"]["history_zip"])
        self.assertTrue(doc["data"]["temporal_dependencies"])
        self.assertIn("has: analyze, analyzeGitRepo", result.stdout)
        self.assertNotIn("lacks", result.stdout)
        self.assertIn(f"runs {jar}", result.stdout)

    def test_older_build_lacks_capabilities(self):
        usage = (FIXTURES / "sokrates-usage.txt").read_text()
        older = "\n".join(line.replace("[-dataOnly] ", "").replace("[-prune] ", "") for line in usage.splitlines() if "analyzeGitHubOrg" not in line)
        env, _ = self.fake_sokrates(older, jar_line=False)
        out = self.tmp / "caps.json"
        result = run("capabilities", "--json", out, env=env)
        self.assert_ok(result)
        doc = read_json(out)
        self.assertFalse(doc["capabilities"]["dataOnly"])
        self.assertFalse(doc["capabilities"]["prune"])
        self.assertFalse(doc["capabilities"]["analyzeGitHubOrg"])
        self.assertTrue(doc["capabilities"]["analyze"])
        self.assertIsNone(doc["jar"])
        self.assertIn("lacks (older build): analyzeGitHubOrg, analyzeGitLabGroup, dataOnly, prune", result.stdout)  # the GitLab line mentions GitHubOrg too

    def test_no_sokrates_is_an_error(self):
        result = run("capabilities", env={"PATH": "/nonexistent", "SOKRATES_JAR": ""})
        self.assertEqual(result.returncode, 1)
        self.assertIn("Sokrates not found", result.stdout)

    def test_a_command_that_does_not_print_the_usage_is_an_error(self):
        env, _ = self.fake_sokrates("something else entirely\n")
        result = run("capabilities", env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("did not print the Sokrates usage", result.stdout)


class StalenessTest(FixtureTest):
    """situation.py calls an analysis stale only when analyzed content changed after it, not after a documentation commit."""

    def commit(self, repo, message, date):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@example.com", GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        import subprocess
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "--no-gpg-sign", "-m", message], check=True, capture_output=True, env=env)

    def test_documentation_commits_do_not_make_the_analysis_stale(self):
        import subprocess
        import time
        repo = self.copy_of(ALPHA)
        subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True, capture_output=True)
        self.commit(repo, "code", "2025-01-01T10:00:00+00:00")
        data_zip = repo / "_sokrates" / "reports" / "data" / "data.zip"
        analyzed_at = time.mktime(time.strptime("2025-06-01", "%Y-%m-%d"))
        os.utime(data_zip, (analyzed_at, analyzed_at))
        (repo / "README.md").write_text("# docs only\n")
        self.commit(repo, "docs", "2025-09-01T10:00:00+00:00")
        doc, result = situation(self, repo)
        self.assertFalse(doc["situation"]["analysis_stale"], "a README commit after the analysis is not staleness")
        self.assertNotIn("STALE", result.stdout)
        (repo / "src" / "app" / "repo.py").write_text("# changed\n")
        self.commit(repo, "code again", "2025-10-01T10:00:00+00:00")
        os.utime(data_zip, (analyzed_at, analyzed_at))
        doc, result = situation(self, repo)
        self.assertTrue(doc["situation"]["analysis_stale"])
        self.assertIn("STALE", result.stdout)
        self.assertEqual(doc["steps"][0]["skill"], "analyze")


class AnalysisWithoutSourceTest(FixtureTest):
    """An analyzeGitRepo output (config.json next to reports/, no source) is recognized and routed to where the source is."""

    def test_analysis_only_folder(self):
        doc, result = situation(self, LANDSCAPE / "acme" / "alpha")
        s = doc["situation"]
        self.assertEqual(s["kind"], "analysis")
        self.assertFalse(s["has_sources"])
        self.assertEqual(s["metrics"]["LINES_OF_CODE_MAIN"], 131)
        self.assertEqual(doc["steps"][0]["skill"], "analyzeGitRepo")
        self.assertIn("analyzeGitRepo -url <git url>", doc["steps"][0]["why"])
        self.assertIn("Analysis of Alpha", result.stdout)
        self.assertIn("without the source", result.stdout)

    def test_source_marker_gives_the_url(self):
        folder = self.copy_of(LANDSCAPE / "acme" / "alpha", "alpha-analysis")
        write_json(folder / "source.json", {"url": "https://github.com/acme/alpha.git", "command": "analyzeLandscape", "analyzedOn": "2025-09-01"})
        doc, result = situation(self, folder)
        self.assertEqual(doc["situation"]["source_url"], "https://github.com/acme/alpha.git")
        self.assertIn("analyzeGitRepo -url https://github.com/acme/alpha.git", doc["steps"][0]["why"])
        self.assertIn("from https://github.com/acme/alpha.git", result.stdout)
