from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills" / "sol-luna"


class PackageContractTests(unittest.TestCase):
    def skill(self) -> str:
        return (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    def policy(self) -> str:
        return (SKILL_ROOT / "references" / "orchestration-policy.md").read_text(encoding="utf-8")

    def readme(self) -> str:
        return (ROOT / "README.md").read_text(encoding="utf-8")

    def test_skill_hot_path_stays_bounded(self) -> None:
        skill = self.skill()
        self.assertLessEqual(len(skill.splitlines()), 85)
        self.assertLessEqual(len(skill.split()), 1200)

    def test_shipped_components_exist_without_inflating_the_hot_path(self) -> None:
        shipped = (
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
            "scripts/closure_contract.py",
            "scripts/net_substitution.py",
        )
        for relative_path in shipped:
            self.assertTrue((SKILL_ROOT / relative_path).is_file(), relative_path)

        skill = self.skill()
        self.assertIn("references/orchestration-policy.md", skill)
        direct_scripts = set(re.findall(r"scripts/[a-z_]+\.py", skill))
        self.assertEqual(
            direct_scripts,
            {
                "scripts/net_substitution.py",
                "scripts/routing_policy.py",
                "scripts/ownership_guard.py",
            },
        )
        self.assertNotIn("references/evidence-and-runtime.md", skill)

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

    def test_allowance_and_credit_boundaries_fail_closed(self) -> None:
        skill = self.skill()
        reference = (SKILL_ROOT / "references" / "evidence-and-runtime.md").read_text(encoding="utf-8")
        self.assertIn("matched five-hour readings", skill)
        self.assertIn("never authorize routing or included-plan conclusions", skill)
        self.assertIn("does **not** fetch billing data", reference)
        self.assertIn("validate a provider signature", reference)
        self.assertIn("does not establish a Codex desktop task-level authenticated credit receipt", self.readme())

    def test_skill_preserves_economic_routing_and_effort_gates(self) -> None:
        skill = self.skill()
        for contract in (
            "included-plan allowance before elapsed time",
            "one complete-Luna envelope",
            "lowest evidence-supported effort",
            "external quality evidence bound to the task family",
            "Default to one retained Luna writer",
            "Sol does not pre-script Luna's internal units",
            "read-only acceptance lane",
            "never shadow-implements Luna work",
        ):
            self.assertIn(contract, skill)

    def test_skill_preserves_ownership_handoff_and_repair_gates(self) -> None:
        skill = self.skill()
        for contract in (
            "schema-2 ownership plan",
            "candidate-digest-bound `OK`",
            "remains `HOLD`",
            "same Luna for at most three focused repairs",
            "at most one evidence-backed effort escalation",
            "reclaim only the affected responsibility unit",
        ):
            self.assertIn(contract, skill)

    def test_route_measurement_boundary_is_explicit(self) -> None:
        skill = self.skill()
        self.assertIn("common independent referee runs outside both route intervals", skill)
        self.assertIn("Luna-specific planning, review, repair, integration, and rework remain inside", skill)
        self.assertIn("five-hour and weekly percentage-point changes", skill)

    def test_detailed_policy_and_readme_contracts_remain_available(self) -> None:
        policy = self.policy()
        readme = self.readme()
        for document in (policy, readme):
            self.assertIn("schema 2", document.lower())
            self.assertIn("schema 1", document.lower())
        for contract in (
            "actual_sol_labor_reduction",
            "structural_net_substitution",
            "min(actual_sol_labor_reduction, structural_net_substitution)",
            "Splitting or renaming packages never increases the allowance",
            "one complete top-level task in one continuous run by a single real Sol controller",
            "must not pre-split, separately dispatch, or artificially serialize Sol packages",
            "automatic_execution_allowed: false",
        ):
            self.assertIn(contract, policy)
        self.assertIn("partition_digest(plan)", readme)
        self.assertIn("executor_execution_union_seconds", readme)
        self.assertIn("execution_overlap_seconds", readme)
        self.assertIn("review never inflates overlap", readme)


if __name__ == "__main__":
    unittest.main()
