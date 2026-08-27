from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / ".agents" / "skills" / "sol-luna" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location("matched_eval", SCRIPT_DIR / "matched_eval.py")
assert SPEC and SPEC.loader
MATCHED = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MATCHED)
LEDGER = MATCHED.evidence_ledger
DIGEST = "sha256:" + "1" * 64
POLICY_DIGEST = "sha256:" + "2" * 64


def plan(pair_count: int = 5) -> dict:
    return MATCHED.validate_plan(
        {
            "schema_version": 1,
            "campaign_id": "campaign-v1",
            "task_family": "bounded-feature",
            "policy_version": "1.0.0",
            "policy_fingerprint": POLICY_DIGEST,
            "pairs": [
                {
                    "pair_id": f"pair-{index:03d}",
                    "starting_candidate_ref": f"git:start-{index}",
                    "task_spec_digest": DIGEST,
                    "acceptance_suite_id": "hidden-v1",
                    "acceptance_suite_digest": DIGEST,
                }
                for index in range(1, pair_count + 1)
            ],
        }
    )


def record(pair: dict, route: str, *, wrong_start: bool = False) -> dict:
    tokens = 1000 if route == "SOL_ONLY" else 700
    phases = (
        {"sol_execution": 1000}
        if route == "SOL_ONLY"
        else {
            "sol_planning": 80,
            "sol_retained_execution": 100,
            "luna_execution": 400,
            "sol_review": 60,
            "integration": 60,
        }
    )
    return LEDGER.validate_record(
        {
            "run_ref": f"{pair['pair_id']}-{route}",
            "campaign_id": "campaign-v1",
            "pair_id": pair["pair_id"],
            "task_family": "bounded-feature",
            "route": route,
            "evaluation_mode": "MATCHED",
            "outcome": "ACCEPTED",
            "independent_acceptance": "PASSED",
            "acceptance_suite_id": pair["acceptance_suite_id"],
            "acceptance_suite_digest": pair["acceptance_suite_digest"],
            "task_spec_digest": pair["task_spec_digest"],
            "starting_candidate_ref": "git:wrong" if wrong_start else pair["starting_candidate_ref"],
            "final_candidate_ref": f"git:{pair['pair_id']}-{route.lower()}",
            "policy_version": "1.0.0",
            "policy_fingerprint": POLICY_DIGEST,
            "luna_effort": "high" if route == "SOL_LUNA" else "",
            "writer_count": 1 if route == "SOL_LUNA" else 0,
            "review_depth": "STANDARD",
            "first_pass_accepted": True,
            "repair_rounds": 0,
            "defects": 0,
            "elapsed_seconds": 1000 if route == "SOL_ONLY" else 700,
            "total_tokens": tokens,
            "token_source": "session-v1",
            "token_uncertainty": "complete diagnostic snapshots",
            "phase_elapsed_seconds": {"sol_execution": 1000}
            if route == "SOL_ONLY"
            else {
                "sol_planning": 50,
                "sol_retained_execution": 500,
                "luna_execution": 500,
                "sol_review": 75,
                "integration": 75,
            },
            "phase_tokens": phases,
            "observed_sol_model": "gpt-5.6-sol",
            "observed_luna_model": "gpt-5.6-luna" if route == "SOL_LUNA" else "",
            "runtime_identity_source": "codex-session-turn-context-v1",
            "runtime_identity_uncertainty": "none",
        }
    )


class MatchedEvalTests(unittest.TestCase):
    def test_run_sheet_freezes_two_arms_from_identical_inputs(self) -> None:
        frozen = plan(1)
        sheet = MATCHED.run_sheet(frozen)
        self.assertEqual(len(sheet["runs"]), 2)
        self.assertEqual({run["route"] for run in sheet["runs"]}, {"SOL_ONLY", "SOL_LUNA"})
        self.assertEqual(len({run["starting_candidate_ref"] for run in sheet["runs"]}), 1)
        self.assertTrue(all("single formal checkout" in run["required_isolation"] for run in sheet["runs"]))
        self.assertTrue(all("do not clone" in run["required_isolation"] for run in sheet["runs"]))
        self.assertTrue(all("five-hour" in run["required_allowance_measurement"] for run in sheet["runs"]))
        self.assertTrue(all("outside both route intervals" in run["required_acceptance"] for run in sheet["runs"]))
        self.assertFalse(sheet["automatic_model_execution_allowed"])

    def test_run_sheet_counterbalances_arm_order(self) -> None:
        sheet = MATCHED.run_sheet(plan(2))
        self.assertEqual(
            [run["route"] for run in sheet["runs"]],
            ["SOL_ONLY", "SOL_LUNA", "SOL_LUNA", "SOL_ONLY"],
        )
        self.assertEqual([run["execution_order"] for run in sheet["runs"]], [1, 2, 3, 4])

    def test_assessment_rejects_starting_candidate_mismatch(self) -> None:
        frozen = plan(1)
        pair = frozen["pairs"][0]
        result = MATCHED.assess(
            frozen,
            [record(pair, "SOL_ONLY"), record(pair, "SOL_LUNA", wrong_start=True)],
            minimum_pairs=5,
        )
        self.assertEqual(result["status"], "invalid_comparison")
        self.assertIn("starting_candidate_ref", result["mismatches"][0])

    def test_assessment_rejects_luna_label_with_sol_runtime(self) -> None:
        frozen = plan(1)
        pair = frozen["pairs"][0]
        bad_route = record(pair, "SOL_LUNA")
        bad_route["observed_luna_model"] = "gpt-5.6-sol"
        result = MATCHED.assess(
            frozen,
            [record(pair, "SOL_ONLY"), bad_route],
            minimum_pairs=5,
        )
        self.assertEqual(result["status"], "invalid_comparison")
        self.assertTrue(any("observed_luna_model" in item for item in result["mismatches"]))

    def test_complete_five_pair_campaign_reaches_human_review_only(self) -> None:
        frozen = plan()
        records = [record(pair, route) for pair in frozen["pairs"] for route in ("SOL_ONLY", "SOL_LUNA")]
        result = MATCHED.assess(frozen, records, minimum_pairs=5)
        self.assertEqual(result["status"], "eligible_for_human_review")
        self.assertFalse(result["automatic_routing_allowed"])
        self.assertEqual(result["evidence"]["largest_cohort_pairs"], 5)


if __name__ == "__main__":
    unittest.main()
