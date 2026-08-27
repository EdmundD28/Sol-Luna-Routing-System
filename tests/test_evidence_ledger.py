from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "evidence_ledger.py"
SPEC = importlib.util.spec_from_file_location("evidence_ledger", SCRIPT)
assert SPEC and SPEC.loader
LEDGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LEDGER)


def accepted_record(route: str, pair_id: str, *, tokens: int, suite: str = "hidden-v1") -> dict:
    return {
        "run_ref": f"private-{pair_id}-{route}",
        "task_family": "bounded-feature",
        "pair_id": pair_id,
        "route": route,
        "outcome": "ACCEPTED",
        "independent_acceptance": "PASSED",
        "acceptance_suite_id": suite,
        "final_candidate_ref": f"git:{pair_id}-{route.lower()}",
        "first_pass_accepted": True,
        "repair_rounds": 0,
        "defects": 0,
        "elapsed_seconds": 100 if route == "SOL_ONLY" else 80,
        "total_tokens": tokens,
        "token_source": "codex-session-log-v1",
        "token_uncertainty": "local diagnostic record, not billing",
    }


def accepted_credit_record(
    route: str,
    pair_id: str,
    *,
    credit_kind: str = "exact",
    first_pass: bool = True,
) -> dict:
    record = accepted_record(route, pair_id, tokens=1)
    for field in ("total_tokens", "token_source", "token_uncertainty"):
        record.pop(field)
    value = 100 if route == "SOL_ONLY" else 80
    record.update(
        {
            "first_pass_accepted": first_pass,
            "credit_value": value,
            "credit_kind": credit_kind,
            "credit_source": "provider-export-v1",
            "credit_uncertainty": "none",
            "phase_credits": {"sol_execution": value}
            if route == "SOL_ONLY"
            else {"sol_planning": 10, "luna_execution": 60, "sol_review": 10},
        }
    )
    return record


def verified_credit_record(route: str, pair_id: str, *, digest_suffix: str = "a") -> dict:
    record = accepted_credit_record(route, pair_id)
    record.update(
        {
            "credit_verification": "PROVIDER_AUTHENTICATED",
            "credit_receipt_ref": f"receipt-{pair_id}-{route.lower()}",
            "credit_receipt_digest": "sha256:" + digest_suffix * 64,
            "billing_window_id": "window-2026-08",
        }
    )
    return record


def verified_claim(record: dict) -> dict:
    claim = {
        "record_id": record["record_id"],
        "record_digest": LEDGER.record_binding_digest(record),
        "task_family": record["task_family"],
        "route": record["route"],
        "pair_id": record["pair_id"],
        "policy_identity": record.get("policy_fingerprint")
        or record.get("policy_version")
        or "legacy-policy",
        "acceptance_suite_identity": record.get("acceptance_suite_digest")
        or record["acceptance_suite_id"],
        "credit_value": record["credit_value"],
        "credit_source": record["credit_source"],
        "credit_uncertainty": record["credit_uncertainty"],
        "billing_window_id": record["billing_window_id"],
        "credit_receipt_ref": record["credit_receipt_ref"],
        "receipt_digest": record["credit_receipt_digest"],
        "runtime_identity_source": record.get("runtime_identity_source", ""),
        "runtime_identity_uncertainty": record.get("runtime_identity_uncertainty", ""),
        "observed_sol_model": record.get("observed_sol_model", ""),
        "observed_luna_model": record.get("observed_luna_model", ""),
    }
    claim["claim_digest"] = LEDGER._canonical_claim_digest(claim)
    return claim


def verified_index(records: list[dict]) -> dict:
    return {
        "schema_version": 2,
        "verification_source": "provider-export-review-v1",
        "claims": [verified_claim(record) for record in records],
    }


class EvidenceLedgerTests(unittest.TestCase):
    def test_append_redacts_run_ref_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.jsonl"
            record = accepted_record("SOL_ONLY", "pair-001", tokens=1000)
            written = LEDGER.append_record(
                path,
                record,
                now=datetime(2026, 8, 26, tzinfo=timezone.utc),
            )
            self.assertTrue(written["run_ref"].startswith("redacted:run:"))
            loaded = LEDGER.load_records(path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["recorded_at"], "2026-08-26T00:00:00+00:00")
            self.assertTrue(loaded[0]["record_id"].startswith("record:"))

    def test_duplicate_append_is_rejected_without_corrupting_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.jsonl"
            record = accepted_record("SOL_ONLY", "pair-001", tokens=1000)
            LEDGER.append_record(path, record)
            with self.assertRaises(LEDGER.LedgerError):
                LEDGER.append_record(path, record)
            self.assertEqual(len(LEDGER.load_records(path)), 1)

    def test_receipt_digest_cannot_be_reused_by_multiple_ledger_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.jsonl"
            first = verified_credit_record("SOL_ONLY", "pair-001")
            LEDGER.append_record(path, first)
            second = verified_credit_record("SOL_LUNA", "pair-001", digest_suffix="a")
            with self.assertRaisesRegex(LEDGER.LedgerError, "duplicate credit_receipt_digest"):
                LEDGER.append_record(path, second)

    def test_concurrent_appends_are_serialized_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.jsonl"
            errors = []

            def append(index: int) -> None:
                try:
                    record = accepted_record("SOL_ONLY", f"pair-{index:03d}", tokens=1000 + index)
                    LEDGER.append_record(path, record)
                except Exception as exc:  # pragma: no cover - asserted below
                    errors.append(exc)

            threads = [threading.Thread(target=append, args=(index,)) for index in range(1, 11)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            self.assertEqual(len(LEDGER.load_records(path)), 10)

    def test_unsupported_sensitive_fields_are_rejected(self) -> None:
        record = accepted_record("SOL_ONLY", "pair-001", tokens=1000)
        record["raw_prompt"] = "private prompt"
        with self.assertRaises(LEDGER.LedgerError):
            LEDGER.validate_record(record)

    def test_accepted_requires_independent_acceptance(self) -> None:
        record = accepted_record("SOL_ONLY", "pair-001", tokens=1000)
        record["independent_acceptance"] = "NOT_RUN"
        with self.assertRaises(LEDGER.LedgerError):
            LEDGER.validate_record(record)

    def test_failed_and_blocked_are_distinct_contracts(self) -> None:
        failed = {
            "run_ref": "failed-1",
            "task_family": "bounded-feature",
            "route": "SOL_LUNA",
            "outcome": "FAILED",
            "independent_acceptance": "FAILED",
            "repair_rounds": 1,
            "defects": 1,
            "failure_class": "verification",
        }
        self.assertEqual(LEDGER.validate_record(failed)["outcome"], "FAILED")
        blocked = dict(failed, run_ref="blocked-1", outcome="BLOCKED")
        with self.assertRaises(LEDGER.LedgerError):
            LEDGER.validate_record(blocked)
        blocked["blocker"] = "Requires a user-owned product decision"
        blocked["failure_class"] = "permission_or_authority"
        self.assertEqual(LEDGER.validate_record(blocked)["outcome"], "BLOCKED")

    def test_second_repair_requires_new_evidence_and_reason(self) -> None:
        record = accepted_record("SOL_LUNA", "pair-001", tokens=900)
        record["repair_rounds"] = 2
        with self.assertRaises(LEDGER.LedgerError):
            LEDGER.validate_record(record)
        record["extra_repair_basis"] = "New failing boundary case makes a second focused repair cheaper than reassignment"
        record["new_evidence_ref"] = "test:boundary-17"
        self.assertEqual(LEDGER.validate_record(record)["repair_rounds"], 2)

    def test_four_pairs_are_insufficient_and_five_only_enable_human_review(self) -> None:
        records = []
        for index in range(1, 6):
            pair_id = f"pair-{index:03d}"
            records.extend(
                [
                    LEDGER.validate_record(accepted_record("SOL_ONLY", pair_id, tokens=1000 + index)),
                    LEDGER.validate_record(accepted_record("SOL_LUNA", pair_id, tokens=800 + index)),
                ]
            )
        four = LEDGER.evidence_status(records[:8], task_family="bounded-feature")
        self.assertEqual(four["status"], "insufficient_evidence")
        self.assertFalse(four["automatic_routing_allowed"])
        five = LEDGER.evidence_status(records, task_family="bounded-feature")
        self.assertEqual(five["status"], "eligible_for_human_review")
        self.assertFalse(five["automatic_routing_allowed"])
        self.assertNotIn("recommended_route", json.dumps(five))

    def test_mismatched_acceptance_suite_does_not_count(self) -> None:
        records = [
            LEDGER.validate_record(accepted_record("SOL_ONLY", "pair-001", tokens=1000, suite="hidden-v1")),
            LEDGER.validate_record(accepted_record("SOL_LUNA", "pair-001", tokens=800, suite="hidden-v2")),
        ]
        status = LEDGER.evidence_status(records, task_family="bounded-feature")
        self.assertEqual(status["qualified_matched_pairs"], 0)
        self.assertEqual(status["rejected_pair_reasons"]["acceptance_suite_id_mismatch"], 1)

    def test_metric_kinds_are_partitioned_into_separate_cohorts(self) -> None:
        records = []
        for index in range(1, 5):
            pair_id = f"pair-{index:03d}"
            records.extend(
                [
                    LEDGER.validate_record(accepted_record("SOL_ONLY", pair_id, tokens=1000)),
                    LEDGER.validate_record(accepted_record("SOL_LUNA", pair_id, tokens=800)),
                ]
            )
        for route in ("SOL_ONLY", "SOL_LUNA"):
            record = accepted_record(route, "pair-005", tokens=1)
            record.pop("total_tokens")
            record.pop("token_source")
            record.pop("token_uncertainty")
            record.update(
                {
                    "credit_value": 100 if route == "SOL_ONLY" else 80,
                    "credit_kind": "exact",
                    "credit_source": "provider-export-v1",
                    "credit_uncertainty": "none",
                }
            )
            records.append(LEDGER.validate_record(record))
        status = LEDGER.evidence_status(records, task_family="bounded-feature")
        self.assertEqual(status["qualified_matched_pairs"], 5)
        self.assertEqual(status["largest_cohort_pairs"], 4)
        self.assertEqual(status["status"], "insufficient_evidence")

    def test_phase_totals_must_reconcile_with_record_totals(self) -> None:
        record = accepted_record("SOL_LUNA", "pair-001", tokens=900)
        record["phase_tokens"] = {"sol_planning": 100, "luna_execution": 700}
        with self.assertRaises(LEDGER.LedgerError):
            LEDGER.validate_record(record)
        failed = accepted_record("SOL_LUNA", "pair-002", tokens=900)
        failed.update({"outcome": "FAILED", "failure_class": "verification"})
        with self.assertRaisesRegex(LEDGER.LedgerError, "FAILED requires"):
            LEDGER.validate_record(failed)
        record["phase_tokens"]["sol_review"] = 100
        self.assertEqual(LEDGER.validate_record(record)["phase_tokens"]["luna_execution"], 700)
        record["phase_elapsed_seconds"] = {"luna_execution": 99}
        with self.assertRaisesRegex(LEDGER.LedgerError, "phase duration"):
            LEDGER.validate_record(record)
        record["elapsed_seconds"] = 100
        record["phase_elapsed_seconds"] = {"sol_planning": 60, "luna_execution": 80}
        self.assertEqual(LEDGER.validate_record(record)["elapsed_seconds"], 100)

    def test_matched_records_require_first_pass_and_elapsed_evidence(self) -> None:
        record = accepted_record("SOL_LUNA", "pair-001", tokens=900)
        record.update(
            {
                "campaign_id": "campaign-v1",
                "evaluation_mode": "MATCHED",
                "acceptance_suite_digest": "sha256:" + "1" * 64,
                "task_spec_digest": "sha256:" + "2" * 64,
                "starting_candidate_ref": "git:start",
                "policy_version": "1.1.0",
                "policy_fingerprint": "sha256:" + "3" * 64,
                "luna_effort": "high",
                "phase_elapsed_seconds": {
                    "sol_retained_execution": 0,
                    "luna_execution": 80,
                },
                "observed_sol_model": "gpt-5.6-sol",
                "observed_luna_model": "gpt-5.6-luna",
                "runtime_identity_source": "codex-session-turn-context-v1",
                "runtime_identity_uncertainty": "none",
            }
        )
        record.pop("first_pass_accepted")
        with self.assertRaises(LEDGER.LedgerError):
            LEDGER.validate_record(record)

    def test_matched_runtime_identity_and_sol_execution_are_fail_closed(self) -> None:
        record = accepted_record("SOL_ONLY", "pair-001", tokens=900)
        record.update(
            {
                "campaign_id": "campaign-v1",
                "evaluation_mode": "MATCHED",
                "acceptance_suite_digest": "sha256:" + "1" * 64,
                "task_spec_digest": "sha256:" + "2" * 64,
                "starting_candidate_ref": "git:start",
                "policy_version": "1.1.0",
                "policy_fingerprint": "sha256:" + "3" * 64,
                "phase_elapsed_seconds": {"sol_execution": 100},
                "phase_tokens": {"sol_execution": 900},
                "observed_sol_model": "gpt-5.6-sol",
                "observed_luna_model": "",
                "runtime_identity_source": "codex-session-turn-context-v1",
                "runtime_identity_uncertainty": "none",
            }
        )
        self.assertEqual(LEDGER.validate_record(record)["phase_tokens"]["sol_execution"], 900)
        record["phase_elapsed_seconds"] = {"sol_planning": 100}
        with self.assertRaisesRegex(LEDGER.LedgerError, "sol_execution"):
            LEDGER.validate_record(record)
        record["phase_elapsed_seconds"] = {"sol_execution": 100}
        record["observed_sol_model"] = "gpt-5.6-luna"
        with self.assertRaisesRegex(LEDGER.LedgerError, "observed_sol_model"):
            LEDGER.validate_record(record)
        record["first_pass_accepted"] = True
        record.pop("elapsed_seconds")
        with self.assertRaises(LEDGER.LedgerError):
            LEDGER.validate_record(record)

    def test_matched_sol_luna_requires_retained_sol_phase_even_when_zero(self) -> None:
        record = accepted_record("SOL_LUNA", "pair-001", tokens=900)
        record.update(
            {
                "campaign_id": "campaign-v1",
                "evaluation_mode": "MATCHED",
                "acceptance_suite_digest": "sha256:" + "1" * 64,
                "task_spec_digest": "sha256:" + "2" * 64,
                "starting_candidate_ref": "git:start",
                "policy_version": "1.3.0",
                "policy_fingerprint": "sha256:" + "3" * 64,
                "luna_effort": "medium",
                "writer_count": 1,
                "phase_elapsed_seconds": {
                    "sol_retained_execution": 0,
                    "luna_execution": 80,
                },
                "phase_tokens": {
                    "sol_retained_execution": 100,
                    "luna_execution": 800,
                },
                "observed_sol_model": "gpt-5.6-sol",
                "observed_luna_model": "gpt-5.6-luna",
                "runtime_identity_source": "codex-session-turn-context-v1",
                "runtime_identity_uncertainty": "none",
            }
        )
        self.assertIn(
            "sol_retained_execution",
            LEDGER.validate_record(record)["phase_elapsed_seconds"],
        )
        del record["phase_elapsed_seconds"]["sol_retained_execution"]
        with self.assertRaisesRegex(LEDGER.LedgerError, "sol_retained_execution"):
            LEDGER.validate_record(record)

    def test_only_credible_credit_can_satisfy_policy_savings_gate(self) -> None:
        token_records = []
        displayed_records = []
        estimated_records = []
        exact_records = []
        for index in range(1, 6):
            pair_id = f"pair-{index:03d}"
            token_records.extend(
                [
                    LEDGER.validate_record(accepted_record("SOL_ONLY", pair_id, tokens=1000)),
                    LEDGER.validate_record(accepted_record("SOL_LUNA", pair_id, tokens=800)),
                ]
            )
            for route in ("SOL_ONLY", "SOL_LUNA"):
                displayed_records.append(
                    LEDGER.validate_record(
                        accepted_credit_record(route, pair_id, credit_kind="displayed_allowance_delta")
                    )
                )
                estimated_records.append(
                    LEDGER.validate_record(
                        accepted_credit_record(route, pair_id, credit_kind="estimated")
                    )
                )
                exact_records.append(LEDGER.validate_record(accepted_credit_record(route, pair_id)))
        token_gate = LEDGER.evidence_status(token_records, task_family="bounded-feature")["cohorts"][0]
        displayed_gate = LEDGER.evidence_status(displayed_records, task_family="bounded-feature")["cohorts"][0]
        estimated_gate = LEDGER.evidence_status(estimated_records, task_family="bounded-feature")["cohorts"][0]
        exact_gate = LEDGER.evidence_status(exact_records, task_family="bounded-feature")["cohorts"][0]
        self.assertFalse(token_gate["success_gates"]["credible_credit_reduction"])
        self.assertFalse(displayed_gate["success_gates"]["credible_credit_reduction"])
        self.assertFalse(estimated_gate["success_gates"]["credible_credit_reduction"])
        self.assertFalse(exact_gate["success_gates"]["credible_credit_reduction"])
        self.assertFalse(exact_gate["policy_change_eligible"])

    def test_exact_credits_take_precedence_when_token_diagnostics_are_also_present(self) -> None:
        records = []
        for index in range(1, 6):
            pair_id = f"pair-{index:03d}"
            for route in ("SOL_ONLY", "SOL_LUNA"):
                record = accepted_credit_record(route, pair_id)
                record.update(
                    {
                        "total_tokens": 1000 if route == "SOL_ONLY" else 2000,
                        "token_source": "codex-session-log-v1",
                        "token_uncertainty": "diagnostic only",
                    }
                )
                records.append(LEDGER.validate_record(record))
        cohort = LEDGER.evidence_status(records, task_family="bounded-feature")["cohorts"][0]
        self.assertEqual(cohort["cohort"]["metric"], "credit_value")
        self.assertFalse(cohort["policy_change_eligible"])

    def test_low_first_pass_rate_blocks_policy_eligibility(self) -> None:
        records = []
        for index in range(1, 6):
            pair_id = f"pair-{index:03d}"
            records.append(LEDGER.validate_record(accepted_credit_record("SOL_ONLY", pair_id)))
            records.append(
                LEDGER.validate_record(accepted_credit_record("SOL_LUNA", pair_id, first_pass=index <= 3))
            )
        cohort = LEDGER.evidence_status(records, task_family="bounded-feature")["cohorts"][0]
        self.assertEqual(cohort["first_pass_acceptance_rate"]["SOL_LUNA"], 0.6)
        self.assertFalse(cohort["success_gates"]["first_pass_acceptance_is_high_enough"])
        self.assertFalse(cohort["policy_change_eligible"])

    def test_failed_matched_arm_counts_against_acceptance_and_defect_gates(self) -> None:
        records = []
        for index in range(1, 6):
            pair_id = f"pair-{index:03d}"
            sol = accepted_credit_record("SOL_ONLY", pair_id)
            luna = accepted_credit_record("SOL_LUNA", pair_id)
            if index == 5:
                luna.update(
                    {
                        "outcome": "FAILED",
                        "independent_acceptance": "FAILED",
                        "first_pass_accepted": False,
                        "defects": 1,
                        "failure_class": "verification",
                    }
                )
            records.extend([LEDGER.validate_record(sol), LEDGER.validate_record(luna)])
        cohort = LEDGER.evidence_status(records, task_family="bounded-feature")["cohorts"][0]
        self.assertEqual(cohort["qualified_matched_pairs"], 5)
        self.assertEqual(cohort["independent_acceptance_rate"]["SOL_LUNA"], 0.8)
        self.assertEqual(cohort["final_defect_rate"]["SOL_LUNA"], 0.2)
        self.assertFalse(cohort["success_gates"]["independent_acceptance_equal_or_better"])
        self.assertFalse(cohort["success_gates"]["no_final_defect_regression"])
        self.assertFalse(cohort["policy_change_eligible"])

    def test_feedback_holds_sol_only_without_credible_credit_evidence(self) -> None:
        records = []
        for index in range(1, 6):
            pair_id = f"pair-{index:03d}"
            records.extend(
                [
                    LEDGER.validate_record(accepted_record("SOL_ONLY", pair_id, tokens=1000)),
                    LEDGER.validate_record(accepted_record("SOL_LUNA", pair_id, tokens=800)),
                ]
            )
        feedback = LEDGER.task_family_feedback(records, task_family="bounded-feature")
        self.assertEqual(feedback["posture"], "HOLD_SOL_ONLY")
        self.assertIn("credible_credit_reduction", feedback["reasons"])
        self.assertFalse(feedback["automatic_routing_allowed"])

    def test_feedback_exposes_only_evidence_backed_luna_efforts_for_review(self) -> None:
        records = []
        for index in range(1, 6):
            pair_id = f"pair-{index:03d}"
            sol = accepted_credit_record("SOL_ONLY", pair_id)
            luna = accepted_credit_record("SOL_LUNA", pair_id)
            luna["luna_effort"] = "xhigh"
            records.extend([LEDGER.validate_record(sol), LEDGER.validate_record(luna)])
        feedback = LEDGER.task_family_feedback(records, task_family="bounded-feature")
        self.assertEqual(feedback["posture"], "HOLD_SOL_ONLY")
        self.assertEqual(feedback["supported_luna_efforts"], [])
        self.assertFalse(feedback["human_policy_review_required"])
        self.assertFalse(feedback["automatic_routing_allowed"])

    def test_legacy_schema_records_are_read_as_unverified(self) -> None:
        record = accepted_credit_record("SOL_ONLY", "pair-001")
        record["schema_version"] = 1
        normalized = LEDGER.validate_record(record)
        self.assertEqual(normalized["schema_version"], 5)
        self.assertEqual(normalized["upgraded_from_schema_version"], 1)
        self.assertEqual(normalized["credit_verification"], "UNVERIFIED")

    def test_schema_four_matched_sol_luna_stays_readable_but_ineligible(self) -> None:
        records = []
        for index in range(1, 6):
            pair_id = f"pair-{index:03d}"
            for route in ("SOL_ONLY", "SOL_LUNA"):
                record = accepted_record(route, pair_id, tokens=1000 if route == "SOL_ONLY" else 800)
                record.update(
                    {
                        "schema_version": 4,
                        "campaign_id": "legacy-campaign",
                        "evaluation_mode": "MATCHED",
                        "acceptance_suite_digest": "sha256:" + "1" * 64,
                        "task_spec_digest": "sha256:" + "2" * 64,
                        "starting_candidate_ref": "git:legacy-start",
                        "policy_version": "1.2.0",
                        "policy_fingerprint": "sha256:" + "3" * 64,
                        "writer_count": 0 if route == "SOL_ONLY" else 1,
                        "luna_effort": "" if route == "SOL_ONLY" else "high",
                        "phase_elapsed_seconds": {"sol_execution": 100}
                        if route == "SOL_ONLY"
                        else {"luna_execution": 80},
                        "phase_tokens": {"sol_execution": 1000}
                        if route == "SOL_ONLY"
                        else {"luna_execution": 800},
                        "observed_sol_model": "gpt-5.6-sol",
                        "runtime_identity_source": "legacy-host-receipt",
                        "runtime_identity_uncertainty": "none",
                    }
                )
                if route == "SOL_LUNA":
                    record["observed_luna_model"] = "gpt-5.6-luna"
                records.append(LEDGER.validate_record(record))
        self.assertTrue(all(item["schema_version"] == 5 for item in records))
        self.assertTrue(all(item["upgraded_from_schema_version"] == 4 for item in records))
        self.assertEqual(
            LEDGER.validate_record(records[1])["upgraded_from_schema_version"],
            4,
        )
        status = LEDGER.evidence_status(records, task_family="bounded-feature")
        self.assertFalse(status["cohorts"][0]["success_gates"]["current_measurement_schema"])
        self.assertFalse(status["cohorts"][0]["policy_change_eligible"])

    def test_schema_four_claim_cannot_be_replayed_after_schema_five_laundering(self) -> None:
        source = verified_credit_record("SOL_LUNA", "pair-001")
        source.update(
            {
                "schema_version": 4,
                "campaign_id": "legacy-campaign",
                "evaluation_mode": "MATCHED",
                "acceptance_suite_digest": "sha256:" + "1" * 64,
                "task_spec_digest": "sha256:" + "2" * 64,
                "starting_candidate_ref": "git:legacy-start",
                "policy_version": "1.2.0",
                "policy_fingerprint": "sha256:" + "3" * 64,
                "writer_count": 1,
                "luna_effort": "high",
                "phase_elapsed_seconds": {"luna_execution": 80},
                "observed_sol_model": "gpt-5.6-sol",
                "observed_luna_model": "gpt-5.6-luna",
                "runtime_identity_source": "legacy-host-receipt",
                "runtime_identity_uncertainty": "none",
            }
        )
        legacy = LEDGER.validate_record(source)
        claims = verified_index([legacy])

        laundered_source = dict(legacy)
        laundered_source.pop("upgraded_from_schema_version")
        laundered_source["phase_elapsed_seconds"] = {
            **laundered_source["phase_elapsed_seconds"],
            "sol_retained_execution": 0,
        }
        laundered_source["phase_credits"] = {
            **laundered_source["phase_credits"],
            "sol_retained_execution": 0,
        }
        laundered = LEDGER.validate_record(laundered_source)
        verified = LEDGER._normalize_verified_credit_receipts(claims)
        self.assertEqual(legacy["record_id"], laundered["record_id"])
        self.assertNotEqual(
            LEDGER.record_binding_digest(legacy),
            LEDGER.record_binding_digest(laundered),
        )
        self.assertFalse(
            LEDGER._credit_record_is_independently_verified(laundered, verified)
        )

    def test_provider_authenticated_credit_requires_exact_receipt_fields(self) -> None:
        record = accepted_credit_record("SOL_ONLY", "pair-001")
        record["credit_verification"] = "PROVIDER_AUTHENTICATED"
        with self.assertRaises(LEDGER.LedgerError):
            LEDGER.validate_record(record)
        record = verified_credit_record("SOL_ONLY", "pair-001")
        record["credit_kind"] = "estimated"
        with self.assertRaises(LEDGER.LedgerError):
            LEDGER.validate_record(record)
        record = verified_credit_record("SOL_ONLY", "pair-001")
        record["credit_receipt_digest"] = "not-a-digest"
        with self.assertRaises(LEDGER.LedgerError):
            LEDGER.validate_record(record)

    def test_self_reported_exact_and_fake_receipt_set_cannot_pass_credit_gate(self) -> None:
        records = []
        for index in range(1, 6):
            pair_id = f"pair-{index:03d}"
            for route in ("SOL_ONLY", "SOL_LUNA"):
                record = accepted_credit_record(route, pair_id)
                suffix = format(index * 2 + (route == "SOL_LUNA"), "x")
                digest = "sha256:" + (suffix * 64)
                record.update(
                    {
                        "credit_receipt_digest": digest,
                        "credit_receipt_ref": f"receipt-{pair_id}-{route.lower()}",
                        "billing_window_id": "window-2026-08",
                    }
                )
                records.append(LEDGER.validate_record(record))
        fake_index = verified_index(records)
        cohort = LEDGER.evidence_status(
            records,
            task_family="bounded-feature",
            verified_credit_receipts=fake_index,
        )["cohorts"][0]
        self.assertFalse(cohort["success_gates"]["credible_credit_reduction"])

        with self.assertRaises(LEDGER.LedgerError):
            LEDGER.evidence_status(
                records,
                task_family="bounded-feature",
                verified_credit_receipts={"sha256:" + "a" * 64},
            )

    def test_only_provider_authenticated_records_in_independent_set_pass(self) -> None:
        records = []
        verified_records = []
        for index in range(1, 6):
            pair_id = f"pair-{index:03d}"
            for route in ("SOL_ONLY", "SOL_LUNA"):
                suffix = format(index * 2 + (route == "SOL_LUNA"), "x")
                record = verified_credit_record(route, pair_id, digest_suffix=suffix)
                if route == "SOL_LUNA":
                    record["credit_value"] = 40
                    record["phase_credits"] = {
                        "sol_planning": 5,
                        "sol_retained_execution": 5,
                        "luna_execution": 25,
                        "sol_review": 5,
                    }
                record = LEDGER.validate_record(record)
                verified_records.append(record)
                records.append(record)
        status = LEDGER.evidence_status(
            records,
            task_family="bounded-feature",
            verified_credit_receipts=verified_index(verified_records),
        )
        self.assertTrue(status["cohorts"][0]["success_gates"]["credible_credit_reduction"])
        self.assertTrue(status["cohorts"][0]["policy_change_eligible"])

    def test_default_credit_reduction_gate_is_fifty_percent(self) -> None:
        records = []
        for index in range(1, 6):
            pair_id = f"pair-{index:03d}"
            for route in ("SOL_ONLY", "SOL_LUNA"):
                suffix = format(index * 2 + (route == "SOL_LUNA"), "x")
                records.append(
                    LEDGER.validate_record(
                        verified_credit_record(route, pair_id, digest_suffix=suffix)
                    )
                )
        claims = verified_index(records)
        default = LEDGER.evidence_status(
            records,
            task_family="bounded-feature",
            verified_credit_receipts=claims,
        )
        legacy_override = LEDGER.evidence_status(
            records,
            task_family="bounded-feature",
            minimum_credit_savings_fraction=0.15,
            verified_credit_receipts=claims,
        )
        self.assertFalse(default["cohorts"][0]["success_gates"]["credible_credit_reduction"])
        self.assertTrue(legacy_override["cohorts"][0]["success_gates"]["credible_credit_reduction"])

    def test_verified_receipt_index_is_strict_and_cli_loadable(self) -> None:
        record = LEDGER.validate_record(verified_credit_record("SOL_ONLY", "pair-001"))
        index_document = verified_index([record])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "receipts.json"
            path.write_text(json.dumps(index_document), encoding="utf-8")
            loaded = LEDGER.load_verified_credit_receipts(path)
            self.assertEqual(loaded["claims"][0]["record_id"], record["record_id"])
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "verification_source": "C:\\Users\\private",
                        "claims": index_document["claims"],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(LEDGER.LedgerError):
                LEDGER.load_verified_credit_receipts(path)

    def test_cli_status_accepts_verified_receipt_index(self) -> None:
        record = LEDGER.validate_record(verified_credit_record("SOL_ONLY", "pair-001"))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            index = root / "receipts.json"
            index.write_text(json.dumps(verified_index([record])), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "status",
                    "--ledger",
                    str(root / "ledger.jsonl"),
                    "--task-family",
                    "bounded-feature",
                    "--verified-credit-receipts",
                    str(index),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["schema_version"], 5)

    def test_cli_nonempty_ledger_rejects_claim_bound_to_wrong_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ledger_path = root / "ledger.jsonl"
            sol = LEDGER.append_record(ledger_path, verified_credit_record("SOL_ONLY", "pair-001"))
            luna = LEDGER.append_record(ledger_path, verified_credit_record("SOL_LUNA", "pair-001", digest_suffix="b"))
            index_document = verified_index([sol, luna])
            index_document["claims"][1]["record_id"] = "record:tampered-claim"
            index_document["claims"][1]["claim_digest"] = LEDGER._canonical_claim_digest(index_document["claims"][1])
            index_path = root / "receipts.json"
            index_path.write_text(json.dumps(index_document), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "status",
                    "--ledger",
                    str(ledger_path),
                    "--task-family",
                    "bounded-feature",
                    "--verified-credit-receipts",
                    str(index_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertFalse(output["cohorts"][0]["success_gates"]["credible_credit_reduction"])

    def test_cli_rejects_non_utf8_receipt_index_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            index_path = root / "receipts.json"
            index_path.write_bytes(b"\xff\xfe\x00")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "status",
                    "--ledger",
                    str(root / "ledger.jsonl"),
                    "--task-family",
                    "bounded-feature",
                    "--verified-credit-receipts",
                    str(index_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("evidence ledger error", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_cohort_identity_separates_effort_uncertainty_writer_and_integration_cost(self) -> None:
        records = []
        for index in range(1, 6):
            pair_id = f"pair-{index:03d}"
            sol = verified_credit_record("SOL_ONLY", pair_id, digest_suffix=format(index * 2, "x"))
            luna = verified_credit_record("SOL_LUNA", pair_id, digest_suffix=format(index * 2 + 1, "x"))
            sol["writer_count"] = luna["writer_count"] = 1
            sol["review_depth"] = luna["review_depth"] = "STANDARD"
            luna["luna_effort"] = "low" if index < 3 else "xhigh"
            luna["phase_credits"] = {"sol_planning": 10, "luna_execution": 50, "sol_review": 10, "integration": 10}
            sol["phase_credits"] = {"sol_execution": 100}
            sol["credit_value"] = 100
            luna["credit_value"] = 80
            records.extend([LEDGER.validate_record(sol), LEDGER.validate_record(luna)])
        status = LEDGER.evidence_status(
            records,
            task_family="bounded-feature",
            verified_credit_receipts=verified_index(records),
        )
        self.assertGreaterEqual(len(status["cohorts"]), 2)
        self.assertFalse(any(c["policy_change_eligible"] for c in status["cohorts"]))

    def test_cohort_identity_separates_token_uncertainty(self) -> None:
        records = []
        for index in range(1, 6):
            pair_id = f"pair-{index:03d}"
            sol = accepted_record("SOL_ONLY", pair_id, tokens=1000)
            luna = accepted_record("SOL_LUNA", pair_id, tokens=800)
            uncertainty = "local-diagnostic" if index <= 2 else "provider-margin-unknown"
            sol["token_uncertainty"] = uncertainty
            luna["token_uncertainty"] = uncertainty
            records.extend([LEDGER.validate_record(sol), LEDGER.validate_record(luna)])
        status = LEDGER.evidence_status(records, task_family="bounded-feature")
        self.assertGreaterEqual(len(status["cohorts"]), 2)

    def test_legacy_schema_cannot_smuggle_explicit_provider_authentication(self) -> None:
        record = verified_credit_record("SOL_ONLY", "pair-001")
        record["schema_version"] = 3
        with self.assertRaisesRegex(LEDGER.LedgerError, "schemas before 4"):
            LEDGER.validate_record(record)

    def test_cohort_identity_uses_structured_side_members_without_delimiter_collision(self) -> None:
        left = accepted_record("SOL_ONLY", "pair-001", tokens=1000)
        right = accepted_record("SOL_LUNA", "pair-001", tokens=800)
        first = LEDGER.cohort_identity(
            dict(left, token_uncertainty="left|right"),
            ("total_tokens", "source"),
            dict(right, token_uncertainty="value"),
        )
        second = LEDGER.cohort_identity(
            dict(left, token_uncertainty="left"),
            ("total_tokens", "source"),
            dict(right, token_uncertainty="right|value"),
        )
        self.assertNotEqual(first, second)
        self.assertEqual(first[6], ("token_uncertainty", json.dumps("left|right")))
        self.assertEqual(first[7], ("token_uncertainty", json.dumps("value")))

    def test_token_cohorts_include_both_billing_window_members(self) -> None:
        records = []
        for index in range(1, 6):
            pair_id = f"pair-{index:03d}"
            sol = accepted_record("SOL_ONLY", pair_id, tokens=1000)
            luna = accepted_record("SOL_LUNA", pair_id, tokens=800)
            sol["billing_window_id"] = "window-a"
            luna["billing_window_id"] = "window-a" if index <= 2 else "window-b"
            records.extend([LEDGER.validate_record(sol), LEDGER.validate_record(luna)])
        status = LEDGER.evidence_status(records, task_family="bounded-feature")
        self.assertEqual(len(status["cohorts"]), 2)
        windows = {
            (
                cohort["cohort"]["billing_window_id"]["SOL_ONLY"],
                cohort["cohort"]["billing_window_id"]["SOL_LUNA"],
            )
            for cohort in status["cohorts"]
        }
        self.assertEqual(windows, {("window-a", "window-a"), ("window-a", "window-b")})

    def test_verified_index_rejects_duplicate_digest_and_claim_mismatch(self) -> None:
        first = LEDGER.validate_record(verified_credit_record("SOL_ONLY", "pair-001", digest_suffix="a"))
        second = LEDGER.validate_record(verified_credit_record("SOL_LUNA", "pair-001", digest_suffix="b"))
        claims = verified_index([first, second])
        claims["claims"][1]["receipt_digest"] = claims["claims"][0]["receipt_digest"]
        claims["claims"][1]["claim_digest"] = LEDGER._canonical_claim_digest(claims["claims"][1])
        with self.assertRaisesRegex(LEDGER.LedgerError, "reused"):
            LEDGER.evidence_status([first, second], task_family="bounded-feature", verified_credit_receipts=claims)

        claims = verified_index([first])
        claims["claims"][0]["credit_value"] = 999
        with self.assertRaisesRegex(LEDGER.LedgerError, "canonical claim JSON"):
            LEDGER.evidence_status([first], task_family="bounded-feature", verified_credit_receipts=claims)

    def test_verified_claims_cannot_replay_across_family_policy_or_suite(self) -> None:
        records = []
        for index in range(1, 6):
            pair_id = f"pair-{index:03d}"
            records.extend(
                [
                    LEDGER.validate_record(verified_credit_record("SOL_ONLY", pair_id, digest_suffix=format(index * 2, "x"))),
                    LEDGER.validate_record(verified_credit_record("SOL_LUNA", pair_id, digest_suffix=format(index * 2 + 1, "x"))),
                ]
            )
        claims = verified_index(records)
        mutations = (
            ("task_family", "relabelled-family"),
            ("policy_fingerprint", "sha256:" + "c" * 64),
            ("acceptance_suite_digest", "sha256:" + "d" * 64),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                replayed = [dict(record, **{field: value}) for record in records]
                task_family = "relabelled-family" if field == "task_family" else "bounded-feature"
                status = LEDGER.evidence_status(
                    replayed,
                    task_family=task_family,
                    verified_credit_receipts=claims,
                )
                self.assertFalse(status["cohorts"][0]["success_gates"]["credible_credit_reduction"])
                self.assertFalse(status["cohorts"][0]["policy_change_eligible"])


if __name__ == "__main__":
    unittest.main()
