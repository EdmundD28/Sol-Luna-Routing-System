from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "allowance_campaign.py"
SPEC = importlib.util.spec_from_file_location("allowance_campaign", SCRIPT)
assert SPEC and SPEC.loader
CAMPAIGN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAMPAIGN)
DIGEST = "sha256:" + "a" * 64


class AllowanceCampaignTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Path(self.temp.name) / "campaign.jsonl"
        self.origin = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)
        CAMPAIGN.initialize(
            self.ledger,
            contract_digest=DIGEST,
            usage_scope_digest="sha256:" + "b" * 64,
            task_family="bounded-feature",
            batch_size=1,
            reading_uncertainty=0.1,
            first_routes="SOL_ONLY,SOL_LUNA,SOL_LUNA,SOL_ONLY",
            five_hour_window_id="five-hour-001",
            five_hour_reset_at=(self.origin + timedelta(hours=10)).isoformat(),
            weekly_window_id="weekly-001",
            weekly_reset_at=(self.origin + timedelta(days=2)).isoformat(),
        )
        first_event = json.loads(self.ledger.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(first_event["previous_event_sha256"], "0" * 64)

    def stamp(self, minute: int) -> str:
        return (self.origin + timedelta(minutes=minute)).isoformat()

    def begin(self, route: str, minute: int, five: float, weekly: float) -> dict:
        return CAMPAIGN.begin_arm(
            self.ledger,
            route=route,
            route_revision="v0.1.1",
            observed_at=self.stamp(minute),
            five_hour_remaining_percent=five,
            weekly_remaining_percent=weekly,
            start_evidence_digest=DIGEST,
        )

    def end(self, route: str, minute: int, five: float, weekly: float, elapsed: float = 10) -> dict:
        return CAMPAIGN.end_arm(
            self.ledger,
            route=route,
            observed_at=self.stamp(minute),
            five_hour_remaining_percent=five,
            weekly_remaining_percent=weekly,
            end_evidence_digest="sha256:" + "c" * 64,
            elapsed_seconds=elapsed,
            independent_acceptance="PASSED",
            defects=0,
        )

    def test_full_four_pair_campaign_records_gaps_recovers_and_assesses(self) -> None:
        remaining_five = 100.0
        remaining_weekly = 100.0
        minute = 1
        routes = ["SOL_ONLY", "SOL_LUNA", "SOL_LUNA", "SOL_ONLY"]
        excluded = 0.0
        for first in routes:
            for route in (first, CAMPAIGN._opposite(first)):
                gap = 0.0 if minute == 1 else 0.2
                remaining_five -= gap
                remaining_weekly -= gap
                started = self.begin(route, minute, remaining_five, remaining_weekly)
                excluded += gap
                self.assertAlmostEqual(
                    started["excluded_since_previous_end_percentage_points"]["five_hour"], gap
                )
                consumption = 8.0 if route == "SOL_ONLY" else 0.5
                remaining_five -= consumption
                remaining_weekly -= consumption
                self.end(route, minute + 1, remaining_five, remaining_weekly, 20 if route == "SOL_ONLY" else 5)
                minute += 3
        status = CAMPAIGN.campaign_status(self.ledger)
        self.assertEqual(status["completed_pairs"], 4)
        self.assertEqual(status["completed_arms"], 8)
        self.assertIsNone(status["active_arm"])
        self.assertIsNone(status["next_route"])
        self.assertAlmostEqual(status["excluded_consumption_percentage_points"]["five_hour"], excluded)
        self.assertEqual(len(CAMPAIGN.replay(self.ledger)["records"]), 8)
        assessment = CAMPAIGN.assess_campaign(
            self.ledger, minimum_advantage_multiple=5, minimum_pairs=4
        )
        self.assertEqual(assessment["campaign_status"], "PASS")
        self.assertEqual(assessment["primary_limit"], "five_hour")
        self.assertEqual(assessment["secondary_limit"], "weekly")

    def test_active_arm_is_recovered_by_status(self) -> None:
        self.begin("SOL_ONLY", 1, 100, 100)
        status = CAMPAIGN.campaign_status(self.ledger)
        self.assertEqual(status["active_arm"]["route"], "SOL_ONLY")
        self.assertEqual(status["next_route"], "SOL_LUNA")
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "active"):
            CAMPAIGN.assess_campaign(self.ledger)
        self.end("SOL_ONLY", 2, 90, 99)
        self.assertEqual(CAMPAIGN.campaign_status(self.ledger)["next_route"], "SOL_LUNA")

    def test_wrong_route_and_duplicate_begin_preserve_ledger(self) -> None:
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "next route"):
            self.begin("SOL_LUNA", 1, 100, 100)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.begin("SOL_ONLY", 1, 100, 100)
        active = self.ledger.read_bytes()
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "active"):
            self.begin("SOL_ONLY", 2, 99, 99)
        self.assertEqual(self.ledger.read_bytes(), active)

    def test_increasing_reading_and_cross_reset_are_rejected_without_corruption(self) -> None:
        self.begin("SOL_ONLY", 1, 100, 100)
        active = self.ledger.read_bytes()
        with self.assertRaises(CAMPAIGN.CampaignError):
            self.end("SOL_ONLY", 2, 101, 99)
        self.assertEqual(self.ledger.read_bytes(), active)
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "reset boundary"):
            CAMPAIGN.end_arm(
                self.ledger,
                route="SOL_ONLY",
                observed_at=(self.origin + timedelta(hours=10)).isoformat(),
                five_hour_remaining_percent=90,
                weekly_remaining_percent=99,
                end_evidence_digest=DIGEST,
                elapsed_seconds=1,
                independent_acceptance="PASSED",
                defects=0,
            )
        self.assertEqual(self.ledger.read_bytes(), active)

    def test_between_arm_increase_is_treated_as_reset_or_inconsistency(self) -> None:
        self.begin("SOL_ONLY", 1, 100, 100)
        self.end("SOL_ONLY", 2, 90, 99)
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "increased between arms"):
            self.begin("SOL_LUNA", 3, 91, 99)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_corrupt_json_unknown_fields_hash_break_and_tampered_record_fail_replay(self) -> None:
        original = self.ledger.read_bytes()
        self.ledger.write_bytes(b"{broken}\n")
        with self.assertRaises(CAMPAIGN.CampaignError):
            CAMPAIGN.replay(self.ledger)
        self.ledger.write_bytes(original)
        event = json.loads(original.decode().splitlines()[0])
        event["unknown"] = True
        self.ledger.write_bytes(CAMPAIGN.canonical_bytes(event) + b"\n")
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "unsupported"):
            CAMPAIGN.replay(self.ledger)

        self.ledger.write_bytes(original)
        self.begin("SOL_ONLY", 1, 100, 100)
        self.end("SOL_ONLY", 2, 90, 99)
        events = [json.loads(line) for line in self.ledger.read_text(encoding="utf-8").splitlines()]
        events[-1]["record"]["elapsed_seconds"] = 999
        for index in range(1, len(events)):
            events[index]["previous_event_sha256"] = CAMPAIGN._event_previous(
                CAMPAIGN.canonical_bytes(events[index - 1])
            )
        self.ledger.write_bytes(b"\n".join(CAMPAIGN.canonical_bytes(item) for item in events) + b"\n")
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "does not match"):
            CAMPAIGN.replay(self.ledger)

    def test_foreign_lock_is_not_removed(self) -> None:
        lock = Path(str(self.ledger) + ".lock")
        lock.write_text("foreign", encoding="utf-8")
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "lock already exists"):
            self.begin("SOL_ONLY", 1, 100, 100)
        self.assertEqual(lock.read_text(encoding="utf-8"), "foreign")
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_atomic_replace_failure_preserves_old_ledger_and_cleans_owned_artifacts(self) -> None:
        before = self.ledger.read_bytes()
        with mock.patch.object(CAMPAIGN.os, "replace", side_effect=OSError("forced")):
            with self.assertRaisesRegex(CAMPAIGN.CampaignError, "atomically"):
                self.begin("SOL_ONLY", 1, 100, 100)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertFalse(Path(str(self.ledger) + ".lock").exists())
        self.assertEqual(list(self.ledger.parent.glob(self.ledger.name + ".*.tmp")), [])

    def test_init_refuses_existing_ledger_without_truncation(self) -> None:
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(CAMPAIGN.CampaignError, "already exists"):
            CAMPAIGN.initialize(
                self.ledger,
                contract_digest=DIGEST,
                usage_scope_digest=DIGEST,
                task_family="bounded-feature",
                batch_size=1,
                reading_uncertainty=1,
                first_routes="SOL_ONLY,SOL_LUNA",
                five_hour_window_id="five-hour-001",
                five_hour_reset_at=self.stamp(100),
                weekly_window_id="weekly-001",
                weekly_reset_at=self.stamp(200),
            )
        self.assertEqual(self.ledger.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
