from __future__ import annotations

import math
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).parents[1] / ".agents" / "skills" / "sol-luna" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import handoff_review_json as transport


class HandoffReviewJsonTests(unittest.TestCase):
    def test_dumps_is_sorted_indented_unicode_and_lf_terminated(self) -> None:
        self.assertEqual('{\n  "a": "café",\n  "z": [\n    1,\n    2\n  ]\n}\n', transport.dumps({"z": [1, 2], "a": "café"}))
        self.assertFalse(transport.dumps({"x": 1}).endswith("\n\n"))

    def test_dumps_rejects_non_finite_values(self) -> None:
        for value in [math.nan, math.inf, -math.inf]:
            with self.subTest(value=value), self.assertRaises(transport.JsonTransportError):
                transport.dumps({"value": value})

    def test_load_file_rejects_duplicate_keys_non_finite_and_bad_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"a": 1, "a": 2}', encoding="utf-8")
            with self.assertRaises(transport.JsonTransportError):
                transport.load_file(duplicate)

            non_finite = root / "non-finite.json"
            non_finite.write_text('{"a": NaN}', encoding="utf-8")
            with self.assertRaises(transport.JsonTransportError):
                transport.load_file(non_finite)

            invalid_utf8 = root / "invalid.json"
            invalid_utf8.write_bytes(b"{\xff}")
            with self.assertRaises(transport.JsonTransportError):
                transport.load_file(invalid_utf8)

            with self.assertRaises(transport.JsonTransportError):
                transport.load_file(root / "missing.json")

    def test_load_file_returns_json_without_rewriting_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            original = '{\n  "b": 2,\n  "a": 1\n}\n'
            path.write_text(original, encoding="utf-8")
            self.assertEqual({"a": 1, "b": 2}, transport.load_file(path))
            self.assertEqual(original, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

