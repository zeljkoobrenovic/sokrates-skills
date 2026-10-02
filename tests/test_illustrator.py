"""The summary illustrator: only the dry run is testable offline (the real run calls the Gemini image API)."""
from tests.support import ALPHA, FixtureTest, run


class IllustratorDryRunTest(FixtureTest):

    def test_dry_run_lists_scanners_and_writes_nothing(self):
        reports = self.copy_of(ALPHA / "_sokrates" / "reports", "reports")
        before = sorted(p.relative_to(reports) for p in reports.rglob("*"))
        result = run("visuals", reports, "--dry-run", env={"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""})
        self.assert_ok(result)
        self.assertIn("[1/2] reliability-scan: dry-run", result.stdout)
        self.assertIn("[2/2] security-scan: dry-run", result.stdout)
        self.assertEqual(sorted(p.relative_to(reports) for p in reports.rglob("*")), before)

    def test_only_limits_to_one_scanner(self):
        reports = self.copy_of(ALPHA / "_sokrates" / "reports", "reports")
        result = run("visuals", reports, "--dry-run", "--only", "security-scan")
        self.assert_ok(result)
        self.assertIn("[1/1] security-scan: dry-run", result.stdout)
        self.assertNotIn("reliability-scan: dry-run", result.stdout)
