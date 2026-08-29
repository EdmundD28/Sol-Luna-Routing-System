from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).parents[1]
CLI = REPO / ".agents" / "skills" / "sol-luna" / "scripts" / "handoff_review_cli.py"


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-B", str(CLI), *arguments],
        cwd=REPO,
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


class HandoffReviewCliTests(unittest.TestCase):
    def test_template_is_exact_json_stdout_only(self) -> None:
        result = run_cli("template")
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stderr)
        self.assertTrue(result.stdout.endswith("\n"))
        self.assertEqual(1, json.loads(result.stdout)["schema_version"])

    def test_compile_and_compare_commands(self) -> None:
        template = json.loads(run_cli("template").stdout)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = root / "before.json"
            after = root / "after.json"
            before.write_text(json.dumps(template), encoding="utf-8")
            after.write_text(json.dumps(template), encoding="utf-8")
            compiled = run_cli("compile", "--input", str(before))
            self.assertEqual(0, compiled.returncode)
            self.assertEqual("", compiled.stderr)
            compiled_value = json.loads(compiled.stdout)
            self.assertIn("snapshot_fingerprint", compiled_value)
            before_snapshot = root / "before-snapshot.json"
            after_snapshot = root / "after-snapshot.json"
            before_snapshot.write_text(compiled.stdout, encoding="utf-8")
            after_snapshot.write_text(compiled.stdout, encoding="utf-8")
            comparison = run_cli("compare", "--before", str(before_snapshot), "--after", str(after_snapshot))
            self.assertEqual(0, comparison.returncode)
            self.assertEqual("", comparison.stderr)
            self.assertEqual([], json.loads(comparison.stdout)["changed_handoff_ids"])

    def test_invalid_arguments_and_missing_file_have_one_error_line(self) -> None:
        for arguments in [(), ("unknown",), ("compile", "--input", "missing.json")]:
            with self.subTest(arguments=arguments):
                result = run_cli(*arguments)
                self.assertEqual(2, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertTrue(result.stderr.startswith("error: "))
                self.assertEqual(1, len(result.stderr.splitlines()))

    def test_success_and_error_do_not_create_bytecode(self) -> None:
        pycache = CLI.parent / "__pycache__"
        before = set(pycache.iterdir()) if pycache.exists() else set()
        self.assertEqual(0, run_cli("template").returncode)
        self.assertEqual(2, run_cli("bad").returncode)
        after = set(pycache.iterdir()) if pycache.exists() else set()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
