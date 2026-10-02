"""The skill pages and scripts as a set: valid front matter, no dangling script references, every script answers --help,
the entry skill's map names every skill, the installer links every skill."""
import re
import subprocess
import sys
import unittest

from tests.support import ROOT, SKILLS, FixtureTest

SKILL_DIRS = sorted(p for p in SKILLS.glob("*/*/SKILL.md")) + sorted(p for p in SKILLS.glob("*/SKILL.md"))
PLACEHOLDER_HOMES = {"this-skill-path": None, "core-skill-path": SKILLS / "scanners/sokrates-scan-core",
                     "scan-core": SKILLS / "scanners/sokrates-scan-core", "landscape-config": SKILLS / "config/sokrates-landscape-config",
                     "people-config": SKILLS / "config/sokrates-people-config", "landscape-synthesis-scan": SKILLS / "scanners/landscape-synthesis-scan"}


def front_matter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    return dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)


class SkillPagesTest(unittest.TestCase):

    def test_front_matter_names_the_folder(self):
        self.assertGreaterEqual(len(SKILL_DIRS), 28)
        for page in SKILL_DIRS:
            with self.subTest(skill=page.parent.name):
                fm = front_matter(page.read_text())
                self.assertIsNotNone(fm, "front matter block")
                self.assertEqual(fm.get("name", "").strip(), page.parent.name)
                self.assertGreater(len(fm.get("description", "").strip()), 80, "a description an agent can route on")

    def test_every_referenced_script_exists(self):
        all_scripts = {p.name: p for p in SKILLS.rglob("scripts/*.py")}
        for page in SKILL_DIRS:
            text = page.read_text()
            for placeholder, script in re.findall(r"<([a-z-]+)>/scripts/([a-z_]+\.py)", text):
                with self.subTest(skill=page.parent.name, ref=f"<{placeholder}>/scripts/{script}"):
                    home = page.parent if placeholder == "this-skill-path" else PLACEHOLDER_HOMES.get(placeholder)
                    if home is not None:
                        self.assertTrue((home / "scripts" / script).is_file(), f"{home.name} has no scripts/{script}")
                    else:
                        self.assertIn(script, all_scripts, f"no script named {script} anywhere")
            for script in re.findall(r"(?<![/\w])scripts/([a-z_]+\.py)", text):
                with self.subTest(skill=page.parent.name, ref=f"scripts/{script}"):
                    self.assertTrue((page.parent / "scripts" / script).is_file() or script in all_scripts, script)

    def test_every_script_answers_help(self):
        for script in sorted(SKILLS.rglob("scripts/*.py")) + sorted(SKILLS.glob("illustrators/*.py")):
            if "argparse" not in script.read_text():
                continue        # a library module (sokrates_data.py), not a command
            with self.subTest(script=str(script.relative_to(SKILLS))):
                result = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr[-500:])
                self.assertIn("usage", result.stdout.lower())

    def test_entry_skill_maps_every_skill(self):
        entry = (SKILLS / "sokrates" / "SKILL.md").read_text()
        for page in SKILL_DIRS:
            name = page.parent.name
            if name == "sokrates":
                continue
            with self.subTest(skill=name):
                self.assertIn(f"`{name}`", entry, f"the entry skill's map does not mention {name}")


class InstallerTest(FixtureTest):

    def test_install_sh_links_every_skill(self):
        target = self.tmp / "skills"
        result = subprocess.run(["sh", str(ROOT / "install.sh"), str(target)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        linked = sorted(p.name for p in target.iterdir())
        self.assertEqual(linked, sorted(p.parent.name for p in SKILL_DIRS))
        self.assertIn(f"linked {len(SKILL_DIRS)} skills", result.stdout)
