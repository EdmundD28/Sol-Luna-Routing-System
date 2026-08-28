from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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

    def _legacy(self) -> dict:
        return {
            "schema_version": 1,
            "run_ref": "redacted:run:0123456789abcdef",
            "route": "SOL_ONLY",
            "created_at": "2026-08-26T00:00:00+00:00",
            "last_event_at": "2026-08-26T00:00:05+00:00",
            "open_phases": {},
            "phase_elapsed_seconds": {"sol_execution": 5},
            "phase_tokens": {"sol_execution": 10},
            "phase_credits": {},
            "events": 2,
        }

    def test_phase_duration_and_source_readings_are_accumulated(self) -> None:
        journal = TRACKER.initialize("private-run", "SOL_LUNA", at="2026-08-26T00:00:00+00:00")
        journal = TRACKER.start(
            journal, "sol_planning", executor_id="sol-main", at="2026-08-26T00:00:00+00:00"
        )
        journal = TRACKER.stop(
            journal, "sol_planning", executor_id="sol-main", at="2026-08-26T00:01:00+00:00",
            tokens=100, credits=2.5,
        )
        journal = TRACKER.start(
            journal, "luna_execution", executor_id="luna-one", at="2026-08-26T00:01:00+00:00"
        )
        journal = TRACKER.stop(
            journal, "luna_execution", executor_id="luna-one", at="2026-08-26T00:06:00+00:00",
            tokens=500, credits=5,
        )
        result = TRACKER.export(journal)
        self.assertEqual(result["elapsed_seconds"], 360)
        self.assertEqual(result["total_tokens"], 600)
        self.assertEqual(result["credit_value"], 7.5)
        self.assertEqual(result["phase_interval_counts"], {"luna_execution": 1, "sol_planning": 1})
        self.assertTrue(result["run_ref"].startswith("redacted:run:"))

    def test_interleaved_execution_overlap_and_review_exclusion(self) -> None:
        journal = TRACKER.initialize("private-run", "SOL_LUNA", at="2026-08-26T00:00:00+00:00")
        journal = TRACKER.start(
            journal, "sol_retained_execution", executor_id="sol-main", interval_id="sol-work",
            at="2026-08-26T00:00:00+00:00",
        )
        journal = TRACKER.start(
            journal, "luna_execution", executor_id="luna-one", interval_id="luna-work",
            at="2026-08-26T00:00:05+00:00",
        )
        journal = TRACKER.start(
            journal, "sol_review", executor_id="sol-main", interval_id="sol-review",
            at="2026-08-26T00:00:06+00:00",
        )
        journal = TRACKER.stop(
            journal, "sol_retained_execution", executor_id="sol-main", interval_id="sol-work",
            at="2026-08-26T00:00:10+00:00",
        )
        journal = TRACKER.stop(
            journal, "sol_review", executor_id="sol-main", interval_id="sol-review",
            at="2026-08-26T00:00:12+00:00",
        )
        journal = TRACKER.stop(
            journal, "luna_execution", executor_id="luna-one", interval_id="luna-work",
            at="2026-08-26T00:00:15+00:00",
        )
        result = TRACKER.export(journal)
        self.assertEqual(result["execution_overlap_seconds"], 5)
        self.assertEqual(result["execution_union_seconds"], 15)
        self.assertEqual(result["executor_execution_union_seconds"], {"luna-one": 10, "sol-main": 10})

    def test_same_executor_overlapping_and_adjacent_execution_is_counted_once(self) -> None:
        journal = TRACKER.initialize("private-run", "SOL_ONLY", at="2026-08-26T00:00:00+00:00")
        for interval_id, start, end in (
            ("first", 0, 10), ("second", 5, 15), ("third", 15, 20)
        ):
            journal = TRACKER.start(
                journal, "sol_execution", executor_id="sol-main", interval_id=interval_id,
                at=f"2026-08-26T00:00:{start:02d}+00:00",
            )
            journal = TRACKER.stop(
                journal, "sol_execution", executor_id="sol-main", interval_id=interval_id,
                at=f"2026-08-26T00:00:{end:02d}+00:00",
            )
        result = TRACKER.export(journal)
        self.assertEqual(result["executor_execution_union_seconds"]["sol-main"], 20)
        self.assertEqual(result["execution_union_seconds"], 20)
        self.assertEqual(result["phase_elapsed_seconds"]["sol_execution"], 25)

    def test_multiple_open_intervals_require_precise_close(self) -> None:
        journal = TRACKER.initialize("private-run", "SOL_LUNA", at="2026-08-26T00:00:00+00:00")
        for interval_id in ("repair-one", "repair-two"):
            journal = TRACKER.start(
                journal, "repair", executor_id="luna-one", interval_id=interval_id,
                at="2026-08-26T00:00:00+00:00",
            )
        with self.assertRaisesRegex(TRACKER.TrackerError, "multiple matching"):
            TRACKER.stop(
                journal, "repair", executor_id="luna-one", at="2026-08-26T00:00:01+00:00"
            )
        journal = TRACKER.stop(
            journal, "repair", executor_id="luna-one", interval_id="repair-one",
            at="2026-08-26T00:00:01+00:00",
        )
        self.assertEqual([item["interval_id"] for item in journal["open_intervals"]], ["repair-two"])

        neutral = TRACKER.initialize("private-run", "SOL_LUNA", at="2026-08-26T00:00:00+00:00")
        neutral = TRACKER.start(
            neutral, "repair", executor_id="worker-one", actor="SOL",
            interval_id="neutral-repair", at="2026-08-26T00:00:00+00:00",
        )
        self.assertEqual(neutral["open_intervals"][0]["actor"], "SOL")

    def test_route_phase_and_actor_constraints_fail_closed(self) -> None:
        sol_only = TRACKER.initialize("private-run", "SOL_ONLY", at="2026-08-26T00:00:00+00:00")
        for phase, executor_id in (
            ("luna_execution", "luna-one"),
            ("sol_retained_execution", "sol-main"),
            ("sol_planning", "luna-one"),
        ):
            with self.subTest(phase=phase), self.assertRaises(TRACKER.TrackerError):
                TRACKER.start(sol_only, phase, executor_id=executor_id, at="2026-08-26T00:00:00+00:00")
        sol_luna = TRACKER.initialize("private-run", "SOL_LUNA", at="2026-08-26T00:00:00+00:00")
        with self.assertRaisesRegex(TRACKER.TrackerError, "sol_execution"):
            TRACKER.start(
                sol_luna, "sol_execution", executor_id="sol-main", at="2026-08-26T00:00:00+00:00"
            )

    def test_non_string_route_identity_and_phase_fail_as_tracker_errors(self) -> None:
        with self.assertRaises(TRACKER.TrackerError):
            TRACKER.initialize("private-run", [])

        journal = TRACKER.initialize("private-run", "SOL_ONLY")
        malformed = dict(journal)
        malformed["route"] = []
        with self.assertRaises(TRACKER.TrackerError):
            TRACKER.validate_journal(malformed)
        for phase, executor_id, interval_id in (
            ([], "sol-main", None),
            ("sol_execution", [], None),
            ("sol_execution", "sol-main", {}),
        ):
            with self.subTest(phase=phase, executor_id=executor_id, interval_id=interval_id):
                with self.assertRaises(TRACKER.TrackerError):
                    TRACKER.start(
                        journal, phase, executor_id=executor_id, interval_id=interval_id,
                    )
        with self.assertRaises(TRACKER.TrackerError):
            TRACKER.stop(journal, [], executor_id="sol-main")

    def test_cli_non_string_route_fails_with_one_tracker_error_line(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "phase.json"
            path.write_text(json.dumps({"schema_version": 2, "route": []}), encoding="utf-8")
            completed = self._run_cli("export", "--journal", str(path))
            self.assertNotEqual(completed.returncode, 0)
            self.assertNotIn("Traceback", completed.stderr)
            self.assertEqual(len(completed.stderr.splitlines()), 1)

    def test_export_fails_closed_when_finite_credits_overflow(self) -> None:
        largest = math.nextafter(float("inf"), 0.0)
        journal = TRACKER.initialize("private-run", "SOL_ONLY", at="2026-08-26T00:00:00+00:00")
        for interval_id, start, end in (("first", 0, 1), ("second", 1, 2)):
            journal = TRACKER.start(
                journal, "sol_execution", executor_id="sol-main", interval_id=interval_id,
                at=f"2026-08-26T00:00:0{start}+00:00",
            )
            journal = TRACKER.stop(
                journal, "sol_execution", executor_id="sol-main", interval_id=interval_id,
                at=f"2026-08-26T00:00:0{end}+00:00", credits=largest,
            )
        with self.assertRaisesRegex(TRACKER.TrackerError, "aggregate is not finite"):
            TRACKER.export(journal)

    def test_cli_export_finite_credit_overflow_has_no_non_finite_output(self) -> None:
        largest = math.nextafter(float("inf"), 0.0)
        journal = TRACKER.initialize("private-run", "SOL_ONLY", at="2026-08-26T00:00:00+00:00")
        for interval_id, start, end in (("first", 0, 1), ("second", 1, 2)):
            journal = TRACKER.start(
                journal, "sol_execution", executor_id="sol-main", interval_id=interval_id,
                at=f"2026-08-26T00:00:0{start}+00:00",
            )
            journal = TRACKER.stop(
                journal, "sol_execution", executor_id="sol-main", interval_id=interval_id,
                at=f"2026-08-26T00:00:0{end}+00:00", credits=largest,
            )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "phase.json"
            TRACKER.atomic_write(path, journal)
            completed = self._run_cli("export", "--journal", str(path))
            self.assertNotEqual(completed.returncode, 0)
            self.assertNotIn("Infinity", completed.stdout)
            self.assertNotIn("NaN", completed.stdout)
            self.assertNotIn("Traceback", completed.stderr)

    def test_end_before_own_start_is_rejected_without_global_order_constraint(self) -> None:
        journal = TRACKER.initialize("private-run", "SOL_LUNA", at="2026-08-26T00:00:00+00:00")
        journal = TRACKER.start(
            journal, "sol_review", executor_id="sol-main", interval_id="review",
            at="2026-08-26T00:00:10+00:00",
        )
        journal = TRACKER.start(
            journal, "luna_execution", executor_id="luna-one", interval_id="work",
            at="2026-08-26T00:00:05+00:00",
        )
        journal = TRACKER.stop(
            journal, "luna_execution", executor_id="luna-one", interval_id="work",
            at="2026-08-26T00:00:08+00:00",
        )
        with self.assertRaisesRegex(TRACKER.TrackerError, "precedes"):
            TRACKER.stop(
                journal, "sol_review", executor_id="sol-main", interval_id="review",
                at="2026-08-26T00:00:09+00:00",
            )

    def test_run_wrapper_closes_interval_on_nonzero_and_launch_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            journal_path = Path(temp) / "phase.json"
            TRACKER.atomic_write(journal_path, TRACKER.initialize("private-run", "SOL_LUNA"))
            exit_code, output = TRACKER.run_command(
                journal_path, "luna_execution", [sys.executable, "-c", "raise SystemExit(7)"],
                executor_id="luna-one", interval_id="failed-command", tokens=12, credits=3,
            )
            self.assertEqual(exit_code, 7)
            self.assertEqual(output["command_exit_code"], 7)
            self.assertEqual(TRACKER.load(journal_path)["open_intervals"], [])
            exit_code, output = TRACKER.run_command(
                journal_path, "luna_execution", [str(Path(temp) / "missing-program")],
                executor_id="luna-one", interval_id="launch-error",
            )
            self.assertEqual(exit_code, 127)
            self.assertIsNotNone(output["command_launch_error"])
            stored = TRACKER.load(journal_path)
            self.assertEqual(stored["open_intervals"], [])
            self.assertIsNotNone(stored["phase_intervals"][-1]["command_launch_error"])

    def test_legacy_schema_is_readable_and_exportable_but_not_writable(self) -> None:
        legacy = self._legacy()
        self.assertEqual(TRACKER.export(legacy)["source_schema_version"], 1)
        with self.assertRaisesRegex(TRACKER.TrackerError, "read-only"):
            TRACKER.start(legacy, "sol_execution", executor_id="sol-main")
        with self.assertRaisesRegex(TRACKER.TrackerError, "read-only"):
            TRACKER.stop(legacy, "sol_execution", executor_id="sol-main")

    def test_atomic_replace_failure_preserves_bytes_and_cleans_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "phase.json"
            original = b"original bytes\n"
            path.write_bytes(original)
            with mock.patch.object(TRACKER.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    TRACKER.atomic_write(path, TRACKER.initialize("private-run", "SOL_ONLY"))
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_cli_refuses_overwrite_and_rejects_bad_json_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "phase.json"
            original = b"do not overwrite\n"
            path.write_bytes(original)
            completed = self._run_cli(
                "init", "--journal", str(path), "--run-ref", "cli", "--route", "SOL_ONLY"
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(path.read_bytes(), original)

            for payload in ('{"schema_version":2,"schema_version":2}', '{"schema_version":NaN}'):
                path.write_text(payload, encoding="utf-8")
                completed = self._run_cli("export", "--journal", str(path))
                self.assertNotEqual(completed.returncode, 0)
                self.assertNotIn("Traceback", completed.stderr)
            path.write_bytes(b"\xff\xfe")
            completed = self._run_cli("export", "--journal", str(path))
            self.assertNotEqual(completed.returncode, 0)
            self.assertNotIn("Traceback", completed.stderr)

    def test_cli_lifecycle_records_executor_interval_and_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "phase.json"
            init = self._run_cli(
                "init", "--journal", str(path), "--run-ref", "cli-smoke", "--route", "SOL_LUNA",
                "--at", "2026-08-26T00:00:00+00:00",
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            start = self._run_cli(
                "start", "--journal", str(path), "--phase", "sol_planning",
                "--executor-id", "sol-main", "--interval-id", "planning",
                "--at", "2026-08-26T00:00:01+00:00",
            )
            self.assertEqual(start.returncode, 0, start.stderr)
            stop = self._run_cli(
                "stop", "--journal", str(path), "--phase", "sol_planning",
                "--executor-id", "sol-main", "--interval-id", "planning",
                "--at", "2026-08-26T00:00:02+00:00", "--tokens", "3", "--credits", "1.5",
            )
            self.assertEqual(stop.returncode, 0, stop.stderr)
            run = self._run_cli(
                "run", "--journal", str(path), "--phase", "luna_execution",
                "--executor-id", "luna-one", "--interval-id", "command", "--tokens", "4",
                "--", sys.executable, "-c", "raise SystemExit(7)",
            )
            self.assertEqual(run.returncode, 7, run.stderr)
            output = json.loads(run.stdout)
            self.assertEqual(output["command_exit_code"], 7)
            self.assertEqual(output["total_tokens"], 7)
            self.assertEqual(TRACKER.load(path)["open_intervals"], [])

    def test_invalid_metrics_unknown_fields_and_open_export_are_rejected(self) -> None:
        journal = TRACKER.initialize("private-run", "SOL_ONLY", at="2026-08-26T00:00:00+00:00")
        journal = TRACKER.start(
            journal, "sol_execution", executor_id="sol-main", at="2026-08-26T00:00:00+00:00"
        )
        with self.assertRaisesRegex(TRACKER.TrackerError, "open intervals"):
            TRACKER.export(journal)
        for tokens, credits in ((True, None), (1.5, None), (None, float("nan")), (None, -1)):
            with self.subTest(tokens=tokens, credits=credits), self.assertRaises(TRACKER.TrackerError):
                TRACKER.stop(
                    journal, "sol_execution", executor_id="sol-main",
                    at="2026-08-26T00:00:01+00:00", tokens=tokens, credits=credits,
                )
        candidate = TRACKER.initialize("private-run", "SOL_ONLY")
        candidate["extra"] = True
        with self.assertRaisesRegex(TRACKER.TrackerError, "unsupported fields"):
            TRACKER.validate_journal(candidate)

    def test_run_invalid_metrics_preserve_journal_and_large_numbers_fail_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "phase.json"
            TRACKER.atomic_write(path, TRACKER.initialize("private-run", "SOL_ONLY"))
            original = path.read_bytes()
            for tokens, credits in ((True, None), (None, float("nan")), (None, 10**10000)):
                with self.subTest(tokens=tokens, credits=credits), self.assertRaises(TRACKER.TrackerError):
                    TRACKER.run_command(
                        path, "sol_execution", [sys.executable, "-c", "raise SystemExit(3)"],
                        executor_id="sol-main", tokens=tokens, credits=credits,
                    )
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(TRACKER.load(path)["open_intervals"], [])

    def test_run_value_error_from_subprocess_is_a_closed_launch_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "phase.json"
            TRACKER.atomic_write(path, TRACKER.initialize("private-run", "SOL_ONLY"))
            with mock.patch.object(TRACKER.subprocess, "run", side_effect=ValueError("embedded null")):
                exit_code, output = TRACKER.run_command(
                    path, "sol_execution", ["not-a-real-command"], executor_id="sol-main",
                )
            self.assertEqual(exit_code, 127)
            self.assertIn("embedded null", output["command_launch_error"])
            self.assertEqual(TRACKER.load(path)["open_intervals"], [])

    def test_cli_run_non_finite_credit_does_not_modify_journal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "phase.json"
            TRACKER.atomic_write(path, TRACKER.initialize("private-run", "SOL_ONLY"))
            original = path.read_bytes()
            for credit in ("NaN", "Infinity", "-Infinity"):
                with self.subTest(credit=credit):
                    completed = self._run_cli(
                        "run", "--journal", str(path), "--phase", "sol_execution",
                        "--executor-id", "sol-main", "--credits", credit,
                        "--", "missing-command",
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertNotIn("Traceback", completed.stderr)
                    self.assertEqual(path.read_bytes(), original)
                    self.assertEqual(TRACKER.load(path)["open_intervals"], [])


if __name__ == "__main__":
    unittest.main()
