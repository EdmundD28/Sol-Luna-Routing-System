from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills" / "sol-luna"


class PackageContractTests(unittest.TestCase):
    def test_skill_hot_path_stays_bounded(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(skill.splitlines()), 85)
        self.assertLessEqual(len(skill.split()), 1200)

    def test_skill_references_every_shipped_evidence_component(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        for relative_path in (
            "references/orchestration-policy.md",
            "references/routing-policy.v1.json",
            "references/evidence-and-runtime.md",
            "scripts/routing_policy.py",
            "scripts/ownership_guard.py",
            "scripts/lifecycle_contract.py",
            "scripts/native_lifecycle_receipt.py",
            "scripts/matched_eval.py",
            "scripts/runtime_receipt.py",
            "scripts/evidence_ledger.py",
            "scripts/phase_tracker.py",
            "scripts/delegation_contract.py",
        ):
            self.assertTrue((SKILL_ROOT / relative_path).is_file(), relative_path)
            self.assertIn(relative_path, skill)

    def test_effort_specific_worker_profiles_cover_the_predictive_ladder(self) -> None:
        for effort in ("low", "medium", "high", "xhigh", "max"):
            profile_path = ROOT / ".codex" / "agents" / f"luna-worker-{effort}.toml"
            with profile_path.open("rb") as handle:
                profile = tomllib.load(handle)
            self.assertEqual(profile["name"], f"luna_worker_{effort}")
            self.assertEqual(profile["model"], "gpt-5.6-luna")
            self.assertEqual(profile["model_reasoning_effort"], effort)
            self.assertEqual(profile["sandbox_mode"], "workspace-write")

    def test_specialized_read_only_profiles_are_minimal(self) -> None:
        expected = {"luna-reviewer.toml": "luna_reviewer", "luna-scout.toml": "luna_scout"}
        for filename, name in expected.items():
            with (ROOT / ".codex" / "agents" / filename).open("rb") as handle:
                profile = tomllib.load(handle)
            self.assertEqual(profile["name"], name)
            self.assertEqual(profile["model"], "gpt-5.6-luna")
            self.assertEqual(profile["sandbox_mode"], "read-only")

    def test_evidence_runtime_directory_is_ignored(self) -> None:
        ignores = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("runtime/sol-luna/", ignores)

    def test_ci_and_setup_lifecycle_are_shipped(self) -> None:
        self.assertTrue((ROOT / ".github" / "workflows" / "ci.yml").is_file())
        self.assertTrue((ROOT / "scripts" / "setup.py").is_file())

    def test_credit_trust_boundary_is_documented_fail_closed(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        reference = (SKILL_ROOT / "references" / "evidence-and-runtime.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("independently supplied claim index bound to each record and receipt", skill)
        self.assertIn("does **not** fetch billing data", reference)
        self.assertIn("validate a provider signature", reference)
        self.assertIn("does not establish a Codex desktop task-level authenticated credit receipt", readme)

    def test_production_ownership_and_phase_schema_boundaries_are_documented(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        policy = (SKILL_ROOT / "references" / "orchestration-policy.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for document in (skill, policy, readme):
            self.assertIn("schema 2", document.lower())
            self.assertIn("schema 1", document.lower())
        self.assertIn("partition_digest(plan)", readme)
        self.assertIn("executor_execution_union_seconds", readme)
        self.assertIn("execution_overlap_seconds", readme)
        self.assertIn("review never inflates overlap", readme)
        self.assertIn("legacy journals read-only", skill)

    def test_rolling_policy_optimizes_accepted_coverage_without_global_repair_budget(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        policy = (SKILL_ROOT / "references" / "orchestration-policy.md").read_text(encoding="utf-8")
        self.assertIn("accepted Luna coverage", skill)
        self.assertIn("genuinely replaces", skill)
        self.assertIn("reusing that worker", skill)
        self.assertIn("one package's repair does not consume another package's budget", skill)
        self.assertIn("same Luna for adjacent packages", policy)
        self.assertIn("A repair used by another package does not consume this package's budget", policy)

    def test_delegation_envelope_subtracts_sol_shadow_work(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        policy = (SKILL_ROOT / "references" / "orchestration-policy.md").read_text(encoding="utf-8")
        self.assertIn("Sol does not pre-script Luna's internal units", skill)
        self.assertIn("subtract it from effective Luna substitution", skill)
        self.assertIn("Stable-domain delegation envelope", policy)
        self.assertIn("Replayed actions are shadow work", policy)


if __name__ == "__main__":
    unittest.main()
