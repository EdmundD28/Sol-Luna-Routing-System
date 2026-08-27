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
        "schema_version": 3,
        "task_family": "bounded-feature",
        "quality_floor": 0.80,
        "minimum_credit_savings_fraction": 0.50,
        "requested_writers": 1,
        "sol_only": {
            "first_pass_probability": 1.0,
            "final_defect_probability": 0.02,
            "execution_credits": 100,
            "execution_seconds": 1000,
            "recovery_credits_if_failed": 0,
            "recovery_seconds_if_failed": 0,
        },
        "coordination": {
            "sol_planning": {"credits": 5, "seconds": 50},
            "sol_retained_execution": {"credits": 8, "seconds": 300},
            "sol_review": {"credits": 5, "seconds": 50},
            "integration": {"credits": 2, "seconds": 25},
        },
        "luna_candidates": [
            {
                "effort": "high",
                "effort_basis": "the task has substantial edge cases that the lower tiers are unlikely to cover",
                "first_pass_probability": 0.65,
                "final_defect_probability": 0.02,
                "execution_credits": 5,
                "execution_seconds": 400,
                "recovery_credits_if_failed": 30,
                "recovery_seconds_if_failed": 500,
                "failure_impact": "low",
            },
            {
                "effort": "xhigh",
                "effort_basis": "the High estimate is below the required first-pass quality floor",
                "first_pass_probability": 0.92,
                "final_defect_probability": 0.01,
                "execution_credits": 15,
                "execution_seconds": 420,
                "recovery_credits_if_failed": 20,
                "recovery_seconds_if_failed": 250,
                "failure_impact": "low",
            },
        ],
    }


def v5_feedback_records() -> list[dict]:
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
                    "campaign_id": "routing-v5",
                    "policy_version": POLICY["policy_version"],
                    "policy_fingerprint": ROUTING.policy_fingerprint(POLICY),
                }
            )
            if route == "SOL_LUNA":
                record["credit_value"] = 40
                record["phase_credits"] = {
                    "sol_planning": 5,
                    "sol_retained_execution": 5,
                    "luna_execution": 25,
                    "sol_review": 5,
                }
            records.append(LEDGER.validate_record(record))
    return records


def v5_verified_index(records: list[dict]) -> dict:
    return {
        "schema_version": 2,
        "verification_source": "provider-export-review-v1",
        "claims": [FIXTURES.verified_claim(record) for record in records],
    }


def write_feedback_ledger(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )


def package(package_id: str, seconds: float, *, credits: float | None = None, depends_on: list[str] | None = None) -> dict:
    return {
        "package_id": package_id,
        "depends_on": depends_on or [],
        "writable_paths": [f"src/{package_id}.py"],
        "execution_credits": seconds if credits is None else credits,
        "execution_seconds": seconds,
        "first_pass_probability": 1.0,
        "repair_probability": 0.0,
        "repair_credits": 0,
        "repair_seconds": 0,
        "terminal_failure_probability": 0.0,
        "terminal_recovery_credits": 0,
        "terminal_recovery_seconds": 0,
        "final_defect_probability": 0.0,
    }


def multiwriter_request() -> dict:
    source = request()
    source["schema_version"] = 4
    source["requested_writers"] = 2
    source["coordination"].update(
        {
            "queue": {"credits": 2, "seconds": 10},
            "merge_contention": {"credits": 2, "seconds": 10},
        }
    )
    source["luna_candidates"] = [
        {
            "effort": "medium",
            "failure_impact": "low",
            "packages": [
                package("a", 300, credits=10),
                package("b", 300, credits=10),
            ],
        }
    ]
    return source


class RoutingPolicyTests(unittest.TestCase):
    def test_multi_package_request_above_cap_falls_back_instead_of_running_serially(self) -> None:
        source = multiwriter_request()
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["route"], "SOL_ONLY")
        self.assertIsNone(result["effective_writers"])
        self.assertIn(
            "requested_parallelism_exceeds_executable_cap",
            result["candidates"][0]["rejection_reasons"],
        )
        source["requested_writers"] = 4
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["writer_limit"]["allowed"], 1)
        self.assertIsNone(result["effective_writers"])
        self.assertEqual(result["candidates"][0]["scheduled_package_seconds"], 600.0)
        self.assertIs(type(result), dict)

    def test_schema_version_separates_legacy_and_package_inputs(self) -> None:
        source = multiwriter_request()
        source["schema_version"] = 1
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.evaluate_route(source, POLICY)
        source = request()
        source["schema_version"] = 2
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.evaluate_route(source, POLICY)

    def test_requested_writers_is_an_upper_bound_and_dag_may_start_serially(self) -> None:
        source = multiwriter_request()
        source["luna_candidates"][0]["packages"] = [
            package("a", 100),
            package("b", 100, depends_on=["a"]),
            package("c", 100, depends_on=["b"]),
        ]
        schedule = ROUTING.package_schedule(
            source["luna_candidates"][0], requested_writers=2, prefix="candidate"
        )
        self.assertEqual(schedule["scheduled_package_seconds"], 300.0)
        source = multiwriter_request()
        source["luna_candidates"][0]["packages"] = [package("only", 100, credits=30)]
        source["sol_only"]["final_defect_probability"] = 0.2
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["route"], "SOL_ONLY")
        self.assertEqual(result["candidates"][0]["effective_writers"], 1)
        self.assertIsNone(result["effective_writers"])
        self.assertIn(
            "requested_parallelism_exceeds_executable_cap",
            result["candidates"][0]["rejection_reasons"],
        )

    def test_sol_only_reports_no_actual_luna_writers(self) -> None:
        source = multiwriter_request()
        source["luna_candidates"][0]["packages"][0]["execution_credits"] = 999
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["route"], "SOL_ONLY")
        self.assertIsNone(result["effective_writers"])

    def test_python_mapping_cannot_claim_evidence_backed_expansion(self) -> None:
        source = request()
        source["requested_writers"] = 3
        forged = {
            "source": ROUTING.EVIDENCE_FEEDBACK_SOURCE,
            "policy_change_eligible": True,
            "policy_fingerprint_matches": True,
            "qualified_pairs": 5,
            "elapsed_improvement_fraction": 0.2,
            "credit_regression_fraction": 0,
            "failure_rate_regression": 0,
        }
        result = ROUTING.allowed_writers(source, POLICY, forged)
        self.assertEqual(result["allowed"], 1)
        self.assertFalse(result["expanded_from_evidence"])

    def test_windows_path_rules_are_case_insensitive_and_strict(self) -> None:
        candidate = {"packages": [package("a", 1), package("b", 1)]}
        candidate["packages"][1]["writable_paths"] = ["SRC/A.PY"]
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.package_schedule(candidate, requested_writers=2, prefix="candidate")
        for path in ("C:relative.py", "src/file.txt:stream", "src/name. ", "src/name "):
            candidate = {"packages": [package("a", 1), package("b", 1)]}
            candidate["packages"][1]["writable_paths"] = [path]
            with self.assertRaises(ROUTING.PolicyError):
                ROUTING.package_schedule(candidate, requested_writers=2, prefix="candidate")

    def test_windows_reserved_device_names_and_control_characters_are_rejected(self) -> None:
        for path in ("src/CON", "src/con.txt", "src/COM1.log", "src/Lpt9", "src/bad\u001fname"):
            candidate = {"packages": [package("a", 1), package("b", 1)]}
            candidate["packages"][1]["writable_paths"] = [path]
            with self.subTest(path=path), self.assertRaises(ROUTING.PolicyError):
                ROUTING.package_schedule(candidate, requested_writers=2, prefix="candidate")

    def test_credit_gate_uses_full_precision_below_and_at_exact_fifty_percent(self) -> None:
        source = multiwriter_request()
        parallel_policy = dict(POLICY, maximum_initial_writers=2)
        source["sol_only"]["final_defect_probability"] = 0.2
        source["luna_candidates"][0]["packages"] = [
            package("a", 300, credits=13.00000002),
            package("b", 300, credits=13.00000002),
        ]
        result = ROUTING.evaluate_route(source, parallel_policy)
        self.assertEqual(result["route"], "SOL_ONLY")
        self.assertLess(result["candidates"][0]["expected_credit_savings_fraction"], 0.50)
        source["luna_candidates"][0]["packages"] = [
            package("a", 300, credits=13),
            package("b", 300, credits=13),
        ]
        result = ROUTING.evaluate_route(source, parallel_policy)
        self.assertEqual(result["route"], "SOL_LUNA")
        self.assertAlmostEqual(result["candidates"][0]["expected_credit_savings_fraction"], 0.50)

    def test_multiwriter_structural_fail_closed_cases(self) -> None:
        cases = []
        source = multiwriter_request()
        source["luna_candidates"][0]["packages"][1]["depends_on"] = ["missing"]
        cases.append(source)
        source = multiwriter_request()
        source["luna_candidates"][0]["packages"][1]["writable_paths"] = ["src/a.py/child"]
        cases.append(source)
        source = multiwriter_request()
        source["luna_candidates"][0]["packages"][1]["depends_on"] = ["a"]
        source["luna_candidates"][0]["packages"].append(package("c", 1, depends_on=["b"]))
        source["luna_candidates"][0]["packages"][0]["depends_on"] = ["c"]
        cases.append(source)
        for invalid in cases:
            with self.assertRaises(ROUTING.PolicyError):
                ROUTING.evaluate_route(invalid, POLICY)

        source = multiwriter_request()
        del source["luna_candidates"][0]["packages"][0]["repair_seconds"]
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.evaluate_route(source, POLICY)

    def test_multiwriter_requires_explicit_cost_phases_and_package_schema(self) -> None:
        source = multiwriter_request()
        del source["coordination"]["queue"]
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.evaluate_route(source, POLICY)
        source = multiwriter_request()
        source["coordination"]["typo"] = {"credits": 1, "seconds": 1}
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.evaluate_route(source, POLICY)
        source = multiwriter_request()
        source["luna_candidates"][0]["packages"][0]["unexpected"] = 1
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.evaluate_route(source, POLICY)

    def test_multiwriter_rejects_probability_sum_and_no_parallel_gain(self) -> None:
        source = multiwriter_request()
        parallel_policy = dict(POLICY, maximum_initial_writers=2)
        source["luna_candidates"][0]["packages"][0]["repair_probability"] = 0.2
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.evaluate_route(source, POLICY)
        source = multiwriter_request()
        source["luna_candidates"][0]["packages"] = [
            package("a", 300), package("b", 0)
        ]
        result = ROUTING.evaluate_route(source, parallel_policy)
        self.assertEqual(result["route"], "SOL_ONLY")
        self.assertIn("no_parallel_package_speedup", result["candidates"][0]["rejection_reasons"])

        source = multiwriter_request()
        for item in source["luna_candidates"][0]["packages"]:
            item["first_pass_probability"] = 0.9
            item["repair_probability"] = 0.1
        result = ROUTING.evaluate_route(source, parallel_policy)
        self.assertEqual(result["candidates"][0]["first_pass_probability"], 0.8)
        self.assertEqual(result["route"], "SOL_LUNA")
        source["luna_candidates"][0]["packages"][0]["first_pass_probability"] = 0.899
        source["luna_candidates"][0]["packages"][0]["repair_probability"] = 0.101
        self.assertEqual(ROUTING.evaluate_route(source, parallel_policy)["route"], "SOL_ONLY")

    def test_multiwriter_expected_metrics_include_repair_and_terminal_recovery(self) -> None:
        source = multiwriter_request()
        parallel_policy = dict(POLICY, maximum_initial_writers=2)
        source["sol_only"]["final_defect_probability"] = 0.2
        for item in source["luna_candidates"][0]["packages"]:
            item.update(
                {
                    "first_pass_probability": 0.9,
                    "repair_probability": 0.05,
                    "repair_credits": 10,
                    "repair_seconds": 100,
                    "terminal_failure_probability": 0.05,
                    "terminal_recovery_credits": 20,
                    "terminal_recovery_seconds": 200,
                }
            )
        result = ROUTING.evaluate_route(source, parallel_policy)
        candidate = result["candidates"][0]
        self.assertEqual(result["route"], "SOL_LUNA")
        self.assertEqual(candidate["expected_recovery_credits"], 3.0)
        self.assertEqual(candidate["expected_recovery_seconds"], 30.0)
        self.assertEqual(candidate["expected_accepted_credits"], 47.0)
        self.assertEqual(candidate["expected_accepted_seconds"], 475.0)

    def test_quality_and_credit_boundaries_are_strict_and_non_lowerable(self) -> None:
        source = request()
        source["luna_candidates"][0]["first_pass_probability"] = 0.80
        self.assertEqual(ROUTING.evaluate_route(source, POLICY)["route"], "SOL_LUNA")
        source["luna_candidates"] = [source["luna_candidates"][0]]
        source["luna_candidates"][0]["first_pass_probability"] = 0.799
        self.assertEqual(ROUTING.evaluate_route(source, POLICY)["route"], "SOL_ONLY")
        source = request()
        source["quality_floor"] = 0.799
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.evaluate_route(source, POLICY)
        source = request()
        source["minimum_credit_savings_fraction"] = 0.499
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.evaluate_route(source, POLICY)

    def test_credit_gate_includes_coordination_and_recovery_costs(self) -> None:
        source = request()
        candidate = source["luna_candidates"][0]
        candidate.update({"execution_credits": 30, "first_pass_probability": 1.0})
        source["luna_candidates"] = [candidate]
        self.assertEqual(ROUTING.evaluate_route(source, POLICY)["route"], "SOL_LUNA")
        candidate["execution_credits"] = 30.1
        self.assertEqual(ROUTING.evaluate_route(source, POLICY)["route"], "SOL_ONLY")
        source = request()
        candidate = source["luna_candidates"][0]
        candidate.update({"execution_credits": 25, "first_pass_probability": 0.8, "recovery_credits_if_failed": 100})
        source["luna_candidates"] = [candidate]
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["route"], "SOL_ONLY")
        self.assertIn("expected_credit_savings_below_floor", result["candidates"][0]["rejection_reasons"])

    def test_elapsed_gate_is_strict_and_counts_recovery(self) -> None:
        source = request()
        candidate = source["luna_candidates"][0]
        candidate.update({"execution_credits": 30, "execution_seconds": 875, "first_pass_probability": 1.0})
        source["luna_candidates"] = [candidate]
        self.assertEqual(ROUTING.evaluate_route(source, POLICY)["route"], "SOL_ONLY")
        candidate["execution_seconds"] = 874.999
        self.assertEqual(ROUTING.evaluate_route(source, POLICY)["route"], "SOL_LUNA")
        source = request()
        candidate = source["luna_candidates"][0]
        candidate.update({"execution_seconds": 200, "first_pass_probability": 0.8, "recovery_seconds_if_failed": 4000})
        source["luna_candidates"] = [candidate]
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["route"], "SOL_ONLY")
        self.assertIn("expected_elapsed_time_regresses", result["candidates"][0]["rejection_reasons"])

    def test_selection_prioritizes_credits_before_elapsed_time(self) -> None:
        source = request()
        source["sol_only"]["execution_credits"] = 130
        source["luna_candidates"] = [
            dict(source["luna_candidates"][0], effort="medium", execution_credits=35, execution_seconds=700, first_pass_probability=1.0),
            dict(source["luna_candidates"][0], effort="xhigh", execution_credits=40, execution_seconds=500, first_pass_probability=1.0),
        ]
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["selected_luna_effort"], "medium")

    def test_unknown_candidate_fields_are_rejected_for_legacy_single_writer(self) -> None:
        source = request()
        source["luna_candidates"][0]["execution_credit"] = 1
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.evaluate_route(source, POLICY)

    def test_high_or_above_requires_an_explicit_effort_basis(self) -> None:
        source = request()
        del source["luna_candidates"][1]["effort_basis"]
        with self.assertRaisesRegex(ROUTING.PolicyError, "effort_basis"):
            ROUTING.evaluate_route(source, POLICY)

    def test_sol_retained_execution_is_required_and_overlaps_luna_time(self) -> None:
        source = request()
        del source["coordination"]["sol_retained_execution"]
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.evaluate_route(source, POLICY)
        result = ROUTING.evaluate_route(request(), POLICY)
        selected = result["selected_metrics"]
        self.assertIsNotNone(selected)
        # 125 serial Sol seconds + max(300 retained, 420 Luna) + 20 expected recovery.
        self.assertEqual(selected["expected_accepted_seconds"], 565.0)
        source = request()
        source["sol_only"]["execution_credit"] = 1
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.evaluate_route(source, POLICY)

    def test_single_writer_legacy_input_remains_readable_but_fails_closed(self) -> None:
        source = request()
        source["schema_version"] = 1
        del source["coordination"]["sol_retained_execution"]
        for candidate in source["luna_candidates"]:
            candidate.pop("effort_basis", None)
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["route"], "SOL_ONLY")
        self.assertIsNone(result["effective_writers"])
        self.assertTrue(
            all(
                "legacy_routing_schema_requires_refresh" in candidate["rejection_reasons"]
                for candidate in result["candidates"]
            )
        )

    def test_event_driven_schedule_does_not_preoccupy_worker_for_unready_package(self) -> None:
        candidate = {
            "packages": [
                package("aa", 100),
                package("b", 1),
                package("c", 1, depends_on=["aa"]),
                package("d", 100, depends_on=["b"]),
            ]
        }
        schedule = ROUTING.package_schedule(candidate, requested_writers=2, prefix="candidate")
        self.assertEqual(schedule["scheduled_package_seconds"], 101.0)

    def test_predictive_selection_can_route_directly_to_xhigh(self) -> None:
        result = ROUTING.evaluate_route(request(), POLICY)
        self.assertEqual(result["route"], "SOL_LUNA")
        self.assertEqual(result["selected_luna_effort"], "xhigh")
        self.assertIn(
            "first_pass_probability_below_floor",
            result["candidates"][0]["rejection_reasons"],
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

    def test_writer_cap_stays_one_without_non_regressive_evidence(self) -> None:
        source = request()
        source["requested_writers"] = 3
        result = ROUTING.allowed_writers(source, POLICY)
        self.assertEqual(result["allowed"], 1)
        self.assertFalse(result["expanded_from_evidence"])

    def test_matched_non_regressive_evidence_recommends_review_without_expansion(self) -> None:
        source = request()
        evidence = {
            "source": "evidence-ledger-feedback-v5",
            "policy_change_eligible": True,
            "policy_fingerprint_matches": True,
            "qualified_pairs": 5,
            "elapsed_improvement_fraction": 0.2,
            "credit_regression_fraction": 0,
            "failure_rate_regression": 0,
        }
        source["requested_writers"] = 3
        result = ROUTING.allowed_writers(source, POLICY, verified_parallel_evidence=evidence)
        self.assertEqual(result["allowed"], 1)
        self.assertFalse(result["expanded_from_evidence"])

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
        source["requested_writers"] = 3
        result = ROUTING.allowed_writers(source, POLICY, verified_parallel_evidence=evidence)
        self.assertEqual(result["allowed"], 1)
        self.assertFalse(result["expanded_from_evidence"])

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
        source["requested_writers"] = 3
        result = ROUTING.allowed_writers(source, POLICY, verified_parallel_evidence=evidence)
        self.assertEqual(result["allowed"], 1)
        self.assertFalse(result["expanded_from_evidence"])

    def test_ledger_feedback_adapter_emits_current_v5_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            evidence = ROUTING.verified_parallel_evidence_from_ledger(
                Path(temp) / "missing-ledger.jsonl",
                "bounded-feature",
                POLICY,
            )
        self.assertEqual(evidence["source"], "evidence-ledger-feedback-v5")
        self.assertEqual(evidence["source"], ROUTING.EVIDENCE_FEEDBACK_SOURCE)
        self.assertIsInstance(evidence, ROUTING._ExternallyBoundEvidence)

    def test_ledger_feedback_without_receipt_index_stays_closed(self) -> None:
        records = v5_feedback_records()
        with tempfile.TemporaryDirectory() as temp:
            ledger_path = Path(temp) / "ledger.jsonl"
            write_feedback_ledger(ledger_path, records)
            evidence = ROUTING.verified_parallel_evidence_from_ledger(
                ledger_path, "bounded-feature", POLICY
            )
        self.assertEqual(evidence["source"], ROUTING.EVIDENCE_FEEDBACK_SOURCE)
        self.assertFalse(evidence["policy_change_eligible"])
        result = ROUTING.evaluate_route(request(), POLICY, verified_parallel_evidence=evidence)
        self.assertIs(type(result), dict)
        self.assertEqual(result["writer_limit"]["allowed"], 1)

    def test_valid_v5_receipt_index_stays_cap_one_and_recommends_human_review(self) -> None:
        records = v5_feedback_records()
        index = v5_verified_index(records)
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
        capped = dict(request(), requested_writers=4)
        limit = ROUTING.allowed_writers(capped, POLICY, evidence)
        self.assertEqual(limit["allowed"], 1)
        self.assertFalse(limit["expanded_from_evidence"])
        self.assertTrue(limit["human_review_recommendation"])
        result = ROUTING.evaluate_route(request(), POLICY, verified_parallel_evidence=evidence)
        self.assertIs(type(result), dict)
        self.assertEqual(result["writer_limit"]["allowed"], 1)

    def test_mismatched_receipt_claim_stays_closed(self) -> None:
        records = v5_feedback_records()
        index = v5_verified_index(records)
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
        self.assertEqual(result["writer_limit"]["allowed"], 1)

    def test_invalid_receipt_index_is_rejected(self) -> None:
        records = v5_feedback_records()
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
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.evaluate_route(source, POLICY)

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
