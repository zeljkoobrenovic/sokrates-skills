"""landscape-synthesis-scan: the digest over a landscape's AI findings."""
import json
import shutil

from tests.support import ALPHA_INSIGHTS, LANDSCAPE, FixtureTest, read_json, run, write_json


class LandscapeDigestTest(FixtureTest):

    def scanned_landscape(self):
        """The landscape fixture with alpha's findings, and beta carrying one of the same findings plus one of its own."""
        root = self.copy_of(LANDSCAPE)
        shutil.copytree(ALPHA_INSIGHTS, root / "acme" / "alpha" / "reports" / "ai-insights")
        beta = root / "acme" / "beta" / "reports" / "ai-insights"
        beta.mkdir(parents=True)
        security = read_json(ALPHA_INSIGHTS / "security-scan.json")
        shared = next(f for f in security["findings"] if f["id"].endswith("runs-as-root"))
        own = {"id": "security-scan/secrets/token-in-properties", "group": "secrets", "title": "Token in a properties file", "severity": "high",
               "confidence": "likely", "description": "x", "recommendation": "move it", "evidence": []}
        write_json(beta / "security-scan.json", {**security, "target": {"name": "Beta", "src_root": "../../.."}, "findings": [shared, own]})
        return root

    def test_digest_from_repository_findings_when_the_landscape_has_no_aggregate(self):
        root = self.scanned_landscape()
        out = self.tmp / "digest.json"
        result = run("landscape_digest", root, "-o", out)
        self.assert_ok(result)
        self.assertIn("(repository findings files; no aggregated ai-insights.json)", result.stdout)
        doc = read_json(out)
        self.assertEqual(doc["totals"]["repositories_with_findings"], 2)
        self.assertEqual(doc["totals"]["repositories_total"], 2)
        self.assertEqual(doc["totals"]["findings"], 8)
        self.assertEqual(doc["totals"]["by_severity"]["high"], 2)
        self.assertEqual([r["repo"] for r in doc["repositories_ranked"]], ["Alpha", "Beta"])
        self.assertEqual(doc["repositories_ranked"][0]["attention"], 4)
        self.assertEqual(doc["repositories_ranked"][0]["scanners"], ["reliability-scan", "security-scan"])
        recurring = doc["recurring"]
        self.assertEqual(len(recurring), 1)
        self.assertEqual(recurring[0]["id"], "security-scan/containers/runs-as-root")
        self.assertEqual(recurring[0]["repositories"], ["Alpha", "Beta"])
        self.assertEqual(doc["scanner_coverage"]["reliability-scan"], {"ran_on": 1, "missing_in": ["Beta"]})
        self.assertEqual(doc["scanner_coverage"]["security-scan"]["missing_in"], [])
        self.assertEqual(doc["top_findings"][0]["severity"], "high")
        self.assertIn("Recurring findings (same id in several repositories): 1", result.stdout)
        self.assertIn("missing in 1: Beta", result.stdout)

    def test_digest_from_the_aggregated_file_sokrates_writes(self):
        root = self.copy_of(LANDSCAPE)
        aggregated = {
            "repositories": [
                {"name": "acme/alpha", "insightsUrl": "acme/alpha/reports/ai-insights/index.html", "reportUrl": "", "scannedAt": "2025-09-01T12:00:00Z",
                 "scanners": [{"scanner": "security-scan", "version": "1.0", "analyzedAt": "2025-09-01T12:00:00Z", "findings": 2, "attention": 1, "summary": "s"}],
                 "findingsBySeverity": {"high": 1, "info": 1}, "findings": 2, "attention": 1},
                {"name": "acme/beta", "insightsUrl": "", "reportUrl": "", "scannedAt": "2025-09-02T12:00:00Z",
                 "scanners": [{"scanner": "security-scan", "version": "1.0", "analyzedAt": "2025-09-02T12:00:00Z", "findings": 1, "attention": 1, "summary": "s"}],
                 "findingsBySeverity": {"high": 1}, "findings": 1, "attention": 1}],
            "findings": [
                {"repo": "acme/alpha", "scanner": "security-scan", "id": "security-scan/infrastructure/public-cache-bucket", "group": "infrastructure",
                 "title": "Cache bucket is public-read", "severity": "high", "confidence": "certain", "description": "", "recommendation": "private", "tags": [], "url": "x#1"},
                {"repo": "acme/alpha", "scanner": "security-scan", "id": "security-scan/secrets/token-from-environment", "group": "secrets",
                 "title": "Token from env", "severity": "info", "confidence": "certain", "description": "", "recommendation": "", "tags": [], "url": "x#2"},
                {"repo": "acme/beta", "scanner": "security-scan", "id": "security-scan/infrastructure/public-cache-bucket", "group": "infrastructure",
                 "title": "Cache bucket is public-read", "severity": "high", "confidence": "certain", "description": "", "recommendation": "private", "tags": [], "url": "y#1"}]}
        write_json(root / "_sokrates_landscape" / "data" / "ai-insights.json", aggregated)
        out = self.tmp / "digest.json"
        result = run("landscape_digest", root, "-o", out)
        self.assert_ok(result)
        self.assertIn("_sokrates_landscape/data/ai-insights.json", result.stdout)
        doc = read_json(out)
        self.assertEqual(doc["totals"]["attention"], 2)
        self.assertEqual(doc["recurring"][0]["repositories"], ["acme/alpha", "acme/beta"])
        self.assertEqual(doc["top_findings"][0]["url"], "x#1", "the aggregate's deep links are kept")

    def test_a_landscape_without_findings_says_so(self):
        result = run("landscape_digest", LANDSCAPE)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no AI findings", result.stderr)
        self.assertIn("analyzeLandscape -ai", result.stderr)

    def test_entry_skill_routes_a_scanned_landscape_to_the_synthesis(self):
        root = self.scanned_landscape()
        out = self.tmp / "situation.json"
        self.assert_ok(run("situation", root, "--json", out))
        doc = read_json(out)
        self.assertEqual(doc["situation"]["repositories_with_findings"], 2)
        self.assertIn("landscape-synthesis-scan", [st["skill"] for st in doc["steps"]])
