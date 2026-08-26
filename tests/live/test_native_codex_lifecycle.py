"""Opt-in validation of a receipt produced by a real native Codex runner."""

from __future__ import annotations

import importlib.util
import json
import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "native_lifecycle_receipt.py"
SPEC = importlib.util.spec_from_file_location("native_lifecycle_receipt", SCRIPT)
assert SPEC and SPEC.loader
RECEIPT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECEIPT)


class NativeCodexLifecycleTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("SOL_LUNA_NATIVE_RECEIPT"), "native receipt path is opt-in")
    def test_host_produced_native_lifecycle_receipt(self) -> None:
        path = Path(os.environ["SOL_LUNA_NATIVE_RECEIPT"])
        result = RECEIPT.validate_receipt(json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["native_lifecycle_proven"])


if __name__ == "__main__":
    unittest.main()
