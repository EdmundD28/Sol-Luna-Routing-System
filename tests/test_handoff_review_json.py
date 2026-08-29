from __future__ import annotations

import json
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "handoff_review_json.py"


def load_transport():
    spec = importlib.util.spec_from_file_location("handoff_review_json_for_tests", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HandoffReviewJsonTests(unittest.TestCase):
    def test_dumps_is_sorted_indented_utf8_and_non_mutating(self) -> None:
        transport = load_transport()
        value = {"z": "é", "a": [2, 1]}
        before = {"z": "é", "a": [2, 1]}
        self.assertEqual(
            transport.dumps(value),
            '{\n  "a": [\n    2,\n    1\n  ],\n  "z": "é"\n}\n',
        )
        self.assertEqual(value, before)

    def test_load_file_rejects_duplicate_keys_nonfinite_and_bad_encoding(self) -> None:
        transport = load_transport()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"a": 1, "a": 2}', encoding="utf-8")
            nonfinite = root / "nonfinite.json"
            nonfinite.write_text("{\"a\": NaN}", encoding="utf-8")
            invalid_utf8 = root / "invalid-utf8.json"
            invalid_utf8.write_bytes(b"\xff")
            for path in (duplicate, nonfinite, invalid_utf8):
                with self.subTest(path=path.name):
                    with self.assertRaises(transport.JsonTransportError):
                        transport.load_file(path)

    def test_dumps_rejects_nonfinite_values(self) -> None:
        transport = load_transport()
        with self.assertRaises(transport.JsonTransportError):
            transport.dumps({"value": float("nan")})
        with self.assertRaises(transport.JsonTransportError):
            transport.dumps({"value": float("inf")})

    def test_load_file_accepts_json_without_mutating_result(self) -> None:
        transport = load_transport()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "valid.json"
            path.write_text(json.dumps({"b": [1], "a": True}), encoding="utf-8")
            result = transport.load_file(path)
        self.assertEqual(result, {"b": [1], "a": True})


if __name__ == "__main__":
    unittest.main()
