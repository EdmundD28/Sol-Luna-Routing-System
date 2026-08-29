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
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "frontier_cli.py"
PLANNER_SCRIPT = SCRIPT.with_name("frontier_planner.py")
SPEC = importlib.util.spec_from_file_location("frontier_planner_for_cli_tests", PLANNER_SCRIPT)
assert SPEC and SPEC.loader
PLANNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLANNER)


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


class FrontierCliTests(unittest.TestCase):
    def test_template_uses_exact_success_serialization(self) -> None:
        result = run_cli("template")
        expected = json.dumps(
            PLANNER.template(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ) + "\n"
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected)
        self.assertEqual(result.stderr, "")
        raw = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "template"],
            capture_output=True,
            check=False,
        )
        self.assertEqual(raw.stdout, expected.encode("utf-8"))

    def test_evaluate_loads_sibling_planner_without_installation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "frontier.json"
            path.write_text(json.dumps(PLANNER.template()), encoding="utf-8")
            before = set(path.parent.iterdir())
            result = run_cli("evaluate", "--input", str(path))
            after = set(path.parent.iterdir())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), PLANNER.plan(PLANNER.template()))
        self.assertEqual(result.stderr, "")
        self.assertEqual(before, after)

    def assert_cli_error(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertTrue(result.stderr.endswith("\n"))
        self.assertNotIn("Traceback", result.stderr)

    def test_invalid_arguments_are_one_line_errors(self) -> None:
        for arguments in ((), ("evaluate",), ("unknown",), ("evaluate", "--input"), ("template", "extra")):
            with self.subTest(arguments=arguments):
                self.assert_cli_error(run_cli(*arguments))

    def test_argument_errors_do_not_import_planner_and_broken_import_is_clean(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            copied_cli = root / "frontier_cli.py"
            shutil.copy2(SCRIPT, copied_cli)
            invalid = subprocess.run(
                [sys.executable, "-B", str(copied_cli), "unknown"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assert_cli_error(invalid)
            (root / "frontier_planner.py").write_text("this is not python", encoding="utf-8")
            broken = subprocess.run(
                [sys.executable, "-B", str(copied_cli), "template"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assert_cli_error(broken)

    def test_missing_and_non_utf8_files_are_one_line_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing = run_cli("evaluate", "--input", str(root / "missing.json"))
            self.assert_cli_error(missing)
            invalid = root / "invalid.json"
            invalid.write_bytes(b"\xff\xfe\x00")
            self.assert_cli_error(run_cli("evaluate", "--input", str(invalid)))

    def test_duplicate_keys_nonfinite_constants_and_overflow_fail_closed(self) -> None:
        documents = [
            '{"schema_version":1,"schema_version":1}',
            json.dumps(PLANNER.template()).replace(
                '"controller_id": "sol-controller"',
                '"controller_id": "sol-controller", "controller_id": "duplicate"',
            ),
            json.dumps(PLANNER.template()).replace("8.0", "NaN"),
            json.dumps(PLANNER.template()).replace("8.0", "1e999"),
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.json"
            for document in documents:
                with self.subTest(document=document):
                    path.write_text(document, encoding="utf-8")
                    self.assert_cli_error(run_cli("evaluate", "--input", str(path)))

    def test_planner_validation_errors_are_one_line_and_no_stdout(self) -> None:
        value = PLANNER.template()
        value["packages"][0]["unexpected"] = 1
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            self.assert_cli_error(run_cli("evaluate", "--input", str(path)))


if __name__ == "__main__":
    unittest.main()
