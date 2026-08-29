from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "handoff_review_cli.py"
REVIEW_SCRIPT = SCRIPT.with_name("handoff_review.py")
JSON_SCRIPT = SCRIPT.with_name("handoff_review_json.py")


def load_review():
    spec = importlib.util.spec_from_file_location("handoff_review_for_cli_tests", REVIEW_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


class HandoffReviewCliTests(unittest.TestCase):
    def assert_cli_error(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertTrue(result.stderr.startswith("error: "))
        self.assertTrue(result.stderr.endswith("\n"))
        self.assertNotIn("Traceback", result.stderr)

    def test_template_uses_transport_serialization(self) -> None:
        review = load_review()
        expected = json.dumps(
            review.template(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ) + "\n"
        result = run_cli("template")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("__pycache__", result.stdout)

    def test_compile_and_compare_round_trip(self) -> None:
        review = load_review()
        source = review.template()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "portfolio.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            compiled = run_cli("compile", "--input", str(path))
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            expected_snapshot = review.compile_portfolio(source)
            self.assertEqual(json.loads(compiled.stdout), expected_snapshot)
            before_path = Path(temp) / "before.json"
            after_path = Path(temp) / "after.json"
            before_path.write_text(json.dumps(expected_snapshot), encoding="utf-8")
            after_path.write_text(json.dumps(expected_snapshot), encoding="utf-8")
            compared = run_cli(
                "compare", "--before", str(before_path), "--after", str(after_path)
            )
        self.assertEqual(compared.returncode, 0, compared.stderr)
        comparison = json.loads(compared.stdout)
        self.assertEqual(comparison["added_handoff_ids"], [])
        self.assertEqual(comparison["changed_handoff_ids"], [])
        self.assertEqual(compared.stderr, "")

    def test_invalid_arguments_and_input_errors_are_one_line(self) -> None:
        argument_sets = (
            (),
            ("unknown",),
            ("compile",),
            ("compile", "--input"),
            ("compare", "--before", "a"),
            ("compare", "--before", "a", "--after"),
            ("template", "extra"),
        )
        for arguments in argument_sets:
            with self.subTest(arguments=arguments):
                self.assert_cli_error(run_cli(*arguments))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assert_cli_error(run_cli("compile", "--input", str(root / "missing.json")))
            invalid = root / "invalid.json"
            invalid.write_text("{", encoding="utf-8")
            self.assert_cli_error(run_cli("compile", "--input", str(invalid)))

    def test_import_system_exit_and_keyboard_interrupt_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cli = root / SCRIPT.name
            shutil.copy2(SCRIPT, cli)
            shutil.copy2(JSON_SCRIPT, root / JSON_SCRIPT.name)
            sibling = root / REVIEW_SCRIPT.name
            for statement in ("raise SystemExit('stop')", "raise KeyboardInterrupt()"):
                sibling.write_text(statement, encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, "-B", str(cli), "template"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assert_cli_error(result)
            self.assertEqual(
                {item.name for item in root.iterdir()},
                {cli.name, JSON_SCRIPT.name, sibling.name},
            )


if __name__ == "__main__":
    unittest.main()
