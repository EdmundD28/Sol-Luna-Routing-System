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
SCRIPTS = ROOT / ".agents" / "skills" / "sol-luna" / "scripts"
SCRIPT = SCRIPTS / "handoff_review_cli.py"
JSON_SCRIPT = SCRIPTS / "handoff_review_json.py"
CORE_SCRIPT = SCRIPTS / "handoff_review.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_cli(*arguments: str, script: Path = SCRIPT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(script), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


class HandoffReviewCliTests(unittest.TestCase):
    def assert_cli_error(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.endswith("\n"))
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertTrue(result.stderr.startswith("error: "))
        self.assertNotIn("Traceback", result.stderr)

    def test_template_matches_transport_exactly(self) -> None:
        core = load_module(CORE_SCRIPT, "handoff_review_for_cli_tests")
        transport = load_module(JSON_SCRIPT, "handoff_review_json_for_cli_tests")
        result = run_cli("template")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, transport.dumps(core.template()))
        self.assertEqual(result.stderr, "")
        self.assertNotIn("\r\n", result.stdout)

    def test_compile_and_compare_use_files_without_creating_files(self) -> None:
        core = load_module(CORE_SCRIPT, "handoff_review_for_cli_tests_2")
        transport = load_module(JSON_SCRIPT, "handoff_review_json_for_cli_tests_2")
        source = core.template()
        compiled_snapshot = core.compile_portfolio(source)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.json"
            before_path = root / "before.json"
            after_path = root / "after.json"
            input_path.write_text(transport.dumps(source), encoding="utf-8")
            before_path.write_text(transport.dumps(compiled_snapshot), encoding="utf-8")
            after_path.write_text(transport.dumps(compiled_snapshot), encoding="utf-8")
            before_files = {path.name for path in root.iterdir()}
            compiled = run_cli("compile", "--input", str(input_path))
            compared = run_cli(
                "compare", "--before", str(before_path), "--after", str(after_path)
            )
            after_files = {path.name for path in root.iterdir()}
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        self.assertEqual(json.loads(compiled.stdout), core.compile_portfolio(source))
        self.assertEqual(compared.returncode, 0, compared.stderr)
        self.assertEqual(
            json.loads(compared.stdout),
            core.compare(compiled_snapshot, compiled_snapshot),
        )
        self.assertEqual(compiled.stderr, "")
        self.assertEqual(compared.stderr, "")
        self.assertEqual(before_files, after_files)

    def test_invalid_arguments_and_input_fail_as_one_line_errors(self) -> None:
        argument_sets = (
            (),
            ("unknown",),
            ("compile",),
            ("compile", "--input"),
            ("compile", "--input", ""),
            ("compare", "--before", "a", "--after"),
            ("compare", "--before", "", "--after", "b"),
        )
        for arguments in argument_sets:
            with self.subTest(arguments=arguments):
                self.assert_cli_error(run_cli(*arguments))
        with tempfile.TemporaryDirectory() as directory:
            self.assert_cli_error(run_cli("compile", "--input", str(Path(directory) / "missing")))

    def test_import_stage_system_exit_and_keyboard_interrupt_are_status_two(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copied_cli = root / SCRIPT.name
            shutil.copy2(SCRIPT, copied_cli)
            (root / JSON_SCRIPT.name).write_text("raise SystemExit('stop')\n", encoding="utf-8")
            self.assert_cli_error(run_cli("template", script=copied_cli))
            (root / JSON_SCRIPT.name).write_text("raise KeyboardInterrupt()\n", encoding="utf-8")
            self.assert_cli_error(run_cli("template", script=copied_cli))
            self.assertEqual(
                {path.name for path in root.iterdir()},
                {SCRIPT.name, JSON_SCRIPT.name},
            )


if __name__ == "__main__":
    unittest.main()
