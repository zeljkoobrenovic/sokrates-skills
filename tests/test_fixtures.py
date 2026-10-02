"""The fixtures themselves: what every other test assumes about tests/fixtures (rebuilt by make_fixtures.sh)."""
import json
import unittest
import zipfile

from tests.support import ALPHA, ALPHA_DATA_ZIP, ALPHA_INSIGHTS, ALPHA_SOKRATES, BETA, LANDSCAPE


class FixtureShapeTest(unittest.TestCase):

    def test_alpha_is_a_repository_with_its_analysis_inside(self):
        self.assertTrue((ALPHA / "src/app/service.py").is_file())
        self.assertTrue((ALPHA / "git-history.txt").is_file())
        config = json.loads((ALPHA_SOKRATES / "config.json").read_text())
        self.assertEqual(config["srcRoot"], "..")
        self.assertEqual(config["metadata"]["name"], "Alpha")
        self.assertIn(".*/_sokrates/.*", [rule["pathPattern"] for rule in config["ignore"]])

    def test_alpha_data_zip_holds_the_exports_the_scripts_read(self):
        with zipfile.ZipFile(ALPHA_DATA_ZIP) as archive:
            names = set(archive.namelist())
            metrics = dict(line.split(": ") for line in archive.read("text/metrics.txt").decode().splitlines() if ": " in line)
        for entry in ("analysisResults.json", "units.json", "duplicates.json", "files.json", "text/aspect_main.txt",
                      "text/mainFilesWithHistory.txt", "text/contributors.txt", "text/units.txt", "text/metrics.txt",
                      "text/temporal_dependencies_different_folders_30_days.txt", "zips/git-history.zip"):
            self.assertIn(entry, names)
        self.assertEqual(metrics["LINES_OF_CODE_MAIN"], "131")
        self.assertEqual(metrics["NUMBER_OF_FILES_MAIN"], "5")

    def test_alpha_history_has_six_commits_and_the_ai_trailer(self):
        shas = {line.split(" ")[2] for line in (ALPHA / "git-history.txt").read_text().splitlines()}
        self.assertEqual(len(shas), 6, "the parentless root commit is skipped by the extractor")
        self.assertEqual(len((ALPHA / "git-commits.txt").read_text().splitlines()), 6)
        self.assertIn("Co-Authored-By: Claude", (ALPHA / "git-commit-trailers.txt").read_text())

    def test_alpha_findings_are_two_scanners(self):
        self.assertEqual(sorted(p.name for p in ALPHA_INSIGHTS.glob("*.json")), ["reliability-scan.json", "security-scan.json"])

    def test_beta_and_landscape_layout(self):
        self.assertTrue((BETA / "_sokrates/reports/data/data.zip").is_file())
        for repo in ("alpha", "beta"):
            self.assertTrue((LANDSCAPE / "acme" / repo / "config.json").is_file())
            self.assertTrue((LANDSCAPE / "acme" / repo / "reports/data/data.zip").is_file())
        self.assertEqual(json.loads((LANDSCAPE / "_sokrates_landscape/config.json").read_text())["analysisRoot"], ".")
