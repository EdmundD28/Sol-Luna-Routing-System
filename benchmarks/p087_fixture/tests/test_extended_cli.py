from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from common import run_cli
from opsworkbench.canonical import canonical_json


class ExtendedCliAcceptance(unittest.TestCase):
    def success(self, command, payload):
        result = run_cli(command, "--input", "-", stdin=json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        self.assertEqual((result.returncode, result.stderr), (0, b""))
        self.assertEqual(len(result.stdout.splitlines()), 1)
        parsed = json.loads(result.stdout)
        self.assertEqual(result.stdout.rstrip(b"\r\n"), canonical_json(parsed).encode("utf-8"))
        return parsed

    def test_A118_artifacts_inventory_and_select_payloads(self):
        item = {"artifact_id": "雪", "version": "1.0.0", "platform": "win", "architecture": "x64", "features": [], "checksum": "a" * 64, "size_bytes": 1, "metadata": {}}
        self.assertEqual(self.success("artifacts", {"operation": "inventory", "artifacts": [item]})["records"][0]["artifact_id"], "雪")
        selected = self.success("artifacts", {"operation": "select", "artifacts": [item], "request": {"artifact_id": "雪", "platform": "win", "architecture": "x64", "features": [], "allow_prerelease": False}})
        self.assertEqual(selected["version"], "1.0.0")

    def test_A119_cache_resolve_and_evict_payloads(self):
        item = {"key": "k", "value": 1, "created_at": 0, "expires_at": None, "size_bytes": 1, "dependencies": [], "last_access": 0, "pinned": False}
        hit = self.success("cache", {"operation": "resolve", "entries": [item], "request": {"key": "k", "now": 1, "allow_prefix": True}})
        self.assertEqual(hit["match"], "exact")
        plan = self.success("cache", {"operation": "evict", "entries": [item], "byte_budget": 0, "now": 1})
        self.assertEqual(plan["delete_keys"], ["k"])

    def test_A120_patches_and_rollout_payloads(self):
        patches = self.success("patches", {"patches": [{"patch_id": "p", "file": "雪.py", "start": 0, "end": 0, "replacement": "月", "depends_on": []}]})
        self.assertEqual(patches["waves"], [["p"]])
        rollout = self.success("rollout", {"targets": [{"target_id": "t", "region": "us", "ring": 0, "eligible": True, "enabled": True, "anti_affinity": None, "depends_on": []}], "request": {"rings": [0], "max_per_wave": 1, "regional_quota": {"us": 1}, "allow_spillover": True}})
        self.assertEqual(rollout["waves"][0]["target_ids"], ["t"])

    def test_A121_retention_payload_and_utf8_output(self):
        payload = {"snapshots": [{"snapshot_id": "雪", "channel": "月", "created_at": 1, "tags": [], "healthy": True, "size_bytes": 1}], "holds": [], "policy": {"keep_last": 1, "max_age": 0, "protected_tags": []}, "now": 2}
        parsed = self.success("retention", payload)
        self.assertEqual(parsed["decisions"][0]["snapshot_id"], "雪")

    def test_A122_payload_unknown_field_is_structured(self):
        result = run_cli("patches", "--input", "-", stdin=b'{"patches":[],"extra":1}')
        self.assertEqual((result.returncode, result.stdout), (2, b""))
        body = json.loads(result.stderr)
        self.assertEqual((body["code"], body["path"]), ("UNKNOWN_FIELD", ["extra"]))

    def test_A123_every_new_leaf_accepts_file_input_without_modifying_it(self):
        payloads = {
            "artifacts": {"operation": "inventory", "artifacts": []},
            "cache": {"operation": "evict", "entries": [], "byte_budget": 0, "now": 0},
            "patches": {"patches": []},
            "rollout": {"targets": [], "request": {"rings": [0], "max_per_wave": 1, "regional_quota": {"us": 1}, "allow_spillover": True}},
            "retention": {"snapshots": [], "holds": [], "policy": {"keep_last": 0, "max_age": None, "protected_tags": []}, "now": 0},
        }
        with tempfile.TemporaryDirectory() as directory:
            for command, payload in payloads.items():
                with self.subTest(command=command):
                    path = Path(directory) / f"{command}.json"
                    original = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    path.write_bytes(original)
                    result = run_cli(command, "--input", str(path))
                    self.assertEqual((result.returncode, result.stderr), (0, b""))
                    self.assertEqual(len(result.stdout.splitlines()), 1)
                    parsed = json.loads(result.stdout)
                    self.assertEqual(result.stdout.rstrip(b"\r\n"), canonical_json(parsed).encode("utf-8"))
                    self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
