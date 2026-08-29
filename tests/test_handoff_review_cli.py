from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "handoff_review_cli.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-B", str(SCRIPT), *args], capture_output=True, text=True, check=False)


class HandoffReviewCliTests(unittest.TestCase):
    def test_template_success_is_json_only(self):
        result = run_cli("template")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(json.loads(result.stdout)["portfolio_id"], "release-alpha")
        self.assertTrue(result.stdout.endswith("\n"))

    def test_compile_and_compare(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "portfolio.json"
            template = json.loads(run_cli("template").stdout)
            path.write_text(json.dumps(template), encoding="utf-8")
            compiled = run_cli("compile", "--input", str(path))
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            snapshot = json.loads(compiled.stdout)
            before = Path(temp) / "before.json"
            after = Path(temp) / "after.json"
            before.write_text(json.dumps(snapshot), encoding="utf-8")
            after.write_text(json.dumps(snapshot), encoding="utf-8")
            compared = run_cli("compare", "--before", str(before), "--after", str(after))
            self.assertEqual(compared.returncode, 0, compared.stderr)
            self.assertEqual(json.loads(compared.stdout)["changed_handoff_ids"], [])

    def test_all_errors_are_single_line_and_no_stdout(self):
        for args in ((), ("unknown",), ("compile", "--input"), ("compare", "--before", "x")):
            with self.subTest(args=args):
                result = run_cli(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertEqual(len(result.stderr.splitlines()), 1)
                self.assertTrue(result.stderr.startswith("error: "))
                self.assertNotIn("Traceback", result.stderr)

    def test_duplicate_json_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            path.write_text('{"schema_version": 1, "schema_version": 1}', encoding="utf-8")
            result = run_cli("compile", "--input", str(path))
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertTrue(result.stderr.startswith("error: "))


if __name__ == "__main__":
    unittest.main()
