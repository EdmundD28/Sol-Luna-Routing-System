from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "native_lifecycle_receipt.py"
SPEC = importlib.util.spec_from_file_location("native_lifecycle_receipt", SCRIPT)
assert SPEC and SPEC.loader
RECEIPT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECEIPT)


def child(reference: str, role: str, effort: str) -> dict:
    contract = {
        "agent_role": role,
        "model": "gpt-5.6-luna",
        "effort": effort,
        "sandbox_mode": "read-only",
        "permission_profile": "managed-read-only",
    }
    return {
        "child_ref": reference,
        "requested": copy.deepcopy(contract),
        "observed": copy.deepcopy(contract),
        "custom_profile_loaded": True,
    }


def valid_receipt() -> dict:
    worker = "redacted:child:1111111111111111"
    timeout = "redacted:child:2222222222222222"
    return {
        "schema_version": 1,
        "runtime": "codex-native",
        "children": [child(worker, "luna_worker_low", "low"), child(timeout, "luna_worker_medium", "medium")],
        "events": [
            {"type": "delegation", "child_ref": worker, "status": "COMPLETED"},
            {
                "type": "focused_repair",
                "child_ref": worker,
                "repair_round": 1,
                "authoritative_check": "PASSED",
            },
            {
                "type": "stale_evidence",
                "child_ref": worker,
                "old_generation": 1,
                "new_generation": 2,
                "acceptance": "REJECTED_STALE",
            },
            {
                "type": "timeout",
                "child_ref": timeout,
                "deadline_seconds": 10,
                "prior_status": "RUNNING",
                "interrupted": True,
            },
            {
                "type": "continuation",
                "child_ref": timeout,
                "after": "timeout",
                "status": "PASSED",
            },
            {
                "type": "ownership_conflict",
                "guard_status": "FAIL",
                "parallel_writes_allowed": False,
                "dispatched_writers": 0,
            },
        ],
    }


class NativeLifecycleReceiptTests(unittest.TestCase):
    def test_complete_host_observed_receipt_passes(self) -> None:
        result = RECEIPT.validate_receipt(valid_receipt())
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["native_lifecycle_proven"])

    def test_requested_observed_mismatch_fails(self) -> None:
        receipt = valid_receipt()
        receipt["children"][0]["observed"]["effort"] = "high"
        with self.assertRaises(RECEIPT.ReceiptError):
            RECEIPT.validate_receipt(receipt)

    def test_unproven_custom_profile_fails(self) -> None:
        receipt = valid_receipt()
        receipt["children"][0]["custom_profile_loaded"] = False
        with self.assertRaises(RECEIPT.ReceiptError):
            RECEIPT.validate_receipt(receipt)

    def test_second_repair_fails(self) -> None:
        receipt = valid_receipt()
        receipt["events"][1]["repair_round"] = 2
        with self.assertRaises(RECEIPT.ReceiptError):
            RECEIPT.validate_receipt(receipt)

    def test_continuation_must_reuse_interrupted_child(self) -> None:
        receipt = valid_receipt()
        receipt["events"][4]["child_ref"] = receipt["events"][0]["child_ref"]
        with self.assertRaises(RECEIPT.ReceiptError):
            RECEIPT.validate_receipt(receipt)

    def test_conflicting_writers_must_not_be_dispatched(self) -> None:
        receipt = valid_receipt()
        receipt["events"][5]["dispatched_writers"] = 1
        with self.assertRaises(RECEIPT.ReceiptError):
            RECEIPT.validate_receipt(receipt)


if __name__ == "__main__":
    unittest.main()
