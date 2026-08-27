from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "benchmark_identity.py"
SPEC = importlib.util.spec_from_file_location("benchmark_identity", SCRIPT)
assert SPEC and SPEC.loader
IDENTITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IDENTITY)


def observed(value: str) -> dict:
    return {"value": value, "provenance": "host_observed"}


def requested(value: str | None) -> dict:
    if value is None:
        return {"value": None, "provenance": "unknown", "issue": "not supplied to receipt tool"}
    return {"value": value, "provenance": "requested"}


def receipt(*, model: str, role: str, marker: str) -> dict:
    return {
        "schema_version": 1,
        "status": "verified",
        "thread_ref": f"redacted:thread:{marker}",
        "source_ref": f"redacted:session:{marker}",
        "source_kind": "explicit_session_jsonl",
        "invalid_jsonl_lines": 0,
        "source_warnings": [],
        "requested": {
            "agent": requested(role),
            "model": requested(model),
            "effort": requested("high"),
            "sandbox_policy_type": requested(None),
            "permission_profile_type": requested(None),
        },
        "host_observed": {
            "agent_role": observed(role),
            "agent_path_ref": observed(f"redacted:agent-path:{marker}"),
            "model_provider": observed("openai"),
            "model": observed(model),
            "effort": observed("high"),
            "sandbox_policy_type": observed("workspace-write"),
            "permission_profile_type": observed("managed"),
            "cwd_ref": observed(f"redacted:cwd:{marker}"),
        },
        "mismatches": [],
        "unknown_identity_fields": [],
        "unknown_boundary_fields": [],
        "self_report_used_as_proof": False,
    }


class BenchmarkIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        (self.directory / "receipts").mkdir()
        self.manifest = self.directory / "manifest.json"
        self.output = self.directory / "index.json"

    def write_receipt(self, name: str, value: dict) -> str:
        path = self.directory / "receipts" / name
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return f"receipts/{name}"

    def valid_manifest(self) -> dict:
        return {
            "schema_version": 1,
            "campaign_id": "campaign-001",
            "runs": [
                {
                    "pair_id": "pair-001",
                    "route": "SOL_ONLY",
                    "controller_receipt": self.write_receipt(
                        "sol-only.json", receipt(model="gpt-5.6-sol", role="default", marker="sol-only")
                    ),
                    "worker_receipts": [],
                },
                {
                    "pair_id": "pair-001",
                    "route": "SOL_LUNA",
                    "controller_receipt": self.write_receipt(
                        "controller.json", receipt(model="gpt-5.6-sol", role="default", marker="controller")
                    ),
                    "worker_receipts": [
                        self.write_receipt(
                            "luna-a.json", receipt(model="gpt-5.6-luna", role="luna_worker", marker="luna-a")
                        ),
                        self.write_receipt(
                            "luna-b.json", receipt(model="gpt-5.6-luna", role="worker", marker="luna-b")
                        ),
                    ],
                },
            ],
        }

    def write_manifest(self, value: dict) -> None:
        self.manifest.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def test_valid_sol_only_and_sol_luna_index_is_redacted_and_self_digesting(self) -> None:
        self.write_manifest(self.valid_manifest())
        index = IDENTITY.build(self.manifest, self.output)
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), index)
        digest = index.pop("index_sha256")
        self.assertEqual(digest, IDENTITY.sha256_bytes(IDENTITY.canonical_bytes(index)))
        rendered = json.dumps(index)
        for secret in ("receipts/", "source_ref", "thread_ref", "cwd_ref", "agent_path_ref"):
            self.assertNotIn(secret, rendered)
        self.assertEqual(index["verification_status"], "verified")
        luna_run = next(run for run in index["runs"] if run["route"] == "SOL_LUNA")
        self.assertEqual(len(luna_run["workers"]), 2)
        self.assertTrue(all(run["controller"]["provider"] == "openai" for run in index["runs"]))

    def test_host_observed_sol_worker_role_is_valid_as_sol_only_controller(self) -> None:
        manifest = self.valid_manifest()
        controller = receipt(model="gpt-5.6-sol", role="worker", marker="sol-worker-controller")
        manifest["runs"][0]["controller_receipt"] = self.write_receipt(
            "sol-worker-controller.json",
            controller,
        )
        self.write_manifest(manifest)
        index = IDENTITY.build_index(self.manifest)
        sol_only = next(run for run in index["runs"] if run["route"] == "SOL_ONLY")
        self.assertEqual(sol_only["controller"]["role"], "worker")
        self.assertEqual(sol_only["controller"]["model"], "gpt-5.6-sol")
        self.assertEqual(sol_only["controller"]["effort"], "high")
        self.assertEqual(sol_only["controller"]["provider"], "openai")
        self.assertEqual(
            sol_only["controller"]["receipt_sha256"],
            IDENTITY.sha256_bytes(IDENTITY.canonical_bytes(controller)),
        )
        self.assertEqual(sol_only["workers"], [])

    def test_luna_cannot_impersonate_sol_controller(self) -> None:
        manifest = self.valid_manifest()
        bad = receipt(model="gpt-5.6-luna", role="default", marker="impostor")
        manifest["runs"][0]["controller_receipt"] = self.write_receipt("impostor.json", bad)
        self.write_manifest(manifest)
        with self.assertRaisesRegex(IDENTITY.IdentityError, "Sol|gpt-5.6-sol"):
            IDENTITY.build_index(self.manifest)

    def test_sol_cannot_impersonate_luna_writer(self) -> None:
        manifest = self.valid_manifest()
        bad = receipt(model="gpt-5.6-sol", role="luna_worker", marker="impostor")
        manifest["runs"][1]["worker_receipts"] = [self.write_receipt("impostor.json", bad)]
        self.write_manifest(manifest)
        with self.assertRaisesRegex(IDENTITY.IdentityError, "Luna|gpt-5.6-luna"):
            IDENTITY.build_index(self.manifest)

    def test_self_report_unknown_identity_and_non_host_provenance_fail_closed(self) -> None:
        variants = []
        source = receipt(model="gpt-5.6-sol", role="default", marker="bad")
        source["self_report_used_as_proof"] = True
        variants.append(source)
        source = receipt(model="gpt-5.6-sol", role="default", marker="bad")
        source["unknown_identity_fields"] = ["model"]
        variants.append(source)
        source = receipt(model="gpt-5.6-sol", role="default", marker="bad")
        source["host_observed"]["model"] = requested("gpt-5.6-sol")
        variants.append(source)
        for index, bad in enumerate(variants):
            with self.subTest(index=index):
                manifest = self.valid_manifest()
                manifest["runs"][0]["controller_receipt"] = self.write_receipt(f"bad-{index}.json", bad)
                self.write_manifest(manifest)
                with self.assertRaises(IDENTITY.IdentityError):
                    IDENTITY.build_index(self.manifest)

    def test_verified_receipt_may_omit_non_identity_path_observations(self) -> None:
        manifest = self.valid_manifest()
        controller = receipt(model="gpt-5.6-sol", role="default", marker="no-paths")
        unknown = {"value": None, "provenance": "unknown", "issue": "not present in host record"}
        controller["host_observed"]["agent_path_ref"] = dict(unknown)
        controller["host_observed"]["cwd_ref"] = dict(unknown)
        manifest["runs"][0]["controller_receipt"] = self.write_receipt("no-paths.json", controller)
        self.write_manifest(manifest)
        index = IDENTITY.build_index(self.manifest)
        self.assertEqual(index["verification_status"], "verified")

    def test_receipt_content_cannot_be_reused_across_runs_or_roles(self) -> None:
        manifest = self.valid_manifest()
        manifest["runs"][1]["controller_receipt"] = manifest["runs"][0]["controller_receipt"]
        self.write_manifest(manifest)
        with self.assertRaisesRegex(IDENTITY.IdentityError, "reused"):
            IDENTITY.build_index(self.manifest)

    def test_logical_receipt_reuse_rejects_different_json_format_and_key_order(self) -> None:
        manifest = self.valid_manifest()
        shared = receipt(model="gpt-5.6-sol", role="default", marker="same-logical-session")
        manifest["runs"][0]["controller_receipt"] = self.write_receipt("shared-pretty.json", shared)
        compact_path = self.directory / "receipts" / "shared-compact.json"
        compact_path.write_text(
            json.dumps(shared, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        manifest["runs"][1]["controller_receipt"] = "receipts/shared-compact.json"
        self.write_manifest(manifest)
        with self.assertRaisesRegex(IDENTITY.IdentityError, "logical receipt.*reused"):
            IDENTITY.build_index(self.manifest)

    def test_each_pair_requires_both_routes(self) -> None:
        manifest = self.valid_manifest()
        manifest["runs"].pop()
        self.write_manifest(manifest)
        with self.assertRaisesRegex(IDENTITY.IdentityError, "each route"):
            IDENTITY.build_index(self.manifest)

    def test_path_traversal_absolute_drive_control_and_device_names_are_rejected(self) -> None:
        invalid = ["../outside.json", "/absolute.json", "C:/receipt.json", "receipts/a\n.json", "CON.json"]
        for index, value in enumerate(invalid):
            with self.subTest(value=value):
                manifest = self.valid_manifest()
                manifest["runs"][0]["controller_receipt"] = value
                self.write_manifest(manifest)
                with self.assertRaises(IDENTITY.IdentityError):
                    IDENTITY.build_index(self.manifest)

    def test_unknown_or_missing_manifest_and_receipt_fields_are_rejected(self) -> None:
        manifest = self.valid_manifest()
        manifest["surprise"] = True
        self.write_manifest(manifest)
        with self.assertRaisesRegex(IDENTITY.IdentityError, "unsupported"):
            IDENTITY.build_index(self.manifest)
        manifest = self.valid_manifest()
        bad = receipt(model="gpt-5.6-sol", role="default", marker="unknown")
        bad["surprise"] = True
        manifest["runs"][0]["controller_receipt"] = self.write_receipt("unknown.json", bad)
        self.write_manifest(manifest)
        with self.assertRaisesRegex(IDENTITY.IdentityError, "unsupported"):
            IDENTITY.build_index(self.manifest)

    def test_existing_output_is_never_overwritten(self) -> None:
        self.write_manifest(self.valid_manifest())
        self.output.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(IDENTITY.IdentityError, "already exists"):
            IDENTITY.build(self.manifest, self.output)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "keep")

    def test_atomic_failure_leaves_no_output_or_temporary_file(self) -> None:
        self.write_manifest(self.valid_manifest())
        with mock.patch.object(IDENTITY.os, "replace", side_effect=OSError("forced")):
            with self.assertRaisesRegex(IDENTITY.IdentityError, "atomically"):
                IDENTITY.build(self.manifest, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.directory.glob("index.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
