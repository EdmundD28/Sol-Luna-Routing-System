from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup.py"
SPEC = importlib.util.spec_from_file_location("sol_luna_setup", SCRIPT)
assert SPEC and SPEC.loader
SETUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SETUP)


class SetupTests(unittest.TestCase):
    def roots(self, root: Path) -> tuple[Path, Path]:
        return root / "codex-home", root / "skills-home"

    def test_preview_is_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            codex, skills = self.roots(Path(temp))
            plan = SETUP.preview(codex, skills)
            self.assertTrue(plan["safe_to_apply"])
            self.assertFalse(plan["writes_performed"])
            self.assertFalse(codex.exists())
            self.assertFalse(skills.exists())

    def test_install_doctor_update_and_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            codex, skills = self.roots(Path(temp))
            installed = SETUP.apply(codex, skills)
            self.assertEqual(installed["doctor"]["status"], "healthy")
            self.assertTrue((skills / "sol-luna" / "SKILL.md").is_file())
            self.assertTrue((codex / "agents" / "luna-worker-xhigh.toml").is_file())
            updated = SETUP.apply(codex, skills, update=True)
            self.assertEqual(updated["doctor"]["status"], "healthy")
            rolled = SETUP.rollback(codex, skills)
            self.assertEqual(rolled["status"], "rolled-back")
            self.assertFalse((skills / "sol-luna" / "SKILL.md").exists())

    def test_conflict_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            codex, skills = self.roots(Path(temp))
            target = skills / "sol-luna" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("user-owned\n", encoding="utf-8")
            plan = SETUP.preview(codex, skills)
            self.assertFalse(plan["safe_to_apply"])
            with self.assertRaises(SETUP.SetupError):
                SETUP.apply(codex, skills)
            self.assertEqual(target.read_text(encoding="utf-8"), "user-owned\n")

    def test_doctor_detects_drift_and_rollback_preserves_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            codex, skills = self.roots(Path(temp))
            SETUP.apply(codex, skills)
            target = skills / "sol-luna" / "SKILL.md"
            target.write_text("user-modified\n", encoding="utf-8")
            self.assertEqual(SETUP.doctor(codex)["status"], "drifted")
            with self.assertRaises(SETUP.SetupError):
                SETUP.rollback(codex, skills)
            self.assertEqual(target.read_text(encoding="utf-8"), "user-modified\n")

    def test_rollback_rejects_tampered_state_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex, skills = self.roots(root)
            SETUP.apply(codex, skills)
            outside = root / "outside.txt"
            outside.write_text("keep me\n", encoding="utf-8")
            state_path = codex / "sol-luna-install-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["installed"] = {str(outside): SETUP.digest(outside)}
            state["previous"] = {str(outside): None}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaises(SETUP.SetupError):
                SETUP.rollback(codex, skills)
            self.assertEqual(outside.read_text(encoding="utf-8"), "keep me\n")

    def test_broad_roots_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SETUP.SetupError):
                SETUP.preview(Path(Path(temp).anchor), Path(temp) / "skills")


if __name__ == "__main__":
    unittest.main()
