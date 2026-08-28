from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup.py"
SPEC = importlib.util.spec_from_file_location("sol_luna_setup", SCRIPT)
assert SPEC and SPEC.loader
SETUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SETUP)


class SetupTests(unittest.TestCase):
    def roots(self, root: Path) -> tuple[Path, Path]:
        return root / ".codex", root / ".agents" / "skills"

    def test_default_skills_root_follows_codex_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            codex = Path(temp) / "custom-codex"
            output = io.StringIO()
            with mock.patch.object(sys, "argv", ["setup.py", "--codex-home", str(codex), "preview"]):
                with redirect_stdout(output):
                    self.assertEqual(SETUP.main(), 0)
            plan = json.loads(output.getvalue())
            skill_targets = [item["target"] for item in plan["operations"] if item["kind"] == "skill"]
            self.assertTrue(skill_targets)
            self.assertTrue(all(str(codex / "skills") in target for target in skill_targets))

    def test_install_doctor_update_and_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            codex = Path(temp) / "codex"
            skills = Path(temp) / "skills"
            self.assertEqual(SETUP.apply(codex, skills)["doctor"]["status"], "healthy")
            self.assertEqual(SETUP.apply(codex, skills, update=True)["doctor"]["status"], "healthy")
            self.assertEqual(SETUP.rollback(codex, skills)["status"], "rolled-back")
            self.assertFalse((skills / "sol-luna").exists())

    def test_migration_preview_migrate_doctor_update_and_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex, old_skills = self.roots(root)
            new_skills = codex / "skills"
            SETUP.apply(codex, old_skills)
            plan = SETUP.migration_plan(codex, new_skills)
            self.assertTrue(plan["safe_to_apply"])
            self.assertTrue(plan["writes_performed"] is False)
            SETUP.migrate(codex, new_skills, plan["plan_fingerprint"])
            self.assertEqual(SETUP.doctor(codex)["status"], "healthy")
            self.assertFalse((old_skills / "sol-luna").exists())
            self.assertTrue((new_skills / "sol-luna").exists())
            self.assertEqual(SETUP.apply(codex, new_skills, update=True)["doctor"]["status"], "healthy")
            SETUP.rollback(codex, new_skills)
            self.assertTrue((old_skills / "sol-luna").exists())
            self.assertFalse((new_skills / "sol-luna").exists())
            self.assertEqual(json.loads(SETUP.state_path(codex).read_text())["skills_home"], str(old_skills.resolve()))
            self.assertEqual(SETUP.doctor(codex)["status"], "healthy")

    def test_legacy_user_file_rejects_migration_without_deleting_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex, old_skills = self.roots(root)
            new_skills = codex / "skills"
            SETUP.apply(codex, old_skills)
            user_file = old_skills / "sol-luna" / "user-owned.txt"
            user_file.write_text("keep", encoding="utf-8")
            plan = SETUP.migration_plan(codex, new_skills)
            self.assertFalse(plan["safe_to_apply"])
            with self.assertRaises(SETUP.SetupError):
                SETUP.migrate(codex, new_skills, plan["plan_fingerprint"])
            self.assertTrue(user_file.exists())
            self.assertFalse((new_skills / "sol-luna").exists())

    def test_drift_target_conflict_and_stale_plan_are_zero_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex, old_skills = self.roots(root)
            new_skills = codex / "skills"
            SETUP.apply(codex, old_skills)
            old_file = old_skills / "sol-luna" / "SKILL.md"
            old_file.write_text("drift", encoding="utf-8")
            with self.assertRaises(SETUP.SetupError):
                SETUP.migration_plan(codex, new_skills)
            old_file.write_bytes((SETUP.SKILL_SOURCE / "SKILL.md").read_bytes())
            plan = SETUP.migration_plan(codex, new_skills)
            target = new_skills / "sol-luna" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("collision", encoding="utf-8")
            conflicted = SETUP.migration_plan(codex, new_skills)
            self.assertFalse(conflicted["safe_to_apply"])
            with self.assertRaises(SETUP.SetupError):
                SETUP.migrate(codex, new_skills, conflicted["plan_fingerprint"])
            self.assertEqual(target.read_text(encoding="utf-8"), "collision")
            target.unlink()
            old_file.write_text("changed after preview", encoding="utf-8")
            with self.assertRaises(SETUP.SetupError):
                SETUP.migrate(codex, new_skills, plan["plan_fingerprint"])
            self.assertFalse((new_skills / "sol-luna" / "orchestration-policy.md").exists())

    def test_untrusted_legacy_without_state_is_explicit_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex = root / ".codex"
            old = root / ".agents" / "skills" / "sol-luna"
            old.mkdir(parents=True)
            (old / "user.txt").write_text("do not guess", encoding="utf-8")
            plan = SETUP.migration_plan(codex, codex / "skills")
            self.assertFalse(plan["safe_to_apply"])
            self.assertTrue(any("untrusted-legacy-source" in item for item in plan["conflicts"]))
            self.assertTrue((old / "user.txt").exists())

    def test_failed_migration_restores_old_tree_agent_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex, old_skills = self.roots(root)
            new_skills = codex / "skills"
            SETUP.apply(codex, old_skills)
            before_state = SETUP.state_path(codex).read_bytes()
            old_file = old_skills / "sol-luna" / "SKILL.md"
            old_bytes = old_file.read_bytes()
            plan = SETUP.migration_plan(codex, new_skills)
            with mock.patch.object(SETUP, "doctor", return_value={"status": "drifted"}):
                with self.assertRaises(SETUP.SetupError):
                    SETUP.migrate(codex, new_skills, plan["plan_fingerprint"])
            self.assertEqual(old_file.read_bytes(), old_bytes)
            self.assertEqual(SETUP.state_path(codex).read_bytes(), before_state)
            self.assertFalse((new_skills / "sol-luna").exists())


    # Retained baseline safety coverage (the v0.7 tests remain independently
    # executable while the tests above exercise the v0.8 migration contract).
    def test_preview_is_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            codex, skills = self.roots(Path(temp))
            plan = SETUP.preview(codex, skills)
            self.assertTrue(plan["safe_to_apply"])
            self.assertFalse(plan["writes_performed"])
            self.assertFalse(codex.exists())
            self.assertFalse(skills.exists())

    def test_conflict_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            codex, skills = self.roots(Path(temp))
            target = skills / "sol-luna" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("user-owned\n", encoding="utf-8")
            self.assertFalse(SETUP.preview(codex, skills)["safe_to_apply"])
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
            state_file = SETUP.state_path(codex)
            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["installed"] = {str(outside): SETUP.digest(outside)}
            state["previous"] = {str(outside): None}
            state_file.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaises(SETUP.SetupError):
                SETUP.rollback(codex, skills)
            self.assertEqual(outside.read_text(encoding="utf-8"), "keep me\n")

    def test_broad_roots_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SETUP.SetupError):
                SETUP.preview(Path(Path(temp).anchor), Path(temp) / "skills")

    def test_legacy_preview_is_non_mutating_and_ordinary_preview_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            codex, skills = self.roots(Path(temp))
            old = codex / "skills" / "sol-luna"
            old.mkdir(parents=True)
            (old / "old.txt").write_text("legacy", encoding="utf-8")
            self.assertFalse(SETUP.preview(codex, skills)["safe_to_apply"])
            before = (old / "old.txt").read_text(encoding="utf-8")
            plan = SETUP.migration_plan(codex, skills)
            self.assertFalse(plan["writes_performed"])
            self.assertEqual(before, (old / "old.txt").read_text(encoding="utf-8"))

    def test_migration_fingerprint_and_rollback_restore_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex, old_skills = self.roots(root)
            new_skills = codex / "skills"
            SETUP.apply(codex, old_skills)
            old = old_skills / "sol-luna"
            old_agent = codex / "agents" / "luna-worker.toml"
            snapshot = (old / "SKILL.md").read_bytes(), old_agent.read_bytes()
            plan = SETUP.migration_plan(codex, new_skills)
            with self.assertRaises(SETUP.SetupError):
                SETUP.migrate(codex, new_skills, "sha256:wrong")
            self.assertEqual(((old / "SKILL.md").read_bytes(), old_agent.read_bytes()), snapshot)
            SETUP.migrate(codex, new_skills, plan["plan_fingerprint"])
            self.assertFalse(old.exists())
            old.mkdir(parents=True)
            self.assertEqual(SETUP.doctor(codex)["status"], "drifted")
            old.rmdir()
            SETUP.rollback(codex, new_skills)
            self.assertEqual((old / "SKILL.md").read_bytes(), snapshot[0])
            self.assertEqual(old_agent.read_bytes(), snapshot[1])

    def test_migration_rejects_overlapping_skill_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            codex = Path(temp) / "codex-home"
            skills = codex / "skills"
            SETUP.apply(codex, skills)
            with self.assertRaises(SETUP.SetupError):
                SETUP.migration_plan(codex, skills)

    def test_migration_rejects_stale_fingerprint_after_legacy_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex, old_skills = self.roots(root)
            new_skills = codex / "skills"
            SETUP.apply(codex, old_skills)
            legacy = old_skills / "sol-luna" / "SKILL.md"
            plan = SETUP.migration_plan(codex, new_skills)
            legacy.write_text("after", encoding="utf-8")
            with self.assertRaises(SETUP.SetupError):
                SETUP.migrate(codex, new_skills, plan["plan_fingerprint"])
            self.assertEqual(legacy.read_text(encoding="utf-8"), "after")
            self.assertFalse((new_skills / "sol-luna").exists())

    def test_failed_post_migration_doctor_restores_everything_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex, old_skills = self.roots(root)
            new_skills = codex / "skills"
            SETUP.apply(codex, old_skills)
            before_state = SETUP.state_path(codex).read_bytes()
            plan = SETUP.migration_plan(codex, new_skills)
            with mock.patch.object(SETUP, "doctor", return_value={"status": "drifted"}):
                with self.assertRaises(SETUP.SetupError):
                    SETUP.migrate(codex, new_skills, plan["plan_fingerprint"])
            self.assertTrue((old_skills / "sol-luna" / "SKILL.md").exists())
            self.assertEqual(SETUP.state_path(codex).read_bytes(), before_state)
            self.assertFalse((new_skills / "sol-luna").exists())

    def test_migration_refuses_existing_managed_installation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex, old_skills = self.roots(root)
            new_skills = codex / "skills"
            SETUP.apply(codex, old_skills)
            plan = SETUP.migration_plan(codex, new_skills)
            self.assertEqual(SETUP.migrate(codex, new_skills, plan["plan_fingerprint"])["status"], "migrated")

    def test_rollback_rejects_tampered_migration_paths_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex, old_skills = self.roots(root)
            new_skills = codex / "skills"
            SETUP.apply(codex, old_skills)
            plan = SETUP.migration_plan(codex, new_skills)
            SETUP.migrate(codex, new_skills, plan["plan_fingerprint"])
            managed = new_skills / "sol-luna" / "SKILL.md"
            managed_before = managed.read_bytes()
            outside = root / "outside"
            outside.mkdir()
            state_file = SETUP.state_path(codex)
            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["migration"]["legacy_skill"] = str(outside)
            state_file.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaises(SETUP.SetupError):
                SETUP.rollback(codex, new_skills)
            self.assertEqual(managed.read_bytes(), managed_before)
            self.assertTrue(outside.is_dir())

    def test_migration_rejects_agent_link_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex, old_skills = self.roots(root)
            new_skills = codex / "skills"
            SETUP.apply(codex, old_skills)
            agent = codex / "agents" / "luna-worker.toml"
            link_target = root / "agent-target"
            link_target.write_bytes(agent.read_bytes())
            try:
                agent.unlink()
                agent.symlink_to(link_target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaises(SETUP.SetupError):
                SETUP.migration_plan(codex, new_skills)

    def test_migration_rollback_removes_agents_added_during_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex, old_skills = self.roots(root)
            new_skills = codex / "skills"
            SETUP.apply(codex, old_skills)
            omitted = codex / "agents" / "luna-reviewer.toml"
            state_file = SETUP.state_path(codex)
            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["installed"].pop(str(omitted), None)
            state["previous"].pop(str(omitted), None)
            state["source_fingerprint"] = SETUP.source_fingerprint_for_state(
                SETUP.managed_assets(codex, old_skills), state["installed"]
            )
            omitted.unlink()
            state_file.write_text(json.dumps(state), encoding="utf-8")
            plan = SETUP.migration_plan(codex, new_skills)
            self.assertTrue(plan["safe_to_apply"])
            SETUP.migrate(codex, new_skills, plan["plan_fingerprint"])
            self.assertTrue(omitted.exists())
            SETUP.rollback(codex, new_skills)
            self.assertFalse(omitted.exists())
            self.assertTrue((old_skills / "sol-luna" / "SKILL.md").exists())
            self.assertEqual(SETUP.doctor(codex)["status"], "healthy")

    def test_migration_accepts_trusted_old_hashes_when_current_source_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex, old_skills = self.roots(root)
            new_skills = codex / "skills"
            SETUP.apply(codex, old_skills)
            old_file = old_skills / "sol-luna" / "SKILL.md"
            old_file.write_text("trusted old source\n", encoding="utf-8")
            state_file = SETUP.state_path(codex)
            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["installed"][str(old_file)] = SETUP.digest(old_file)
            state["source_fingerprint"] = SETUP.installed_fingerprint_for_state(
                SETUP.managed_assets(codex, old_skills), state["installed"]
            )
            state_file.write_text(json.dumps(state), encoding="utf-8")
            self.assertNotEqual(SETUP.digest(old_file), SETUP.digest(SETUP.SKILL_SOURCE / "SKILL.md"))
            plan = SETUP.migration_plan(codex, new_skills)
            self.assertTrue(plan["safe_to_apply"])
            self.assertEqual(SETUP.migrate(codex, new_skills, plan["plan_fingerprint"])["status"], "migrated")
            self.assertEqual((new_skills / "sol-luna" / "SKILL.md").read_bytes(),
                             (SETUP.SKILL_SOURCE / "SKILL.md").read_bytes())

    def test_update_accepts_new_managed_asset_and_rollback_removes_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex, skills = self.roots(root)
            full_assets = SETUP.managed_assets(codex, skills)
            added = next(item for item in full_assets if item["relative"] == "scripts/delegation_contract.py")
            subset = [item for item in full_assets if item is not added]
            with mock.patch.object(SETUP, "managed_assets", return_value=subset):
                SETUP.apply(codex, skills)
            self.assertFalse(added["target"].exists())
            plan = SETUP.preview(codex, skills, require_installed=True)
            operation = next(item for item in plan["operations"] if item["target"] == str(added["target"]))
            self.assertEqual(operation["action"], "create")
            self.assertTrue(plan["safe_to_apply"])
            updated = SETUP.apply(codex, skills, update=True)
            self.assertEqual(updated["doctor"]["status"], "healthy")
            self.assertTrue(added["target"].exists())
            self.assertEqual(SETUP.rollback(codex, skills)["status"], "rolled-back")
            self.assertFalse(added["target"].exists())

    def test_migrated_install_can_add_asset_then_rollback_to_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex, old_skills = self.roots(root)
            new_skills = codex / "skills"
            managed_assets = SETUP.managed_assets

            def without_new_asset(codex_home: Path, skills_home: Path) -> list[dict]:
                return [
                    item
                    for item in managed_assets(codex_home, skills_home)
                    if item["relative"] != "scripts/delegation_contract.py"
                ]

            with mock.patch.object(SETUP, "managed_assets", side_effect=without_new_asset):
                SETUP.apply(codex, old_skills)
                plan = SETUP.migration_plan(codex, new_skills)
                SETUP.migrate(codex, new_skills, plan["plan_fingerprint"])

            added_new = next(
                item
                for item in SETUP.managed_assets(codex, new_skills)
                if item["relative"] == "scripts/delegation_contract.py"
            )
            self.assertFalse(added_new["target"].exists())
            self.assertEqual(SETUP.apply(codex, new_skills, update=True)["doctor"]["status"], "healthy")
            self.assertTrue(added_new["target"].exists())

            self.assertEqual(SETUP.rollback(codex, new_skills)["status"], "rolled-back")
            self.assertFalse((new_skills / "sol-luna").exists())
            self.assertTrue((old_skills / "sol-luna" / "SKILL.md").exists())
            self.assertFalse(old_skills.joinpath("sol-luna", "scripts", "delegation_contract.py").exists())
            restored_state = json.loads(SETUP.state_path(codex).read_text(encoding="utf-8"))
            self.assertEqual(restored_state["skills_home"], str(old_skills.resolve()))
            self.assertEqual(SETUP.doctor(codex)["status"], "healthy")

    def test_update_rejects_source_removal_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex, skills = self.roots(root)
            SETUP.apply(codex, skills)
            full_assets = SETUP.managed_assets(codex, skills)
            removed = next(item for item in full_assets if item["relative"] == "scripts/delegation_contract.py")
            state_file = SETUP.state_path(codex)
            before_state = state_file.read_bytes()
            before_file = removed["target"].read_bytes()
            subset = [item for item in full_assets if item is not removed]
            with mock.patch.object(SETUP, "managed_assets", return_value=subset):
                with self.assertRaises(SETUP.SetupError):
                    SETUP.preview(codex, skills, require_installed=True)
                with self.assertRaises(SETUP.SetupError):
                    SETUP.apply(codex, skills, update=True)
            self.assertEqual(state_file.read_bytes(), before_state)
            self.assertEqual(removed["target"].read_bytes(), before_file)

    def test_update_rejects_user_conflict_at_new_managed_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex, skills = self.roots(root)
            full_assets = SETUP.managed_assets(codex, skills)
            added = next(item for item in full_assets if item["relative"] == "scripts/delegation_contract.py")
            subset = [item for item in full_assets if item is not added]
            with mock.patch.object(SETUP, "managed_assets", return_value=subset):
                SETUP.apply(codex, skills)
            added["target"].parent.mkdir(parents=True, exist_ok=True)
            added["target"].write_text("user-owned", encoding="utf-8")
            before_state = SETUP.state_path(codex).read_bytes()
            plan = SETUP.preview(codex, skills, require_installed=True)
            self.assertFalse(plan["safe_to_apply"])
            with self.assertRaises(SETUP.SetupError):
                SETUP.apply(codex, skills, update=True)
            self.assertEqual(added["target"].read_text(encoding="utf-8"), "user-owned")
            self.assertEqual(SETUP.state_path(codex).read_bytes(), before_state)


if __name__ == "__main__":
    unittest.main()
