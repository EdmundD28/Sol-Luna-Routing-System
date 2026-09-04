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

    def test_writer_profiles_use_lean_human_readable_contract(self) -> None:
        required = (
            "specified repository", "Read only named dependencies", "never read declared-excluded content", "exclusive paths",
            "complete semantic change", "file-scoped in-place", "Never delete a tracked file", "hide executable code",
            "simulate a refactor by duplication", "stable file-scoped stages", "game line caps through compression",
            "For semantic refactors", "minimal causal smoke per changed public boundary",
            "parse or compile already-read source/schema without emitting files",
            "explicit contract permission", "Refresh affected checks after edits",
            "Review the candidate during preflight", "designated final suite last and once",
            "On failure return FAILED", "repair only after Sol sends new evidence", "After PASS, return immediately",
            "Stop refused edits", "never bypass edit safety",
            "after required user confirmation; otherwise BLOCK",
            "Do not spawn agents", "architecture/product decisions", "separate authority", "network/external systems", "publish",
            "commit", "push", "deploy", "install",
            "READY|<package>|PATH=<paths>|TEST=<acceptance-id>:PASS:<passed>/<total>:EXIT=<code>|RISK=<none-or-code>",
            "BLOCK|<package>|K=<code>|REF=<minimal>",
            "FAILED|<package>|TEST=<acceptance-id>:FAIL:EXIT=<code>", "Retain context", "only new evidence",
        )
        for filename, effort in (("luna-worker.toml", "high"), *( (f"luna-worker-{e}.toml", e) for e in ("low", "medium", "high", "xhigh", "max") )):
            path = ROOT / ".codex" / "agents" / filename
            with path.open("rb") as handle:
                instructions = tomllib.load(handle)["developer_instructions"]
            self.assertLessEqual(len(instructions.split()), 185)
            self.assertNotIn("compact_protocol", instructions)
            self.assertNotIn("candidate_digest", instructions)
            self.assertNotIn("path_set_digest", instructions)
            self.assertIn("Return one concise line", instructions)
            for phrase in required:
                self.assertIn(phrase, instructions)

    def test_lean_skill_keeps_numeric_route_gates_and_host_observed_results(self) -> None:
        skill = (ROOT / ".agents" / "skills" / "sol-luna" / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for phrase in (
            "at least 80% predicted first-pass acceptance",
            "at least 50% expected accepted-cost reduction",
            "no predicted final-defect or elapsed regression",
        ):
            self.assertIn(phrase, skill)
        self.assertIn("or its test result is not host-observable", readme)
        self.assertNotIn("A lower-effort failure is not required", readme)
        self.assertIn("same-allocation lower-effort option is rejected by a quality or defect gate", readme)

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
        self.assertIn("matched five-hour and weekly readings", skill)
        self.assertIn("never authorize routing or included-plan claims", skill)
        self.assertIn("does **not** fetch billing data", reference)
        self.assertIn("validate a provider signature", reference)
        self.assertIn("does not establish a Codex desktop task-level authenticated credit receipt", self.readme())

    def test_skill_preserves_economic_routing_and_effort_gates(self) -> None:
        skill = self.skill()
        for contract in (
            "Quality and included-plan allowance are co-primary gates",
            "same independent acceptance contract",
            "predicted quality and defects are no worse",
            "expected included-plan allowance is lower",
            "expected elapsed time is no worse",
            "matched task-family evidence",
            "one low-impact complete-Luna Low/Medium cold start",
            "empty Sol controller queue",
            "conservative execution plus one repair plus Sol recovery and downstream dependency-closure re-execution",
            "one Luna can own substantial",
            "lowest effort supported by the task",
            "same-allocation lower-effort option is rejected by a quality or defect gate",
            "Default to one retained Luna writer",
            "Sol will not repeat that work",
            "Sol never shadow-implements Luna-owned work",
        ):
            self.assertIn(contract, skill)
        self.assertNotIn("first-pass completion is plausible", skill)

    def test_skill_preserves_ownership_handoff_and_repair_gates(self) -> None:
        skill = self.skill()
        for contract in (
            "Do not require a manifest, digest, ledger, ownership tool, or receipt generator on the normal path",
            "Use schema-2 ownership and compact receipts only for formal evidence",
            "does not change the candidate or retest until Sol sends exact new failure evidence",
            "Do not resend the task background",
            "all exact failures from that suite",
            "failure count alone is not a reclaim signal",
            "reclaims only the affected slice",
        ):
            self.assertIn(contract, skill)

    def test_skill_prevents_context_and_full_suite_replay(self) -> None:
        skill = self.skill()
        policy = self.policy()
        readme = self.readme()
        for contract in (
            'fork_turns="none"',
            "Do not resend the task background",
            "Exactly one executor runs the final full suite",
            "Sol does not rerun it",
            "host-observed test command/result",
            "without redoing Luna's investigation",
            "Never delete a tracked file merely to replace it",
            "Stop a refused edit and never route around it",
            "after any required user confirmation, otherwise report `BLOCK`",
            "Complete\" is semantic",
            "never hide old executable source inside strings or comments",
            "when the acceptance contract requires a public compatibility facade",
            "cheapest affected in-memory preflight",
            "direct imports only when the contract explicitly requires and permits them",
            "A candidate-changing edit invalidates only its affected checks",
            "one smallest representative causal smoke per moved public boundary",
            "structural preflight alone is not acceptance",
            "does not change the candidate or retest until Sol sends exact new failure evidence",
            "compress statements to game a line cap",
            "returns immediately after a pass without post-pass rereads, diffs, status checks, or tests",
        ):
            self.assertIn(contract.casefold(), skill.casefold())
        self.assertIn("Sol is the sole full-suite executor", skill)
        self.assertNotIn("multiple independent failure clusters", skill)
        self.assertIn("number of failing tests or causal roots alone never forces reclaim", policy)
        self.assertIn("reuse the same luna for focused repair and transmit only new failure evidence", policy.casefold())
        self.assertIn("A formal route also reviews its candidate receipt", policy)
        self.assertIn("Luna reviews before the only final suite and returns immediately after a pass", readme)

    def test_route_measurement_boundary_is_explicit(self) -> None:
        skill = self.skill()
        self.assertIn("five-hour and weekly percentage-point changes", skill)
        self.assertIn("Diagnostic tokens explain failures", skill)
        self.assertIn("never replace matched five-hour and weekly readings", skill)

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
