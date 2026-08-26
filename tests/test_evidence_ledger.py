from __future__ import annotations

import importlib.util
import json
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
                "phase_elapsed_seconds": {"luna_execution": 80},
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
        self.assertTrue(exact_gate["success_gates"]["credible_credit_reduction"])
        self.assertTrue(exact_gate["policy_change_eligible"])

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
        self.assertTrue(cohort["policy_change_eligible"])

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
        self.assertEqual(feedback["posture"], "SOL_LUNA_POLICY_REVIEW_CANDIDATE")
        self.assertEqual(feedback["supported_luna_efforts"], ["xhigh"])
        self.assertTrue(feedback["human_policy_review_required"])
        self.assertFalse(feedback["automatic_routing_allowed"])


if __name__ == "__main__":
    unittest.main()
