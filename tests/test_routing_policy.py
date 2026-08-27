from __future__ import annotations

import importlib.util
import json
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "routing_policy.py"
SPEC = importlib.util.spec_from_file_location("routing_policy", SCRIPT)
assert SPEC and SPEC.loader
ROUTING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ROUTING)
POLICY = ROUTING.load_policy(
    ROOT / ".agents" / "skills" / "sol-luna" / "references" / "routing-policy.v1.json"
)
FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "evidence_ledger_routing_fixtures", ROOT / "tests" / "test_evidence_ledger.py"
)
assert FIXTURE_SPEC and FIXTURE_SPEC.loader
FIXTURES = importlib.util.module_from_spec(FIXTURE_SPEC)
FIXTURE_SPEC.loader.exec_module(FIXTURES)
LEDGER = FIXTURES.LEDGER


def request() -> dict:
    return {
        "schema_version": 1,
        "task_family": "bounded-feature",
        "quality_floor": 0.6,
        "minimum_credit_savings_fraction": 0.15,
        "requested_writers": 3,
        "sol_only": {
            "first_pass_probability": 1.0,
            "final_defect_probability": 0.02,
            "execution_credits": 100,
            "execution_seconds": 1000,
            "recovery_credits_if_failed": 0,
            "recovery_seconds_if_failed": 0,
        },
        "coordination": {
            "sol_planning": {"credits": 8, "seconds": 50},
            "sol_review": {"credits": 8, "seconds": 50},
            "integration": {"credits": 4, "seconds": 25},
        },
        "luna_candidates": [
            {
                "effort": "high",
                "first_pass_probability": 0.65,
                "final_defect_probability": 0.02,
                "execution_credits": 20,
                "execution_seconds": 400,
                "recovery_credits_if_failed": 80,
                "recovery_seconds_if_failed": 500,
                "failure_impact": "low",
            },
            {
                "effort": "xhigh",
                "first_pass_probability": 0.92,
                "final_defect_probability": 0.01,
                "execution_credits": 40,
                "execution_seconds": 420,
                "recovery_credits_if_failed": 30,
                "recovery_seconds_if_failed": 250,
                "failure_impact": "low",
            },
        ],
    }


def v4_feedback_records() -> list[dict]:
    records = []
    for index in range(1, 6):
        pair_id = f"pair-{index:03d}"
        for route_index, route in enumerate(("SOL_ONLY", "SOL_LUNA")):
            record = FIXTURES.verified_credit_record(
                route,
                pair_id,
                digest_suffix=str(index) if route_index == 0 else format(index + 5, "x"),
            )
            record.update(
                {
                    "campaign_id": "routing-v4",
                    "policy_version": POLICY["policy_version"],
                    "policy_fingerprint": ROUTING.policy_fingerprint(POLICY),
                }
            )
            records.append(LEDGER.validate_record(record))
    return records


def v4_verified_index(records: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "verification_source": "provider-export-review-v1",
        "claims": [FIXTURES.verified_claim(record) for record in records],
    }


def write_feedback_ledger(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )


class RoutingPolicyTests(unittest.TestCase):
    def test_predictive_selection_can_route_directly_to_xhigh(self) -> None:
        result = ROUTING.evaluate_route(request(), POLICY)
        self.assertEqual(result["route"], "SOL_LUNA")
        self.assertEqual(result["selected_luna_effort"], "xhigh")
        self.assertLess(
            result["candidates"][1]["expected_accepted_credits"],
            result["candidates"][0]["expected_accepted_credits"],
        )

    def test_light_alias_normalizes_to_actual_low_effort(self) -> None:
        source = request()
        source["luna_candidates"] = [dict(source["luna_candidates"][1], effort="light")]
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["selected_luna_effort"], "low")

    def test_quality_defect_savings_and_latency_are_hard_gates(self) -> None:
        source = request()
        candidate = source["luna_candidates"][1]
        candidate["first_pass_probability"] = 0.5
        candidate["final_defect_probability"] = 0.5
        candidate["execution_credits"] = 95
        candidate["execution_seconds"] = 1200
        source["luna_candidates"] = [candidate]
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["route"], "SOL_ONLY")
        self.assertEqual(
            set(result["candidates"][0]["rejection_reasons"]),
            {
                "first_pass_probability_below_floor",
                "predicted_defect_rate_regresses",
                "expected_credit_savings_below_floor",
                "expected_elapsed_time_regresses",
            },
        )

    def test_writer_cap_stays_two_without_non_regressive_evidence(self) -> None:
        result = ROUTING.evaluate_route(request(), POLICY)
        self.assertEqual(result["writer_limit"]["allowed"], 2)
        self.assertFalse(result["writer_limit"]["expanded_from_evidence"])

    def test_writer_cap_expands_only_with_matched_non_regressive_evidence(self) -> None:
        source = request()
        evidence = {
            "source": "evidence-ledger-feedback-v4",
            "policy_change_eligible": True,
            "policy_fingerprint_matches": True,
            "qualified_pairs": 5,
            "elapsed_improvement_fraction": 0.2,
            "credit_regression_fraction": 0,
            "failure_rate_regression": 0,
        }
        result = ROUTING.evaluate_route(source, POLICY, verified_parallel_evidence=evidence)
        self.assertEqual(result["writer_limit"]["allowed"], 3)
        self.assertTrue(result["writer_limit"]["expanded_from_evidence"])

    def test_legacy_v3_feedback_cannot_expand_writer_cap(self) -> None:
        source = request()
        evidence = {
            "source": "evidence-ledger-feedback-v3",
            "policy_change_eligible": True,
            "policy_fingerprint_matches": True,
            "qualified_pairs": 5,
            "elapsed_improvement_fraction": 0.2,
            "credit_regression_fraction": 0,
            "failure_rate_regression": 0,
        }
        result = ROUTING.evaluate_route(source, POLICY, verified_parallel_evidence=evidence)
        self.assertEqual(result["writer_limit"]["allowed"], 2)
        self.assertFalse(result["writer_limit"]["expanded_from_evidence"])

    def test_unknown_feedback_version_fails_closed(self) -> None:
        source = request()
        evidence = {
            "source": "evidence-ledger-feedback-v99",
            "policy_change_eligible": True,
            "policy_fingerprint_matches": True,
            "qualified_pairs": 5,
            "elapsed_improvement_fraction": 0.2,
            "credit_regression_fraction": 0,
            "failure_rate_regression": 0,
        }
        result = ROUTING.evaluate_route(source, POLICY, verified_parallel_evidence=evidence)
        self.assertEqual(result["writer_limit"]["allowed"], 2)
        self.assertFalse(result["writer_limit"]["expanded_from_evidence"])

    def test_ledger_feedback_adapter_emits_current_v4_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            evidence = ROUTING.verified_parallel_evidence_from_ledger(
                Path(temp) / "missing-ledger.jsonl",
                "bounded-feature",
                POLICY,
            )
        self.assertEqual(evidence["source"], "evidence-ledger-feedback-v4")
        self.assertEqual(evidence["source"], ROUTING.EVIDENCE_FEEDBACK_SOURCE)

    def test_ledger_feedback_without_receipt_index_stays_closed(self) -> None:
        records = v4_feedback_records()
        with tempfile.TemporaryDirectory() as temp:
            ledger_path = Path(temp) / "ledger.jsonl"
            write_feedback_ledger(ledger_path, records)
            evidence = ROUTING.verified_parallel_evidence_from_ledger(
                ledger_path, "bounded-feature", POLICY
            )
        self.assertEqual(evidence["source"], ROUTING.EVIDENCE_FEEDBACK_SOURCE)
        self.assertFalse(evidence["policy_change_eligible"])
        result = ROUTING.evaluate_route(request(), POLICY, verified_parallel_evidence=evidence)
        self.assertEqual(result["writer_limit"]["allowed"], 2)

    def test_valid_v4_receipt_index_enables_evidence_backed_writer_cap(self) -> None:
        records = v4_feedback_records()
        index = v4_verified_index(records)
        with tempfile.TemporaryDirectory() as temp:
            ledger_path = Path(temp) / "ledger.jsonl"
            write_feedback_ledger(ledger_path, records)
            evidence = ROUTING.verified_parallel_evidence_from_ledger(
                ledger_path,
                "bounded-feature",
                POLICY,
                verified_credit_receipts=index,
            )
        self.assertEqual(evidence["source"], ROUTING.EVIDENCE_FEEDBACK_SOURCE)
        self.assertTrue(evidence["policy_change_eligible"])
        result = ROUTING.evaluate_route(request(), POLICY, verified_parallel_evidence=evidence)
        self.assertEqual(result["writer_limit"]["allowed"], 3)

    def test_mismatched_receipt_claim_stays_closed(self) -> None:
        records = v4_feedback_records()
        index = v4_verified_index(records)
        index["claims"][0]["credit_value"] += 1
        index["claims"][0]["claim_digest"] = LEDGER._canonical_claim_digest(index["claims"][0])
        with tempfile.TemporaryDirectory() as temp:
            ledger_path = Path(temp) / "ledger.jsonl"
            write_feedback_ledger(ledger_path, records)
            evidence = ROUTING.verified_parallel_evidence_from_ledger(
                ledger_path,
                "bounded-feature",
                POLICY,
                verified_credit_receipts=index,
            )
        self.assertFalse(evidence["policy_change_eligible"])
        result = ROUTING.evaluate_route(request(), POLICY, verified_parallel_evidence=evidence)
        self.assertEqual(result["writer_limit"]["allowed"], 2)

    def test_invalid_receipt_index_is_rejected(self) -> None:
        records = v4_feedback_records()
        with tempfile.TemporaryDirectory() as temp:
            ledger_path = Path(temp) / "ledger.jsonl"
            index_path = Path(temp) / "receipts.json"
            write_feedback_ledger(ledger_path, records)
            index_path.write_text(
                json.dumps({"schema_version": 1, "verification_source": "", "claims": []}),
                encoding="utf-8",
            )
            with self.assertRaises(ROUTING.PolicyError):
                ROUTING.verified_parallel_evidence_from_ledger(
                    ledger_path,
                    "bounded-feature",
                    POLICY,
                    verified_credit_receipts=index_path,
                )

    def test_evaluate_parser_accepts_explicit_receipt_index(self) -> None:
        args = ROUTING.parser().parse_args(
            [
                "evaluate",
                "--input",
                "route.json",
                "--ledger",
                "ledger.jsonl",
                "--verified-credit-receipts",
                "receipts.json",
            ]
        )
        self.assertEqual(args.verified_credit_receipts, Path("receipts.json"))

    def test_evaluate_receipt_index_requires_ledger(self) -> None:
        stderr = io.StringIO()
        with mock.patch.object(
            sys,
            "argv",
            [
                "routing_policy.py",
                "evaluate",
                "--input",
                "route.json",
                "--verified-credit-receipts",
                "receipts.json",
            ],
        ), redirect_stderr(stderr):
            result = ROUTING.main()
        self.assertEqual(result, 2)
        self.assertIn("requires --ledger", stderr.getvalue())

    def test_request_cannot_self_assert_parallel_evidence(self) -> None:
        source = request()
        source["parallel_evidence"] = {
            "source": "evidence-ledger-feedback-v3",
            "policy_change_eligible": True,
            "policy_fingerprint_matches": True,
            "qualified_pairs": 999,
            "elapsed_improvement_fraction": 1,
            "credit_regression_fraction": 0,
            "failure_rate_regression": 0,
        }
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["writer_limit"]["allowed"], 2)
        self.assertFalse(result["writer_limit"]["expanded_from_evidence"])

    def test_rework_allows_one_repair_then_repartition_escalation_or_reclaim(self) -> None:
        repair = ROUTING.rework_decision(
            {
                "current_effort": "high",
                "new_evidence": True,
                "focused_repairs_used": 0,
                "effort_escalations_used": 0,
            },
            POLICY,
        )
        self.assertEqual(repair["action"], "FOCUSED_REPAIR")
        repartition = ROUTING.rework_decision(
            {
                "current_effort": "high",
                "new_evidence": False,
                "focused_repairs_used": 1,
                "effort_escalations_used": 0,
                "can_repartition": True,
            },
            POLICY,
        )
        self.assertEqual(repartition["action"], "REPARTITION")
        escalate = ROUTING.rework_decision(
            {
                "current_effort": "high",
                "new_evidence": False,
                "focused_repairs_used": 1,
                "effort_escalations_used": 0,
            },
            POLICY,
        )
        self.assertEqual(escalate, {
            "action": "ESCALATE_ONCE",
            "next_effort": "xhigh",
            "reason": "one evidence-backed effort escalation remains",
        })
        reclaim = ROUTING.rework_decision(
            {
                "current_effort": "max",
                "new_evidence": False,
                "focused_repairs_used": 1,
                "effort_escalations_used": 1,
            },
            POLICY,
        )
        self.assertEqual(reclaim["action"], "SOL_RECLAIM")

    def test_review_depth_is_risk_proportional(self) -> None:
        targeted = ROUTING.review_depth(
            {"risk_level": "low", "authoritative_checks_passed": True}
        )
        self.assertEqual(targeted["review_depth"], "TARGETED")
        deep = ROUTING.review_depth(
            {"risk_level": "low", "authoritative_checks_passed": True, "shared_interface": True}
        )
        self.assertEqual(deep["review_depth"], "DEEP")

    def test_policy_fingerprint_is_stable_and_route_never_executes(self) -> None:
        self.assertEqual(ROUTING.policy_fingerprint(POLICY), ROUTING.policy_fingerprint(POLICY))
        self.assertFalse(ROUTING.evaluate_route(request(), POLICY)["automatic_execution_allowed"])


if __name__ == "__main__":
    unittest.main()
