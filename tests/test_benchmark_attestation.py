from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "benchmark_attestation.py"
SPEC = importlib.util.spec_from_file_location("benchmark_attestation", SCRIPT)
assert SPEC and SPEC.loader
ATTEST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ATTEST)

DIGEST = "sha256:" + "a" * 64

class BenchmarkAttestationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = self.root / "campaign.jsonl"
        self.index = self.root / "identity.json"
        self.contract = self.root / "contract.json"
        self.output = self.root / "attestation.json"
        origin = datetime(2026, 8, 28, tzinfo=timezone.utc)
        ATTEST.CAMPAIGN.initialize(self.ledger, contract_digest=DIGEST, usage_scope_digest=DIGEST,
            task_family="bounded-feature", batch_size=1, reading_uncertainty=0.1,
            first_routes="SOL_ONLY,SOL_LUNA,SOL_LUNA,SOL_ONLY,SOL_ONLY",
            starting_commit_sha="a" * 40,
            task_spec_digest="sha256:" + "c" * 64,
            acceptance_suite_digest="sha256:" + "d" * 64,
            repair_policy_digest="sha256:" + "f" * 64,
            sol_luna_worker_count=2, sol_luna_active_luna_writer_count=1,
            five_hour_window_id="five-hour-001", five_hour_reset_at=(origin + timedelta(hours=10)).isoformat(),
            weekly_window_id="weekly-001", weekly_reset_at=(origin + timedelta(days=2)).isoformat())
        minute = 1
        remaining = 100
        for first in ("SOL_ONLY", "SOL_LUNA", "SOL_LUNA", "SOL_ONLY", "SOL_ONLY"):
            for route in (first, "SOL_LUNA" if first == "SOL_ONLY" else "SOL_ONLY"):
                start = origin + timedelta(minutes=minute)
                end = origin + timedelta(minutes=minute + 1)
                remaining -= 1
                started = ATTEST.CAMPAIGN.begin_arm(self.ledger, route=route, route_revision="v0.6.0",
                    observed_at=start.isoformat(), five_hour_remaining_percent=remaining, weekly_remaining_percent=remaining,
                    start_evidence_digest=DIGEST)
                remaining -= 1
                ended = ATTEST.CAMPAIGN.end_arm(self.ledger, pair_id=started["pair_id"], route=route, observed_at=end.isoformat(),
                    five_hour_remaining_percent=remaining, weekly_remaining_percent=remaining,
                    end_evidence_digest="sha256:" + "b" * 64, elapsed_seconds=1,
                    candidate_digest=DIGEST)
                ATTEST.CAMPAIGN.record_acceptance(
                    self.ledger, pair_id=ended["pair_id"], route=route,
                    candidate_digest=DIGEST, acceptance_command_digest=DIGEST,
                    acceptance_result_digest=DIGEST, acceptance_suite_digest="sha256:" + "d" * 64,
                    observed_at=(origin + timedelta(minutes=minute + 2)).isoformat(),
                    acceptance_elapsed_seconds=1, independent_acceptance="PASSED", defects=0)
                minute += 3
        self.contract.write_text(json.dumps({"schema_version": 2, "campaign_id": "campaign-001",
            "benchmark_contract_digest": DIGEST, "task_spec_digest": "sha256:" + "c" * 64,
            "acceptance_suite_digest": "sha256:" + "d" * 64, "policy_fingerprint": "sha256:" + "e" * 64,
            "route_revision": "v0.6.0", "expected_pairs": 5, "expected_batch_size": 1,
            "expected_sol_luna_effort": "medium", "expected_sol_luna_worker_count": 2,
            "expected_sol_luna_active_luna_writer_count": 1,
            "expected_sol_only_topology": "single-controller-no-workers",
            "expected_sol_luna_topology": "single-controller-one-active-luna"}, indent=2) + "\n", encoding="utf-8")
        runs = []
        for pair in range(1, 6):
            for route in ("SOL_ONLY", "SOL_LUNA"):
                def identity(model: str, effort: str, number: int) -> dict:
                    return {"model": model, "effort": effort, "role": "default" if model.endswith("sol") else "luna_worker_medium", "provider": "openai", "receipt_sha256": "sha256:" + format(number, "064x")}
                controller = identity("gpt-5.6-sol", "high", (pair - 1) * 2 + (1 if route == "SOL_ONLY" else 2))
                workers = [] if route == "SOL_ONLY" else [
                    identity("gpt-5.6-luna", "medium", 100 + pair),
                    identity("gpt-5.6-luna", "medium", 200 + pair),
                ]
                runs.append({"pair_id": f"pair-{pair:03d}", "route": route, "controller": controller, "workers": workers})
        content = {"schema_version": 2, "campaign_id": "campaign-001", "sol_luna_effort": "medium", "sol_luna_writer_count": 2, "runs": sorted(runs, key=lambda x: (x["pair_id"], x["route"])), "verification_status": "verified"}
        content["index_sha256"] = ATTEST.sha256_bytes(ATTEST.canonical_bytes(content))
        self.index.write_text(json.dumps(content, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_happy_path_is_deterministic_and_redacted(self) -> None:
        first = ATTEST.build_attestation(self.ledger, self.index, self.contract)
        second = ATTEST.build_attestation(self.ledger, self.index, self.contract)
        self.assertEqual(first, second)
        self.assertEqual(first["completed_pairs"], 5)
        self.assertEqual(first["arm_count"], 10)
        self.assertEqual(first["sol_luna_worker_count"], 2)
        self.assertEqual(first["sol_luna_active_luna_writer_count"], 1)
        self.assertEqual(first["attestation_sha256"], ATTEST.sha256_bytes(ATTEST.canonical_bytes({k: v for k, v in first.items() if k != "attestation_sha256"})))
        self.assertNotIn("campaign.jsonl", json.dumps(first))

    def test_binding_and_strict_identity_fail_closed(self) -> None:
        contract = json.loads(self.contract.read_text())
        original_contract = dict(contract)
        contract["route_revision"] = "v9.9.9"
        self.contract.write_text(json.dumps(contract), encoding="utf-8")
        with self.assertRaises(ATTEST.AttestationError): ATTEST.build_attestation(self.ledger, self.index, self.contract)
        self.contract.write_text(json.dumps(original_contract), encoding="utf-8")
        self.index.write_text(self.index.read_text().replace('"verification_status": "verified"', '"verification_status": "tampered"'), encoding="utf-8")
        with self.assertRaises(ATTEST.AttestationError): ATTEST.build_attestation(self.ledger, self.index, self.contract)

    def test_campaign_task_suite_and_worker_count_must_match_contract(self) -> None:
        original_replay = ATTEST.CAMPAIGN.replay
        for field, value in (
            ("task_spec_digest", "sha256:" + "9" * 64),
            ("acceptance_suite_digest", "sha256:" + "8" * 64),
            ("sol_luna_worker_count", 3),
            ("sol_luna_active_luna_writer_count", 2),
            ("sol_only_topology", "tampered-topology"),
        ):
            state = original_replay(self.ledger)
            state["config"] = dict(state["config"])
            state["config"][field] = value
            with self.subTest(field=field), mock.patch.object(
                ATTEST.CAMPAIGN, "replay", return_value=state
            ), self.assertRaisesRegex(ATTEST.AttestationError, "does not match contract"):
                ATTEST.build_attestation(self.ledger, self.index, self.contract)

    def test_write_refuses_overwrite_and_cleans_failed_replace(self) -> None:
        self.output.write_text("keep", encoding="utf-8")
        with self.assertRaises(ATTEST.AttestationError): ATTEST.write_attestation(self.ledger, self.index, self.contract, self.output)
        self.assertEqual(self.output.read_text(), "keep")
        self.output.unlink()
        with mock.patch.object(ATTEST.os, "replace", side_effect=OSError("forced")):
            with self.assertRaises(ATTEST.AttestationError): ATTEST.write_attestation(self.ledger, self.index, self.contract, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob("attestation.json.*.tmp")), [])

    def test_digest_prefix_and_float_integer_values_are_strict(self) -> None:
        value = ATTEST.build_attestation(self.ledger, self.index, self.contract)
        self.assertRegex(value["campaign_last_event_sha256"], r"^sha256:[0-9a-f]{64}$")
        contract = json.loads(self.contract.read_text())
        contract["schema_version"] = 1.0
        self.contract.write_text(json.dumps(contract), encoding="utf-8")
        with self.assertRaises(ATTEST.AttestationError):
            ATTEST.build_attestation(self.ledger, self.index, self.contract)

        contract["schema_version"] = 2
        contract["expected_sol_luna_worker_count"] = 1.0
        self.contract.write_text(json.dumps(contract), encoding="utf-8")
        with self.assertRaises(ATTEST.AttestationError):
            ATTEST.build_attestation(self.ledger, self.index, self.contract)

        contract["expected_sol_luna_worker_count"] = 0
        self.contract.write_text(json.dumps(contract), encoding="utf-8")
        with self.assertRaisesRegex(ATTEST.AttestationError, "positive integer"):
            ATTEST.build_attestation(self.ledger, self.index, self.contract)

    def test_duplicate_nonfinite_and_unhashable_values_fail_without_traceback(self) -> None:
        duplicate = '{"schema_version":1,"schema_version":1}'
        self.contract.write_text(duplicate, encoding="utf-8")
        with self.assertRaises(ATTEST.AttestationError):
            ATTEST.build_attestation(self.ledger, self.index, self.contract)
        contract = json.loads(json.dumps({"schema_version": 2, "campaign_id": "campaign-001",
            "benchmark_contract_digest": DIGEST, "task_spec_digest": "sha256:" + "c" * 64,
            "acceptance_suite_digest": "sha256:" + "d" * 64, "policy_fingerprint": "sha256:" + "e" * 64,
            "route_revision": "v0.6.0", "expected_pairs": 5, "expected_batch_size": 1,
            "expected_sol_luna_effort": "medium", "expected_sol_luna_worker_count": 2,
            "expected_sol_luna_active_luna_writer_count": 1,
            "expected_sol_only_topology": "single-controller-no-workers",
            "expected_sol_luna_topology": "single-controller-one-active-luna"}))
        contract["expected_sol_luna_effort"] = []
        self.contract.write_text(json.dumps(contract), encoding="utf-8")
        with self.assertRaises(ATTEST.AttestationError):
            ATTEST.build_attestation(self.ledger, self.index, self.contract)
        self.contract.write_text('{"schema_version":1,"campaign_id":"campaign-001","expected_pairs":NaN}', encoding="utf-8")
        with self.assertRaises(ATTEST.AttestationError):
            ATTEST.build_attestation(self.ledger, self.index, self.contract)
        result = subprocess.run([sys.executable, str(SCRIPT), "build", "--campaign-ledger", str(self.ledger),
            "--identity-index", str(self.index), "--contract", str(self.contract), "--output", str(self.output)],
            capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("benchmark attestation error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

if __name__ == "__main__": unittest.main()
