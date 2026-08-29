from __future__ import annotations

import importlib.util
import hashlib
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


def v5_package(package_id: str, executor: str, seconds: float, baseline_seconds: float, *, credits: float = 1, critical_path: bool = False, depends_on: list[str] | None = None) -> dict:
    item = package(package_id, seconds, credits=credits, depends_on=depends_on)
    item.update({"executor": executor, "critical_path": critical_path, "acceptance_ids": [f"accept-{package_id}"], "baseline_sol_credits": baseline_seconds / 10, "baseline_sol_seconds": baseline_seconds})
    return item


def v5_request() -> dict:
    source = request()
    source["schema_version"] = 5
    source["requested_writers"] = 1
    source["acceptance_contract_ids"] = ["accept-sol-core", "accept-luna-tests"]
    source["coordination"].pop("sol_retained_execution")
    source["coordination"].update({"queue": {"credits": 1, "seconds": 1}, "merge_contention": {"credits": 1, "seconds": 1}})
    source["luna_candidates"] = [{"effort": "medium", "allocation_id": "allocation-a", "failure_impact": "low", "packages": [
        v5_package("sol-core", "SOL", 500, 500, credits=20, critical_path=True),
        v5_package("luna-tests", "LUNA", 300, 500, credits=10),
    ]}]
    # The baseline map is the complete Sol-only execution, not actual route cost.
    source["sol_only"]["execution_credits"] = 100
    source["sol_only"]["execution_seconds"] = 1000
    source["luna_candidates"][0]["packages"][0]["baseline_sol_credits"] = 50
    source["luna_candidates"][0]["packages"][1]["baseline_sol_credits"] = 50
    return source


def _sha256_json(value: dict | list) -> str:
    return "sha256:" + hashlib.sha256(ROUTING.canonical_json(value)).hexdigest()


def schema6_request(*, first_pass_accepted: int = 1, observations: int = 1) -> tuple[dict, dict]:
    source = v5_request()
    source["schema_version"] = 6
    source["acceptance_suite_digest"] = _sha256_json(source["acceptance_contract_ids"])
    candidate = source["luna_candidates"][0]
    shape = ROUTING.package_schedule_v5(candidate, requested_writers=1, prefix="fixture")["allocation_shape_fingerprint"]
    evidence = {
        "evidence_id": "evidence-medium-a",
        "task_family": source["task_family"],
        "effort": candidate["effort"],
        "allocation_shape_fingerprint": shape,
        "acceptance_suite_digest": source["acceptance_suite_digest"],
        "observations": observations,
        "first_pass_accepted": first_pass_accepted,
        "final_defect_runs": 0,
        "source_kind": "controlled-routing-campaign",
    }
    evidence["evidence_digest"] = _sha256_json(evidence)
    candidate["quality_evidence_id"] = evidence["evidence_id"]
    return source, evidence


def schema7_profile(**overrides: object) -> dict:
    profile = {
        "architecture_settled": True,
        "deterministic_acceptance": True,
        "semantic_coupling": "low",
        "cross_module_invariants": False,
        "multi_interface_contract": False,
        "adversarial_edge_cases": False,
        "platform_sensitive_io": False,
        "strict_serialization": False,
    }
    profile.update(overrides)
    return profile


def schema7_request(profile: dict | None = None, *, effort: str = "medium") -> tuple[dict, dict]:
    source, evidence = schema6_request()
    source["schema_version"] = 7
    source["reasoning_profile"] = schema7_profile() if profile is None else profile
    candidate = source["luna_candidates"][0]
    candidate["effort"] = effort
    candidate["effort_basis"] = "profile-derived reasoning floor test"
    evidence["effort"] = effort
    evidence["evidence_digest"] = _sha256_json(
        {key: value for key, value in evidence.items() if key != "evidence_digest"}
    )
    return source, evidence


def bound_quality(source: dict, *evidence: dict) -> dict:
    return ROUTING._ExternallyBoundQualityEvidence(
        ROUTING.quality_evidence_index(
            list(evidence),
            task_family=source["task_family"],
            acceptance_suite_digest=source["acceptance_suite_digest"],
        )
    )


class RoutingPolicyTests(unittest.TestCase):
    def test_direct_policy_mapping_is_strictly_validated_without_mutation(self) -> None:
        for field, value in (
            ("maximum_active_luna_writers", None),
            ("maximum_duplicate_work_fraction", True),
            ("repair_precedes_new_luna_dispatch", None),
            ("repair_precedes_new_luna_dispatch", False),
            ("high_effort_critical_path_requires_lower_effort_quality_evidence", None),
            ("high_effort_critical_path_requires_lower_effort_quality_evidence", False),
        ):
            malformed = dict(POLICY)
            malformed.pop(field, None)
            if value is not None:
                malformed[field] = value
            with self.assertRaises(ROUTING.PolicyError):
                ROUTING.evaluate_route(v5_request(), malformed)
        unchanged = dict(POLICY)
        ROUTING.evaluate_route(v5_request(), unchanged)
        self.assertEqual(unchanged, POLICY)

    def test_template_is_evaluable_v7_complete_allocation(self) -> None:
        source = ROUTING.template()
        evidence_document = ROUTING.quality_evidence_template()
        self.assertEqual(source["schema_version"], 7)
        self.assertEqual(source["reasoning_profile"]["semantic_coupling"], "low")
        self.assertRegex(source["acceptance_suite_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn("quality_evidence", source)
        self.assertEqual(len(evidence_document["evidence"]), 1)
        self.assertEqual(
            source["luna_candidates"][0]["quality_evidence_id"],
            evidence_document["evidence"][0]["evidence_id"],
        )
        self.assertNotIn("sol_retained_execution", source["coordination"])
        candidate = source["luna_candidates"][0]
        self.assertEqual(candidate["allocation_id"], "allocation-default")
        self.assertEqual({item["executor"] for item in candidate["packages"]}, {"SOL", "LUNA"})
        self.assertTrue(any(item["executor"] == "SOL" and item["critical_path"] for item in candidate["packages"]))
        result = ROUTING.evaluate_route(
            source,
            POLICY,
            verified_quality_evidence=bound_quality(source, *evidence_document["evidence"]),
        )
        self.assertEqual(result["route"], "SOL_ONLY")
        self.assertIsNone(result["selected_metrics"])

    def test_v5_one_active_luna_writer_rolls_multiple_packages(self) -> None:
        source = v5_request()
        source["luna_candidates"][0]["packages"].append(v5_package("luna-docs", "LUNA", 100, 0, credits=1, depends_on=["luna-tests"]))
        source["acceptance_contract_ids"].append("accept-luna-docs")
        result = ROUTING.evaluate_route(source, POLICY)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["delegated_package_count"], 2)
        self.assertEqual(candidate["effective_writers"], 1)
        self.assertEqual(candidate["luna_leaf_package_ids"], ["luna-docs"])
        self.assertEqual(candidate["luna_leaf_package_count"], 1)
        self.assertEqual(candidate["luna_critical_path_package_ids"], [])

    def test_v5_active_cap_is_independent_of_delegated_coverage(self) -> None:
        source = v5_request()
        source["requested_writers"] = 1
        source["luna_candidates"][0]["packages"].append(v5_package("luna-docs", "LUNA", 100, 0, depends_on=["luna-tests"]))
        source["acceptance_contract_ids"].append("accept-luna-docs")
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["candidates"][0]["delegated_package_count"], 2)

    def test_v5_baseline_mismatch_and_candidate_drift_are_rejected(self) -> None:
        source = v5_request()
        source["luna_candidates"][0]["packages"][0]["baseline_sol_seconds"] = 501
        with self.assertRaises(ROUTING.PolicyError): ROUTING.evaluate_route(source, POLICY)
        source = v5_request()
        source["luna_candidates"].append(dict(source["luna_candidates"][0], allocation_id="allocation-b", packages=list(source["luna_candidates"][0]["packages"])))
        source["luna_candidates"][1]["packages"][1] = dict(source["luna_candidates"][1]["packages"][1], baseline_sol_seconds=401)
        with self.assertRaises(ROUTING.PolicyError): ROUTING.evaluate_route(source, POLICY)

    def test_v5_rejects_double_owner(self) -> None:
        source = v5_request()
        source["luna_candidates"][0]["packages"][1]["writable_paths"] = source["luna_candidates"][0]["packages"][0]["writable_paths"]
        with self.assertRaises(ROUTING.PolicyError): ROUTING.evaluate_route(source, POLICY)

    def test_v5_all_luna_allocation_allows_productive_sol_wait(self) -> None:
        source = v5_request()
        for item in source["luna_candidates"][0]["packages"]:
            item["executor"] = "LUNA"
            item["execution_credits"] = 5
            item["execution_seconds"] = 350
        source["luna_candidates"][0]["sol_controller_queue"] = {
            "ready_packages": 0,
            "review_items": 0,
            "integration_items": 0,
            "dispatch_items": 0,
            "acceptance_items": 0,
        }
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["route"], "SOL_LUNA")
        self.assertEqual(result["selected_metrics"]["controller_mode"], "WAIT_ALLOWED")
        self.assertEqual(result["selected_metrics"]["sol_retained_package_count"], 0)
        self.assertEqual(result["selected_metrics"]["delegated_baseline_credit_fraction"], 1.0)
        self.assertEqual(result["selected_metrics"]["sol_luna_overlap_seconds"], 0.0)

    def test_v5_wait_requires_an_explicit_empty_controller_queue(self) -> None:
        source = v5_request()
        for item in source["luna_candidates"][0]["packages"]:
            item["executor"] = "LUNA"
            item["execution_credits"] = 5
            item["execution_seconds"] = 350
        with self.assertRaisesRegex(ROUTING.PolicyError, "sol_controller_queue"):
            ROUTING.evaluate_route(source, POLICY)
        source["luna_candidates"][0]["sol_controller_queue"] = {
            "ready_packages": 0,
            "review_items": 1,
            "integration_items": 0,
            "dispatch_items": 0,
            "acceptance_items": 0,
        }
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["route"], "SOL_ONLY")
        self.assertEqual(result["candidates"][0]["controller_mode"], "CONTROLLER_QUEUE_PENDING")
        self.assertIn(
            "unallocated_sol_controller_work", result["candidates"][0]["rejection_reasons"]
        )

    def test_v5_mixed_allocation_rejects_malformed_controller_queue(self) -> None:
        source = v5_request()
        source["luna_candidates"][0]["sol_controller_queue"] = "not-a-snapshot"
        with self.assertRaisesRegex(ROUTING.PolicyError, "sol_controller_queue"):
            ROUTING.evaluate_route(source, POLICY)
        source = v5_request()
        source["luna_candidates"][0]["sol_controller_queue"] = {
            "ready_packages": 0,
            "review_items": 0,
            "integration_items": 0,
            "dispatch_items": 0,
        }
        with self.assertRaisesRegex(ROUTING.PolicyError, "acceptance_items"):
            ROUTING.evaluate_route(source, POLICY)

    def test_lower_luna_cost_cannot_worsen_coordination_share(self) -> None:
        ordinary = v5_request()
        ordinary_result = ROUTING.evaluate_route(ordinary, POLICY)
        cheaper = v5_request()
        for item in cheaper["luna_candidates"][0]["packages"]:
            if item["executor"] == "LUNA":
                item["execution_credits"] /= 10
        cheaper_result = ROUTING.evaluate_route(cheaper, POLICY)
        ordinary_candidate = ordinary_result["candidates"][0]
        cheaper_candidate = cheaper_result["candidates"][0]
        self.assertEqual(
            cheaper_candidate["coordination_credit_share"],
            ordinary_candidate["coordination_credit_share"],
        )
        self.assertNotIn(
            "coordination_credit_share_too_high", cheaper_candidate["rejection_reasons"]
        )

    def test_v5_allows_sequential_handoff_but_rejects_coordination_retained_field(self) -> None:
        source = v5_request()
        source["coordination"]["sol_retained_execution"] = {"credits": 0, "seconds": 0}
        with self.assertRaises(ROUTING.PolicyError): ROUTING.evaluate_route(source, POLICY)
        source = v5_request()
        source["luna_candidates"][0]["packages"][1]["depends_on"] = ["sol-core"]
        source["luna_candidates"][0]["packages"][0]["execution_seconds"] = 0
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["route"], "SOL_LUNA")
        self.assertEqual(result["selected_metrics"]["controller_mode"], "SEQUENTIAL_HANDOFF")

    def test_v5_same_effort_allocations_are_allowed_and_cheapest_selected(self) -> None:
        source = v5_request()
        second = json.loads(json.dumps(source["luna_candidates"][0]))
        second["allocation_id"] = "allocation-b"
        second["packages"][1]["execution_credits"] = 1
        source["luna_candidates"].append(second)
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["selected_luna_effort"], "medium")
        self.assertEqual(result["candidates"][1]["allocation_id"], "allocation-b")

    def test_v5_high_critical_path_requires_lower_effort_quality_evidence(self) -> None:
        source = v5_request()
        high = source["luna_candidates"][0]
        high.update(
            {
                "allocation_id": "allocation-high",
                "effort": "high",
                "effort_basis": "critical-path logic needs stronger reasoning",
            }
        )
        high["packages"][1]["critical_path"] = True
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["route"], "SOL_ONLY")
        self.assertIn(
            "high_effort_critical_path_requires_lower_effort_quality_evidence",
            result["candidates"][0]["rejection_reasons"],
        )

        medium = json.loads(json.dumps(high))
        medium.update({"allocation_id": "allocation-medium", "effort": "medium"})
        medium.pop("effort_basis")
        medium["packages"][1].update(
            {"first_pass_probability": 0.5, "repair_probability": 0.5}
        )
        source["luna_candidates"] = [medium, high]
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["route"], "SOL_LUNA")
        self.assertEqual(result["selected_luna_effort"], "high")
        self.assertIn(
            "first_pass_probability_below_floor",
            result["candidates"][0]["rejection_reasons"],
        )
        self.assertNotIn(
            "high_effort_critical_path_requires_lower_effort_quality_evidence",
            result["candidates"][1]["rejection_reasons"],
        )

        mismatched_medium = json.loads(json.dumps(medium))
        mismatched_medium["packages"][0]["executor"] = "LUNA"
        mismatched_medium["packages"][1]["executor"] = "SOL"
        source["luna_candidates"] = [mismatched_medium, high]
        result = ROUTING.evaluate_route(source, POLICY)
        self.assertIn(
            "high_effort_critical_path_requires_lower_effort_quality_evidence",
            result["candidates"][1]["rejection_reasons"],
        )

    def test_v5_xhigh_critical_path_accepts_same_shape_high_quality_failure(self) -> None:
        source = v5_request()
        high = source["luna_candidates"][0]
        high.update(
            {
                "allocation_id": "allocation-high",
                "effort": "high",
                "effort_basis": "high is a deliberate quality-failure comparator",
            }
        )
        high["packages"][1].update(
            {"critical_path": True, "first_pass_probability": 0.65, "repair_probability": 0.35}
        )

        xhigh = json.loads(json.dumps(high))
        xhigh.update(
            {
                "allocation_id": "allocation-xhigh",
                "effort": "xhigh",
                "effort_basis": "xhigh is required after the high comparator fails quality",
            }
        )
        xhigh["packages"][1].update({"first_pass_probability": 0.92, "repair_probability": 0.08})
        source["luna_candidates"] = [high, xhigh]

        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["route"], "SOL_LUNA")
        self.assertEqual(result["selected_luna_effort"], "xhigh")
        self.assertEqual(
            result["candidates"][0]["allocation_shape_fingerprint"],
            result["candidates"][1]["allocation_shape_fingerprint"],
        )
        self.assertIn("first_pass_probability_below_floor", result["candidates"][0]["rejection_reasons"])
        self.assertNotIn(
            "high_effort_critical_path_requires_lower_effort_quality_evidence",
            result["candidates"][1]["rejection_reasons"],
        )

    def test_v5_max_critical_path_accepts_same_shape_xhigh_quality_failure(self) -> None:
        source = v5_request()
        xhigh = source["luna_candidates"][0]
        xhigh.update(
            {
                "allocation_id": "allocation-xhigh",
                "effort": "xhigh",
                "effort_basis": "xhigh is a deliberate quality-failure comparator",
            }
        )
        xhigh["packages"][1].update(
            {"critical_path": True, "first_pass_probability": 0.65, "repair_probability": 0.35}
        )

        maximum = json.loads(json.dumps(xhigh))
        maximum.update(
            {
                "allocation_id": "allocation-max",
                "effort": "max",
                "effort_basis": "max is required after the xhigh comparator fails quality",
            }
        )
        maximum["packages"][1].update({"first_pass_probability": 0.92, "repair_probability": 0.08})
        source["luna_candidates"] = [xhigh, maximum]

        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["route"], "SOL_LUNA")
        self.assertEqual(result["selected_luna_effort"], "max")
        self.assertEqual(
            result["candidates"][0]["allocation_shape_fingerprint"],
            result["candidates"][1]["allocation_shape_fingerprint"],
        )
        self.assertIn("first_pass_probability_below_floor", result["candidates"][0]["rejection_reasons"])
        self.assertNotIn(
            "high_effort_critical_path_requires_lower_effort_quality_evidence",
            result["candidates"][1]["rejection_reasons"],
        )

    def test_v5_same_or_higher_effort_cannot_masquerade_as_lower_comparator(self) -> None:
        source = v5_request()
        high = source["luna_candidates"][0]
        high.update(
            {
                "allocation_id": "allocation-high",
                "effort": "high",
                "effort_basis": "high critical-path candidate",
            }
        )
        high["packages"][1].update(
            {"critical_path": True, "first_pass_probability": 0.92, "repair_probability": 0.08}
        )

        xhigh = json.loads(json.dumps(high))
        xhigh.update(
            {
                "allocation_id": "allocation-xhigh",
                "effort": "xhigh",
                "effort_basis": "higher effort must not satisfy high comparator requirement",
            }
        )
        source["luna_candidates"] = [high, xhigh]

        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["route"], "SOL_ONLY")
        self.assertIn(
            "high_effort_critical_path_requires_lower_effort_quality_evidence",
            result["candidates"][0]["rejection_reasons"],
        )
        self.assertIn(
            "high_effort_critical_path_requires_lower_effort_quality_evidence",
            result["candidates"][1]["rejection_reasons"],
        )

    def test_v5_high_effort_requires_every_same_shape_lower_candidate_to_fail_quality(self) -> None:
        source = v5_request()
        high = source["luna_candidates"][0]
        high.update(
            {
                "allocation_id": "allocation-high",
                "effort": "high",
                "effort_basis": "high remains an actual lower-effort comparator",
            }
        )
        high["packages"][1].update(
            {"critical_path": True, "first_pass_probability": 0.92, "repair_probability": 0.08}
        )

        xhigh = json.loads(json.dumps(high))
        xhigh.update(
            {
                "allocation_id": "allocation-xhigh",
                "effort": "xhigh",
                "effort_basis": "xhigh is a quality-failure comparator",
            }
        )
        xhigh["packages"][1].update({"first_pass_probability": 0.65, "repair_probability": 0.35})

        maximum = json.loads(json.dumps(xhigh))
        maximum.update(
            {
                "allocation_id": "allocation-max",
                "effort": "max",
                "effort_basis": "max cannot bypass the passing high comparator",
            }
        )
        maximum["packages"][1].update({"first_pass_probability": 0.92, "repair_probability": 0.08})
        source["luna_candidates"] = [high, xhigh, maximum]

        result = ROUTING.evaluate_route(source, POLICY)
        self.assertEqual(result["route"], "SOL_ONLY")
        self.assertIn(
            "high_effort_critical_path_requires_lower_effort_quality_evidence",
            result["candidates"][2]["rejection_reasons"],
        )
        self.assertNotIn(
            "first_pass_probability_below_floor",
            result["candidates"][0]["rejection_reasons"],
        )
        self.assertIn("first_pass_probability_below_floor", result["candidates"][1]["rejection_reasons"])

    def test_v5_reports_overlap_and_no_duplicate_cost(self) -> None:
        result = ROUTING.evaluate_route(v5_request(), POLICY)
        candidate = result["candidates"][0]
        self.assertGreater(candidate["sol_luna_overlap_seconds"], 0)
        self.assertEqual(candidate["controller_mode"], "COMPLEMENTARY_PARALLEL")
        self.assertEqual(candidate["duplicate_work_fraction"], 0.0)

    def test_v5_hybrid_dag_respects_cross_executor_dependency(self) -> None:
        source = v5_request()
        source["luna_candidates"][0]["packages"][0]["depends_on"] = []
        source["luna_candidates"][0]["packages"][1]["depends_on"] = ["sol-core"]
        schedule = ROUTING.package_schedule_v5(source["luna_candidates"][0], requested_writers=1, prefix="candidate")
        self.assertEqual(schedule["scheduled_package_seconds"], 800.0)
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
                "--quality-evidence-index",
                "quality.json",
            ]
        )
        self.assertEqual(args.verified_credit_receipts, Path("receipts.json"))
        self.assertEqual(args.quality_evidence_index, Path("quality.json"))

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

    def test_rework_allows_bounded_evidence_backed_repairs_then_fallbacks(self) -> None:
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
        self.assertEqual(repair["remaining_focused_repairs"], 0)
        second = ROUTING.rework_decision(
            {
                "current_effort": "high",
                "new_evidence": True,
                "focused_repairs_used": 1,
                "effort_escalations_used": 0,
            },
            POLICY,
        )
        self.assertEqual(second["action"], "ESCALATE_ONCE")
        repartition = ROUTING.rework_decision(
            {
                "current_effort": "high",
                "new_evidence": False,
                "focused_repairs_used": 3,
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
                "focused_repairs_used": 3,
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
                "focused_repairs_used": 3,
                "effort_escalations_used": 1,
            },
            POLICY,
        )
        self.assertEqual(reclaim["action"], "SOL_RECLAIM")

    def test_strict_closure_repair_requires_target_evidence_and_positive_margin(self) -> None:
        request = {
            "current_effort": "high",
            "new_evidence": True,
            "focused_repairs_used": 1,
            "effort_escalations_used": 0,
            "failure_evidence_ref": "receipt-review-two",
            "target_action_ids": ["restore-economic-gate"],
            "marginal_net_substitution": 0.3,
            "repair_cost_weight": 0.1,
            "repair_cost_weight_used": 0.1,
            "repair_cost_weight_limit": 0.5,
        }
        result = ROUTING.rework_decision(request, POLICY)
        self.assertEqual(result["action"], "FOCUSED_REPAIR")
        self.assertEqual(result["remaining_focused_repairs"], 1)
        self.assertEqual(result["target_action_ids"], ["restore-economic-gate"])
        self.assertAlmostEqual(result["remaining_repair_cost_weight"], 0.3)

        third = dict(request, focused_repairs_used=2, repair_cost_weight_used=0.2)
        third_result = ROUTING.rework_decision(third, POLICY)
        self.assertEqual(third_result["action"], "FOCUSED_REPAIR")
        self.assertEqual(third_result["remaining_focused_repairs"], 0)

        regressive = dict(request, marginal_net_substitution=0)
        self.assertEqual(ROUTING.rework_decision(regressive, POLICY)["action"], "SOL_RECLAIM")
        exhausted = dict(request, repair_cost_weight=0.5)
        self.assertEqual(ROUTING.rework_decision(exhausted, POLICY)["action"], "REPAIR_LOCKED")
        attempts_exhausted = dict(request, focused_repairs_used=3)
        self.assertEqual(ROUTING.rework_decision(attempts_exhausted, POLICY)["action"], "REPAIR_LOCKED")
        missing_new_evidence = dict(request, new_evidence=False)
        self.assertEqual(ROUTING.rework_decision(missing_new_evidence, POLICY)["action"], "REPAIR_LOCKED")
        for missing in ("failure_evidence_ref", "target_action_ids", "marginal_net_substitution", "repair_cost_weight_limit"):
            malformed = dict(request)
            del malformed[missing]
            with self.subTest(missing=missing), self.assertRaises(ROUTING.PolicyError):
                ROUTING.rework_decision(malformed, POLICY)

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

    def test_schema6_selects_matching_medium_quality_evidence_and_exposes_only_reference(self) -> None:
        source, evidence = schema6_request()
        result = ROUTING.evaluate_route(
            source,
            POLICY,
            verified_quality_evidence=bound_quality(source, evidence),
        )
        self.assertEqual(result["route"], "SOL_LUNA")
        selected = result["candidates"][0]
        self.assertEqual(selected["quality_evidence_id"], "evidence-medium-a")
        self.assertEqual(selected["quality_evidence_source"], "controlled-routing-campaign")
        self.assertNotIn("quality_evidence", selected)
        self.assertNotIn("observations", selected)

    def test_schema6_p010_zero_of_one_evidence_rejects_ninety_percent_self_report(self) -> None:
        source, evidence = schema6_request(first_pass_accepted=0, observations=1)
        for item in source["luna_candidates"][0]["packages"]:
            item["first_pass_probability"] = 0.9
            item["repair_probability"] = 0.1
            item["repair_credits"] = 1
            item["repair_seconds"] = 1
        result = ROUTING.evaluate_route(
            source,
            POLICY,
            verified_quality_evidence=bound_quality(source, evidence),
        )
        self.assertEqual(result["route"], "SOL_ONLY")
        self.assertFalse(result["candidates"][0]["eligible"])

    def test_schema6_evidence_family_effort_shape_suite_and_digest_mismatch_fail_closed(self) -> None:
        for field, value in (
            ("task_family", "other-family"),
            ("acceptance_suite_digest", "sha256:" + "1" * 64),
            ("evidence_digest", "sha256:" + "2" * 64),
        ):
            source, evidence = schema6_request()
            evidence[field] = value
            with self.subTest(field=field), self.assertRaises(ROUTING.PolicyError):
                bound_quality(source, evidence)

        for field, value in (
            ("effort", "high"),
            ("allocation_shape_fingerprint", "sha256:" + "0" * 64),
        ):
            source, evidence = schema6_request()
            evidence[field] = value
            evidence["evidence_digest"] = _sha256_json(
                {
                    key: item
                    for key, item in evidence.items()
                    if key != "evidence_digest"
                }
            )
            result = ROUTING.evaluate_route(
                source,
                POLICY,
                verified_quality_evidence=bound_quality(source, evidence),
            )
            with self.subTest(field=field):
                self.assertEqual(result["route"], "SOL_ONLY")
                self.assertFalse(result["candidates"][0]["eligible"])

    def test_schema6_requires_bound_unique_strict_evidence(self) -> None:
        source, evidence = schema6_request()
        del source["luna_candidates"][0]["quality_evidence_id"]
        try:
            result = ROUTING.evaluate_route(
                source,
                POLICY,
                verified_quality_evidence=bound_quality(source, evidence),
            )
        except ROUTING.PolicyError:
            pass
        else:
            self.assertEqual(result["route"], "SOL_ONLY")
            self.assertFalse(result["candidates"][0]["eligible"])

        for malformed in (
            {"observations": True},
            {"first_pass_accepted": 2},
            {"final_defect_runs": -1},
            {"evidence_id": "evidence-medium-a", "extra": 1},
        ):
            candidate, evidence = schema6_request()
            evidence.update(malformed)
            with self.subTest(malformed=malformed), self.assertRaises(ROUTING.PolicyError):
                bound_quality(candidate, evidence)

        duplicate, evidence = schema6_request()
        with self.assertRaises(ROUTING.PolicyError):
            bound_quality(duplicate, evidence, dict(evidence))

    def test_schema6_input_is_not_mutated_and_schema5_remains_compatible(self) -> None:
        source, evidence = schema6_request()
        before = json.loads(json.dumps(source))
        ROUTING.evaluate_route(
            source,
            POLICY,
            verified_quality_evidence=bound_quality(source, evidence),
        )
        self.assertEqual(source, before)
        self.assertEqual(ROUTING.evaluate_route(v5_request(), POLICY)["route"], "SOL_LUNA")

    def test_schema6_missing_external_evidence_fails_closed(self) -> None:
        source, _ = schema6_request()
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.evaluate_route(source, POLICY)

    def test_schema6_rejects_plain_mapping_and_loads_strict_external_index(self) -> None:
        source, evidence = schema6_request()
        plain = ROUTING.quality_evidence_index(
            [evidence],
            task_family=source["task_family"],
            acceptance_suite_digest=source["acceptance_suite_digest"],
        )
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.evaluate_route(source, POLICY, verified_quality_evidence=plain)

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "quality.json"
            path.write_text(
                json.dumps({"schema_version": 1, "evidence": [evidence]}),
                encoding="utf-8",
            )
            loaded = ROUTING.load_quality_evidence_index(
                path,
                task_family=source["task_family"],
                acceptance_suite_digest=source["acceptance_suite_digest"],
            )
            self.assertIsInstance(loaded, ROUTING._ExternallyBoundQualityEvidence)
            self.assertEqual(
                ROUTING.evaluate_route(
                    source,
                    POLICY,
                    verified_quality_evidence=loaded,
                )["route"],
                "SOL_LUNA",
            )

            path.write_text(
                json.dumps({"schema_version": 1, "evidence": [evidence], "extra": 1}),
                encoding="utf-8",
            )
            with self.assertRaises(ROUTING.PolicyError):
                ROUTING.load_quality_evidence_index(
                    path,
                    task_family=source["task_family"],
                    acceptance_suite_digest=source["acceptance_suite_digest"],
                )

    def test_schema6_cli_requires_and_uses_external_quality_index(self) -> None:
        source, evidence = schema6_request()
        with tempfile.TemporaryDirectory() as temp:
            route_path = Path(temp) / "route.json"
            evidence_path = Path(temp) / "quality.json"
            route_path.write_text(json.dumps(source), encoding="utf-8")
            evidence_path.write_text(
                json.dumps({"schema_version": 1, "evidence": [evidence]}),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch.object(
                sys,
                "argv",
                [
                    "routing_policy.py",
                    "evaluate",
                    "--input",
                    str(route_path),
                    "--quality-evidence-index",
                    str(evidence_path),
                ],
            ), mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
                self.assertEqual(ROUTING.main(), 0)
            self.assertEqual(json.loads(stdout.getvalue())["route"], "SOL_LUNA")
            self.assertEqual(stderr.getvalue(), "")

            with mock.patch.object(
                sys,
                "argv",
                ["routing_policy.py", "evaluate", "--input", str(route_path)],
            ), mock.patch("sys.stdout", io.StringIO()), mock.patch("sys.stderr", stderr := io.StringIO()):
                self.assertEqual(ROUTING.main(), 2)
            self.assertIn("externally loaded quality evidence index", stderr.getvalue())

    def test_schema7_reasoning_profile_has_strict_shape_and_types(self) -> None:
        source, evidence = schema7_request()
        before = json.loads(json.dumps(source))
        floor = ROUTING.reasoning_effort_floor(source["reasoning_profile"], POLICY)
        self.assertEqual(set(floor), {"minimum_effort", "complexity_signal_count", "reasons"})
        self.assertEqual(source, before)
        for field, value in (
            ("architecture_settled", 1),
            ("deterministic_acceptance", 0),
            ("cross_module_invariants", "true"),
            ("semantic_coupling", "critical"),
        ):
            malformed = dict(source["reasoning_profile"])
            malformed[field] = value
            with self.subTest(field=field), self.assertRaises(ROUTING.PolicyError):
                ROUTING.reasoning_effort_floor(malformed, POLICY)
        malformed = dict(source["reasoning_profile"], unexpected=False)
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.reasoning_effort_floor(malformed, POLICY)
        for invalid in (
            dict(source, reasoning_profile=None),
            dict(source, reasoning_profile=dict(source["reasoning_profile"], unexpected=False)),
        ):
            with self.subTest(invalid_profile=invalid["reasoning_profile"]), self.assertRaises(ROUTING.PolicyError):
                ROUTING.evaluate_route(
                    invalid,
                    POLICY,
                    verified_quality_evidence=bound_quality(source, evidence),
                )

    def test_schema7_reasoning_floor_four_boundaries_and_no_max_autopromotion(self) -> None:
        cases = (
            (schema7_profile(), "low", 0),
            (schema7_profile(cross_module_invariants=True), "medium", 1),
            (schema7_profile(semantic_coupling="high"), "high", 1),
            (schema7_profile(architecture_settled=False, cross_module_invariants=True,
                             multi_interface_contract=True, adversarial_edge_cases=True,
                             platform_sensitive_io=True), "xhigh", 4),
        )
        for profile, minimum, count in cases:
            with self.subTest(profile=profile):
                result = ROUTING.reasoning_effort_floor(profile, POLICY)
                self.assertEqual(result["minimum_effort"], minimum)
                self.assertEqual(result["complexity_signal_count"], count)
                self.assertIsInstance(result["reasons"], list)
                self.assertNotEqual(result["minimum_effort"], "max")

    def test_schema7_p010_medium_is_below_floor_but_evidenced_high_is_selectable(self) -> None:
        profile = schema7_profile(
            semantic_coupling="medium", cross_module_invariants=True,
            multi_interface_contract=True, adversarial_edge_cases=True,
            platform_sensitive_io=True, strict_serialization=True,
        )
        source, medium_evidence = schema7_request(profile, effort="medium")
        high = json.loads(json.dumps(source["luna_candidates"][0]))
        high["allocation_id"] = "allocation-high"
        high["effort"] = "high"
        high["quality_evidence_id"] = "evidence-high-a"
        source["luna_candidates"].append(high)
        high_evidence = dict(medium_evidence, evidence_id="evidence-high-a", effort="high")
        high_evidence["evidence_digest"] = _sha256_json(
            {key: value for key, value in high_evidence.items() if key != "evidence_digest"}
        )
        evidence = bound_quality(source, medium_evidence, high_evidence)
        result = ROUTING.evaluate_route(source, POLICY, verified_quality_evidence=evidence)
        self.assertEqual(result["route"], "SOL_LUNA")
        self.assertEqual(result["selected_luna_effort"], "high")
        self.assertIn("effort_below_reasoning_floor", result["candidates"][0]["rejection_reasons"])
        self.assertNotIn("effort_below_reasoning_floor", result["candidates"][1]["rejection_reasons"])
        self.assertNotIn("reasoning_profile", result)
        self.assertNotIn("reasoning_profile", result["candidates"][0])
        self.assertNotIn("complexity_signals", result["candidates"][0])

    def test_schema7_high_without_external_quality_evidence_fails_closed(self) -> None:
        source, _ = schema7_request(schema7_profile(semantic_coupling="high"), effort="high")
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.evaluate_route(source, POLICY)

    def test_schema7_input_is_unchanged_and_schema6_remains_compatible(self) -> None:
        source, evidence = schema7_request()
        before = json.loads(json.dumps(source))
        try:
            ROUTING.evaluate_route(source, POLICY, verified_quality_evidence=bound_quality(source, evidence))
        except ROUTING.PolicyError:
            pass
        self.assertEqual(source, before)
        schema6, evidence6 = schema6_request()
        self.assertEqual(
            ROUTING.evaluate_route(schema6, POLICY, verified_quality_evidence=bound_quality(schema6, evidence6))["route"],
            "SOL_LUNA",
        )


if __name__ == "__main__":
    unittest.main()
