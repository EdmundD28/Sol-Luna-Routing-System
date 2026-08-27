from __future__ import annotations

import importlib.util
import json
import subprocess
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
    def _run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "phase_tracker.py"), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )

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

    def test_cli_lifecycle_and_run_preserve_subprocess_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            journal_path = Path(temp) / "phase.json"
            init = self._run_cli(
                "init",
                "--journal",
                str(journal_path),
                "--run-ref",
                "cli-smoke",
                "--route",
                "SOL_LUNA",
                "--at",
                "2026-08-26T00:00:00+00:00",
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            self.assertEqual(json.loads(init.stdout)["events"], 0)

            start = self._run_cli(
                "start",
                "--journal",
                str(journal_path),
                "--phase",
                "sol_planning",
                "--at",
                "2026-08-26T00:00:01+00:00",
            )
            self.assertEqual(start.returncode, 0, start.stderr)
            stop = self._run_cli(
                "stop",
                "--journal",
                str(journal_path),
                "--phase",
                "sol_planning",
                "--at",
                "2026-08-26T00:00:02+00:00",
                "--tokens",
                "3",
                "--credits",
                "1.5",
            )
            self.assertEqual(stop.returncode, 0, stop.stderr)
            exported = self._run_cli("export", "--journal", str(journal_path))
            self.assertEqual(exported.returncode, 0, exported.stderr)
            self.assertEqual(json.loads(exported.stdout)["total_tokens"], 3)

            run = self._run_cli(
                "run",
                "--journal",
                str(journal_path),
                "--phase",
                "luna_execution",
                "--tokens",
                "4",
                "--credits",
                "2",
                "--",
                sys.executable,
                "-c",
                "raise SystemExit(7)",
            )
            self.assertEqual(run.returncode, 7, run.stderr)
            result = json.loads(run.stdout)
            self.assertEqual(result["command_exit_code"], 7)
            self.assertEqual(result["total_tokens"], 7)
            self.assertEqual(result["credit_value"], 3.5)
            self.assertEqual(TRACKER.load(journal_path)["open_phases"], {})

    def test_validate_journal_rejects_invalid_metrics_times_and_route_phases(self) -> None:
        base = TRACKER.initialize("private-run", "SOL_LUNA", at="2026-08-26T00:00:00+00:00")
        invalid_cases = (
            ("phase_elapsed_seconds", {"sol_planning": -1}),
            ("phase_elapsed_seconds", {"sol_planning": float("inf")}),
            ("phase_tokens", {"sol_planning": True}),
            ("phase_tokens", {"sol_planning": 1.5}),
            ("phase_tokens", {"sol_planning": -1}),
            ("phase_credits", {"sol_planning": True}),
            ("phase_credits", {"sol_planning": -1}),
            ("phase_credits", {"sol_planning": float("nan")}),
        )
        for field, value in invalid_cases:
            with self.subTest(field=field, value=value):
                candidate = dict(base)
                candidate[field] = value
                with self.assertRaises(TRACKER.TrackerError):
                    TRACKER.validate_journal(candidate)

        for field, value in (
            ("events", True),
            ("events", -1),
            ("events", 1.5),
            ("open_phases", {"luna_execution": "not-a-time"}),
            ("open_phases", {"luna_execution": "2026-08-26T00:00:01"}),
        ):
            with self.subTest(field=field, value=value):
                candidate = dict(base)
                candidate[field] = value
                with self.assertRaises(TRACKER.TrackerError):
                    TRACKER.validate_journal(candidate)

        candidate = dict(base)
        candidate["phase_elapsed_seconds"] = {"sol_execution": 0}
        with self.assertRaisesRegex(TRACKER.TrackerError, "sol_execution"):
            TRACKER.validate_journal(candidate)

        candidate = dict(base)
        candidate["phase_tokens"] = {"sol_planning": 1}
        with self.assertRaisesRegex(TRACKER.TrackerError, "no elapsed"):
            TRACKER.validate_journal(candidate)

        candidate = dict(base)
        candidate["route"] = "SOL_ONLY"
        candidate["open_phases"] = {"luna_execution": base["created_at"]}
        with self.assertRaisesRegex(TRACKER.TrackerError, "luna_execution"):
            TRACKER.validate_journal(candidate)

        sol_only = TRACKER.initialize("private-run", "SOL_ONLY", at="2026-08-26T00:00:00+00:00")
        with self.assertRaisesRegex(TRACKER.TrackerError, "luna_execution"):
            TRACKER.start(sol_only, "luna_execution", at="2026-08-26T00:00:00+00:00")

        luna = TRACKER.initialize("private-run", "SOL_LUNA", at="2026-08-26T00:00:00+00:00")
        with self.assertRaisesRegex(TRACKER.TrackerError, "sol_execution"):
            TRACKER.start(luna, "sol_execution", at="2026-08-26T00:00:00+00:00")

    def test_validate_journal_rejects_unknown_top_level_fields(self) -> None:
        journal = TRACKER.initialize("private-run", "SOL_ONLY", at="2026-08-26T00:00:00+00:00")
        for field in ("raw_prompt", "extra"):
            with self.subTest(field=field):
                candidate = dict(journal)
                candidate[field] = "must not be stored"
                with self.assertRaisesRegex(TRACKER.TrackerError, "unsupported fields"):
                    TRACKER.validate_journal(candidate)


if __name__ == "__main__":
    unittest.main()
