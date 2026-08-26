from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "runtime_receipt.py"
SPEC = importlib.util.spec_from_file_location("runtime_receipt", SCRIPT)
assert SPEC and SPEC.loader
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


class RuntimeReceiptTests(unittest.TestCase):
    def fixture(self, name: str) -> Path:
        return ROOT / "tests" / "fixtures" / name

    def test_consistent_host_record_is_verified_and_redacted(self) -> None:
        receipt = RUNTIME.build_receipt(
            self.fixture("runtime-consistent.jsonl"),
            "thread-123",
            requested_agent="luna_worker",
            requested_model="gpt-5.6-luna",
            requested_effort="max",
        )
        self.assertEqual(receipt["status"], "verified")
        self.assertEqual(receipt["host_observed"]["model"]["value"], "gpt-5.6-luna")
        self.assertEqual(receipt["host_observed"]["model"]["provenance"], "host_observed")
        self.assertTrue(receipt["thread_ref"].startswith("redacted:thread:"))
        self.assertTrue(receipt["host_observed"]["cwd_ref"]["value"].startswith("redacted:cwd:"))
        self.assertFalse(receipt["self_report_used_as_proof"])
        self.assertEqual(receipt["mismatches"], [])

    def test_conflicting_host_values_remain_unknown(self) -> None:
        receipt = RUNTIME.build_receipt(
            self.fixture("runtime-conflict.jsonl"),
            "thread-123",
            requested_model="gpt-5.6-luna",
        )
        self.assertEqual(receipt["status"], "conflicted")
        self.assertEqual(receipt["host_observed"]["model"]["provenance"], "unknown")
        self.assertIn("model", receipt["unknown_identity_fields"])
        with self.assertRaises(RUNTIME.ReceiptError):
            RUNTIME.enforce_requirements(receipt, require_identity=True, require_boundary=False)

    def test_wrong_thread_is_rejected_instead_of_scanning_another_session(self) -> None:
        with self.assertRaises(RUNTIME.ReceiptError):
            RUNTIME.build_receipt(self.fixture("runtime-consistent.jsonl"), "wrong-thread")

    def test_requested_mismatch_is_disclosed(self) -> None:
        receipt = RUNTIME.build_receipt(
            self.fixture("runtime-consistent.jsonl"),
            "thread-123",
            requested_model="gpt-5.6-sol",
        )
        self.assertEqual(receipt["status"], "conflicted")
        self.assertEqual(len(receipt["mismatches"]), 1)
        with self.assertRaises(RUNTIME.ReceiptError):
            RUNTIME.enforce_requirements(receipt, require_identity=False, require_boundary=False)

    def test_combined_multi_session_file_is_rejected(self) -> None:
        source = self.fixture("runtime-consistent.jsonl").read_text(encoding="utf-8")
        other = json.dumps({"type": "session_meta", "payload": {"id": "other-thread"}})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "combined.jsonl"
            path.write_text(source + other + "\n", encoding="utf-8")
            with self.assertRaises(RUNTIME.ReceiptError):
                RUNTIME.build_receipt(path, "thread-123")

    def test_unreadable_lines_prevent_strict_runtime_proof(self) -> None:
        source = self.fixture("runtime-consistent.jsonl").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "damaged.jsonl"
            path.write_text(source + "{not-json}\n", encoding="utf-8")
            receipt = RUNTIME.build_receipt(path, "thread-123")
        self.assertEqual(receipt["status"], "partial")
        self.assertEqual(receipt["invalid_jsonl_lines"], 1)
        with self.assertRaises(RUNTIME.ReceiptError):
            RUNTIME.enforce_requirements(receipt, require_identity=True, require_boundary=False)


if __name__ == "__main__":
    unittest.main()
