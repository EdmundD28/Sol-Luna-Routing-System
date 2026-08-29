from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "handoff_review_json.py"
SPEC = importlib.util.spec_from_file_location("handoff_review_json_test_module", SCRIPT)
assert SPEC and SPEC.loader
TRANSPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRANSPORT)


class HandoffReviewJsonTests(unittest.TestCase):
    def test_dumps_is_sorted_indented_utf8_and_lf_terminated(self):
        self.assertEqual(TRANSPORT.dumps({"z": "é", "a": [1]}), '{\n  "a": [\n    1\n  ],\n  "z": "é"\n}\n')

    def test_load_rejects_duplicate_keys_nonfinite_and_bad_encoding(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"a": 1, "a": 2}', encoding="utf-8")
            with self.assertRaises(TRANSPORT.JsonTransportError):
                TRANSPORT.load_file(duplicate)
            nonfinite = root / "nonfinite.json"
            nonfinite.write_text('{"a": 1e999}', encoding="utf-8")
            with self.assertRaises(TRANSPORT.JsonTransportError):
                TRANSPORT.load_file(nonfinite)
            bad = root / "bad.json"
            bad.write_bytes(b"\xff")
            with self.assertRaises(TRANSPORT.JsonTransportError):
                TRANSPORT.load_file(bad)

    def test_round_trip_and_nonfinite_dump(self):
        value = {"a": [1, True, None]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "value.json"
            path.write_text(TRANSPORT.dumps(value), encoding="utf-8")
            self.assertEqual(TRANSPORT.load_file(path), value)
        with self.assertRaises(TRANSPORT.JsonTransportError):
            TRANSPORT.dumps(float("inf"))


if __name__ == "__main__":
    unittest.main()
