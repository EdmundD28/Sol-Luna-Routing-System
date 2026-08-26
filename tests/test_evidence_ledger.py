from __future__ import annotations

import importlib.util
import json
import tempfile
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
        self.assertEqual(status["rejected_pair_reasons"]["acceptance_suite_mismatch"], 1)


if __name__ == "__main__":
    unittest.main()
