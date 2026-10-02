"""sokrates-scan-core: validate, merge, diff and render findings files."""
import json
import shutil

from tests.support import ALPHA, ALPHA_INSIGHTS, FixtureTest, read_json, run, write_json


class ValidateFindingsTest(FixtureTest):

    def test_fixture_findings_verify_against_the_source(self):
        for name in ("security-scan.json", "reliability-scan.json"):
            result = run("validate", ALPHA_INSIGHTS / name)
            self.assert_ok(result, name)
            self.assertIn("OK: 3/3 findings fully verified", result.stdout)

    def test_src_root_defaults_to_the_declared_target_relative_to_the_file(self):
        result = run("validate", ALPHA_INSIGHTS / "security-scan.json", "--json")
        self.assert_ok(result)
        report = json.loads(result.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual((report["findings_total"], report["findings_verified"]), (3, 3))

    def test_a_finding_without_evidence_is_only_a_warning_when_possible(self):
        result = run("validate", ALPHA_INSIGHTS / "reliability-scan.json")
        self.assertIn("WARNING reliability-scan/overview/single-upstream: no file/line evidence", result.stdout)

    def test_wrong_snippet_fails_with_a_drift_hint(self):
        folder = self.copy_of(ALPHA_INSIGHTS)
        doc = read_json(folder / "security-scan.json")
        bucket = doc["findings"][0]["evidence"][0]
        bucket["start_line"] += 1
        bucket["end_line"] += 1                      # the snippet is still in the file, one line up
        doc["findings"][1]["evidence"][0]["snippet"] = "USER nobody"   # not in the file at all
        write_json(folder / "security-scan.json", doc)
        result = run("validate", folder / "security-scan.json", "--src-root", ALPHA)
        self.assertEqual(result.returncode, 1)
        self.assertIn("snippet does not match infra/main.tf", result.stdout)
        self.assertIn("(snippet found near line", result.stdout)
        self.assertIn("snippet does not match Dockerfile", result.stdout)
        self.assertIn("(snippet not found anywhere in file)", result.stdout)
        self.assertIn("FAILED: 1/3 findings fully verified", result.stdout)

    def test_structure_errors(self):
        folder = self.copy_of(ALPHA_INSIGHTS)
        doc = read_json(folder / "security-scan.json")
        doc["findings"][0]["severity"] = "urgent"
        doc["findings"][1]["id"] = "Not A Valid Id"
        doc["findings"][2]["id"] = doc["findings"][0]["id"]
        del doc["findings"][2]["confidence"]
        del doc["summary"]
        write_json(folder / "security-scan.json", doc)
        result = run("validate", folder / "security-scan.json", "--src-root", ALPHA)
        self.assertEqual(result.returncode, 1)
        for text in ("missing required field 'summary'", "severity must be one of", "does not match <scanner>/<group>/<slug>",
                     "duplicate id", "missing required field 'confidence'"):
            self.assertIn(text, result.stdout)

    def test_cross_reference_must_resolve_within_the_folder(self):
        folder = self.copy_of(ALPHA_INSIGHTS)
        (folder / "reliability-scan.json").unlink()      # the referenced finding lives there
        result = run("validate", folder / "security-scan.json", "--src-root", ALPHA)
        self.assertEqual(result.returncode, 1)
        self.assertIn("cites finding:reliability-scan/error-handling/swallowed-cache-write-error but no findings file", result.stdout)

    def test_missing_file_and_bad_src_root_are_invocation_errors(self):
        self.assertEqual(run("validate", self.tmp / "nope.json").returncode, 2)
        self.assertEqual(run("validate", ALPHA_INSIGHTS / "security-scan.json", "--src-root", self.tmp / "missing").returncode, 2)


class MergeFindingsTest(FixtureTest):

    def test_merges_a_folder_into_a_valid_combined_document(self):
        folder = self.copy_of(ALPHA_INSIGHTS)
        result = run("merge", folder)
        self.assert_ok(result)
        combined = read_json(folder / "combined-report.json")
        self.assertEqual(combined["scanner"], "combined")
        self.assertEqual(len(combined["findings"]), 6)
        self.assertEqual(combined["target"]["name"], "acme / alpha")
        self.assertIn("security-scan/infrastructure/public-cache-bucket", [f["id"] for f in combined["findings"]])
        validated = run("validate", folder / "combined-report.json", "--src-root", ALPHA)
        self.assert_ok(validated, "the combined document must pass the validator")
        self.assertIn("6/6 findings fully verified", validated.stdout)

    def test_remerging_skips_the_previous_combined_report(self):
        folder = self.copy_of(ALPHA_INSIGHTS)
        self.assert_ok(run("merge", folder))
        again = run("merge", folder)
        self.assert_ok(again)
        self.assertIn("skipped combined-report.json", again.stderr)
        self.assertEqual(len(read_json(folder / "combined-report.json")["findings"]), 6)

    def test_descends_from_the_reports_folder_and_honours_output_path(self):
        reports = self.copy_of(ALPHA / "_sokrates" / "reports", "reports")
        out = self.tmp / "merged.json"
        self.assert_ok(run("merge", reports, "-o", out))
        self.assertEqual(len(read_json(out)["findings"]), 6)
        self.assertFalse((reports / "ai-insights" / "combined-report.json").exists())

    def test_nothing_to_merge_is_an_error(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        self.assertNotEqual(run("merge", empty).returncode, 0)


class DiffFindingsTest(FixtureTest):

    def test_identical_runs_report_no_changes_and_exit_zero(self):
        result = run("diff", ALPHA_INSIGHTS / "reliability-scan.json", ALPHA_INSIGHTS / "reliability-scan.json")
        self.assert_ok(result)
        self.assertIn("0 new · 0 resolved · 3 persisting (0 changed)", result.stdout)
        self.assertIn("No changes", result.stdout)

    def test_new_resolved_and_changed_findings_exit_one(self):
        new_doc = read_json(ALPHA_INSIGHTS / "reliability-scan.json")
        resolved = new_doc["findings"].pop(1)
        new_doc["findings"][0]["severity"] = "high"
        new_doc["findings"].append({**resolved, "id": "reliability-scan/retries/no-jitter", "title": "Retries have no jitter"})
        new_path = self.tmp / "new.json"
        write_json(new_path, new_doc)
        result = run("diff", ALPHA_INSIGHTS / "reliability-scan.json", new_path, "-o", self.tmp / "diff.md")
        self.assertEqual(result.returncode, 1)
        text = (self.tmp / "diff.md").read_text()
        self.assertIn("1 new · 1 resolved · 2 persisting (1 changed)", text)
        self.assertIn("reliability-scan/retries/no-jitter", text)
        self.assertIn("reliability-scan/retries/fixed-sleep-retry", text)
        self.assertIn("severity medium → high", text)

    def test_a_non_findings_file_is_rejected(self):
        write_json(self.tmp / "x.json", {"hello": 1})
        result = run("diff", self.tmp / "x.json", ALPHA_INSIGHTS / "reliability-scan.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a findings file", result.stderr)


class RenderFindingsTest(FixtureTest):

    def test_renders_a_self_contained_explorer_next_to_the_findings(self):
        folder = self.copy_of(ALPHA_INSIGHTS)
        result = run("render", folder)
        self.assert_ok(result)
        self.assertIn("2 scanners, 6 findings", result.stdout)
        html = (folder / "index.html").read_text()
        self.assertIn("Cache bucket is public-read", html)
        self.assertIn("reliability-scan", html)
        for token in ("${data}", "${icons}", "${scanners}", "${generatedAt}"):
            self.assertNotIn(token, html, "every placeholder must be substituted")
        self.assertNotIn("</script>", html.split("Cache bucket is public-read")[0][-200:],
                         "embedded JSON must not be able to close the script tag")

    def test_descends_from_reports_and_skips_the_combined_report(self):
        reports = self.copy_of(ALPHA / "_sokrates" / "reports", "reports")
        self.assert_ok(run("merge", reports))
        result = run("render", reports)
        self.assert_ok(result)
        self.assertIn("2 scanners, 6 findings", result.stdout)
        self.assertTrue((reports / "ai-insights" / "index.html").is_file())

    def test_missing_placeholder_in_template_is_an_error(self):
        folder = self.copy_of(ALPHA_INSIGHTS)
        template = self.tmp / "broken.html"
        template.write_text("<html>${data}</html>")
        result = run("render", folder, "--template", template)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("template lacks placeholder", result.stderr)


class StatsConsistencyTest(FixtureTest):

    def test_stats_that_disagree_with_the_findings_are_a_warning(self):
        folder = self.copy_of(ALPHA_INSIGHTS)
        doc = read_json(folder / "reliability-scan.json")
        doc["stats"] = {"findings_total": 5, "findings_above_info": 2, "handling_sites": 3}
        write_json(folder / "reliability-scan.json", doc)
        result = run("validate", folder / "reliability-scan.json", "--src-root", ALPHA)
        self.assert_ok(result, "stats drift is a warning, not an error")
        self.assertIn("WARNING stats.findings_total is 5 but the file holds 3", result.stdout)
        self.assertNotIn("stats.findings_above_info", result.stdout, "2 above info is right (one finding is info)")


class SummarizeFindingsTest(FixtureTest):

    def test_markdown_summary(self):
        result = run("summarize", ALPHA_INSIGHTS, "--top", "3")
        self.assert_ok(result)
        text = result.stdout
        self.assertIn("# AI insights — acme / alpha", text)
        self.assertIn("**AI insights: 1 high · 2 medium · 1 low (2 informational) from 2 scanners**, analyzed 2025-09-01", text)
        self.assertIn("## Needs attention (3 of 4)", text)
        first = text.split("## Needs attention")[1].splitlines()[2]
        self.assertTrue(first.startswith("- **Cache bucket is public-read** — high, security-scan, `infra/main.tf:18`. Set the ACL to private"), first)
        self.assertIn("| reliability-scan | 3 | 2 | 2025-09-01 |", text)
        self.assertIn("| security-scan | 3 | 2 | 2025-09-01 |", text)

    def test_badge_and_output_file(self):
        result = run("summarize", ALPHA / "_sokrates" / "reports", "--badge")
        self.assert_ok(result)
        self.assertEqual(result.stdout.strip(), "AI insights: 1 high · 2 medium · 1 low (2 informational) from 2 scanners")
        out = self.tmp / "summary.md"
        self.assert_ok(run("summarize", ALPHA_INSIGHTS / "security-scan.json", "-o", out))
        self.assertIn("from 1 scanner**", out.read_text())

    def test_no_findings_is_an_error(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        self.assertEqual(run("summarize", empty).returncode, 1)


class RecheckFindingsTest(FixtureTest):
    """recheck_findings.py: intact / moved / gone evidence after the code changed, without re-running a scanner."""

    def changed_repo(self):
        """A copy of alpha where main.tf gained a comment line (evidence moves) and the Dockerfile's USER line is gone."""
        repo = self.copy_of(ALPHA)
        tf = repo / "infra" / "main.tf"
        tf.write_text("# managed by terraform\n" + tf.read_text())
        docker = repo / "Dockerfile"
        docker.write_text(docker.read_text().replace("USER root\n", "USER app\n"))
        return repo

    def test_unchanged_tree_is_all_intact(self):
        result = run("recheck", ALPHA_INSIGHTS)
        self.assert_ok(result)
        self.assertIn("security-scan.json: 3 findings — 3 intact, 0 moved, 0 gone, 0 without evidence", result.stdout)
        self.assertIn("reliability-scan.json: 3 findings — 2 intact, 0 moved, 0 gone, 1 without evidence", result.stdout)

    def test_moved_and_gone_evidence(self):
        repo = self.changed_repo()
        out = self.tmp / "recheck.json"
        result = run("recheck", repo / "_sokrates" / "reports" / "ai-insights" / "security-scan.json", "--json", out)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("1 intact, 1 moved, 1 gone", result.stdout)
        self.assertIn("moved  security-scan/infrastructure/public-cache-bucket", result.stdout)
        self.assertIn("infra/main.tf: 18-18 -> 19-19", result.stdout)
        self.assertIn("gone   security-scan/containers/runs-as-root", result.stdout)
        self.assertIn("1 finding(s) cite code that changed", result.stdout)
        states = {r["id"]: r["state"] for r in read_json(out)[0]["results"]}
        self.assertEqual(states["security-scan/secrets/token-from-environment"], "intact")

    def test_fix_lines_rewrites_moved_evidence_so_the_validator_passes_again(self):
        repo = self.changed_repo()
        findings = repo / "_sokrates" / "reports" / "ai-insights" / "security-scan.json"
        self.assertEqual(run("validate", findings).returncode, 1, "before the fix the moved snippet fails validation")
        result = run("recheck", findings, "--ids", "security-scan/infrastructure/public-cache-bucket", "--fix-lines")
        self.assert_ok(result, "only the moved finding was selected, nothing is gone")
        self.assertIn("1 evidence line ranges rewritten", result.stdout)
        doc = read_json(findings)
        bucket = next(f for f in doc["findings"] if f["id"].endswith("public-cache-bucket"))
        self.assertEqual((bucket["evidence"][0]["start_line"], bucket["evidence"][0]["end_line"]), (19, 19))
        validated = run("validate", findings)
        self.assertIn("snippet does not match Dockerfile", validated.stdout, "the gone one still fails, as it should")
        self.assertNotIn("infra/main.tf", validated.stdout)

    def test_prompt_names_only_the_gone_findings(self):
        repo = self.changed_repo()
        result = run("recheck", repo / "_sokrates" / "reports" / "ai-insights", "--prompt")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Re-check mode (sokrates-scan-core)", result.stdout)
        self.assertIn("  - security-scan/containers/runs-as-root", result.stdout)
        self.assertNotIn("  - security-scan/infrastructure/public-cache-bucket", result.stdout)
        self.assertNotIn("  - reliability-scan/", result.stdout)

    def test_missing_target(self):
        self.assertEqual(run("recheck", self.tmp / "nope.json").returncode, 2)
