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
CLI = SCRIPTS / "handoff_review_cli.py"


def load_module(name: str):
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-B", str(CLI), *args], capture_output=True, text=True, check=False)


class HandoffReviewCliTests(unittest.TestCase):
    def assert_error(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertTrue(result.stderr.startswith("error: "))
        self.assertTrue(result.stderr.endswith("\n"))
        self.assertNotIn("Traceback", result.stderr)

    def test_template_compile_and_compare(self) -> None:
        review = load_module("handoff_review.py")
        transport = load_module("handoff_review_json.py")
        template_result = run_cli("template")
        self.assertEqual(template_result.returncode, 0, template_result.stderr)
        self.assertEqual(template_result.stdout, transport.dumps(review.template()))
        self.assertEqual(template_result.stderr, "")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            portfolio = root / "portfolio.json"
            portfolio.write_text(json.dumps(review.template()), encoding="utf-8")
            compiled_result = run_cli("compile", "--input", str(portfolio))
            self.assertEqual(compiled_result.returncode, 0, compiled_result.stderr)
            snapshot = json.loads(compiled_result.stdout)
            before = root / "before.json"
            after = root / "after.json"
            before.write_text(json.dumps(snapshot), encoding="utf-8")
            after.write_text(json.dumps(snapshot), encoding="utf-8")
            compared = run_cli("compare", "--before", str(before), "--after", str(after))
            self.assertEqual(compared.returncode, 0, compared.stderr)
            self.assertEqual(json.loads(compared.stdout)["changed_handoff_ids"], [])

    def test_argument_file_json_and_validation_errors(self) -> None:
        for args in ((), ("unknown",), ("compile", "--input"), ("compare", "--after", "x", "--before", "y")):
            with self.subTest(args=args):
                self.assert_error(run_cli(*args))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            path.write_text('{"a":1,"a":2}', encoding="utf-8")
            self.assert_error(run_cli("compile", "--input", str(path)))
            self.assert_error(run_cli("compile", "--input", str(path.with_name("missing.json"))))

    def test_import_systemexit_keyboardinterrupt_and_noise_are_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copy2(CLI, root / CLI.name)
            shutil.copy2(SCRIPTS / "handoff_review_json.py", root / "handoff_review_json.py")
            sibling = root / "handoff_review.py"
            for body in ("raise SystemExit(7)\n", "raise KeyboardInterrupt()\n", "print('noise')\ndef template(): return {}\ndef compile_portfolio(x): return {}\ndef compare(a,b): return {}\n"):
                sibling.write_text(body, encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, "-B", str(root / CLI.name), "template"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assert_error(result)
            self.assertFalse((root / "__pycache__").exists())


if __name__ == "__main__":
    unittest.main()
