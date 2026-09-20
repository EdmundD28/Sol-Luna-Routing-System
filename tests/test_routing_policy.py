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
COLD_START_TEMP = tempfile.TemporaryDirectory()


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


def schema6_request(*, first_pass_accepted: int = 16, observations: int = 16) -> tuple[dict, dict]:
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


def schema8_request() -> dict:
    source = v5_request()
    source["schema_version"] = 8
    manifest = schema8_manifest(source["acceptance_contract_ids"])
    source["acceptance_suite_digest"] = _sha256_json(
        ROUTING.cold_start_acceptance_manifest(manifest)
    )
    source["reasoning_profile"] = schema7_profile()
    candidate = source["luna_candidates"][0]
    candidate["effort"] = "medium"
    candidate["effort_basis"] = "settled low-risk work with deterministic acceptance"
    candidate["sol_controller_queue"] = {
        "ready_packages": 0,
        "review_items": 0,
        "integration_items": 0,
        "dispatch_items": 0,
        "acceptance_items": 0,
    }
    for package_item in candidate["packages"]:
        package_item["executor"] = "LUNA"
        package_item["first_pass_probability"] = 1.0
        package_item["repair_probability"] = 0.0
        package_item["repair_credits"] = 1
        package_item["repair_seconds"] = 5
        package_item["terminal_failure_probability"] = 0.0
        package_item["terminal_recovery_credits"] = 1
        package_item["terminal_recovery_seconds"] = 5
        package_item["final_defect_probability"] = 0.0
    return source


def schema8_manifest(acceptance_ids: list[str] | None = None) -> dict:
    ids = acceptance_ids or ["accept-core", "accept-tests"]
    return {
        "schema_version": 1,
        "task_family": "bounded-feature",
        "acceptance_contracts": [
            {
                "acceptance_id": acceptance_id,
                "command": ["python", "-m", "unittest", acceptance_id],
                "expected_signal": "exit 0",
            }
            for acceptance_id in ids
        ],
    }


def bound_cold_start(source: dict, manifest: dict | None = None) -> dict:
    normalized = ROUTING.cold_start_acceptance_manifest(
        manifest or schema8_manifest(source["acceptance_contract_ids"])
    )
    manifest_bytes = ROUTING.canonical_json(normalized)
    manifest_name = hashlib.sha256(manifest_bytes).hexdigest() + ".json"
    manifest_path = Path(COLD_START_TEMP.name) / manifest_name
    manifest_path.write_bytes(manifest_bytes)
    return ROUTING.load_cold_start_evidence(manifest_path, request=source)


def evaluate_schema8(source: dict, manifest: dict | None = None) -> dict:
    return ROUTING.evaluate_route(
        source,
        POLICY,
        verified_cold_start_evidence=bound_cold_start(source, manifest),
    )


def bound_quality(source: dict, *evidence: dict) -> dict:
    return ROUTING._ExternallyBoundQualityEvidence(
        ROUTING.quality_evidence_index(
            list(evidence),
            task_family=source["task_family"],
            acceptance_suite_digest=source["acceptance_suite_digest"],
        )
    )


class RoutingPolicyTests(unittest.TestCase):

    def adaptive_task(self, **overrides: object) -> dict:
        task = {
            "task_family": "adaptive-demo", "distribution_id": "same-distribution-v1",
            "required_input_modalities": ["text"],
            "output_kind": "code",
            "required_tool_capabilities": [],
            "acceptance": {"kind": "deterministic", "independent": True, "closed": True, "suite_digest": "sha256:" + "0" * 64},
            "coupling": "low", "risk": "low", "size": "normal",
            "coordination_overhead": 0,
            "economics": {
                "baseline_credits": 100, "execution_credits": 20, "coordination_credits": 5,
                "recovery_credits": 10, "baseline_seconds": 100, "execution_seconds": 30,
                "coordination_seconds": 5, "recovery_seconds": 10,
            },
        }
        task.update(overrides)
        return task

    def difficulty_profile(self, *, stages: int = 1, interactions: int = 0, ambiguities: int = 0) -> dict:
        return {
            "reasoning_stages": [f"stage-{index}" for index in range(stages)],
            "constraint_interactions": [f"constraint-{index}|constraint-{index + 1}" for index in range(interactions)],
            "semantic_ambiguities": [f"ambiguity-{index}" for index in range(ambiguities)],
            "sources": {
                "reasoning_stages": "task_contract",
                "constraint_interactions": "task_contract",
                "semantic_ambiguities": "acceptance_contract",
            },
        }

    def adaptive_evidence(self, task: dict, effort: str) -> dict:
        evidence = {
            "effort": effort, "status": "MATCHED_EXPERIENCE",
            "lower_effort_comparator": effort == "high",
            "task_family": task["task_family"],
            "input_modalities": task["required_input_modalities"],
            "output_kind": task["output_kind"],
            "acceptance_kind": task["acceptance"]["kind"],
            "distribution_id": task["distribution_id"],
            "acceptance_suite_digest": task["acceptance"]["suite_digest"],
            "observations": 16, "first_pass_accepted": 16,
        }
        if "difficulty_profile" in task:
            evidence["difficulty_profile_fingerprint"] = ROUTING.adaptive_difficulty_profile(
                task["difficulty_profile"]
            )["profile_fingerprint"]
        return evidence

    def adaptive_matching_spec(self, task: dict, **overrides: object) -> dict:
        difficulty = ROUTING.adaptive_difficulty_profile(task.get("difficulty_profile"))
        test_bindings = [
            item for item in task.get("required_tool_capabilities", [])
            if item["operation"] == "test_execution"
        ]
        self.assertLessEqual(len(test_bindings), 1)
        test_binding = test_bindings[0] if test_bindings else {
            "actor": "SOL", "surface": "shell",
        }
        role_bindings = [
            {"actor": "LUNA", "operation": "implementation", "surface": "filesystem"},
            {
                "actor": test_binding["actor"],
                "operation": "test_execution",
                "surface": test_binding["surface"],
            },
        ]
        role_bindings.extend(
            {
                "actor": item["actor"],
                "operation": item["operation"],
                "surface": item["surface"],
            }
            for item in task.get("required_tool_capabilities", [])
        )
        role_bindings = [
            {"actor": actor, "operation": operation, "surface": surface}
            for actor, operation, surface in sorted({
                (item["actor"], item["operation"], item["surface"])
                for item in role_bindings
            })
        ]
        spec = {
            "schema_version": 1,
            "distribution_id": task["distribution_id"],
            "acceptance_protocol_version": task["acceptance"]["protocol_version"],
            "acceptance_protocol_digest": task["acceptance"]["protocol_digest"],
            "input_modalities": sorted(task["required_input_modalities"]),
            "output_kind": task["output_kind"],
            "acceptance_kind": task["acceptance"]["kind"],
            "difficulty_schema_version": "adaptive-difficulty-v1",
            "difficulty_band": difficulty["band"],
            "role_bindings": role_bindings,
            "coupling": task["coupling"],
            "risk": task["risk"],
            "repair_policy": "one-focused-repair",
            "environment_boundary_digest": "sha256:" + "e" * 64,
        }
        execution_configuration = task.get("execution_configuration")
        if execution_configuration is not None:
            spec["schema_version"] = 2
            spec.update({
                field: execution_configuration[field]
                for field in (
                    "controller_model", "controller_effort", "writer_model",
                    "baseline_model", "baseline_effort",
                )
            })
        spec.update(overrides)
        spec["spec_digest"] = "sha256:" + hashlib.sha256(
            ROUTING.canonical_json(spec)
        ).hexdigest()
        return spec

    def adaptive_execution_configuration(self, **overrides: object) -> dict:
        configuration = {
            "schema_version": 1,
            "controller_model": "gpt-5.6-sol",
            "controller_effort": "high",
            "writer_model": "gpt-5.6-luna",
            "baseline_model": "gpt-5.6-sol",
            "baseline_effort": "high",
        }
        configuration.update(overrides)
        return configuration

    def adaptive_candidate_economics(
        self, matching_spec: dict | None = None, **execution_credits: float,
    ) -> list[dict]:
        defaults = {"low": 24.0, "medium": 18.0, "high": 12.0}
        defaults.update(execution_credits)
        result = []
        for index, effort in enumerate(("low", "medium", "high")):
            item = {
                "effort": effort,
                "execution_credits": defaults[effort],
                "coordination_credits": 5.0,
                "recovery_credits": 10.0,
                "execution_seconds": 30.0 + index,
                "coordination_seconds": 5.0,
                "recovery_seconds": 10.0,
            }
            if matching_spec is not None and matching_spec["schema_version"] == 2:
                item["complete_config_digest"] = (
                    ROUTING._adaptive_candidate_configuration_digest(
                        matching_spec, effort
                    )
                )
            result.append(item)
        return result

    def adaptive_cluster(
        self, spec: dict, effort: str, index: int, *,
        member_ids: tuple[str, ...] = ("primary",),
        passed: bool = True,
        repaired: bool = False,
        missing_last: bool = False,
    ) -> dict:
        present = member_ids[:-1] if missing_last else member_ids
        result = {
            "record_id": f"{effort}-record-{index}",
            "matching_spec_digest": spec["spec_digest"],
            "semantic_cluster_id": f"cluster-{index}",
            "effort": effort,
            "expected_member_ids": list(member_ids),
            "members": [
                {
                    "member_id": member_id,
                    "instance_digest": "sha256:" + hashlib.sha256(
                        f"{index}:{member_id}:instance".encode()
                    ).hexdigest(),
                    "material_digest": "sha256:" + hashlib.sha256(
                        f"{index}:{member_id}:material".encode()
                    ).hexdigest(),
                    "acceptance_instance_digest": "sha256:" + hashlib.sha256(
                        f"{index}:{member_id}:acceptance".encode()
                    ).hexdigest(),
                    "first_pass_accepted": passed and not repaired,
                    "final_accepted": passed or repaired,
                    "repair_attempts": 1 if repaired else 0,
                    "final_defect": False,
                }
                for member_id in present
            ],
        }
        if spec["schema_version"] == 2:
            result["complete_config_digest"] = (
                ROUTING._adaptive_candidate_configuration_digest(spec, effort)
            )
        return result

    def adaptive_cross_instance_task(self, **overrides: object) -> dict:
        task = self.adaptive_task(
            task_contract_digest="sha256:" + "a" * 64,
            material_digest="sha256:" + "b" * 64,
            difficulty_profile=self.difficulty_profile(stages=6, interactions=3),
        )
        task.pop("economics")
        task.update(overrides)
        task["acceptance"] = dict(
            task["acceptance"], protocol_version="acceptance-v1",
            protocol_digest="sha256:" + "c" * 64,
        )
        task["matching_spec"] = self.adaptive_matching_spec(task)
        task["candidate_economics"] = self.adaptive_candidate_economics(
            task["matching_spec"]
        )
        task["baseline_economics"] = {
            "baseline_credits": 100.0,
            "baseline_seconds": 100.0,
        }
        if task["matching_spec"]["schema_version"] == 2:
            task["baseline_economics"]["complete_config_digest"] = (
                ROUTING._adaptive_configuration_digest(
                    ROUTING._adaptive_baseline_configuration(
                        task["execution_configuration"]
                    )
                )
            )
        return task

    def bound_adaptive_pool(self, records: list[dict]) -> object:
        return ROUTING._ExternallyBoundAdaptiveEvidencePool(records)

    def adaptive_research_task(self, effort: str = "high") -> dict:
        profile = self.difficulty_profile(stages=10, interactions=6, ambiguities=1)
        profile_fingerprint = ROUTING.adaptive_difficulty_profile(profile)["profile_fingerprint"]
        task_digest = "sha256:" + "1" * 64
        suite_digest = "sha256:" + "0" * 64
        plan = {
            "experiment_id": "P130-C5-PAIR-01", "requested_effort": effort,
            "task_contract_digest": task_digest,
            "acceptance_suite_digest": suite_digest,
            "difficulty_profile_fingerprint": profile_fingerprint,
            "time_budget_seconds": 300, "attempt_budget": 2,
        }
        if effort == "high":
            plan["paired_medium_comparator"] = {
                "planned": True, "effort": "medium",
                "task_contract_digest": task_digest,
                "acceptance_suite_digest": suite_digest,
            }
        return self.adaptive_task(
            decision_context="budgeted_research", difficulty_profile=profile,
            task_contract_digest=task_digest, research_exploration=plan,
        )

    def test_adaptive_shape_changes_low_medium_and_s0(self) -> None:
        evidence = {"effort": "low", "status": "MATCHED_EXPERIENCE", "lower_effort_comparator": False, "task_family": "adaptive-demo", "input_modalities": ["text"], "output_kind": "code", "acceptance_kind": "deterministic", "distribution_id": "same-distribution-v1", "acceptance_suite_digest": "sha256:" + "0" * 64, "observations": 16, "first_pass_accepted": 16}
        low = ROUTING.select_adaptive_route(self.adaptive_task(), evidence=evidence)
        self.assertEqual((low["candidate"], low["effort"]), ("S1", "low"))
        visual = self.adaptive_task(
            required_input_modalities=["screenshot"], output_kind="document",
            coupling="medium",
            required_tool_capabilities=[{"name": "vision", "status": "basic-proven", "source": "basic-proven", "operation": "document_review", "actor": "LUNA", "surface": "view_image"}],
            acceptance={"kind": "document_review", "independent": True, "closed": True, "suite_digest": "sha256:" + "0" * 64},
        )
        medium = ROUTING.select_adaptive_route(visual, evidence=dict(evidence, input_modalities=["screenshot"], output_kind="document", acceptance_kind="document_review", effort="medium"))
        self.assertEqual((medium["candidate"], medium["effort"]), ("S2", "medium"))
        small = ROUTING.select_adaptive_route(self.adaptive_task(size="small"))
        self.assertEqual(small["candidate"], "S0")

    def test_adaptive_unknown_unavailable_and_unproven_are_distinct(self) -> None:
        unknown = self.adaptive_task(required_tool_capabilities=[{"name": "vision", "status": "unknown", "source": "host-observed", "operation": "visual_review", "actor": "LUNA", "surface": "browser"}])
        self.assertEqual(ROUTING.select_adaptive_route(unknown)["candidate"], "S0")
        research = self.adaptive_task(required_tool_capabilities=[{"name": "vision", "status": "host-observed", "source": "unknown", "operation": "visual_review", "actor": "LUNA", "surface": "browser"}])
        self.assertEqual(ROUTING.select_adaptive_route(research)["candidate"], "S0")

    def test_adaptive_budgeted_research_is_explicit_and_effort_sensitive(self) -> None:
        production = self.adaptive_task()
        self.assertEqual(ROUTING.select_adaptive_route(production)["candidate"], "S0")
        text = self.adaptive_task(decision_context="budgeted_research")
        text_result = ROUTING.select_adaptive_route(text)
        self.assertEqual((text_result["candidate"], text_result["effort"]), ("S4", "low"))
        visual = self.adaptive_task(
            decision_context="budgeted_research", required_input_modalities=["screenshot"], output_kind="document",
            required_tool_capabilities=[{"name": "vision", "status": "basic-proven", "source": "basic-proven", "operation": "document_review", "actor": "LUNA", "surface": "view_image"}],
            acceptance={"kind": "document_review", "independent": True, "closed": True, "suite_digest": "sha256:" + "0" * 64},
            size="large", coupling="medium",
        )
        visual_result = ROUTING.select_adaptive_route(visual)
        self.assertEqual((visual_result["candidate"], visual_result["effort"]), ("S4", "medium"))

    def test_adaptive_high_requires_matching_lower_effort_evidence(self) -> None:
        task = self.adaptive_task(output_kind="text", risk="medium")
        no_evidence = ROUTING.select_adaptive_route(task, evidence={"effort": "high", "status": "UNKNOWN", "lower_effort_comparator": False})
        self.assertNotEqual(no_evidence["candidate"], "S3")
        evidence = {"effort": "high", "status": "MATCHED_EXPERIENCE", "lower_effort_comparator": True, "task_family": "adaptive-demo", "input_modalities": ["text"], "output_kind": "text", "acceptance_kind": "deterministic", "distribution_id": "same-distribution-v1", "acceptance_suite_digest": "sha256:" + "0" * 64, "observations": 16, "first_pass_accepted": 16}
        high = ROUTING.select_adaptive_route(task, evidence=evidence)
        self.assertEqual(high["candidate"], "S3")
        borrowed = dict(evidence, effort="medium")
        self.assertEqual(ROUTING.select_adaptive_route(task, evidence=borrowed)["candidate"], "S0")

    def test_adaptive_cold_start_exact_q_boundary(self) -> None:
        base = self.adaptive_task(cold_start=True, cold_start_constraints={key: True for key in ("architecture_settled", "deterministic_acceptance", "low_risk", "low_coupling", "complete_luna_ownership", "exclusive_write", "single_writer", "sol_queue_empty")}, economics={"baseline_credits": 10, "launch_credits": 2, "overhead_credits": 3, "recovery_credits": 5, "baseline_seconds": 100, "launch_seconds": 20, "overhead_seconds": 5, "recovery_seconds": 10, "failure_probability": 0})
        self.assertEqual(ROUTING.select_adaptive_route(base)["candidate"], "S1")
        over = dict(base, economics=dict(base["economics"], failure_probability=0.0001))
        self.assertEqual(ROUTING.select_adaptive_route(over)["candidate"], "S0")
        self.assertEqual(ROUTING.cold_start_credit_bound(10, 5, 0, 5), 0)
        self.assertEqual(ROUTING.cold_start_credit_bound(10, 5.1, 0, 5), -1)

    def test_adaptive_explicit_test_executor_cannot_use_legacy_cold_start_exception(self) -> None:
        luna_test_capability = {
            "name": "luna-tests",
            "status": "host-observed",
            "source": "host-observed",
            "operation": "test_execution",
            "actor": "LUNA",
            "surface": "shell",
        }
        constraints = {
            key: True
            for key in (
                "architecture_settled", "deterministic_acceptance", "low_risk",
                "low_coupling", "complete_luna_ownership", "exclusive_write",
                "single_writer", "sol_queue_empty",
            )
        }
        economics = {
            "baseline_credits": 10,
            "launch_credits": 2,
            "overhead_credits": 3,
            "recovery_credits": 5,
            "baseline_seconds": 100,
            "launch_seconds": 20,
            "overhead_seconds": 5,
            "recovery_seconds": 10,
            "failure_probability": 0,
        }
        cold_start = self.adaptive_task(
            required_tool_capabilities=[luna_test_capability],
            cold_start=True,
            cold_start_constraints=constraints,
            economics=economics,
        )
        rejected = ROUTING.select_adaptive_route(cold_start)
        self.assertEqual(
            (rejected["candidate"], rejected["route"], rejected["evidence_status"]),
            ("S0", "SOL_ONLY", "UNKNOWN"),
        )
        self.assertEqual(
            rejected["reason_code"],
            "cold_start_explicit_test_execution_requires_matching_evidence",
        )
        self.assertEqual(
            rejected["responsibilities"]["test_execution"],
            {"actor": "SOL", "surface": "shell"},
        )

        research = self.adaptive_task(
            required_tool_capabilities=[luna_test_capability],
            decision_context="budgeted_research",
        )
        explored = ROUTING.select_adaptive_route(research)
        self.assertEqual((explored["candidate"], explored["route"]), ("S4", "SOL_LUNA"))
        self.assertEqual(
            explored["responsibilities"]["test_execution"],
            {"actor": "LUNA", "surface": "shell"},
        )

    def test_adaptive_execution_mismatch_fails_closed(self) -> None:
        selected = ROUTING.select_adaptive_route(self.adaptive_task(cold_start=True, cold_start_constraints={key: True for key in ("architecture_settled", "deterministic_acceptance", "low_risk", "low_coupling", "complete_luna_ownership", "exclusive_write", "single_writer", "sol_queue_empty")}, economics={"baseline_credits": 10, "launch_credits": 2, "overhead_credits": 3, "recovery_credits": 5, "baseline_seconds": 100, "launch_seconds": 20, "overhead_seconds": 5, "recovery_seconds": 10, "failure_probability": 0}))
        actual = {key: selected[key] for key in ("route", "candidate", "model", "effort", "execution_token", "responsibilities")}
        self.assertTrue(ROUTING.validate_adaptive_execution(selected, actual)["valid"])
        actual["effort"] = "medium"
        with self.assertRaisesRegex(ROUTING.PolicyError, "execution mismatch"):
            ROUTING.validate_adaptive_execution(selected, actual)

    def test_adaptive_difficulty_is_observable_order_stable_and_not_high_mapping(self) -> None:
        d1 = self.adaptive_task(
            decision_context="budgeted_research",
            difficulty_profile=self.difficulty_profile(stages=2),
        )
        d3_profile = self.difficulty_profile(stages=10, interactions=6, ambiguities=1)
        d3 = self.adaptive_task(
            decision_context="budgeted_research", difficulty_profile=d3_profile,
        )
        low = ROUTING.select_adaptive_route(d1)
        hard = ROUTING.select_adaptive_route(d3)
        self.assertEqual((low["difficulty"]["band"], low["effort"]), ("D1", "low"))
        self.assertEqual((hard["difficulty"]["band"], hard["effort"]), ("D3", "medium"))
        self.assertNotEqual(hard["effort"], "high")

        equivalent = dict(d3_profile)
        equivalent["reasoning_stages"] = list(reversed(d3_profile["reasoning_stages"]))
        renamed = self.adaptive_task(
            task_family="renamed-family", required_input_modalities=["code"],
            decision_context="budgeted_research", difficulty_profile=equivalent,
        )
        renamed_result = ROUTING.select_adaptive_route(renamed)
        self.assertEqual(renamed_result["effort"], hard["effort"])
        self.assertEqual(
            renamed_result["difficulty"]["profile_fingerprint"],
            hard["difficulty"]["profile_fingerprint"],
        )

    def test_adaptive_profile_evidence_cannot_cross_difficulty_or_missing_profile(self) -> None:
        d1 = self.adaptive_task(difficulty_profile=self.difficulty_profile(stages=2))
        d3 = self.adaptive_task(difficulty_profile=self.difficulty_profile(stages=10, interactions=6, ambiguities=1))
        d1_evidence = self.adaptive_evidence(d1, "low")
        self.assertEqual(ROUTING.select_adaptive_route(d1, evidence=d1_evidence)["candidate"], "S1")
        self.assertEqual(ROUTING.select_adaptive_route(d3, evidence=d1_evidence)["candidate"], "S0")

        legacy = self.adaptive_evidence(self.adaptive_task(), "low")
        self.assertEqual(ROUTING.select_adaptive_route(d3, evidence=legacy)["candidate"], "S0")
        d3_evidence = self.adaptive_evidence(d3, "medium")
        self.assertEqual(ROUTING.select_adaptive_route(d3, evidence=d3_evidence)["candidate"], "S2")
        d3_high_evidence = self.adaptive_evidence(d3, "high")
        self.assertEqual(ROUTING.select_adaptive_route(d3, evidence=d3_high_evidence)["candidate"], "S3")

    def test_adaptive_difficulty_rejects_unknown_post_outcome_and_duplicate_facts(self) -> None:
        cases = []
        unknown = self.difficulty_profile()
        unknown["result_quality"] = "passed"
        cases.append(unknown)
        post_outcome = self.difficulty_profile()
        post_outcome["sources"] = dict(post_outcome["sources"], reasoning_stages="execution_result")
        cases.append(post_outcome)
        duplicate = self.difficulty_profile(stages=2)
        duplicate["reasoning_stages"][1] = duplicate["reasoning_stages"][0]
        cases.append(duplicate)
        for profile in cases:
            with self.subTest(profile=profile), self.assertRaises(ROUTING.PolicyError):
                ROUTING.select_adaptive_route(self.adaptive_task(difficulty_profile=profile))

    def test_adaptive_preregistered_high_is_research_only_and_fully_bound(self) -> None:
        task = self.adaptive_research_task("high")
        selected = ROUTING.select_adaptive_route(task)
        self.assertEqual((selected["candidate"], selected["effort"]), ("S4", "high"))
        self.assertEqual(selected["effort_selection"], "PREREGISTERED_COUNTERFACTUAL")
        self.assertEqual(selected["evidence_status"], "BUDGETED_RESEARCH_EXPLORATION")
        self.assertEqual(selected["research_plan"]["evidence_effect"], "PREREGISTERED_PLAN_NOT_OBSERVED_EVIDENCE")

        missing_pair = self.adaptive_research_task("high")
        missing_pair["research_exploration"].pop("paired_medium_comparator")
        with self.assertRaises(ROUTING.PolicyError):
            ROUTING.select_adaptive_route(missing_pair)
        for field in ("time_budget_seconds", "attempt_budget"):
            incomplete = self.adaptive_research_task("medium")
            incomplete["research_exploration"].pop(field)
            with self.subTest(field=field), self.assertRaises(ROUTING.PolicyError):
                ROUTING.select_adaptive_route(incomplete)
        production = self.adaptive_research_task("medium")
        production["decision_context"] = "production"
        with self.assertRaisesRegex(ROUTING.PolicyError, "budgeted_research"):
            ROUTING.select_adaptive_route(production)
        drift = self.adaptive_research_task("medium")
        drift["research_exploration"]["acceptance_suite_digest"] = "sha256:" + "2" * 64
        with self.assertRaisesRegex(ROUTING.PolicyError, "acceptance_suite_digest drift"):
            ROUTING.select_adaptive_route(drift)

    def test_adaptive_research_execution_binds_plan_and_observed_budget(self) -> None:
        selected = ROUTING.select_adaptive_route(self.adaptive_research_task("high"))
        actual = {key: selected[key] for key in (
            "route", "candidate", "model", "effort", "execution_token", "responsibilities", "research_plan",
        )}
        unverified = ROUTING.validate_adaptive_execution(selected, actual)
        self.assertEqual(unverified["budget_status"], "DECLARED_NOT_RUNTIME_VERIFIED")
        self.assertEqual(unverified["budget_enforcement"], "NOT_AUTOMATIC")

        receipt = {
            "experiment_id": selected["research_plan"]["experiment_id"],
            "task_contract_digest": selected["research_plan"]["task_contract_digest"],
            "acceptance_suite_digest": selected["research_plan"]["acceptance_suite_digest"],
            "difficulty_profile_fingerprint": selected["research_plan"]["difficulty_profile_fingerprint"],
            "effort": selected["effort"], "elapsed_seconds": 299.5, "attempts": 2,
        }
        actual["research_receipt"] = receipt
        verified = ROUTING.validate_adaptive_execution(selected, actual)
        self.assertEqual(verified["budget_status"], "VERIFIED_WITHIN_DECLARED_BUDGET")

        for field, value in (
            ("elapsed_seconds", 301), ("attempts", 3), ("effort", "medium"),
            ("task_contract_digest", "sha256:" + "3" * 64),
        ):
            bad = dict(actual, research_receipt=dict(receipt, **{field: value}))
            with self.subTest(field=field), self.assertRaises(ROUTING.PolicyError):
                ROUTING.validate_adaptive_execution(selected, bad)

    def test_cross_instance_reuse_enumerates_all_efforts_and_selects_lowest_cost(self) -> None:
        task = self.adaptive_cross_instance_task()
        records = [
            self.adaptive_cluster(task["matching_spec"], effort, index)
            for effort in ("low", "medium", "high")
            for index in range(16)
        ]
        selected = ROUTING.select_adaptive_route(
            task, verified_evidence_pool=self.bound_adaptive_pool(records)
        )
        self.assertEqual((selected["candidate"], selected["effort"]), ("S3", "high"))
        self.assertEqual(selected["selection_basis"], "MIN_CONSERVATIVE_COMPLETE_COST_THEN_TIME")
        self.assertEqual(
            selected["trace_digests"],
            {
                "instance": task["task_contract_digest"],
                "material": task["material_digest"],
                "acceptance_instance": task["acceptance"]["suite_digest"],
                "matching_spec": task["matching_spec"]["spec_digest"],
            },
        )
        self.assertEqual(
            {item["effort"] for item in selected["candidate_evaluations"]},
            {"low", "medium", "high"},
        )

        reordered = dict(task, candidate_economics=list(reversed(task["candidate_economics"])))
        repeated = ROUTING.select_adaptive_route(
            reordered, verified_evidence_pool=self.bound_adaptive_pool(list(reversed(records)))
        )
        self.assertEqual(repeated["effort"], selected["effort"])
        self.assertEqual(repeated["execution_token"], selected["execution_token"])

    def test_cross_instance_test_executor_is_bound_to_capability_evidence_and_execution(self) -> None:
        def test_capability(actor: str, status: str = "host-observed") -> dict:
            return {
                "name": f"{actor.lower()}-tests",
                "status": status,
                "source": status,
                "operation": "test_execution",
                "actor": actor,
                "surface": "shell",
            }

        selected_by_actor = {}
        task_by_actor = {}
        records_by_actor = {}
        for actor in ("SOL", "LUNA"):
            task = self.adaptive_cross_instance_task(
                required_tool_capabilities=[test_capability(actor)]
            )
            records = [
                self.adaptive_cluster(task["matching_spec"], "low", index)
                for index in range(16)
            ]
            selected = ROUTING.select_adaptive_route(
                task, verified_evidence_pool=self.bound_adaptive_pool(records)
            )
            self.assertEqual((selected["candidate"], selected["route"]), ("S1", "SOL_LUNA"))
            self.assertEqual(
                selected["responsibilities"]["test_execution"],
                {"actor": actor, "surface": "shell"},
            )
            self.assertEqual(selected["responsibilities"]["final_acceptance_owner"], "SOL")
            self.assertEqual(selected["acceptance"]["responsibility"], "SOL")
            actual = {
                key: selected[key]
                for key in (
                    "route", "candidate", "model", "effort",
                    "execution_token", "responsibilities",
                )
            }
            self.assertTrue(ROUTING.validate_adaptive_execution(selected, actual)["valid"])
            selected_by_actor[actor] = selected
            task_by_actor[actor] = task
            records_by_actor[actor] = records

        self.assertNotEqual(
            task_by_actor["SOL"]["matching_spec"]["spec_digest"],
            task_by_actor["LUNA"]["matching_spec"]["spec_digest"],
        )
        self.assertNotEqual(
            selected_by_actor["SOL"]["execution_token"],
            selected_by_actor["LUNA"]["execution_token"],
        )
        with self.assertRaisesRegex(ROUTING.PolicyError, "matching_spec drift"):
            ROUTING.select_adaptive_route(
                task_by_actor["LUNA"],
                verified_evidence_pool=self.bound_adaptive_pool(records_by_actor["SOL"]),
            )

        drifted_actual = {
            key: selected_by_actor["LUNA"][key]
            for key in (
                "route", "candidate", "model", "effort",
                "execution_token", "responsibilities",
            )
        }
        drifted_actual["responsibilities"] = dict(drifted_actual["responsibilities"])
        drifted_actual["responsibilities"]["test_execution"] = {
            "actor": "SOL", "surface": "shell",
        }
        with self.assertRaisesRegex(ROUTING.PolicyError, "responsibilities"):
            ROUTING.validate_adaptive_execution(selected_by_actor["LUNA"], drifted_actual)

        no_evidence = ROUTING.select_adaptive_route(task_by_actor["LUNA"])
        self.assertEqual(
            (no_evidence["candidate"], no_evidence["evidence_status"]),
            ("S0", "UNKNOWN"),
        )
        self.assertEqual(no_evidence["responsibilities"]["final_acceptance_owner"], "SOL")

        legacy_task = self.adaptive_task(
            required_tool_capabilities=[test_capability("LUNA")]
        )
        legacy_evidence = self.adaptive_evidence(legacy_task, "low")
        legacy_result = ROUTING.select_adaptive_route(
            legacy_task, evidence=legacy_evidence
        )
        self.assertEqual(
            (legacy_result["candidate"], legacy_result["evidence_status"]),
            ("S0", "UNKNOWN"),
        )

        old_request = self.adaptive_cross_instance_task()
        old_records = [
            self.adaptive_cluster(old_request["matching_spec"], "low", index)
            for index in range(16)
        ]
        old_selected = ROUTING.select_adaptive_route(
            old_request, verified_evidence_pool=self.bound_adaptive_pool(old_records)
        )
        self.assertEqual(
            old_selected["responsibilities"]["test_execution"],
            {"actor": "SOL", "surface": "shell"},
        )

        unavailable = self.adaptive_cross_instance_task(
            required_tool_capabilities=[test_capability("LUNA", "unknown")]
        )
        unavailable_result = ROUTING.select_adaptive_route(unavailable)
        self.assertEqual(
            (unavailable_result["candidate"], unavailable_result["reason_code"]),
            ("S0", "required_capability_unknown"),
        )

        undeclared = self.adaptive_cross_instance_task()
        undeclared["matching_spec"] = self.adaptive_matching_spec(
            undeclared,
            role_bindings=[
                {"actor": "LUNA", "operation": "implementation", "surface": "filesystem"},
                {"actor": "LUNA", "operation": "test_execution", "surface": "shell"},
            ],
        )
        with self.assertRaisesRegex(ROUTING.PolicyError, "role_bindings"):
            ROUTING.select_adaptive_route(undeclared)

    def test_cross_instance_v2_configuration_identity_binds_selection_and_execution(self) -> None:
        configuration = self.adaptive_execution_configuration(
            controller_effort="low", baseline_effort="high",
        )
        luna_test = {
            "name": "luna-tests",
            "status": "host-observed",
            "source": "host-observed",
            "operation": "test_execution",
            "actor": "LUNA",
            "surface": "shell",
        }
        task = self.adaptive_cross_instance_task(
            execution_configuration=configuration,
            required_tool_capabilities=[luna_test],
        )

        fallback = ROUTING.select_adaptive_route(task)
        self.assertEqual(
            (fallback["candidate"], fallback["route"], fallback["evidence_status"]),
            ("S0", "SOL_ONLY", "UNKNOWN"),
        )
        self.assertEqual(
            (fallback["model"], fallback["effort"]),
            (configuration["baseline_model"], configuration["baseline_effort"]),
        )
        self.assertEqual(
            fallback["selected_configuration"],
            ROUTING._adaptive_baseline_configuration(configuration),
        )
        self.assertEqual(
            fallback["complete_config_digest"],
            task["baseline_economics"]["complete_config_digest"],
        )
        self.assertEqual(
            fallback["responsibilities"]["test_execution"],
            {"actor": "SOL", "surface": "shell"},
        )

        records = [
            self.adaptive_cluster(task["matching_spec"], "low", index)
            for index in range(16)
        ]
        selected = ROUTING.select_adaptive_route(
            task, verified_evidence_pool=self.bound_adaptive_pool(records)
        )
        self.assertEqual((selected["candidate"], selected["route"]), ("S1", "SOL_LUNA"))
        self.assertEqual(
            selected["selected_configuration"],
            ROUTING._adaptive_candidate_configuration(
                configuration,
                task["matching_spec"]["role_bindings"],
                "low",
            ),
        )
        expected_digest = ROUTING._adaptive_candidate_configuration_digest(
            task["matching_spec"], "low"
        )
        self.assertEqual(selected["complete_config_digest"], expected_digest)
        self.assertEqual(records[0]["complete_config_digest"], expected_digest)
        self.assertEqual(
            next(
                item for item in task["candidate_economics"]
                if item["effort"] == "low"
            )["complete_config_digest"],
            expected_digest,
        )
        self.assertEqual(
            selected["responsibilities"]["test_execution"],
            {"actor": "LUNA", "surface": "shell"},
        )
        actual = {
            key: selected[key]
            for key in (
                "route", "candidate", "model", "effort", "execution_token",
                "responsibilities", "selected_configuration",
                "complete_config_digest",
            )
        }
        self.assertTrue(ROUTING.validate_adaptive_execution(selected, actual)["valid"])
        drifted_actual = dict(actual)
        drifted_actual["selected_configuration"] = dict(
            actual["selected_configuration"], controller_effort="high"
        )
        with self.assertRaisesRegex(ROUTING.PolicyError, "selected_configuration"):
            ROUTING.validate_adaptive_execution(selected, drifted_actual)

    def test_cross_instance_v2_rejects_identity_evidence_and_economics_drift(self) -> None:
        configuration = self.adaptive_execution_configuration(
            controller_effort="low", baseline_effort="high",
        )
        task = self.adaptive_cross_instance_task(
            execution_configuration=configuration,
        )

        for field, value in (
            ("controller_model", "gpt-6-astra"),
            ("controller_effort", "medium"),
            ("writer_model", "gpt-5.6-terra"),
            ("baseline_model", "gpt-6-astra"),
            ("baseline_effort", "medium"),
        ):
            drifted = dict(task)
            drifted["execution_configuration"] = dict(
                configuration, **{field: value}
            )
            with self.subTest(identity_field=field), self.assertRaisesRegex(
                ROUTING.PolicyError, field
            ):
                ROUTING.select_adaptive_route(drifted)

        old_economics = dict(task)
        old_economics["candidate_economics"] = self.adaptive_candidate_economics()
        with self.assertRaisesRegex(ROUTING.PolicyError, "incomplete"):
            ROUTING.select_adaptive_route(old_economics)

        wrong_candidate_economics = dict(task)
        wrong_candidate_economics["candidate_economics"] = [
            dict(item) for item in task["candidate_economics"]
        ]
        wrong_candidate_economics["candidate_economics"][0][
            "complete_config_digest"
        ] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(ROUTING.PolicyError, "complete_config_digest"):
            ROUTING.select_adaptive_route(wrong_candidate_economics)

        missing_baseline_identity = dict(task)
        missing_baseline_identity["baseline_economics"] = {
            "baseline_credits": 100.0, "baseline_seconds": 100.0,
        }
        with self.assertRaisesRegex(ROUTING.PolicyError, "incomplete"):
            ROUTING.select_adaptive_route(missing_baseline_identity)

        wrong_baseline_identity = dict(task)
        wrong_baseline_identity["baseline_economics"] = dict(
            task["baseline_economics"],
            complete_config_digest="sha256:" + "f" * 64,
        )
        with self.assertRaisesRegex(ROUTING.PolicyError, "baseline_economics"):
            ROUTING.select_adaptive_route(wrong_baseline_identity)

        record = self.adaptive_cluster(task["matching_spec"], "low", 0)
        missing_record_identity = dict(record)
        missing_record_identity.pop("complete_config_digest")
        with self.assertRaisesRegex(ROUTING.PolicyError, "incomplete"):
            ROUTING.select_adaptive_route(
                task,
                verified_evidence_pool=self.bound_adaptive_pool(
                    [missing_record_identity]
                ),
            )
        wrong_record_identity = dict(
            record, complete_config_digest="sha256:" + "f" * 64
        )
        with self.assertRaisesRegex(ROUTING.PolicyError, "configuration drift"):
            ROUTING.select_adaptive_route(
                task,
                verified_evidence_pool=self.bound_adaptive_pool(
                    [wrong_record_identity]
                ),
            )

        other_task = self.adaptive_cross_instance_task(
            execution_configuration=self.adaptive_execution_configuration(
                controller_effort="high"
            )
        )
        mixed_records = [
            self.adaptive_cluster(task["matching_spec"], effort, index)
            for effort in ("medium", "high")
            for index in range(16)
        ]
        mixed_records[-1] = self.adaptive_cluster(
            other_task["matching_spec"], "high", 15
        )
        with self.assertRaisesRegex(ROUTING.PolicyError, "matching_spec drift"):
            ROUTING.select_adaptive_route(
                task,
                verified_evidence_pool=self.bound_adaptive_pool(mixed_records),
            )

    def test_cross_instance_matching_spec_rejects_drift_and_inline_claims(self) -> None:
        task = self.adaptive_cross_instance_task()
        records = [
            self.adaptive_cluster(task["matching_spec"], "low", index)
            for index in range(16)
        ]
        with self.assertRaisesRegex(ROUTING.PolicyError, "externally bound"):
            ROUTING.select_adaptive_route(task, verified_evidence_pool=records)

        for field, value in (
            ("difficulty_band", "D3"),
            ("acceptance_protocol_version", "acceptance-v2"),
            ("environment_boundary_digest", "sha256:" + "f" * 64),
            ("coupling", "medium"),
            ("risk", "medium"),
        ):
            drifted = dict(task)
            drifted["matching_spec"] = self.adaptive_matching_spec(task, **{field: value})
            with self.subTest(field=field), self.assertRaises(ROUTING.PolicyError):
                ROUTING.select_adaptive_route(
                    drifted, verified_evidence_pool=self.bound_adaptive_pool(records)
                )

        for field, drifted in (
            ("output_kind", dict(task, output_kind="text")),
            (
                "input_modalities",
                dict(task, required_input_modalities=["text", "image"]),
            ),
            (
                "acceptance_kind",
                dict(task, acceptance=dict(task["acceptance"], kind="text_review")),
            ),
            (
                "acceptance_protocol_digest",
                dict(
                    task,
                    acceptance=dict(
                        task["acceptance"], protocol_digest="sha256:" + "d" * 64,
                    ),
                ),
            ),
            (
                "acceptance_protocol_version",
                dict(
                    task,
                    acceptance=dict(task["acceptance"], protocol_version="acceptance-v2"),
                ),
            ),
        ):
            with self.subTest(field=field), self.assertRaises(ROUTING.PolicyError):
                ROUTING.select_adaptive_route(
                    drifted, verified_evidence_pool=self.bound_adaptive_pool(records)
                )

        visual = dict(task)
        visual["required_tool_capabilities"] = [{
            "name": "vision", "status": "host-observed", "source": "host-observed",
            "operation": "visual_review", "actor": "LUNA", "surface": "view_image",
        }]
        with self.assertRaisesRegex(ROUTING.PolicyError, "role_bindings"):
            ROUTING.select_adaptive_route(
                visual, verified_evidence_pool=self.bound_adaptive_pool(records)
            )

    def test_semantic_clusters_count_once_require_all_members_and_reject_duplicates(self) -> None:
        task = self.adaptive_cross_instance_task()
        records = [
            self.adaptive_cluster(
                task["matching_spec"], "low", index,
                member_ids=("text", "visual"), missing_last=index == 15,
            )
            for index in range(16)
        ]
        selected = ROUTING.select_adaptive_route(
            task, verified_evidence_pool=self.bound_adaptive_pool(records)
        )
        low = next(item for item in selected["candidate_evaluations"] if item["effort"] == "low")
        self.assertEqual(
            (low["semantic_clusters"], low["first_pass_accepted_clusters"]),
            (16, 15),
        )
        self.assertEqual(low["status"], "FINAL_ACCEPTANCE_GATE_FAILED")
        self.assertEqual(selected["candidate"], "S0")

        duplicate_record = records + [dict(records[0])]
        with self.assertRaisesRegex(ROUTING.PolicyError, "duplicate"):
            ROUTING.select_adaptive_route(
                task, verified_evidence_pool=self.bound_adaptive_pool(duplicate_record)
            )
        duplicate_instance = [dict(item) for item in records]
        duplicate_instance[1] = dict(
            duplicate_instance[1],
            members=[dict(member) for member in duplicate_instance[1]["members"]],
        )
        duplicate_instance[1]["members"][0]["instance_digest"] = records[0]["members"][0]["instance_digest"]
        with self.assertRaisesRegex(ROUTING.PolicyError, "duplicate instance"):
            ROUTING.select_adaptive_route(
                task, verified_evidence_pool=self.bound_adaptive_pool(duplicate_instance)
            )

    def test_cross_instance_candidates_fail_closed_on_quality_time_and_missing_high_comparator(self) -> None:
        task = self.adaptive_cross_instance_task()
        economics = [dict(item) for item in task["candidate_economics"]]
        next(item for item in economics if item["effort"] == "low")["execution_credits"] = 1.0
        next(item for item in economics if item["effort"] == "medium")["execution_credits"] = 2.0
        next(item for item in economics if item["effort"] == "medium")["execution_seconds"] = 100.0
        task["candidate_economics"] = economics
        records = [
            self.adaptive_cluster(
                task["matching_spec"], effort, index,
                repaired=effort == "low" and index == 15,
            )
            for effort in ("low", "medium", "high")
            for index in range(16)
        ]
        selected = ROUTING.select_adaptive_route(
            task, verified_evidence_pool=self.bound_adaptive_pool(records)
        )
        evaluations = {item["effort"]: item for item in selected["candidate_evaluations"]}
        self.assertEqual(evaluations["low"]["status"], "QUALITY_GATE_FAILED")
        self.assertEqual(evaluations["medium"]["status"], "TIME_GATE_FAILED")
        self.assertEqual((selected["candidate"], selected["effort"]), ("S3", "high"))

        no_economics = dict(task)
        no_economics.pop("candidate_economics")
        unknown = ROUTING.select_adaptive_route(
            no_economics, verified_evidence_pool=self.bound_adaptive_pool(records)
        )
        self.assertEqual((unknown["candidate"], unknown["evidence_status"]), ("S0", "UNKNOWN"))
        self.assertTrue(all(
            item["status"] == "ECONOMICS_UNKNOWN"
            for item in unknown["candidate_evaluations"]
            if item["semantic_clusters"] and item["status"] != "QUALITY_GATE_FAILED"
        ))

        high_only = [record for record in records if record["effort"] == "high"]
        no_comparator = ROUTING.select_adaptive_route(
            task, verified_evidence_pool=self.bound_adaptive_pool(high_only)
        )
        high = next(item for item in no_comparator["candidate_evaluations"] if item["effort"] == "high")
        self.assertEqual(high["status"], "HIGH_COMPARATOR_MISSING")
        self.assertEqual(no_comparator["candidate"], "S0")

    def test_cross_instance_allows_low_only_economics_with_shared_baseline(self) -> None:
        task = self.adaptive_cross_instance_task()
        task["candidate_economics"] = [
            item for item in task["candidate_economics"] if item["effort"] == "low"
        ]
        records = [
            self.adaptive_cluster(task["matching_spec"], "low", index)
            for index in range(16)
        ]
        selected = ROUTING.select_adaptive_route(
            task, verified_evidence_pool=self.bound_adaptive_pool(records)
        )
        self.assertEqual((selected["candidate"], selected["effort"]), ("S1", "low"))
        evaluations = {item["effort"]: item for item in selected["candidate_evaluations"]}
        self.assertEqual(evaluations["medium"]["status"], "EVIDENCE_UNKNOWN")
        self.assertEqual(evaluations["high"]["status"], "EVIDENCE_UNKNOWN")

        malformed = dict(task)
        malformed["candidate_economics"] = [
            dict(task["candidate_economics"][0], baseline_credits=100.0)
        ]
        with self.assertRaisesRegex(ROUTING.PolicyError, "unknown fields"):
            ROUTING.select_adaptive_route(
                malformed, verified_evidence_pool=self.bound_adaptive_pool(records)
            )

        no_baseline = dict(task)
        no_baseline.pop("baseline_economics")
        unknown = ROUTING.select_adaptive_route(
            no_baseline, verified_evidence_pool=self.bound_adaptive_pool(records)
        )
        low = next(
            item for item in unknown["candidate_evaluations"] if item["effort"] == "low"
        )
        self.assertEqual((unknown["candidate"], low["status"]), ("S0", "ECONOMICS_UNKNOWN"))

    def test_cross_instance_repaired_successes_do_not_count_as_first_pass(self) -> None:
        task = self.adaptive_cross_instance_task()
        task["candidate_economics"] = [
            item for item in task["candidate_economics"] if item["effort"] == "low"
        ]
        records = [
            self.adaptive_cluster(
                task["matching_spec"], "low", index, passed=False, repaired=True,
            )
            for index in range(16)
        ]
        selected = ROUTING.select_adaptive_route(
            task, verified_evidence_pool=self.bound_adaptive_pool(records)
        )
        low = next(
            item for item in selected["candidate_evaluations"] if item["effort"] == "low"
        )
        self.assertEqual(
            (
                low["first_pass_accepted_clusters"],
                low["final_accepted_clusters"],
                low["repair_observed_clusters"],
            ),
            (0, 16, 16),
        )
        self.assertEqual(low["status"], "QUALITY_GATE_FAILED")
        self.assertNotIn("failure_probability_bound", low)
        self.assertEqual(selected["candidate"], "S0")

        excessive = [dict(record) for record in records]
        excessive[0] = dict(
            excessive[0], members=[dict(member) for member in excessive[0]["members"]],
        )
        excessive[0]["members"][0]["repair_attempts"] = 2
        with self.assertRaisesRegex(ROUTING.PolicyError, "repair policy"):
            ROUTING.select_adaptive_route(
                task, verified_evidence_pool=self.bound_adaptive_pool(excessive)
            )

    def test_legacy_adaptive_entry_remains_compatible(self) -> None:
        task = self.adaptive_task()
        expected = ROUTING.select_adaptive_route(task, evidence=self.adaptive_evidence(task, "low"))
        self.assertEqual((expected["candidate"], expected["effort"]), ("S1", "low"))
        self.assertNotIn("candidate_evaluations", expected)

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

    def test_schema6_uses_conservative_quality_bound_at_original_entry(self) -> None:
        for accepted, observations in ((1, 1), (2, 2)):
            source, evidence = schema6_request(first_pass_accepted=accepted, observations=observations)
            result = ROUTING.evaluate_route(source, POLICY, verified_quality_evidence=bound_quality(source, evidence))
            self.assertEqual(result["route"], "SOL_ONLY")
            selected = result["candidates"][0]
            self.assertEqual(selected["first_pass_probability"], ROUTING.wilson_lower_bound(accepted, observations))
            self.assertEqual(selected["first_pass_probability_empirical"], 1.0)
            self.assertEqual(selected["first_pass_wilson_lower_bound_95"], selected["first_pass_probability"])
            self.assertLess(selected["first_pass_probability"], 0.8)
        source, evidence = schema6_request(first_pass_accepted=16, observations=16)
        result = ROUTING.evaluate_route(source, POLICY, verified_quality_evidence=bound_quality(source, evidence))
        selected = result["candidates"][0]
        self.assertEqual(result["route"], "SOL_LUNA")
        self.assertEqual(selected["first_pass_probability"], ROUTING.wilson_lower_bound(16, 16))
        self.assertGreaterEqual(selected["first_pass_probability"], 0.8)
        self.assertEqual(selected["first_pass_probability_empirical"], 1.0)

    def test_adaptive_production_economics_is_hard_for_low_and_high(self) -> None:
        task = self.adaptive_task()
        evidence = {"effort": "low", "status": "MATCHED_EXPERIENCE", "lower_effort_comparator": False,
                    "task_family": "adaptive-demo", "input_modalities": ["text"], "output_kind": "code",
                    "acceptance_kind": "deterministic", "distribution_id": "same-distribution-v1",
                    "acceptance_suite_digest": "sha256:" + "0" * 64, "observations": 16, "first_pass_accepted": 16}
        bad = dict(task, economics=dict(task["economics"], baseline_credits=10, execution_credits=100))
        self.assertEqual(ROUTING.select_adaptive_route(bad, evidence=evidence)["candidate"], "S0")
        high_evidence = dict(evidence, effort="high", lower_effort_comparator=True)
        high = dict(task, risk="medium", economics=dict(task["economics"], baseline_credits=10, execution_credits=100))
        self.assertEqual(ROUTING.select_adaptive_route(high, evidence=high_evidence)["candidate"], "S0")

    def test_adaptive_ui_binds_luna_implementation_to_sol_visual_acceptance(self) -> None:
        task = self.adaptive_task(
            required_input_modalities=["screenshot"], output_kind="document", coupling="medium",
            acceptance={"kind": "mixed_review", "independent": True, "closed": True,
                        "verification_cost": "medium", "suite_digest": "sha256:" + "0" * 64},
            required_tool_capabilities=[
                {"name": "writer", "status": "host-observed", "source": "host-observed", "operation": "implementation", "actor": "LUNA", "surface": "filesystem"},
                {"name": "browser", "status": "host-observed", "source": "host-observed", "operation": "browser_render", "actor": "SOL", "surface": "browser"},
                {"name": "visual", "status": "host-observed", "source": "host-observed", "operation": "visual_review", "actor": "SOL", "surface": "browser"},
            ],
        )
        evidence = {"effort": "medium", "status": "MATCHED_EXPERIENCE", "lower_effort_comparator": False,
                    "task_family": "adaptive-demo", "input_modalities": ["screenshot"], "output_kind": "document",
                    "acceptance_kind": "mixed_review", "distribution_id": "same-distribution-v1",
                    "acceptance_suite_digest": "sha256:" + "0" * 64, "observations": 16, "first_pass_accepted": 16}
        result = ROUTING.select_adaptive_route(task, evidence=evidence)
        self.assertEqual(result["candidate"], "S2")
        self.assertEqual(result["responsibilities"]["implementer"], "LUNA")
        self.assertEqual(result["responsibilities"]["visual_document_reviewer"], "SOL")
        self.assertEqual(sum(item["operation"] == "visual_review" for item in result["required_tools"]), 1)

        bad = dict(task, required_tool_capabilities=[
            dict(item, operation="test_execution") for item in task["required_tool_capabilities"]
        ])
        bad_result = ROUTING.select_adaptive_route(bad, evidence=evidence)
        self.assertEqual(bad_result["candidate"], "S0")
        self.assertEqual(bad_result["reason_code"], "required_operation_capability_missing")
        self.assertEqual(bad_result["responsibilities"]["visual_document_reviewer"], "SOL")
        self.assertTrue(all(item["actor"] == "SOL" for item in bad_result["responsibilities"]["capability_bindings"]))

    def test_adaptive_static_image_review_does_not_require_browser_render(self) -> None:
        task = self.adaptive_task(
            required_input_modalities=["image"], output_kind="text",
            acceptance={"kind": "visual_review", "independent": True, "closed": True,
                        "verification_cost": "low", "suite_digest": "sha256:" + "0" * 64},
            required_tool_capabilities=[
                {"name": "writer", "status": "host-observed", "source": "host-observed", "operation": "implementation", "actor": "LUNA", "surface": "filesystem"},
                {"name": "image-view", "status": "host-observed", "source": "host-observed", "operation": "visual_review", "actor": "SOL", "surface": "view_image"},
            ],
        )
        evidence = {"effort": "low", "status": "MATCHED_EXPERIENCE", "lower_effort_comparator": False,
                    "task_family": "adaptive-demo", "input_modalities": ["image"], "output_kind": "text",
                    "acceptance_kind": "visual_review", "distribution_id": "same-distribution-v1",
                    "acceptance_suite_digest": "sha256:" + "0" * 64, "observations": 16, "first_pass_accepted": 16}
        result = ROUTING.select_adaptive_route(task, evidence=evidence)
        self.assertEqual((result["candidate"], result["route"]), ("S1", "SOL_LUNA"))
        self.assertNotIn("browser_render", {item["operation"] for item in result["required_tools"]})

    def test_adaptive_coordination_number_is_not_an_effort_or_rejection_threshold(self) -> None:
        evidence = {"effort": "low", "status": "MATCHED_EXPERIENCE", "lower_effort_comparator": False,
                    "task_family": "adaptive-demo", "input_modalities": ["text"], "output_kind": "code",
                    "acceptance_kind": "deterministic", "distribution_id": "same-distribution-v1",
                    "acceptance_suite_digest": "sha256:" + "0" * 64, "observations": 16, "first_pass_accepted": 16}
        result = ROUTING.select_adaptive_route(self.adaptive_task(coordination_overhead=1000), evidence=evidence)
        self.assertEqual((result["candidate"], result["effort"]), ("S1", "low"))

    def test_adaptive_cold_start_requires_time_improvement(self) -> None:
        constraints = {key: True for key in (
            "architecture_settled", "deterministic_acceptance", "low_risk", "low_coupling",
            "complete_luna_ownership", "exclusive_write", "single_writer", "sol_queue_empty",
        )}
        economics = {"baseline_credits": 10, "launch_credits": 2, "overhead_credits": 2,
                     "recovery_credits": 1, "failure_probability": 0,
                     "baseline_seconds": 25, "launch_seconds": 20, "overhead_seconds": 5,
                     "recovery_seconds": 1}
        result = ROUTING.select_adaptive_route(self.adaptive_task(
            cold_start=True, cold_start_constraints=constraints, economics=economics,
        ))
        self.assertEqual((result["candidate"], result["reason_code"]), ("S0", "cold_start_economics_fail"))

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

    def test_schema8_bounded_cold_start_uses_worst_case_without_quality_index(self) -> None:
        source = schema8_request()
        before = json.loads(json.dumps(source))
        result = evaluate_schema8(source)
        self.assertEqual(source, before)
        self.assertEqual(result["route"], "SOL_LUNA")
        self.assertEqual(result["selected_luna_effort"], "medium")
        self.assertEqual(
            result["quality_gate_basis"],
            "deterministic acceptance plus worst-case repair and terminal recovery",
        )
        selected = result["candidates"][0]
        self.assertEqual(selected["quality_evidence_source"], "bounded-cold-start-worst-case")
        self.assertIsNone(selected["first_pass_probability"])
        self.assertIsNone(selected["final_defect_probability"])
        self.assertEqual(selected["expected_accepted_credits"], 48.0)
        self.assertEqual(selected["expected_accepted_seconds"], 947.0)
        self.assertFalse(result["automatic_execution_allowed"])

    def test_schema8_cli_template_is_evaluable_without_quality_index(self) -> None:
        manifest = schema8_manifest()
        source = ROUTING.cold_start_template(manifest)
        self.assertEqual(source["schema_version"], 8)
        self.assertNotIn("quality_evidence_id", source["luna_candidates"][0])
        result = evaluate_schema8(source, manifest)
        self.assertIn(result["route"], {"SOL_ONLY", "SOL_LUNA"})
        self.assertEqual(result["quality_gate_basis"], "deterministic acceptance plus worst-case repair and terminal recovery")
        self.assertIn("Sol must approve", result["cold_start_trust_boundary"])

    def test_schema8_loader_binds_manifest_ids_content_and_request(self) -> None:
        source = schema8_request()
        manifest = schema8_manifest(source["acceptance_contract_ids"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "acceptance.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            evidence = ROUTING.load_cold_start_evidence(path, request=source)
            result = ROUTING.evaluate_route(
                source,
                POLICY,
                verified_cold_start_evidence=evidence,
            )
            self.assertEqual(result["route"], "SOL_LUNA")

            changed = json.loads(json.dumps(source))
            changed["coordination"]["sol_review"]["credits"] += 1
            with self.assertRaisesRegex(ROUTING.PolicyError, "route request changed after manifest binding"):
                ROUTING.evaluate_route(
                    changed,
                    POLICY,
                    verified_cold_start_evidence=evidence,
                )

            manifest["acceptance_contracts"][0]["command"].append("--changed")
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ROUTING.PolicyError, "manifest changed after binding"):
                ROUTING.evaluate_route(
                    source,
                    POLICY,
                    verified_cold_start_evidence=evidence,
                )

    def test_schema8_rejects_missing_plain_malformed_or_mismatched_manifest(self) -> None:
        source = schema8_request()
        with self.assertRaisesRegex(ROUTING.PolicyError, "externally loaded frozen acceptance manifest"):
            ROUTING.evaluate_route(source, POLICY)
        with self.assertRaisesRegex(ROUTING.PolicyError, "externally loaded frozen acceptance manifest"):
            ROUTING.evaluate_route(
                source,
                POLICY,
                verified_cold_start_evidence=dict(bound_cold_start(source)),
            )

        malformed = schema8_manifest(source["acceptance_contract_ids"])
        malformed["acceptance_contracts"][0].pop("expected_signal")
        mismatched = schema8_manifest([source["acceptance_contract_ids"][0]])
        with tempfile.TemporaryDirectory() as directory:
            malformed_path = Path(directory) / "malformed.json"
            malformed_path.write_text(json.dumps(malformed), encoding="utf-8")
            with self.assertRaisesRegex(ROUTING.PolicyError, "must contain acceptance_id"):
                ROUTING.load_cold_start_evidence(malformed_path, request=source)

            mismatch_path = Path(directory) / "mismatch.json"
            mismatch_path.write_text(json.dumps(mismatched), encoding="utf-8")
            evidence = ROUTING.load_cold_start_evidence(mismatch_path, request=source)
            with self.assertRaisesRegex(ROUTING.PolicyError, "contract IDs do not match request"):
                ROUTING.evaluate_route(
                    source,
                    POLICY,
                    verified_cold_start_evidence=evidence,
                )

    def test_schema8_cli_rejects_surrogate_manifest_without_traceback(self) -> None:
        raw_manifest = (
            '{"schema_version":1,"task_family":"bounded-feature",'
            '"acceptance_contracts":[{"acceptance_id":"accept-core",'
            '"command":["python","-m","unittest"],'
            '"expected_signal":"\\ud800"}]}'
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "surrogate.json"
            path.write_text(raw_manifest, encoding="utf-8")
            stderr = io.StringIO()
            with mock.patch.object(
                sys,
                "argv",
                ["routing_policy.py", "cold-start-template", "--acceptance-manifest", str(path)],
            ), redirect_stderr(stderr):
                self.assertEqual(ROUTING.main(), 2)
        self.assertIn("must be a non-empty single-line string", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_schema8_rejects_zero_costs_and_multiple_candidates(self) -> None:
        for field in (
            "execution_credits", "execution_seconds", "repair_credits",
            "repair_seconds", "terminal_recovery_credits", "terminal_recovery_seconds",
        ):
            source = schema8_request()
            source["luna_candidates"][0]["packages"][0][field] = 0
            with self.subTest(field=field), self.assertRaisesRegex(
                ROUTING.PolicyError, "must be positive for schema 8"
            ):
                evaluate_schema8(source)

        source = schema8_request()
        second = json.loads(json.dumps(source["luna_candidates"][0]))
        second["allocation_id"] = "allocation-second"
        source["luna_candidates"].append(second)
        result = evaluate_schema8(source)
        self.assertEqual(result["route"], "SOL_ONLY")
        self.assertTrue(all(
            "cold_start_requires_single_candidate" in candidate["rejection_reasons"]
            for candidate in result["candidates"]
        ))

    def test_schema8_worst_case_cost_and_time_are_hard_gates(self) -> None:
        cost = schema8_request()
        cost["luna_candidates"][0]["packages"][0]["repair_credits"] += 3
        cost_result = evaluate_schema8(cost)
        self.assertEqual(cost_result["route"], "SOL_ONLY")
        self.assertIn(
            "expected_credit_savings_below_floor",
            cost_result["candidates"][0]["rejection_reasons"],
        )

        elapsed = schema8_request()
        elapsed["luna_candidates"][0]["packages"][0]["terminal_recovery_seconds"] += 100
        elapsed_result = evaluate_schema8(elapsed)
        self.assertEqual(elapsed_result["route"], "SOL_ONLY")
        self.assertIn(
            "expected_elapsed_time_regresses",
            elapsed_result["candidates"][0]["rejection_reasons"],
        )

    def test_schema8_upstream_recovery_reexecutes_downstream_closure(self) -> None:
        source = schema8_request()
        packages = source["luna_candidates"][0]["packages"]
        upstream, downstream = packages
        downstream["depends_on"] = [upstream["package_id"]]
        base = evaluate_schema8(source)["candidates"][0]
        downstream_execution_credits = downstream["execution_credits"]
        downstream_execution_seconds = downstream["execution_seconds"]
        self.assertEqual(
            base["expected_recovery_credits"],
            4 + 2 * downstream_execution_credits,
        )
        self.assertEqual(
            base["expected_recovery_seconds"],
            20 + 2 * downstream_execution_seconds,
        )
        self.assertIn(
            "expected_credit_savings_below_floor",
            base["rejection_reasons"],
        )

    def test_schema8_optimistic_probabilities_cannot_reduce_worst_case(self) -> None:
        optimistic = schema8_request()
        pessimistic = schema8_request()
        for package_item in pessimistic["luna_candidates"][0]["packages"]:
            package_item["first_pass_probability"] = 0.0
            package_item["repair_probability"] = 1.0
            package_item["final_defect_probability"] = 1.0
        optimistic_result = evaluate_schema8(optimistic)["candidates"][0]
        pessimistic_result = evaluate_schema8(pessimistic)["candidates"][0]
        self.assertEqual(
            optimistic_result["expected_accepted_credits"],
            pessimistic_result["expected_accepted_credits"],
        )
        self.assertEqual(
            optimistic_result["expected_accepted_seconds"],
            pessimistic_result["expected_accepted_seconds"],
        )

    def test_schema8_rejects_nonbounded_exploration_shapes(self) -> None:
        cases = []
        nondeterministic = schema8_request()
        nondeterministic["reasoning_profile"]["deterministic_acceptance"] = False
        cases.append((nondeterministic, "cold_start_requires_low_risk_reasoning_profile"))
        high_effort = schema8_request()
        high_effort["luna_candidates"][0]["effort"] = "high"
        cases.append((high_effort, "cold_start_effort_above_medium"))
        medium_impact = schema8_request()
        medium_impact["luna_candidates"][0]["failure_impact"] = "medium"
        cases.append((medium_impact, "cold_start_requires_low_failure_impact"))
        mixed = schema8_request()
        mixed["luna_candidates"][0]["packages"][0]["executor"] = "SOL"
        cases.append((mixed, "cold_start_requires_complete_luna_allocation"))
        multiwriter = schema8_request()
        multiwriter["requested_writers"] = 2
        cases.append((multiwriter, "cold_start_requires_single_writer"))
        queued = schema8_request()
        queued["luna_candidates"][0]["sol_controller_queue"]["acceptance_items"] = 1
        cases.append((queued, "cold_start_requires_empty_controller_queue"))
        for source, reason in cases:
            with self.subTest(reason=reason):
                result = evaluate_schema8(source)
                self.assertEqual(result["route"], "SOL_ONLY")
                self.assertIn(reason, result["candidates"][0]["rejection_reasons"])

    def test_schema8_cannot_accept_external_quality_index(self) -> None:
        source = schema8_request()
        schema7, evidence = schema7_request()
        with self.assertRaisesRegex(ROUTING.PolicyError, "requires routing schema 6 or 7"):
            ROUTING.evaluate_route(
                source,
                POLICY,
                verified_quality_evidence=bound_quality(schema7, evidence),
                verified_cold_start_evidence=bound_cold_start(source),
            )


if __name__ == "__main__":
    unittest.main()
