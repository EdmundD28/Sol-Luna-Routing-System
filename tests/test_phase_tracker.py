from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / ".agents" / "skills" / "sol-luna" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location("phase_tracker", SCRIPT_DIR / "phase_tracker.py")
assert SPEC and SPEC.loader
TRACKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRACKER)


class PhaseTrackerTests(unittest.TestCase):
    def test_phase_duration_and_source_readings_are_accumulated(self) -> None:
        journal = TRACKER.initialize("private-run", "SOL_LUNA", at="2026-08-26T00:00:00+00:00")
        journal = TRACKER.start(journal, "sol_planning", at="2026-08-26T00:00:00+00:00")
        journal = TRACKER.stop(
            journal,
            "sol_planning",
            at="2026-08-26T00:01:00+00:00",
            tokens=100,
            credits=2.5,
        )
        journal = TRACKER.start(journal, "luna_execution", at="2026-08-26T00:01:00+00:00")
        journal = TRACKER.stop(
            journal,
            "luna_execution",
            at="2026-08-26T00:06:00+00:00",
            tokens=500,
            credits=5,
        )
        result = TRACKER.export(journal)
        self.assertEqual(result["elapsed_seconds"], 360)
        self.assertEqual(result["total_tokens"], 600)
        self.assertEqual(result["credit_value"], 7.5)
        self.assertTrue(result["run_ref"].startswith("redacted:run:"))

    def test_repair_phase_can_accumulate_multiple_intervals(self) -> None:
        journal = TRACKER.initialize("private-run", "SOL_LUNA", at="2026-08-26T00:00:00+00:00")
        for start, end in (("00:00:00", "00:01:00"), ("00:02:00", "00:03:30")):
            journal = TRACKER.start(journal, "repair", at=f"2026-08-26T{start}+00:00")
            journal = TRACKER.stop(journal, "repair", at=f"2026-08-26T{end}+00:00")
        self.assertEqual(TRACKER.export(journal)["phase_elapsed_seconds"]["repair"], 150)

    def test_overlapping_phase_durations_do_not_inflate_wall_clock(self) -> None:
        journal = TRACKER.initialize("private-run", "SOL_LUNA", at="2026-08-26T00:00:00+00:00")
        journal = TRACKER.start(journal, "sol_planning", at="2026-08-26T00:00:00+00:00")
        journal = TRACKER.start(journal, "luna_execution", at="2026-08-26T00:00:10+00:00")
        journal = TRACKER.stop(journal, "sol_planning", at="2026-08-26T00:01:00+00:00")
        journal = TRACKER.stop(journal, "luna_execution", at="2026-08-26T00:01:10+00:00")
        result = TRACKER.export(journal)
        self.assertEqual(result["elapsed_seconds"], 70)
        self.assertEqual(sum(result["phase_elapsed_seconds"].values()), 120)

    def test_run_wrapper_records_elapsed_and_exit_even_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            journal_path = Path(temp) / "phase.json"
            TRACKER.atomic_write(journal_path, TRACKER.initialize("private-run", "SOL_LUNA"))
            exit_code, output = TRACKER.run_command(
                journal_path,
                "luna_execution",
                [sys.executable, "-c", "raise SystemExit(7)"],
                tokens=12,
                credits=3,
            )
            self.assertEqual(exit_code, 7)
            self.assertEqual(output["command_exit_code"], 7)
            self.assertEqual(output["total_tokens"], 12)
            self.assertEqual(output["credit_value"], 3)
            self.assertGreaterEqual(output["phase_elapsed_seconds"]["luna_execution"], 0)
            self.assertEqual(TRACKER.load(journal_path)["open_phases"], {})

    def test_open_phase_blocks_export(self) -> None:
        journal = TRACKER.start(TRACKER.initialize("private-run", "SOL_ONLY"), "sol_planning")
        with self.assertRaisesRegex(TRACKER.TrackerError, "open phases"):
            TRACKER.export(journal)

    def test_sol_only_execution_has_a_distinct_phase(self) -> None:
        journal = TRACKER.initialize("private-run", "SOL_ONLY", at="2026-08-26T00:00:00+00:00")
        journal = TRACKER.start(journal, "sol_execution", at="2026-08-26T00:00:00+00:00")
        journal = TRACKER.stop(
            journal,
            "sol_execution",
            at="2026-08-26T00:00:05+00:00",
            tokens=25,
        )
        result = TRACKER.export(journal)
        self.assertEqual(result["phase_elapsed_seconds"]["sol_execution"], 5)
        self.assertEqual(result["phase_tokens"]["sol_execution"], 25)

    def test_end_before_start_is_rejected(self) -> None:
        journal = TRACKER.initialize("private-run", "SOL_ONLY", at="2026-08-26T00:00:00+00:00")
        journal = TRACKER.start(journal, "sol_planning", at="2026-08-26T00:01:00+00:00")
        with self.assertRaisesRegex(TRACKER.TrackerError, "precedes"):
            TRACKER.stop(journal, "sol_planning", at="2026-08-26T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
