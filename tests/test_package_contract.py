from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills" / "sol-luna"


class PackageContractTests(unittest.TestCase):
    def test_skill_references_every_shipped_evidence_component(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        for relative_path in (
            "references/evidence-and-runtime.md",
            "scripts/runtime_receipt.py",
            "scripts/evidence_ledger.py",
        ):
            self.assertTrue((SKILL_ROOT / relative_path).is_file(), relative_path)
            self.assertIn(relative_path, skill)

    def test_worker_profile_remains_luna_max(self) -> None:
        profile_path = ROOT / ".codex" / "agents" / "luna-worker.toml"
        with profile_path.open("rb") as handle:
            profile = tomllib.load(handle)
        self.assertEqual(profile["model"], "gpt-5.6-luna")
        self.assertEqual(profile["model_reasoning_effort"], "max")
        self.assertNotIn("terra", profile["model"].lower())

    def test_evidence_runtime_directory_is_ignored(self) -> None:
        ignores = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("runtime/sol-luna/", ignores)


if __name__ == "__main__":
    unittest.main()
