from __future__ import annotations

import re
import importlib.util
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

    def test_writer_profiles_use_compact_v033_execution_contract(self) -> None:
        required = (
            "specified repository root", "capsule dependency closure", "declared",
            "supplied runtime", "one bounded read", "one candidate edit",
            "exactly one combined command", "emits path/digests", "No separate diff/status check",
            "messaging tool", "broad", "repeat", "full diff", "second round", "exclusive",
            "agents", "OK|<package_ref>|C=<candidate_digest>|PD=<path_set_digest>|TEST=<passed>/<total>|PATH=<count>|REPAIR=<count>|EX=0",
            "BLOCK|<package_ref>|K=<code>|REF=<minimal>|OPT=<ids>", "same Luna", "FAILED|",
        )
        for filename, effort in (("luna-worker.toml", "high"), *( (f"luna-worker-{e}.toml", e) for e in ("low", "medium", "high", "xhigh", "max") )):
            path = ROOT / ".codex" / "agents" / filename
            with path.open("rb") as handle:
                instructions = tomllib.load(handle)["developer_instructions"]
            self.assertNotIn("READY_FOR_REVIEW", instructions)
            self.assertLessEqual(len(instructions.split()), 110)
            self.assertIn("Return only one final line", instructions)
            for phrase in required:
                self.assertIn(phrase, instructions)
            spec = importlib.util.spec_from_file_location(
                "compact_protocol", SKILL_ROOT / "scripts" / "compact_protocol.py"
            )
            self.assertIsNotNone(spec and spec.loader)
            protocol = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(protocol)
            digest = "sha256:" + "1" * 64
            frozen = protocol.freeze_manifest({
                "schema_version": 1, "package_id": "profile", "executor_id": "luna-01",
                "ownership_id": "own-01", "task_digest": digest, "allocation_digest": digest,
                "luna_effort": effort, "objective": "test", "write_scope": ["src/a.py"],
                "acceptance_ids": ["accept-a"], "forbidden_actions": ["network"],
                "stop_conditions": ["scope"], "context_refs": [],
            })
            package = protocol.package_ref(frozen)
            ok_match = re.search(
                r"OK\|<package_ref>\|C=<candidate_digest>\|PD=<path_set_digest>\|"
                r"TEST=<passed>/<total>\|PATH=<count>\|REPAIR=<count>\|EX=0",
                instructions,
            )
            self.assertIsNotNone(ok_match)
            assert ok_match is not None
            ok = ok_match.group(0)
            ok = ok.replace("<package_ref>", package).replace("<candidate_digest>", "1" * 64).replace("<path_set_digest>", "2" * 64).replace("<passed>/<total>", "1/1").replace("<count>", "0")
            self.assertEqual(protocol.parse_line(ok, frozen)["record_type"], "OK")
            block_match = re.search(
                r"BLOCK\|<package_ref>\|K=<code>\|REF=<minimal>\|OPT=<ids>", instructions
            )
            self.assertIsNotNone(block_match)
            assert block_match is not None
            block = block_match.group(0)
            block = block.replace("<package_ref>", package).replace("<code>", "WAIT").replace("<minimal>", "minimal").replace("<ids>", "ask-user")
            self.assertEqual(protocol.parse_line(block, frozen)["record_type"], "BLOCK")

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

    def test_skill_prevents_context_and_full_suite_replay(self) -> None:
        skill = self.skill()
        policy = self.policy()
        readme = self.readme()
        for contract in (
            'fork_turns="none"',
            "never paste its body into model messages",
            "do not resend the manifest or prior background",
            "one in-route executor per suite",
            "before the only final full suite",
            "without rerunning Luna's checks",
        ):
            self.assertIn(contract.casefold(), skill.casefold())
        self.assertIn("Sol is the sole full-suite executor", skill)
        self.assertIn("same luna and transmits only new failure evidence", policy.casefold())
        self.assertIn("The designated executor then runs that suite once", readme)

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
