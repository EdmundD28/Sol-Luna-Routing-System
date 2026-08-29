from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from importlib.util import module_from_spec, spec_from_file_location


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "handoff_review_json.py"
SPEC = spec_from_file_location("handoff_review_json_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
JSON = module_from_spec(SPEC)
SPEC.loader.exec_module(JSON)


class HandoffReviewJsonTests(unittest.TestCase):
    def test_dumps_is_sorted_utf8_indented_and_lf_terminated(self) -> None:
        value = {"z": "雪", "a": [1, {"é": True}]}
        original = copy.deepcopy(value)
        actual = JSON.dumps(value)
        expected = json.dumps(
            value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        ) + "\n"
        self.assertEqual(actual, expected)
        self.assertEqual(actual.encode("utf-8").count(b"\r"), 0)
        self.assertTrue(actual.endswith("\n"))
        self.assertEqual(value, original)

    def test_load_file_rejects_duplicate_keys_and_nonfinite_values(self) -> None:
        documents = (
            '{"schema_version":1,"schema_version":1}',
            '{"value":NaN}',
            '{"value":Infinity}',
            '{"value":-Infinity}',
            '{"value":1e999}',
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            for document in documents:
                with self.subTest(document=document):
                    path.write_text(document, encoding="utf-8")
                    with self.assertRaises(JSON.JsonTransportError):
                        JSON.load_file(path)

    def test_load_file_unifies_file_encoding_and_json_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(JSON.JsonTransportError):
                JSON.load_file(root / "missing.json")
            invalid_utf8 = root / "invalid-utf8.json"
            invalid_utf8.write_bytes(b"\xff\xfe")
            with self.assertRaises(JSON.JsonTransportError):
                JSON.load_file(invalid_utf8)
            invalid_json = root / "invalid.json"
            invalid_json.write_text("{", encoding="utf-8")
            with self.assertRaises(JSON.JsonTransportError):
                JSON.load_file(invalid_json)

    def test_dumps_rejects_nonfinite_values_without_mutating_input(self) -> None:
        for value in (math.nan, math.inf, -math.inf, {"nested": [math.nan]}):
            with self.subTest(value=repr(value)):
                original = repr(value)
                with self.assertRaises(JSON.JsonTransportError):
                    JSON.dumps(value)
                self.assertEqual(repr(value), original)


if __name__ == "__main__":
    unittest.main()
