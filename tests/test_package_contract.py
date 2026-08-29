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
            "scripts/closure_contract.py",
            "scripts/net_substitution.py",
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

    def test_rolling_policy_optimizes_net_substitution_without_package_inflation(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        policy = (SKILL_ROOT / "references" / "orchestration-policy.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("net substitution of expensive Sol work", skill)
        self.assertIn("Calls, packages, actions, and writer count never enter the benefit numerator", skill)
        self.assertIn("marginal net substitution is positive", skill)
        self.assertIn("domain, assumptions, or independence need changes", skill)
        self.assertIn("route-independent repair cap by acceptance claim or baseline weight", skill)
        self.assertNotIn("one package's repair does not consume another package's budget", skill)
        self.assertIn("sol_baseline - luna_execution", policy)
        self.assertIn("actual_sol_labor_reduction", policy)
        self.assertIn("structural_net_substitution", policy)
        self.assertIn("min(actual_sol_labor_reduction, structural_net_substitution)", policy)
        self.assertIn("Splitting or renaming packages never increases the allowance", policy)
        self.assertIn("one complete top-level task in one continuous run by a single real Sol controller", policy)
        self.assertIn("must not pre-split, separately dispatch, or artificially serialize Sol packages", policy)
        self.assertIn("v0.10 evidence remains `HOLD`", policy)
        self.assertIn("automatic_execution_allowed: false", policy)
        self.assertIn("P005 field pilot", readme)
        self.assertIn("Both remain `HOLD`", readme)

    def test_common_referee_is_external_but_luna_specific_sol_labor_is_internal(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        policy = (SKILL_ROOT / "references" / "orchestration-policy.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for document in (skill, policy, readme):
            self.assertIn("common independent referee", document)
            self.assertIn("outside both route intervals", document)
        self.assertIn("Luna-specific review, integration, replay, and rework remain inside", skill)
        self.assertIn("required specifically because Luna participated stays inside", policy)
        self.assertIn("Luna-specific planning, review, integration, replay, and rework remain inside", readme)
        self.assertIn("one continuous run by a single real Sol controller", readme)

    def test_delegation_envelope_subtracts_sol_shadow_work(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        policy = (SKILL_ROOT / "references" / "orchestration-policy.md").read_text(encoding="utf-8")
        self.assertIn("Sol does not pre-script Luna's internal units", skill)
        self.assertIn("Repeated implementation shadows the affected responsibility unit", skill)
        self.assertIn("Stable-domain delegation envelope", policy)
        self.assertIn("a replay shadows only the affected unit", policy)
        self.assertIn("scripts/closure_contract.py", skill)
        self.assertIn("net substitution of expensive Sol work", skill)
        self.assertIn("schema-2 candidate-bound handoff", skill)

    def test_complete_luna_candidate_is_not_displaced_by_busywork(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        policy = (SKILL_ROOT / "references" / "orchestration-policy.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Always evaluate one complete-Luna envelope", skill)
        self.assertIn("do not retain Sol implementation merely to keep Sol busy", skill)
        self.assertIn("Sol has a read-only acceptance lane", skill)
        self.assertIn("candidate set must include one complete-Luna envelope", policy)
        self.assertIn("Do not reserve a Sol implementation unit merely to keep the controller busy", policy)
        self.assertIn("bounded waiting is economically preferable", policy)
        self.assertIn("compare a complete-Luna envelope", readme)
        self.assertIn("does not keep an implementation package merely to stay busy", readme)


if __name__ == "__main__":
    unittest.main()
