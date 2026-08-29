from __future__ import annotations

import importlib.util
import math
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "handoff_review_json.py"
SPEC = importlib.util.spec_from_file_location("handoff_review_json", SCRIPT)
assert SPEC and SPEC.loader
TRANSPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRANSPORT)


class HandoffReviewJsonTests(unittest.TestCase):
    def test_load_and_exact_dump(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.json"
            path.write_text('{"z":"雪","a":1}', encoding="utf-8")
            value = TRANSPORT.load_file(path)
        self.assertEqual(TRANSPORT.dumps(value), '{\n  "a": 1,\n  "z": "雪"\n}\n')

    def test_duplicate_nonfinite_invalid_utf8_and_missing_rejected(self) -> None:
        documents = [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}', b'{']
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.json"
            for document in documents:
                path.write_bytes(document)
                with self.subTest(document=document), self.assertRaises(TRANSPORT.JsonTransportError):
                    TRANSPORT.load_file(path)
            path.write_bytes(b"\xff")
            with self.assertRaises(TRANSPORT.JsonTransportError):
                TRANSPORT.load_file(path)
            with self.assertRaises(TRANSPORT.JsonTransportError):
                TRANSPORT.load_file(path.with_name("missing.json"))

    def test_dump_rejects_nonfinite(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaises(TRANSPORT.JsonTransportError):
                TRANSPORT.dumps({"value": value})


if __name__ == "__main__":
    unittest.main()
