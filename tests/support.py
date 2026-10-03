"""Shared helpers for the script tests: fixture paths, running a script, reading its JSON."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
ALPHA = FIXTURES / "alpha"                      # Python + JavaScript service, analyzed; findings in reports/ai-insights
BETA = FIXTURES / "beta"                        # Java library, analyzed
LANDSCAPE = FIXTURES / "landscape"              # both, laid out as analyzeGitRepo does, plus _sokrates_landscape
ALPHA_SOKRATES = ALPHA / "_sokrates"
ALPHA_INSIGHTS = ALPHA_SOKRATES / "reports" / "ai-insights"
ALPHA_DATA_ZIP = ALPHA_SOKRATES / "reports" / "data" / "data.zip"

SCRIPTS = {
    "validate": SKILLS / "scanners/sokrates-scan-core/scripts/validate_findings.py",
    "merge": SKILLS / "scanners/sokrates-scan-core/scripts/merge_findings.py",
    "diff": SKILLS / "scanners/sokrates-scan-core/scripts/diff_findings.py",
    "render": SKILLS / "scanners/sokrates-scan-core/scripts/render_findings.py",
    "count_config": SKILLS / "scanners/configuration-scan/scripts/count_config_sites.py",
    "count_iac": SKILLS / "scanners/iac-scan/scripts/count_iac_sites.py",
    "count_network": SKILLS / "scanners/network-scan/scripts/count_network_sites.py",
    "count_perf": SKILLS / "scanners/performance-scan/scripts/count_perf_sites.py",
    "count_handling": SKILLS / "scanners/reliability-scan/scripts/count_handling_sites.py",
    "count_storage": SKILLS / "scanners/storage-scan/scripts/count_storage_sites.py",
    "count_test": SKILLS / "scanners/testing-scan/scripts/count_test_sites.py",
    "hotspots": SKILLS / "scanners/risk-synthesis-scan/scripts/select_hotspots.py",
    "maintainability": SKILLS / "scanners/maintainability-scan/scripts/compute_maintainability.py",
    "evolution": SKILLS / "scanners/evolution-scan/scripts/evolution_timeline.py",
    "select_targets": SKILLS / "improve/sokrates-improve/scripts/select_targets.py",
    "measure": SKILLS / "improve/sokrates-improve/scripts/measure.py",
    "diff_outputs": SKILLS / "improve/sokrates-improve/scripts/diff_outputs.py",
    "check_imports": SKILLS / "improve/sokrates-improve/scripts/check_imports.py",
    "preview_config": SKILLS / "config/sokrates-repo-config/scripts/preview_config.py",
    "propose_decompositions": SKILLS / "config/sokrates-decompositions/scripts/propose_decompositions.py",
    "propose_concerns": SKILLS / "config/sokrates-features-of-interest/scripts/propose_concerns.py",
    "check_landscape": SKILLS / "config/sokrates-landscape-config/scripts/check_landscape.py",
    "propose_virtual_landscapes": SKILLS / "config/sokrates-virtual-landscapes/scripts/propose_virtual_landscapes.py",
    "people": SKILLS / "config/sokrates-people-config/scripts/build_people_config.py",
    "visuals": SKILLS / "illustrators/generate_summary_visuals.py",
    "situation": SKILLS / "sokrates/scripts/situation.py",
    "capabilities": SKILLS / "sokrates/scripts/capabilities.py",
    "summarize": SKILLS / "scanners/sokrates-scan-core/scripts/summarize_findings.py",
    "recheck": SKILLS / "scanners/sokrates-scan-core/scripts/recheck_findings.py",
    "landscape_digest": SKILLS / "scanners/landscape-synthesis-scan/scripts/landscape_digest.py",
}


def run(script, *args, cwd=None, env=None):
    """Run a script with the test interpreter; returns the CompletedProcess (stdout/stderr as text, never raises)."""
    full_env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if env:
        full_env.update(env)
    return subprocess.run([sys.executable, str(SCRIPTS[script]), *map(str, args)], cwd=cwd, env=full_env,
                          capture_output=True, text=True, timeout=120)


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, doc):
    Path(path).write_text(json.dumps(doc, indent=2) + "\n")


def find_values(doc, key):
    """Every value stored under `key` anywhere in a nested JSON document."""
    found = []
    if isinstance(doc, dict):
        for k, v in doc.items():
            if k == key:
                found.append(v)
            found.extend(find_values(v, key))
    elif isinstance(doc, list):
        for item in doc:
            found.extend(find_values(item, key))
    return found


class FixtureTest(unittest.TestCase):
    """A temporary folder per test, with helpers to copy fixtures into it (scripts that write get a copy)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="sokrates-skills-test-")
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def copy_of(self, source, name=None):
        target = self.tmp / (name or Path(source).name)
        shutil.copytree(source, target)
        return target

    def extracted_data(self, data_zip=ALPHA_DATA_ZIP, name="data"):
        """The unzipped data.zip folder, the input of the scripts that read loose exports."""
        target = self.tmp / name
        with zipfile.ZipFile(data_zip) as archive:
            archive.extractall(target)
        return target

    def assert_ok(self, result, message=""):
        self.assertEqual(result.returncode, 0, f"{message}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
