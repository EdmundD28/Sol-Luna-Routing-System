from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from common import run_cli
from opsworkbench.canonical import canonical_json


class CliAcceptance(unittest.TestCase):
    def assert_canonical_success(self, result):
        self.assertEqual((result.returncode, result.stderr), (0, b""))
        self.assertEqual(len(result.stdout.splitlines()), 1)
        parsed = json.loads(result.stdout)
        self.assertEqual(result.stdout.rstrip(b"\r\n"), canonical_json(parsed).encode("utf-8"))

    def test_A058_config_stdin_success_is_canonical_json(self):
        payload = [{"id": "base", "data": {"月": 2, "a": 1}}]
        result = run_cli("config", "--input", "-", stdin=json.dumps(payload, ensure_ascii=False).encode())
        self.assert_canonical_success(result)
        self.assertEqual(json.loads(result.stdout)["data"], {"a": 1, "月": 2})

    def test_A059_schedule_stdin_success(self):
        payload = {"jobs": [{"id": "b", "depends_on": ["a"]}, {"id": "a"}], "max_parallel": 2}
        result = run_cli("schedule", "--input", "-", stdin=json.dumps(payload).encode())
        self.assert_canonical_success(result)
        self.assertEqual(json.loads(result.stdout), {"blocked": [], "waves": [["a"], ["b"]]})

    def test_A060_results_stdin_success(self):
        payload = [{"case_id": "雪", "attempt": 1, "status": "pass", "duration_ms": 3, "finished_at": "2026-01-01"}]
        result = run_cli("results", "--input", "-", stdin=json.dumps(payload, ensure_ascii=False).encode())
        self.assert_canonical_success(result)
        self.assertEqual(json.loads(result.stdout)["counts"]["pass"], 1)
        self.assertIn("雪".encode(), result.stdout)

    def test_A061_file_input_is_not_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            original = b'[{"id":"base","data":{"x":1}}]'
            path.write_bytes(original)
            result = run_cli("config", "--input", str(path))
            self.assert_canonical_success(result)
            self.assertEqual(path.read_bytes(), original)

    def test_A062_invalid_json_is_structured_and_quiet(self):
        result = run_cli("config", "--input", "-", stdin=b"{")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(set(json.loads(result.stderr)), {"code", "path", "message", "details"})
        self.assertEqual(json.loads(result.stderr)["code"], "INVALID_JSON")

    def test_A063_domain_error_preserves_code_and_path(self):
        result = run_cli("schedule", "--input", "-", stdin=b'{"jobs":[],"max_parallel":true}')
        body = json.loads(result.stderr)
        self.assertEqual(result.returncode, 2)
        self.assertEqual((body["code"], body["path"]), ("INVALID_LIMIT", ["max_parallel"]))

    def test_A064_unknown_command_and_missing_file_are_nonzero(self):
        unknown = run_cli("other", "--input", "-", stdin=b"[]")
        self.assertEqual((unknown.returncode, unknown.stdout), (2, b""))
        unknown_body = json.loads(unknown.stderr)
        self.assertEqual(set(unknown_body), {"code", "path", "message", "details"})
        self.assertEqual(unknown_body["code"], "INVALID_CLI")
        with tempfile.TemporaryDirectory() as directory:
            missing_path = Path(directory) / "missing.json"
            missing = run_cli("results", "--input", str(missing_path))
            self.assertEqual(missing.returncode, 2)
            self.assertEqual(json.loads(missing.stderr)["code"], "IO_ERROR")

    def test_A065_output_is_repeatable_and_utf8_without_ascii_escape(self):
        payload = json.dumps([{"id": "雪", "data": {"月": 2}}], ensure_ascii=False).encode()
        first = run_cli("config", "--input", "-", stdin=payload)
        second = run_cli("config", "--input", "-", stdin=payload)
        self.assert_canonical_success(first)
        self.assert_canonical_success(second)
        self.assertEqual(first.stdout, second.stdout)
        self.assertIn("月".encode(), first.stdout)
        self.assertNotIn(b"\\u", first.stdout)

    def test_A066_large_integer_survives_cli(self):
        huge = 10**100
        payload = json.dumps([{"case_id": "x", "attempt": 1, "status": "pass", "duration_ms": huge, "finished_at": "2026"}]).encode()
        result = run_cli("results", "--input", "-", stdin=payload)
        self.assertEqual(json.loads(result.stdout)["total_duration_ms"], huge)


if __name__ == "__main__":
    unittest.main()
