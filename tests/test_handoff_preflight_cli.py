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
SCRIPT = (
    ROOT
    / ".agents"
    / "skills"
    / "sol-luna"
    / "scripts"
    / "handoff_preflight_cli.py"
)
PREFLIGHT_SCRIPT = SCRIPT.with_name("handoff_preflight.py")


def load_preflight():
    spec = importlib.util.spec_from_file_location(
        "handoff_preflight_for_cli_tests", PREFLIGHT_SCRIPT
    )
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


class HandoffPreflightCliTests(unittest.TestCase):
    def assert_cli_error(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertTrue(result.stderr.endswith("\n"))
        self.assertNotIn("Traceback", result.stderr)

    def test_template_uses_exact_utf8_lf_success_serialization(self) -> None:
        preflight = load_preflight()
        expected = json.dumps(
            preflight.template(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ) + "\n"
        result = run_cli("template")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected)
        self.assertEqual(result.stderr, "")
        raw = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "template"],
            capture_output=True,
            check=False,
        )
        self.assertEqual(raw.stdout, expected.encode("utf-8"))
        self.assertNotIn(b"\r\n", raw.stdout)

    def test_evaluate_loads_sibling_module_and_writes_no_files(self) -> None:
        preflight = load_preflight()
        source = preflight.template()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "handoff.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            before = {item.name for item in path.parent.iterdir()}
            result = run_cli("evaluate", "--input", str(path))
            after = {item.name for item in path.parent.iterdir()}
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), preflight.evaluate(source))
        self.assertEqual(result.stderr, "")
        self.assertEqual(before, after)

    def test_invalid_arguments_are_one_line_errors_without_import(self) -> None:
        argument_sets = (
            (),
            ("evaluate",),
            ("unknown",),
            ("evaluate", "--input"),
            ("evaluate", "--input", ""),
            ("template", "extra"),
        )
        with tempfile.TemporaryDirectory() as temp:
            copied_cli = Path(temp) / "handoff_preflight_cli.py"
            shutil.copy2(SCRIPT, copied_cli)
            for arguments in argument_sets:
                with self.subTest(arguments=arguments):
                    result = subprocess.run(
                        [sys.executable, "-B", str(copied_cli), *arguments],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assert_cli_error(result)

    def test_missing_non_utf8_and_invalid_json_files_fail_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assert_cli_error(
                run_cli("evaluate", "--input", str(root / "missing.json"))
            )
            invalid_utf8 = root / "invalid-utf8.json"
            invalid_utf8.write_bytes(b"\xff\xfe\x00")
            self.assert_cli_error(run_cli("evaluate", "--input", str(invalid_utf8)))
            invalid_json = root / "invalid.json"
            invalid_json.write_text("{", encoding="utf-8")
            self.assert_cli_error(run_cli("evaluate", "--input", str(invalid_json)))

    def test_duplicate_keys_and_nonfinite_values_fail_closed(self) -> None:
        preflight = load_preflight()
        valid = json.dumps(preflight.template())
        documents = (
            '{"schema_version":1,"schema_version":1}',
            valid.replace(
                '"package_id": "core-package"',
                '"package_id": "core-package", "package_id": "duplicate"',
            ),
            valid.replace('"repair_rounds": 0', '"repair_rounds": NaN'),
            valid.replace('"repair_rounds": 0', '"repair_rounds": Infinity'),
            valid.replace('"repair_rounds": 0', '"repair_rounds": 1e999'),
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.json"
            for document in documents:
                with self.subTest(document=document):
                    path.write_text(document, encoding="utf-8")
                    self.assert_cli_error(run_cli("evaluate", "--input", str(path)))

    def test_preflight_validation_and_import_failures_are_one_line(self) -> None:
        preflight = load_preflight()
        source = preflight.template()
        source["unexpected"] = True
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "input.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            self.assert_cli_error(run_cli("evaluate", "--input", str(path)))

            copied_cli = root / "handoff_preflight_cli.py"
            shutil.copy2(SCRIPT, copied_cli)
            broken = root / "handoff_preflight.py"
            broken.write_text("this is not valid python", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-B", str(copied_cli), "template"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assert_cli_error(result)

            broken.write_text(
                "print('import noise')\nraise RuntimeError('broken import')\n",
                encoding="utf-8",
            )
            noisy = subprocess.run(
                [sys.executable, "-B", str(copied_cli), "template"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assert_cli_error(noisy)


if __name__ == "__main__":
    unittest.main()
